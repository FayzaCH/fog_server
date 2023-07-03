# Copyright (C) 2016 Li Cheng at Beijing University of Posts
# and Telecommunications. www.muzixing.com

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from time import time

from ryu.base.app_manager import RyuApp
from ryu.controller.handler import set_ev_cls, MAIN_DISPATCHER
from ryu.controller.ofp_event import EventOFPPacketIn, EventOFPEchoReply
from ryu.lib.hub import spawn, sleep
from ryu.topology.switches import LLDPPacket
from ryu.topology.event import EventSwitchLeave, EventLinkDelete

from common import *


class NetworkDelayDetector(RyuApp):
    '''
        Ryu app for monitoring delays and jitters of links between switches by 
        collecting LLDP packets and calculating LLDP latencies, and 
        periodically sending ECHO requests to all switches to monitor latencies 
        between controller and switches, and finally subtracting ECHO latencies 
        from LLDP latencies to get delays on each link, , and then calculating 
        the differences between each two instances. Most recent measures are 
        saved in dictionaries.

        Requirements:
        -------------
        Switches app (built-in): for datapath and port lists.

        Attributes:
        ----------- 
        lldp_latency: dict mapping src DPID and dst DPID to LLDP latency 
        in seconds (one-way).

        echo_latency: dict mapping DPID to controller-switch latency 
        in seconds (two-way).

        delay: dict mapping src DPID and dst DPID to link delay in seconds 
        (one-way).

        jitter: dict mapping src DPID and dst DPID to link jitter in seconds
        (one-way).
    '''

    def __init__(self, *args, **kwargs):
        super(NetworkDelayDetector, self).__init__(*args, **kwargs)
        self.name = NETWORK_DELAY_DETECTOR

        self._switches = get_app(SWITCHES)

        self.lldp_latency = {}
        self.echo_latency = {}
        self.delay = {}
        self._delay_history = {}
        self.jitter = {}
        spawn(self._detector)

    def _detector(self):
        while True:
            self._send_echo_requests()
            for src, dsts in list(self.lldp_latency.items()):
                self.delay.setdefault(src, {})
                self.jitter.setdefault(src, {})
                for dst, lldp_lat in list(dsts.items()):
                    '''
                                        Controller
                                        |        |
                        src_echo_latency|        |dst_echo_latency
                                        |        |
                                  SwitchA--------SwitchB

                         fwd_lldp_latency------->
                                         <-------rpl_lldp_latency

                        fwd_delay = (fwd_lldp_latency - dst_echo_latency / 2)
                        rpl_delay = (rpl_lldp_latency - src_echo_latency / 2)
                    '''
                    delay = max(
                        0, (lldp_lat
                            - self.echo_latency.get(dst, -float('inf')) / 2))
                    self.delay[src][dst] = delay

                    # =========================================================
                    #  code for jitter calculations
                    key = (src, dst)
                    self._save_stats(self._delay_history, key, delay,
                                     MONITOR_SAMPLES)
                    if len(self._delay_history[key]) > 1:
                        self.jitter[src][dst] = abs(
                            self._delay_history[key][1]
                            - self._delay_history[key][0])
                    # =========================================================

            sleep(MONITOR_PERIOD)

    def _send_echo_requests(self):
        for datapath in list(self._switches.dps.values()):
            datapath.send_msg(
                datapath.ofproto_parser.OFPEchoRequest(
                    datapath, data=bytes('%f' % time(), 'utf-8')))

            # Important! Don't send echo requests together, because that will
            # generate a lot of echo replies almost at the same time, which
            # will generate a lot of delay of waiting in queue when handling
            # echo replies.
            sleep(0.05)

    def _save_stats(self, _dict, key, value, length):
        _dict.setdefault(key, [])
        _dict[key].append(value)
        if len(_dict[key]) > length:
            _dict[key].pop(0)

    @set_ev_cls(EventOFPPacketIn, MAIN_DISPATCHER)
    def _lldp_packet_in_handler(self, ev):
        msg = ev.msg
        try:
            src_dpid, src_port_no = LLDPPacket.lldp_parse(msg.data)

        except LLDPPacket.LLDPUnknownFormat:
            return

        else:
            for port, port_data in list(self._switches.ports.items()):
                lldp_timestamp = port_data.timestamp
                if (lldp_timestamp
                        and src_dpid == port.dpid
                        and src_port_no == port.port_no):
                    self.lldp_latency.setdefault(src_dpid, {})
                    self.lldp_latency[src_dpid][msg.datapath.id] = (
                        ev.timestamp - lldp_timestamp)
                    return

    @set_ev_cls(EventOFPEchoReply, MAIN_DISPATCHER)
    def _echo_reply_handler(self, ev):
        msg = ev.msg
        self.echo_latency[msg.datapath.id] = (ev.timestamp - eval(msg.data))

    @set_ev_cls(EventSwitchLeave)
    def _switch_leave_handler(self, ev):
        dpid = ev.switch.dp.id
        self.lldp_latency.pop(dpid, None)
        for dsts in list(self.lldp_latency.values()):
            dsts.pop(dpid, None)
        self.echo_latency.pop(dpid, None)
        self.delay.pop(dpid, None)
        for dsts in list(self.delay.values()):
            dsts.pop(dpid, None)

    @set_ev_cls(EventLinkDelete)
    def _link_delete_handler(self, ev):
        link = ev.link
        self.lldp_latency.get(link.src.dpid, {}).pop(link.dst.dpid, None)
        self.delay.get(link.src.dpid, {}).pop(link.dst.dpid, None)
