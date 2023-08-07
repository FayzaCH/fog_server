from time import time
from logging import info, basicConfig, INFO

from ryu.base.app_manager import RyuApp
from ryu.controller.handler import set_ev_cls, MAIN_DISPATCHER
from ryu.controller.ofp_event import EventOFPPacketIn
from ryu.lib.packet.ether_types import ETH_TYPE_IP
from ryu.lib.packet.in_proto import IPPROTO_IP
from ryu.lib.hub import spawn, Event
from ryu.topology.event import EventSwitchEnter

from scapy.all import (Packet, ByteEnumField, StrLenField, IntEnumField,
                       StrField, IntField, ConditionalField, bind_layers,
                       Ether, IP)

from networkx import shortest_path

from model import CoS, Request, Attempt, Response, Path
from selection import NodeSelector, PathSelector
from common import *
import config


# protocol config
try:
    PROTO_TIMEOUT = float(getenv('PROTOCOL_TIMEOUT', None))
except:
    print(' *** WARNING in protocol: '
          'PROTOCOL:TIMEOUT parameter invalid or missing from conf.yml. '
          'Defaulting to 1s.')
    PROTO_TIMEOUT = 1

try:
    PROTO_RETRIES = int(getenv('PROTOCOL_RETRIES', None))
except:
    print(' *** WARNING in protocol: '
          'PROTOCOL:RETRIES parameter invalid or missing from conf.yml. '
          'Defaulting to 3 retries.')
    PROTO_RETRIES = 3

_proto_verbose = getenv('PROTOCOL_VERBOSE', '').upper()
if _proto_verbose not in ('TRUE', 'FALSE'):
    _proto_verbose = 'FALSE'
PROTO_VERBOSE = _proto_verbose == 'TRUE'

if PROTO_VERBOSE:
    basicConfig(level=INFO, format='%(message)s')

cos_dict = {cos.id: cos for cos in CoS.select()}
cos_names = {id: cos.name for id, cos in cos_dict.items()}

# dict of resource reservation events (keys are ((src IP, request ID), host IP))
_events = {}

# dict of responses (keys are ((src IP, request ID), host IP))
_responses = {}


