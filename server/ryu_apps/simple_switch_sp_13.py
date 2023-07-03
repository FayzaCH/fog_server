from ryu.app.simple_switch_13 import SimpleSwitch13
from ryu.controller.handler import set_ev_cls, MAIN_DISPATCHER
from ryu.controller.ofp_event import EventOFPPacketIn
from ryu.lib.packet.packet import Packet
from ryu.lib.packet.ethernet import ethernet
from ryu.lib.packet.llc import llc
from ryu.lib.packet.ether_types import (ETH_TYPE_LLDP, ETH_TYPE_ARP,
                                        ETH_TYPE_IPV6)
from ryu.topology.event import (EventLinkAdd, EventLinkDelete,
                                EventSwitchLeave, EventSwitchEnter)

from networkx import DiGraph, shortest_path
from networkx.exception import NetworkXError, NetworkXNoPath

from common import *


class SimpleSwitchSP13(SimpleSwitch13):
    '''
        Ryu app for basic automatic management of switches' flow tables, 
        especially useful for network loop management. At each packet-in
        the shortest path (SP) between source and destination (in terms of L2 
        hops for unweighted edges) is computed and flows are installed 
        accordingly on switches.

        Requirements:
        -------------
        Switches app (built-in): for datapath list.

        SimpleARP app: for ARP proxy.
    '''

    def __init__(self, *args, **kwargs):
        super(SimpleSwitchSP13, self).__init__(*args, **kwargs)
        self.name = SIMPLE_SWITCH_SP_13

        self._switches = get_app(SWITCHES)
        self._simple_arp = get_app(SIMPLE_ARP)

        self._net = DiGraph()   # network graph
        self._outs = {}         # out ports on path between src -> dst
        self._paths = set()     # paths (src, dst) that are already selected

    def delete_flow(self, datapath, priority, match):
        ofproto = datapath.ofproto
        datapath.send_msg(
            datapath.ofproto_parser.OFPFlowMod(
                datapath, command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY,
                priority=priority, match=match))

    @set_ev_cls(EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        # If you hit this you might want to increase
        # the "miss_send_length" of your switch
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        in_port = msg.match['in_port']

        pkt = Packet(msg.data)

        if pkt.get_protocol(llc):
            # ignore llc packets
            return

        eth = pkt.get_protocols(ethernet)[0]
        eth_type = eth.ethertype

        if eth_type == ETH_TYPE_LLDP or eth_type == ETH_TYPE_ARP:
            # ignore lldp packets and arp packets (handled by other apps)
            return

        dst = eth.dst
        src = eth.src

        if dst == DECOY_MAC or src == DECOY_MAC:
            # ignore packets from or to decoy controller
            return

        if dst[0:8] == '01:00:5e':
            # ignore mDNS (and subsequent protocols) packets
            return

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        # ==============================================
        # START OF SHORTEST PATH FORWARDING CODE SNIPPET
        #
        # Inspired by the following work:
        # https://github.com/castroflavio/ryu/blob/master/ryu/app/shortestpath.py
        #
        # Instead of simply getting out_port from mac_to_port, the shortest
        # path between src and dst is calculated instead and out_port is
        # selected based on the next node in the path.
        #
        # This solution also helps with network loops by installing flows
        # on the datapaths to avoid flooding.

        if src not in self._net:
            self._net.add_edge(src, dpid, in_port=in_port)
            self._net.add_edge(dpid, src, out_port=in_port)

        if dst in self._net and (src, dst) not in self._paths:
            try:
                # this part is to optimize shortest path calculation
                # if a path is already calculated between src and dst,
                # out ports are saved for next switches to send packet-in
                # without having to recalculate path
                if (src not in self._outs
                        or (src in self._outs and dst not in self._outs[src])):
                    path = shortest_path(self._net, src, dst)
                    self._outs.setdefault(src, {})
                    self._outs[src].setdefault(dst, {})
                    for i in range(1, len(path) - 1):
                        # save (out_port, dpid, in_port)
                        self._outs[src][dst][path[i]] = (
                            self._net[path[i]][path[i+1]]['out_port'],
                            path[i+1],
                            self._net[path[i-1]][path[i]]['in_port'])

                # if dpid or in_port not part of path
                path = self._outs[src][dst]
                if (dpid not in path
                        or (dpid in path and in_port != path[dpid][2])):
                    return

                out_port = path[dpid][0]

                # TODO if links are always two-way, path is same in both
                # directions. set out_ports for dst --> src to avoid
                # re-calculating path for response

                # TODO install flows on all switches to reduce packet-ins

            except NetworkXNoPath:
                return

            except Exception as e:
                print(' *** ERROR in simple_switch_sp_13._packet_in_handler:',
                      e.__class__.__name__, e)
                return

        else:
            out_port = ofproto.OFPP_FLOOD

        # END OF SHORTEST PATH FORWARDING CODE SNIPPET
        # ============================================

        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            # verify if we have a valid buffer_id, if yes avoid to send both
            # flow_mod & packet_out
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    @set_ev_cls(EventLinkAdd)
    def _link_add_handler(self, ev):
        link = ev.link
        src = link.src
        src_dpid = src.dpid
        src_port = src.port_no
        dst = link.dst
        dst_dpid = dst.dpid
        dst_port = dst.port_no
        self._net.add_edge(src_dpid, dst_dpid, out_port=src_port,
                           in_port=dst_port)
        self._net.add_edge(dst_dpid, src_dpid, out_port=dst_port,
                           in_port=src_port)

    @set_ev_cls(EventLinkDelete)
    def _link_delete_handler(self, ev):
        link = ev.link
        src_dpid = link.src.dpid
        dst_dpid = link.dst.dpid
        try:
            self._net.remove_edge(src_dpid, dst_dpid)

        except NetworkXError:
            pass

        # when link is deleted, paths it belonged to become invalid
        # delete them so they are recalculated when needed
        # and delete flows that use this link
        for src, dsts in list(self._outs.items()):
            for dst, path in list(dsts.items()):
                if (src_dpid in path and path[src_dpid][1] == dst_dpid):
                    for dpid in path:
                        datapath = self._switches.dps.get(dpid, None)
                        if datapath:
                            match = datapath.ofproto_parser.OFPMatch
                            self.delete_flow(
                                datapath, 1, match(eth_src=src, eth_dst=dst))
                            self.delete_flow(
                                datapath, 1, match(eth_src=dst, eth_dst=src))

                    dsts.pop(dst, None)
                    if not dsts:
                        self._outs.pop(src, None)

    @set_ev_cls(EventSwitchEnter)
    def _switch_enter_handler(self, ev):
        datapath = ev.switch.dp
        self.add_flow(datapath, 1,
                      datapath.ofproto_parser.OFPMatch(eth_type=ETH_TYPE_IPV6),
                      [])

    @set_ev_cls(EventSwitchLeave)
    def _switch_leave_handler(self, ev):
        dpid = ev.switch.dp.id
        try:
            self._net.remove_node(dpid)

        except NetworkXError:
            pass

        # delete _outs entries for host-switch links (because
        # _link_delete_handler only considers switch-switch links)
        for src, dsts in list(self._outs.items()):
            for dst, path in list(dsts.items()):
                if dpid in path:
                    dsts.pop(dst, None)
                    if not dsts:
                        self._outs.pop(src, None)
