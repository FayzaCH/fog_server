# Copyright 2017 Wildan Maulana Syahidillah

# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from ipaddress import ip_address
from re import sub

from ryu.base.app_manager import RyuApp
from ryu.controller.handler import set_ev_cls, MAIN_DISPATCHER
from ryu.controller.ofp_event import EventOFPPacketIn
from ryu.lib.packet.packet import Packet
from ryu.lib.packet.ethernet import ethernet
from ryu.lib.packet.arp import arp, ARP_REQUEST, ARP_REPLY
from ryu.lib.packet.ether_types import ETH_TYPE_ARP
from ryu.lib.mac import BROADCAST_STR
from ryu.lib.hub import sleep, spawn
from ryu.topology.event import (EventSwitchEnter, EventSwitchLeave,
                                EventHostAdd)

from logger import console, file
from common import *
import config


try:
    ARP_REFRESH = float(getenv('NETWORK_ARP_REFRESH', None))
except:
    console.warning('NETWORK:ARP_REFRESH parameter invalid or missing from '
                    'conf.yml. '
                    'Defaulting to 60s')
    file.warning('NETWORK:ARP_REFRESH parameter invalid or missing from '
                 'conf.yml', exc_info=True)
    ARP_REFRESH = 60

IPS = []
IP_POOL = getenv('NETWORK_IP_POOL', '')
if not IP_POOL:
    console.warning('NETWORK:IP_POOL parameter missing from conf.yml. '
                    'Defaulting to empty IP address pool.')
    file.warning('NETWORK:IP_POOL parameter missing from conf.yml')
else:
    # get individual IP addresses from IP_POOL
    _pools = sub('[^0-9.:,]+', '', IP_POOL).split(',')
    for _pool in _pools:
        try:
            # if _pool is an interval
            _start, _end = _pool.split(':')
            for ip in range(int(ip_address(_start).packed.hex(), 16),
                            int(ip_address(_end).packed.hex(), 16) + 1):
                IPS.append(ip_address(ip).exploded)

        except ValueError:
            # if _pool is one value
            try:
                IPS.append(ip_address(_pool).exploded)

            except ValueError:
                console.error('Invalid IP address pool or value (%s)', _pool)
                file.exception('Invalid IP address pool or value')