class MyProtocol(Packet):
    '''
        Class deriving from Scapy's Packet class to define the communication 
        protocol between hosts and orchestrator in ORCHESTRATOR mode, including 
        the packet header's fields, as well as ways to detect if a packet is an 
        answer to another.

        Fields:
        -------
        state: 1 byte indicating the state of the protocol, enumeration of 
        HREQ (1) (host request), HRES (2) (host response), RREQ (3) (resource 
        reservation request), RRES (4) (resource reservation response), RACK 
        (5) (resource reservation acknowledgement), RCAN (6) (resource 
        reservation cancellation), DREQ (7) (data exchange request), DRES (8) 
        (data exchange response), DACK (9) (data exchange acknowledgement), 
        DCAN (10) (data exchange cancellation), DWAIT (11) (data exchange 
        wait). Default is HREQ (1).

        req_id: String of 10 bytes indicating the request's ID. Default is ''.

        attempt_no: Integer of 4 bytes indicating the attempt number. Default 
        is 1. 

        cos_id: Integer of 4 bytes indicating the application's CoS ID. Default 
        is 1 (best-effort). Conditional field for state == HREQ (1) or state 
        == RREQ (3).

        data: String of undefined number of bytes containing input data and 
        possibly program to execute. Default is ''. Conditional field for 
        state == DREQ (7) or state == DRES (8).

        src_mac: String of 17 bytes indicating the source node's MAC address 
        (for intermediate communications between potential hosts and 
        orchestrator/controller, where Ether layer no longer contains source 
        node's MAC address). Conditional field for state == RREQ (3), 
        state == RRES (4), state == DACK (9) or state == DCAN (10).

        src_ip: String of 15 bytes indicating the source node's IPv4 address 
        (for intermediate communications between potential hosts and 
        orchestrator/controller, where IP layer no longer contains source 
        node's IP address). Conditional field for state == RREQ (3), 
        state == RRES (4), state == RACK (5), state == RCAN (6), state == DACK 
        (9) or state == DCAN (10).

        host_mac: String of 17 bytes indicating the selected host's MAC 
        address to be communicated to the source node. Conditional field for 
        state == HRES (2).

        host_ip: String of 15 bytes indicating the selected host's IPv4 
        address to be communicated to the source node. Conditional field for 
        state == HRES (2).
    '''

    _states = {
        HREQ: 'host request (HREQ)',
        HRES: 'host response (HRES)',
        RREQ: 'resource reservation request (RREQ)',
        RRES: 'resource reservation response (RRES)',
        RACK: 'resource reservation acknowledgement (RACK)',
        RCAN: 'resource reservation cancellation (RCAN)',
        DREQ: 'data exchange request (DREQ)',
        DRES: 'data exchange response (DRES)',
        DACK: 'data exchange acknowledgement (DACK)',
        DCAN: 'data exchange cancellation (DCAN)',
        DWAIT: 'data exchange wait (DWAIT)',
    }

    name = 'MyProtocol'
    fields_desc = [
        ByteEnumField('state', HREQ, _states),
        StrLenField('req_id', '', lambda _: REQ_ID_LEN),
        IntField('attempt_no', 1),
        ConditionalField(IntEnumField('cos_id', 1, cos_names),
                         lambda pkt: pkt.state == HREQ or pkt.state == RREQ),
        ConditionalField(StrField('data', ''),
                         lambda pkt: pkt.state == DREQ or pkt.state == DRES),
        ConditionalField(StrLenField('src_mac', ' ' * MAC_LEN,
                                     lambda _: MAC_LEN),
                         lambda pkt: pkt.state == RREQ or pkt.state == RRES
                         or pkt.state == RACK or pkt.state == RCAN
                         or pkt.state == DACK or pkt.state == DCAN),
        ConditionalField(StrLenField('src_ip', ' ' * IP_LEN, lambda _: IP_LEN),
                         lambda pkt: pkt.state == RREQ or pkt.state == RRES
                         or pkt.state == RACK or pkt.state == RCAN
                         or pkt.state == DACK or pkt.state == DCAN),
        ConditionalField(StrLenField('host_mac', ' ' * MAC_LEN,
                                     lambda _: MAC_LEN),
                         lambda pkt: pkt.state == HRES or pkt.state == DCAN
                         or pkt.state == DACK),
        ConditionalField(StrLenField('host_ip', ' ' * IP_LEN,
                                     lambda _: IP_LEN),
                         lambda pkt: pkt.state == HRES or pkt.state == DCAN
                         or pkt.state == DACK),
    ]

    def show(self):
        if PROTO_VERBOSE:
            print()
            return super().show()

    def hashret(self):
        return self.req_id

    def answers(self, other):
        if (isinstance(other, MyProtocol)
            # host request expects host response
            and (other.state == HREQ and self.state == HRES
                 # resource reservation request expects resource reservation
                 # response or resource reservation cancellation
                 or other.state == RREQ and (self.state == RRES
                                             or self.state == RCAN)
                 # resource reservation response expects data exchange request
                 # or resource reservation cancellation
                 or other.state == RRES and (self.state == RACK
                                             or self.state == RCAN)
                 # data exchange request expects data exchange response, data
                 # exchange wait, or data exchange cancellation
                 or other.state == DREQ and (self.state == DRES
                                             or self.state == DWAIT
                                             or self.state == DCAN)
                 # data exchange response expects data exchange acknowledgement
                 # or data exchange cancellation
                 or other.state == DRES and (self.state == DACK
                                             or self.state == DCAN))):
            return 1
        return 0


# for scapy to be able to dissect MyProtocol packets
bind_layers(Ether, MyProtocol)
bind_layers(IP, MyProtocol)


