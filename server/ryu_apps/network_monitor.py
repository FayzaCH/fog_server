# Copyright (C) 2016 Li Cheng at Beijing University of Posts
# and Telecommunications. www.muzixing.com

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from ryu.base.app_manager import RyuApp
from ryu.controller.handler import set_ev_cls, MAIN_DISPATCHER
from ryu.controller.ofp_event import (EventOFPPortStatsReply,
                                      EventOFPPortDescStatsReply)
from ryu.ofproto.ofproto_v1_3 import OFPP_LOCAL
from ryu.lib.hub import spawn, sleep
from ryu.topology.event import (EventSwitchLeave, EventPortDelete,
                                EventLinkAdd, EventLinkDelete)

from common import *


class NetworkMonitor(RyuApp):
    '''
        Ryu app for collecting traffic information for ports (state, Tx and Rx
        packets and bytes, free upload and download bandwidths, etc.) by 
        periodically sending port desc stats requests and port stats requests 
        to all switches. Most recent measures are saved in dictionaries. 

        Requirements:
        -------------
        Switches app (built-in): for datapath and list.

        Attributes:
        -----------
        port_features: dict mapping DPID and port number (nested) to tuple of 
        port's state, connected link's state, and port's capacity in kB/s.

        port_stats: dict mapping DPID and port number to list of 
        MONITOR_SAMPLES number of the most recent measures of port's Tx and Rx 
        bytes, packets, errors, and dropped, and period of measure in seconds 
        and nanoseconds.

        port_speed: dict mapping DPID and port number to list of of 
        MONITOR_SAMPLES number of the most recent measures of port's speeds 
        (up and down) in B/s.

        free_bandwidth: dict mapping DPID and port number (nested) to tuple of 
        port's current available bandwidths (up and down) in Mbit/s.

        loss_rate: dict mapping src DPID and dst DPID (nested) to loss rate 
        of link between the two switches.
    '''

    def __init__(self, *args, **kwargs):
        super(NetworkMonitor, self).__init__(*args, **kwargs)
        self.name = NETWORK_MONITOR

        self._switches = get_app(SWITCHES)

        self.port_features = {}
        self.port_stats = {}
        self.port_speed = {}
        self.free_bandwidth = {}
        self._link_ports = {}
        self.loss_rate = {}
        self._loss_rate_at_port = {}
        spawn(self._monitor)

    def _monitor(self):
        while True:
            for datapath in list(self._switches.dps.values()):
                parser = datapath.ofproto_parser
                datapath.send_msg(parser.OFPPortDescStatsRequest(datapath, 0))
                datapath.send_msg(parser.OFPPortStatsRequest(
                    datapath, 0, datapath.ofproto.OFPP_ANY))

                # Important! Don't send requests together, because that will
                # generate a lot of replies almost at the same time, which
                # will generate a lot of delay of waiting in queue when
                # handling them.
                sleep(0.05)

            sleep(MONITOR_PERIOD)

    def _save_stats(self, _dict, key, value, length):
        _dict.setdefault(key, [])
        _dict[key].append(value)
        if len(_dict[key]) > length:
            _dict[key].pop(0)

    @set_ev_cls(EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def _port_desc_stats_reply_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        config_dict = {ofproto.OFPPC_PORT_DOWN: 'Down',
                       ofproto.OFPPC_NO_RECV: 'No Recv',
                       ofproto.OFPPC_NO_FWD: 'No Fwd',
                       ofproto.OFPPC_NO_PACKET_IN: 'No Packet-in'}
        state_dict = {ofproto.OFPPS_LINK_DOWN: 'Down',
                      ofproto.OFPPS_BLOCKED: 'Blocked',
                      ofproto.OFPPS_LIVE: 'Live'}

        dpid = datapath.id
        self.port_features.setdefault(dpid, {})
        for port in msg.body:
            port_no = port.port_no
            if port_no != OFPP_LOCAL:
                config = port.config
                state = port.state
                curr_speed = 0
                try:
                    curr_speed = port.curr_speed

                except AttributeError:
                    for p in port.properties:
                        if isinstance(p, parser.OFPPortDescPropEthernet):
                            curr_speed = p.curr_speed
                            break

                self.port_features[dpid][port_no] = (
                    config_dict[config] if config in config_dict else 'up',
                    state_dict[state] if state in state_dict else 'up',
                    curr_speed)

    @set_ev_cls(EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        msg = ev.msg
        dpid = msg.datapath.id
        self.free_bandwidth.setdefault(dpid, {})
        for stat in msg.body:
            port_no = stat.port_no
            if port_no != OFPP_LOCAL:
                key = (dpid, port_no)
                self._save_stats(
                    self.port_stats, key, (stat.tx_bytes, stat.rx_bytes,
                                           stat.tx_packets, stat.rx_packets,
                                           stat.tx_errors, stat.rx_errors,
                                           stat.tx_dropped, stat.rx_dropped,
                                           stat.duration_sec,
                                           stat.duration_nsec),
                    MONITOR_SAMPLES)

                # =============================================================
                # this section of the code is changed from the original
                # the original code combines up speed and down speed
                # the new code separates them
                up_pre = 0
                down_pre = 0
                period = MONITOR_PERIOD
                tmp = self.port_stats[key]
                if len(tmp) > 1:
                    up_pre = tmp[-2][0]
                    down_pre = tmp[-2][1]
                    period = (tmp[-1][-2] + tmp[-1][-1] / (10 ** 9)
                              - tmp[-2][-2] + tmp[-2][-1] / (10 ** 9))
                up_speed = ((tmp[-1][0] - up_pre) / period) if period else 0
                down_speed = ((tmp[-1][1] - down_pre) /
                              period) if period else 0
                self._save_stats(
                    self.port_speed, key, (up_speed, down_speed),
                    MONITOR_SAMPLES)

                capacity = self.port_features.get(
                    dpid, {}).get(port_no, (0, 0, 0))[2] / 10**3

                self.free_bandwidth[dpid][port_no] = (
                    max(capacity - up_speed * 8/10**6, 0),    # unit: Mbit/s
                    max(capacity - down_speed * 8/10**6, 0))  # unit: Mbit/s
                # =============================================================

                # =============================================================
                # code for loss rate calculation
                # sometimes counters are reset leading to Rx being higher than
                # Tx, so maybe use packet counts periodically?
                dst_key = self._link_ports.get(key, (None, None))
                if dst_key in self.port_stats:
                    # tx_pre = 0
                    # rx_pre = 0
                    tx_pkt = 0
                    if len(tmp) > 0:  # > 1
                        # tx_pre = tmp[-2][2]
                        # rx_pre = tmp[-2][3]
                        tx_pkt = tmp[-1][2]
                    # tx_pkt = tmp[-1][2] - tx_pre
                    # rx_pkt = tmp[-1][3] - rx_pre

                    dst_tmp = self.port_stats[dst_key]
                    # dst_tx_pre = 0
                    # dst_rx_pre = 0
                    if len(dst_tmp) > 0:  # > 1
                        # dst_tx_pre = dst_tmp[-2][2]
                        # dst_rx_pre = dst_tmp[-2][3]
                        dst_rx_pkt = dst_tmp[-1][3]
                    # dst_tx_pkt = dst_tmp[-1][2] - dst_tx_pre
                    # dst_rx_pkt = dst_tmp[-1][3] - dst_rx_pre

                    try:
                        loss_rate = max(0, (tx_pkt - dst_rx_pkt) / tx_pkt)
                    except:
                        loss_rate = 1
                    self.loss_rate.setdefault(dpid, {})
                    self.loss_rate[dpid][dst_key[0]] = loss_rate
                    self._loss_rate_at_port[key] = loss_rate
                    # print(key, '->', dst_key, ':', round(loss_rate * 100, 2),
                    #      '%', '(Tx=%d,Rx=%d)' % (tx_pkt, dst_rx_pkt))
                # =============================================================

    @set_ev_cls(EventSwitchLeave)
    def _switch_leave_handler(self, ev):
        dpid = ev.switch.dp.id
        self.port_features.pop(dpid, None)
        for _, port_no in list(self.port_stats):
            self.port_stats.pop((dpid, port_no), None)
        for _, port_no in list(self.port_speed):
            self.port_speed.pop((dpid, port_no), None)
        self.free_bandwidth.pop(dpid, None)

    @set_ev_cls(EventPortDelete)
    def _port_delete_handler(self, ev):
        port = ev.port
        dpid = port.dpid
        port_no = port.port_no
        self.port_features.get(dpid, {}).pop(port_no)
        self.port_stats.pop((dpid, port_no), None)
        self.port_speed.pop((dpid, port_no), None)
        self.free_bandwidth.get(dpid, {}).pop(port_no, None)

    @set_ev_cls(EventLinkAdd)
    def _link_add_handler(self, ev):
        link = ev.link
        src = link.src
        dst = link.dst
        self._link_ports[(src.dpid, src.port_no)] = (dst.dpid, dst.port_no)

    @set_ev_cls(EventLinkDelete)
    def _link_delete_handler(self, ev):
        src = ev.link.src
        self._link_ports.pop(src.dpid, src.port_no)