class SimpleARP(RyuApp):
    '''
        Ryu app for IPv4 layer discovery through ARP requests sent by 
        controller to pools of IP addresses by way of each connected switch 
        (at each consumption of EventSwitchEnter). Creates ARP table mapping 
        hosts' IP addresses to MAC addresses, updated periodically (by default 
        every 60s).

        Also acts as ARP proxy; responding to hosts' ARP requests which are 
        directed to controller via flows installed on switches.

        Requirements:
        -------------
        Switches app (built-in): for datapath list.

        Attributes:
        -----------
        arp_table: dict mapping hosts' IP addresses to MAC addresses.
    '''

    def __init__(self, *args, **kwargs):
        super(SimpleARP, self).__init__(*args, **kwargs)
        self.name = SIMPLE_ARP

        self._switches = get_app(SWITCHES)

        self.arp_table = {}             # ip -> mac
        self._reverse_arp_table = {}    # mac -> ip
        self._in_ports = {}             # mac -> (dpid, port_no)

        self._threads = {}

    def _arp(self, datapath):
        while datapath.id in self._switches.dps:
            self._batch_arp(datapath)
            if not self.arp_table:
                sleep(10)
            else:
                sleep(ARP_REFRESH)

    def _batch_arp(self, datapath, out_port=None):
        for ip in IPS:
            self._request_arp(datapath, ip, out_port)

            # don't send ARP requests together to not overwhelm network
            # with traffic and controller with handlers
            sleep(0.05)

    def _request_arp(self, datapath, dst_ip, out_port=None):
        pkt = Packet()
        pkt.add_protocol(
            ethernet(ethertype=ETH_TYPE_ARP, src=DECOY_MAC, dst=BROADCAST_STR))
        pkt.add_protocol(
            arp(opcode=ARP_REQUEST, src_mac=DECOY_MAC, src_ip=DECOY_IP,
                dst_mac=BROADCAST_STR, dst_ip=dst_ip))
        pkt.serialize()

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        if out_port == None:
            out_port = ofproto.OFPP_FLOOD

        datapath.send_msg(
            parser.OFPPacketOut(
                datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=ofproto.OFPP_CONTROLLER, data=pkt.data,
                actions=[parser.OFPActionOutput(out_port)]))

    def _reply_arp(self, datapath, requested_ip, eth_dst, ip_dst, out_port):
        # this is needed to resolve decoy controller ARP entries for ARP
        # poisoning prevention systems, by replying to ARP requests sent
        # to controller
        # it also acts as ARP proxy
        if requested_ip == DECOY_IP:
            requested_mac = DECOY_MAC
        else:
            requested_mac = self.arp_table.get(requested_ip, None)

        if not requested_mac:
            return

        pkt = Packet()
        pkt.add_protocol(
            ethernet(ethertype=ETH_TYPE_ARP, src=requested_mac, dst=eth_dst))
        pkt.add_protocol(
            arp(opcode=ARP_REPLY, src_mac=requested_mac, src_ip=requested_ip,
                dst_mac=eth_dst, dst_ip=ip_dst))
        pkt.serialize()

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        datapath.send_msg(
            parser.OFPPacketOut(
                datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=ofproto.OFPP_CONTROLLER, data=pkt.data,
                actions=[parser.OFPActionOutput(out_port)]))

    def _add_flow(self, datapath, priority, match, actions):
        parser = datapath.ofproto_parser
        datapath.send_msg(
            parser.OFPFlowMod(
                datapath=datapath, priority=priority, match=match,
                instructions=[parser.OFPInstructionActions(
                    datapath.ofproto.OFPIT_APPLY_ACTIONS, actions)]))

    @set_ev_cls(EventSwitchEnter)
    def _switch_enter_handler(self, ev):
        datapath = ev.switch.dp
        parser = datapath.ofproto_parser

        # install flow to allow ARP replies to reach controller decoy
        if STP_ENABLED:
            match = parser.OFPMatch(eth_type=ETH_TYPE_ARP, arp_tpa=DECOY_IP)
        else:
            match = parser.OFPMatch(eth_type=ETH_TYPE_ARP)
        self._add_flow(
            datapath, 65535, match,
            [parser.OFPActionOutput(datapath.ofproto.OFPP_CONTROLLER)])

        dpid = datapath.id
        thread = self._threads.get(dpid, None)
        if thread:
            thread.kill()
        self._threads[dpid] = spawn(self._arp, datapath)

    @set_ev_cls(EventHostAdd)
    def _host_add_handler(self, ev):
        # some hosts may take a while before manifesting. when they do, send
        # ARP requests without waiting for ARP_REFRESH
        host = ev.host
        mac = host.mac
        if mac == DECOY_MAC:
            return

        port = host.port
        dpid = port.dpid
        port_no = port.port_no
        self._in_ports[mac] = (dpid, port_no)

        if mac not in self._reverse_arp_table:
            datapath = self._switches.dps.get(dpid, None)
            if datapath:
                self._batch_arp(datapath, port_no)

    @set_ev_cls(EventOFPPacketIn, MAIN_DISPATCHER)
    def _arp_packet_in_handler(self, ev):
        pkt = Packet(ev.msg.data)
        arp_pkt = pkt.get_protocol(arp)
        if arp_pkt:
            eth = pkt.get_protocol(ethernet)
            if eth.dst != BROADCAST_STR:
                src = eth.src
                src_ip = arp_pkt.src_ip
                self.arp_table[src_ip] = src
                self._reverse_arp_table[src] = src_ip

            else:
                self._reply_arp(ev.msg.datapath, arp_pkt.dst_ip, eth.src,
                                arp_pkt.src_ip, ev.msg.match['in_port'])

    @set_ev_cls(EventSwitchLeave)
    def _switch_leave_handler(self, ev):
        dpid = ev.switch.dp.id
        thread = self._threads.get(dpid, None)
        if thread:
            thread.kill()

        for mac, (host_dpid, _) in list(self._in_ports.items()):
            if host_dpid == dpid:
                ip = self._reverse_arp_table.get(mac, None)
                self.arp_table.pop(ip, None)
                self._reverse_arp_table.pop(mac, None)