class Protocol(RyuApp):
    '''
        Ryu app for the protocol's responder (Answering Machine), which takes 
        decisions and builds and sends replies to received packets based on 
        the protocol's state.

        Requirements:
        -------------
        Switches app (built-in): for datapath list.

        Topology app: for network graph.

        TopologyState app: for updating node specs.

        SimpleSwitchSP13 app (if STP disabled and path selection enabled): 
        to stop installing default flows.

        Attributes:
        -----------
        requests: dict of requests received by provider (keys are 
        (src IP, request ID))
    '''

    def __init__(self, *args, **kwargs):
        super(Protocol, self).__init__(*args, **kwargs)
        self.name = PROTOCOL

        # dict of requests received by provider (keys are (src IP, request ID))
        self.requests = {}

        self._topology = get_app(TOPOLOGY)
        self._topology_state = get_app(TOPOLOGY_STATE)
        self._switches = get_app(SWITCHES)
        if not STP_ENABLED and ORCHESTRATOR_PATHS:
            self._simple_switch_sp_13 = get_app(SIMPLE_SWITCH_SP_13)

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

        # install flow to allow ICMP replies to reach controller decoy
        self._add_flow(
            datapath, 65535,
            parser.OFPMatch(eth_type=ETH_TYPE_IP, ip_proto=IPPROTO_IP,
                            ipv4_dst=DECOY_IP),
            [parser.OFPActionOutput(datapath.ofproto.OFPP_CONTROLLER)])

    def _is_request(self, req):
        # a packet must have Ether, IP and MyProtocol layers
        return (Ether in req and IP in req and MyProtocol in req
                # and no other layer
                and not any((layer is not Ether
                             and layer is not IP
                             and layer is not MyProtocol)
                            for layer in req.layers())
                # and not self
                and req[IP].src != DECOY_IP
                and req[IP].src != DEFAULT_IP
                # and decoy controller
                and req[Ether].dst == DECOY_MAC
                and req[IP].dst == DECOY_IP
                # and must have an ID
                and req[MyProtocol].req_id)

    @set_ev_cls(EventOFPPacketIn, MAIN_DISPATCHER)
    def _protocol_handler(self, ev):
        req = Ether(ev.msg.data)
        if self._is_request(req):
            my_proto = req[MyProtocol]
            eth_src = req[Ether].src
            ip_src = req[IP].src
            req_id = my_proto.req_id.decode()
            _req_id = (ip_src, req_id)
            state = my_proto.state
            att_no = my_proto.attempt_no

            _req = self.requests.get(_req_id, None)

            # controller receives host request
            if state == HREQ:
                # if new request
                if not _req:
                    _req = Request(
                        req_id, self._topology.get_node(
                            self._topology.get_by_mac(eth_src, 'node_id')),
                        None, None, state=HREQ)
                    self.requests[_req_id] = _req
                # if not processed yet
                if _req.state == HREQ or _req.state == HRES:
                    info('Recv host request from %s' % ip_src)
                    my_proto.show()
                    # set cos (for new requests and in case CoS was changed
                    # from old request)
                    _req.cos = cos_dict[my_proto.cos_id]
                    _req.state = RREQ
                    _req.host = None
                    _req._host_mac_ip = None
                    _req.attempts[att_no] = Attempt(req_id, ip_src, att_no)
                    spawn(self._select_host,
                          my_proto, _req_id, _req, eth_src, ip_src)
                return

            # controller receives resource reservation response
            if state == RRES:
                rres_at = time()
                src_ip = my_proto.src_ip.decode().strip()
                _req_id = (src_ip, req_id)
                _req = self.requests.get(_req_id, None)
                if _req:
                    # if late rres from previous host
                    if _req.host:
                        if _req._host_mac_ip != (eth_src, ip_src):
                            info('Recv late resource reservation response '
                                 'from %s' % ip_src)
                            my_proto.show()
                            # cancel with previous host
                            info('Send resource reservation cancellation '
                                 'to %s' % ip_src)
                            my_proto.state = RCAN
                            self._sendp(Ether(src=DECOY_MAC, dst=eth_src)
                                        / IP(src=DECOY_IP, dst=ip_src)
                                        / my_proto, eth_src)
                            return
                    # if regular rres
                    elif _req.state == RREQ:
                        _req.state = HRES
                        _req.attempts[att_no].rres_at = rres_at
                        _req._host_mac_ip = (eth_src, ip_src)
                        info('Recv resource reservation response '
                             'from %s' % ip_src)
                        my_proto.show()
                        _key = (_req_id, eth_src)
                        _responses[_key] = req
                        if _key in _events:
                            _events[_key].set()
                        # update node specs (not necessary, just to eliminate
                        # the node in case it no longer has resources)
                        host_id = self._topology.get_by_mac(eth_src, 'node_id')
                        host = self._topology.get_node(host_id)
                        cos = self.requests[_req_id].cos
                        self._topology_state.update_node_specs(
                            host_id,
                            host.get_cpu_free() - cos.get_min_cpu(),
                            host.get_memory_free() - cos.get_min_ram(),
                            host.get_disk_free() - cos.get_min_disk())
                    info('Send resource reservation acknowledgement '
                         'to %s' % ip_src)
                    self._sendp(Ether(src=DECOY_MAC, dst=eth_src)
                                / IP(src=DECOY_IP, dst=ip_src)
                                / MyProtocol(req_id=req_id, state=RACK,
                                             attempt_no=att_no,
                                             src_mac=my_proto.src_mac,
                                             src_ip=my_proto.src_ip), eth_src)
                    info('Send host response to %s' % src_ip)
                    dst_mac = my_proto.src_mac.decode()
                    self._sendp(Ether(src=DECOY_MAC, dst=dst_mac)
                                / IP(src=DECOY_IP, dst=src_ip)
                                / MyProtocol(req_id=req_id, state=HRES,
                                             attempt_no=att_no,
                                             host_mac=eth_src,
                                             host_ip=ip_src), dst_mac)
                return

            if state == RCAN:
                src_ip = my_proto.src_ip.decode().strip()
                _req_id = (src_ip, req_id)
                _req = self.requests.get(_req_id, None)
                if (_req and _req.state == RREQ
                    and (not _req.host
                         or _req._host_mac_ip == (eth_src, ip_src))):
                    info('Recv resource reservation cancellation '
                         'from %s' % ip_src)
                    my_proto.show()
                    _key = (_req_id, eth_src)
                    _responses[_key] = req
                    if _key in _events:
                        _events[_key].set()
                return

            if state == DACK and _req:
                info('Recv data exchange acknowledgement from %s' % ip_src)
                my_proto.src_mac = eth_src
                my_proto.src_ip = ip_src.ljust(IP_LEN, ' ')
                my_proto.show()
                host_mac = my_proto.host_mac.decode()
                host_ip = my_proto.host_ip.decode().strip()
                info('Send data exchange acknowledgement to %s' % host_ip)
                self._sendp(Ether(src=DECOY_MAC, dst=host_mac)
                            / IP(src=DECOY_IP, dst=host_ip)
                            / my_proto, host_mac)

            if state == DCAN and _req:
                info('Recv data exchange cancellation from %s' % ip_src)
                my_proto.src_mac = eth_src
                my_proto.src_ip = ip_src.ljust(IP_LEN, ' ')
                my_proto.show()
                host_mac = my_proto.host_mac.decode()
                host_ip = my_proto.host_ip.decode().strip()
                info('Send data exchange cancellation to %s' % host_ip)
                self._sendp(Ether(src=DECOY_MAC, dst=host_mac)
                            / IP(src=DECOY_IP, dst=host_ip)
                            / my_proto, host_mac)

    def _sendp(self, packet, eth_dst):
        datapath = self._switches.dps[self._topology.get_by_mac(eth_dst,
                                                                'dpid')]
        out_port = self._topology.get_by_mac(eth_dst, 'port_no')
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        datapath.send_msg(
            parser.OFPPacketOut(
                datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=ofproto.OFPP_CONTROLLER, data=bytes(packet),
                actions=[parser.OFPActionOutput(out_port)]))

    def _srp1(self, packet, eth_dst, _req_id):
        self._sendp(packet, eth_dst)
        _key = (_req_id, eth_dst)
        ev = Event()
        _events[_key] = ev
        ev.wait(PROTO_TIMEOUT)
        if not ev.is_set():
            return None
        return _responses[_key]

    def _select_host(self, my_proto, _req_id, req, eth_src, ip_src):
        # to keep track of all possible hosts
        # the default strategy ALL is applied
        # the hosts are then tried first (in list) to last
        hosts = NodeSelector(NODE_ALGO).select(
            self._topology.get_nodes().values(), req)
        host_ip = ''
        if hosts:
            spawn(self._save_hosts, _req_id, my_proto.attempt_no, hosts)
            my_proto.state = RREQ
            my_proto.src_mac = eth_src
            my_proto.src_ip = ip_src.ljust(IP_LEN, ' ')
            if not STP_ENABLED and ORCHESTRATOR_PATHS:
                # to keep track of all possible paths
                # the default strategy ALL is applied
                # the paths are then tried best (least cost) to worst
                paths, weights = PathSelector(PATH_ALGO).select(
                    self._topology.get_graph(), hosts, req, PATH_WEIGHT)
                if paths:
                    spawn(self._save_paths,
                          _req_id, my_proto.attempt_no, paths, weights)
                    w_idx = []
                    for target, _weights in weights.items():
                        for i, weight in enumerate(_weights):
                            w_idx.append((target, i, weight))
                    for target, i, _ in sorted(w_idx, key=lambda x: x[2]):
                        info('Selecting host')
                        path = paths[target][i]
                        last_link = self._topology.get_link(path[-2], path[-1])
                        host_mac = last_link.dst_port.mac
                        host_ip = last_link.dst_port.ipv4
                        rreq_rt = PROTO_RETRIES
                        rres = None
                        while not rres and rreq_rt and req.state == RREQ:
                            info('Send resource reservation request to %s' %
                                 host_ip)
                            info(req)
                            rreq_rt -= 1
                            # send and wait for positive response
                            rres = self._srp1(Ether(src=DECOY_MAC,
                                                    dst=host_mac)
                                              / IP(src=DECOY_IP,
                                                   dst=host_ip)
                                              / my_proto, host_mac, _req_id)
                        if rres:
                            if rres[MyProtocol].state == RRES:
                                # install flows on switches
                                in_port = self._topology.get_by_mac(eth_src,
                                                                    'port_no')
                                self._install_flows(
                                    # switches only path
                                    # (path minus src and dst)
                                    path[1:-1],
                                    {
                                        'src_ip': ip_src,
                                        'dst_ip': host_ip,
                                        'in_port': in_port,
                                        'src_mac': eth_src,
                                        'dst_mac': host_mac
                                    })
                                # stop installing default flows
                                self._simple_switch_sp_13._paths.add(
                                    (eth_src, host_mac))
                                # save paths for logging
                                req.path = path
                                req.attempts[my_proto.attempt_no].path = path
                                return
                            if rres[MyProtocol].state == RCAN:
                                continue
            else:
                for host in hosts:
                    info('Selecting host')
                    try:
                        host_mac = host.main_interface.mac
                        host_ip = host.main_interface.ipv4
                    except:
                        continue
                    rreq_rt = PROTO_RETRIES
                    rres = None
                    while not rres and rreq_rt and req.state == RREQ:
                        info('Send resource reservation request '
                             'to %s' % host_ip)
                        info(req)
                        rreq_rt -= 1
                        # send and wait for positive response
                        rres = self._srp1(Ether(src=DECOY_MAC, dst=host_mac)
                                          / IP(src=DECOY_IP, dst=host_ip)
                                          / my_proto, host_mac, _req_id)
                    if rres:
                        if rres[MyProtocol].state == RRES:
                            return
                        if rres[MyProtocol].state == RCAN:
                            continue
        if req.state == RREQ:
            info('No hosts available')
            req.state = HREQ

    def _save_hosts(self, _req_id, attempt_no, hosts):
        src_ip, req_id = _req_id
        timestamp = time()
        for host in hosts:
            host_ip = host.main_interface.ipv4
            Response(req_id, src_ip, attempt_no, host_ip, NODE_ALGO,
                     host.get_cpu_free(), host.get_memory_free(),
                     host.get_disk_free(), timestamp).insert()
            Response.as_csv()
            if STP_ENABLED or not ORCHESTRATOR_PATHS:
                graph = self._topology.get_graph()
                src = self._topology.get_by_ip(src_ip, 'node_id')
                if src in graph.nodes:
                    dst = self._topology.get_by_ip(host_ip, 'node_id')
                    if dst in graph.nodes:
                        path = shortest_path(graph, src, dst, weight=None)
                        _path, bws, dels, jits, loss, ts = get_path(
                            path, True)
                        Path(req_id, src_ip, attempt_no, host_ip, _path,
                             PATH_ALGO, bws, dels, jits, loss, PATH_WEIGHT,
                             None, ts).insert()
                Path.as_csv()

    def _save_paths(self, _req_id, attempt_no, paths, weights):
        src_ip, req_id = _req_id
        for host, _paths in paths.items():
            for idx, path in enumerate(_paths):
                _path, bws, dels, jits, loss, ts = get_path(path, True)
                Path(req_id, src_ip, attempt_no, host, _path, PATH_ALGO,
                     bws, dels, jits, loss, PATH_WEIGHT, weights[host][idx],
                     ts).insert()
        Path.as_csv()

    # the following methods are inspired by
    # https://github.com/muzixing/ryu/blob/master/ryu/app/network_awareness/shortest_forwarding.py

    def _install_flows(self, path, flow_info):
        in_port = flow_info['in_port']
        first_dp = self._switches.dps[path[0]]
        dst_mac = flow_info['dst_mac']
        back_info = {
            'src_ip': flow_info['dst_ip'],
            'dst_ip': flow_info['src_ip'],
            'in_port': in_port,
            'src_mac': dst_mac,
            'dst_mac': flow_info['src_mac'],
        }
        len_path = len(path)

        # inter-link
        if len_path > 2:
            for i in range(1, len(path)-1):
                dp = self._switches.dps[path[i]]
                if dp:
                    src_port = self._topology.get_link(
                        path[i-1], path[i]).dst_port.num
                    dst_port = self._topology.get_link(
                        path[i], path[i+1]).src_port.num
                    self._send_flow_mod(dp, flow_info, src_port, dst_port)
                    self._send_flow_mod(dp, back_info, dst_port, src_port)

        if len_path > 1:
            # last flow entry (last dp -> dst)
            try:
                src_port = self._topology.get_link(
                    path[-2], path[-1]).dst_port.num
            except:
                self.logger.info("Last src port is not found")
                return
                # TODO manage exception
            dst_port = self._topology.get_by_mac(dst_mac, 'port_no')
            if not dst_port:
                self.logger.info("Last dst port is not found")
                return
            last_dp = self._switches.dps[path[-1]]
            self._send_flow_mod(last_dp, flow_info, src_port, dst_port)
            self._send_flow_mod(last_dp, back_info, dst_port, src_port)

            # first flow entry (src -> first dp)
            out_port = self._topology.get_link(path[0], path[1]).src_port.num
            if not out_port:
                self.logger.info("First src port not found")
                return
            self._send_flow_mod(first_dp, flow_info, in_port, out_port)
            self._send_flow_mod(first_dp, back_info, out_port, in_port)

        # src and dst on the same datapath
        else:
            out_port = self._topology.get_by_mac(dst_mac, 'port_no')
            if not out_port:
                self.logger.info("out_port is None in same dp")
                return
            self._send_flow_mod(first_dp, flow_info, in_port, out_port)
            self._send_flow_mod(first_dp, back_info, out_port, in_port)

    def _send_flow_mod(self, datapath, flow_info, src_port, dst_port):
        src_ip = flow_info['src_ip']
        dst_ip = flow_info['dst_ip']

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # delete existing flows between src and dst
        datapath.send_msg(parser.OFPFlowMod(
            datapath, command=ofproto.OFPFC_DELETE, out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY, priority=2, match=parser.OFPMatch(
                ipv4_src=src_ip, ipv4_dst=dst_ip, eth_type=ETH_TYPE_IP)))

        # install new flows between src and dst
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, priority=2, match=parser.OFPMatch(
                eth_type=ETH_TYPE_IP, in_port=src_port, ipv4_src=src_ip,
                ipv4_dst=dst_ip),
            instructions=[parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS,
                [parser.OFPActionOutput(dst_port)])]))
