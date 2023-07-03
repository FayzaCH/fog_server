# Copyright 2017 Wildan Maulana Syahidillah

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from time import time

from ryu.base.app_manager import RyuApp
from ryu.controller.handler import set_ev_cls, MAIN_DISPATCHER
from ryu.controller.ofp_event import EventOFPPacketIn
from ryu.lib.packet.packet import Packet
from ryu.lib.packet.ethernet import ethernet
from ryu.lib.packet.ipv4 import ipv4
from ryu.lib.packet.icmp import icmp, echo
from ryu.lib.packet.ether_types import ETH_TYPE_IP
from ryu.lib.packet.in_proto import IPPROTO_ICMP
from ryu.lib.hub import spawn, sleep
from ryu.topology.event import EventSwitchEnter

from common import *


class DelayMonitor(RyuApp):
    '''
        Ryu app for monitoring delays and jitters between hosts and switches 
        by sending ICMP packets (pings) to hosts by means of their respective 
        switches, receiving their responses, and calculating the total elapsed 
        time, and then calculating the differences between each two instances. 
        The most recent measures are saved in dictionaries. 

        Requirements:
        -------------
        Switches app (built-in): for datapath list.

        SimpleARP app: for ARP table and ARP proxy.

        NetworkDelayDetector app: for filtering switch-controller latency.

        Attributes:
        -----------
        delay: dict mapping host IP address to delay of link to switch 
        in seconds (two-way).

        jitter: dict mapping host IP address to jitter of link to switch 
        in seconds (two-way).
    '''

    def __init__(self, *args, **kwargs):
        super(DelayMonitor, self).__init__(*args, **kwargs)
        self.name = DELAY_MONITOR
        self._hosts = set()

        self._switches = get_app(SWITCHES)
        self._simple_arp = get_app(SIMPLE_ARP)
        self._network_delay_detector = get_app(NETWORK_DELAY_DETECTOR)

        self.delay = {}
        self._mac_delay = {}
        self._ip_2_mac = {}
        self._delay_history = {}
        self.jitter = {}
        self._mac_jitter = {}
        spawn(self._monitor)

    def _monitor(self):
        while True:
            for ip in list(self.delay):
                if ip not in self._simple_arp.arp_table:
                    self.delay.pop(ip, None)
                    self._mac_delay.pop(self._ip_2_mac.get(ip, None), None)
                    self._ip_2_mac.pop(ip, None)

            for ip, mac in list(self._simple_arp.arp_table.items()):
                dpid, port = self._simple_arp._in_ports.get(mac,
                                                            (None, None))
                datapath = self._switches.dps.get(dpid, None)
                if datapath:
                    self._send_icmp_packet(datapath, ip, mac, port)

                # Important! Don't send pings together, because that will
                # generate a lot of replies almost at the same time, which
                # will generate a lot of delay of waiting in queue when
                # handling them.
                sleep(0.05)

            sleep(MONITOR_PERIOD)

    def _send_icmp_packet(self, datapath, dst_ip, dst_mac, out_port):
        pkt = Packet()
        pkt.add_protocol(
            ethernet(ethertype=ETH_TYPE_IP, src=DECOY_MAC, dst=dst_mac))
        pkt.add_protocol(
            ipv4(proto=IPPROTO_ICMP, src=DECOY_IP, dst=dst_ip))
        pkt.add_protocol(
            icmp(data=echo(data=bytes('%f' % time(), 'utf-8'))))
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

    def _save_stats(self, _dict, key, value, length):
        _dict.setdefault(key, [])
        _dict[key].append(value)
        if len(_dict[key]) > length:
            _dict[key].pop(0)

    @set_ev_cls(EventSwitchEnter)
    def _switch_enter_handler(self, ev):
        datapath = ev.switch.dp
        parser = datapath.ofproto_parser

        # install flow to allow ICMP replies to reach controller decoy
        self._add_flow(
            datapath, 65535,
            parser.OFPMatch(eth_type=ETH_TYPE_IP, ip_proto=IPPROTO_ICMP,
                            ipv4_dst=DECOY_IP),
            [parser.OFPActionOutput(datapath.ofproto.OFPP_CONTROLLER)])

    @set_ev_cls(EventOFPPacketIn, MAIN_DISPATCHER)
    def _icmp_packet_in_handler(self, ev):
        pkt = Packet(ev.msg.data)
        eth = pkt.get_protocol(ethernet)
        if eth.dst == DECOY_MAC:
            icmp_pkt = pkt.get_protocol(icmp)
            if icmp_pkt:
                '''
                    ICMP packet:
                    Controller <---------------> Switch <---------------> Host
                                ctrl_switch_lat          switch_host_lat
                               <---------------------------------------->
                                                latency 

                    switch_host_lat = latency - ctrl_switch_lat
                '''
                try:
                    s_timestamp = float(icmp_pkt.data.data)

                except ValueError:
                    return

                else:
                    ip_src = pkt.get_protocol(ipv4).src
                    delay = max(
                        0, (ev.timestamp
                            - s_timestamp
                            - self._network_delay_detector.echo_latency.get(
                                ev.msg.datapath.id, 0)))
                    self.delay[ip_src] = delay

                    eth_src = eth.src
                    self._mac_delay[eth_src] = delay
                    self._ip_2_mac[ip_src] = eth_src

                    # =========================================================
                    #  code for jitter calculations
                    self._save_stats(self._delay_history, ip_src, delay,
                                     MONITOR_SAMPLES)
                    if len(self._delay_history[ip_src]) > 1:
                        jitter = abs(
                            self._delay_history[ip_src][1]
                            - self._delay_history[ip_src][0])
                        self.jitter[ip_src] = jitter
                        self._mac_jitter[eth_src] = jitter
                    # =========================================================
