from ryu.base.app_manager import RyuApp
from ryu.controller.handler import set_ev_cls
from ryu.lib.hub import spawn, sleep
from ryu.topology.event import *

from model import Node, NodeType, Topology as Topo
from udp_server import serve, clients
from common import *
import config


try:
    UDP_PORT = int(getenv('ORCHESTRATOR_UDP_PORT', None))
except:
    print(' *** WARNING in topology: '
          'ORCHESTRATOR:UDP_PORT parameter invalid or missing from conf.yml. '
          'Defaulting to 7070.')
    UDP_PORT = 7070

try:
    UDP_TIMEOUT = int(getenv('ORCHESTRATOR_UDP_TIMEOUT', None))
except:
    print(' *** WARNING in topology: '
          'ORCHESTRATOR:UDP_TIMEOUT parameter invalid or missing from conf.yml. '
          'Defaulting to 3s.')
    UDP_TIMEOUT = 3


class Topology(RyuApp, Topo):
    '''
        Ryu app for discovering and managing the orchestrated network topology. 
        Represents the bridge between the controller and the orchestrator. At 
        every API call or topology event consumed (switch enter, switch leave, 
        port add, port delete, port modify, link add, link delete), it updates 
        the data structures describing the topology.

        Requirements:
        -------------
        Switches app (built-in): for datapath list.

        Methods:
        --------
        get_graph(): Returns NetworkX DiGraph object.

        get_node(id): Returns Node object identified by id.

        add_node(id, state, type, label): Create Node object and add it to 
        topology graph.

        delete_node(id): Delete node identified by id from topology graph 
        (also deletes associated interfaces and links).

        get_interface(node_id, ref): Returns Interface object identified by 
        ref (which can be either interface name or number) and attached to node 
        identified by node_id.

        add_interface(node_id, name, num, mac, ipv4): Create Interface object
        and add it to interfaces dict of Node object identified by node_id.

        delete_interface(node_id, name): Delete interface identified by name 
        and attached to node identified by node_id (also deletes associated 
        links).

        get_link(src_id, dst_id): Returns Link object connecting nodes
        identified by src_id and dst_id.

        add_link(src_id, dst_id, src_port_name, dst_port_name, state): Create 
        Link object and add it to topology graph.

        delete_link(src_id, dst_id): Delete link connecting nodes identified by
        src_id and dst_id from topology graph.

        get_nodes(as_dict): Returns dict of all nodes with their IDs as keys 
        (values are Node objects by default, or dicts if as_dict is True).

        get_dst_at_port(src_id, port_ref): Returns destination Node object 
        found at the end of the link connected to port identified by port_ref 
        (which can be port name or port number) and attached to node 
        identified by src_id.

        get_by_mac(mac, attr): Returns value of attribute attr of interface 
        identified by mac (attr can be 'node_id', 'name', 'ipv4', 'dpid', 
        'port_name', or 'port_no').

        get_links(): Returns nested dict of Link objects with source node ID 
        and destination node ID as keys.

        get_link_at_port(src_id, port_ref): Returns one-way Link object 
        connected to port identified by port_ref (which can be port name or 
        port number) and attached to node identified by src_id, None if it 
        doesn't exist.

        get_links_at_port(src_id, port_ref): Returns tuple of Link objects 
        connected to a port identified by port_ref (which can be port name 
        or port number) and attached to node identified by src_id.
    '''

    def __init__(self, *args, **kwargs):
        super(Topology, self).__init__(*args, **kwargs)
        self.name = TOPOLOGY

        self._switches = get_app(SWITCHES)

        spawn(self._add_host_links)
        spawn(self._check_clients)

    @set_ev_cls(EventSwitchEnter)
    def _switch_enter_handler(self, ev):
        switch = ev.switch
        datapath = switch.dp
        dpid = datapath.id
        self.add_node(dpid, datapath.is_active,
                      NodeType(NodeType.SWITCH), f's_{dpid:x}')
        for port in switch.ports:
            self.add_interface(dpid, port.name.decode(), port.port_no)

    @set_ev_cls(EventSwitchLeave)
    def _switch_leave_handler(self, ev):
        self.delete_node(ev.switch.dp.id)

    @set_ev_cls(EventPortAdd)
    def _port_add_handler(self, ev, retry=3):
        port = ev.port
        if not self.add_interface(port.dpid, port.name.decode(), port.port_no):
            # if there is any error or exception, mainly from the asynchronous
            # nature of event handlers (switch not yet added, for example),
            # retry 3 times with 1 sec intervals.
            retry -= 1
            if retry:
                sleep(1)
                self._port_add_handler(ev, retry)

    @set_ev_cls(EventPortDelete)
    def _port_delete_handler(self, ev):
        port = ev.port
        self.delete_interface(port.dpid, port.name.decode())

    @set_ev_cls(EventPortModify)
    def _port_modify_handler(self, ev):
        self._port_delete_handler(ev)
        self._port_add_handler(ev)
        # TODO handle port modify properly

    @set_ev_cls(EventLinkAdd)
    def _link_add_handler(self, ev, retry=3):
        src = ev.link.src
        dst = ev.link.dst
        if not self.add_link(src.dpid, dst.dpid, src.name.decode(),
                             dst.name.decode(), False):
            # if there is any error or exception, mainly from the asynchronous
            # nature of event handlers (switch not yet added, for example),
            # retry 3 times with 1 sec intervals.
            retry -= 1
            if retry:
                sleep(1)
                self._link_add_handler(ev, retry)

    @set_ev_cls(EventLinkDelete)
    def _link_delete_handler(self, ev):
        link = ev.link
        self.delete_link(link.src.dpid, link.dst.dpid)

    @set_ev_cls(EventHostAdd)
    def _host_add_handler(self, ev):
        host = ev.host
        mac = host.mac
        port = host.port
        self._interfaces.setdefault(mac, {})
        self._interfaces[mac]['dpid'] = port.dpid
        self._interfaces[mac]['port_name'] = port.name.decode()
        self._interfaces[mac]['port_no'] = port.port_no

    @set_ev_cls(EventHostDelete)
    def _host_delete_handler(self, ev):
        pass

    @set_ev_cls(EventHostMove)
    def _host_move_handler(self, ev):
        self._host_delete_handler(ev)
        self._host_add_handler(ev)
        # TODO handle host move properly

    def _add_host_links(self):
        while True:
            for mac in list(self._interfaces):
                node_id = self.get_by_mac(mac, 'node_id')
                dpid = self.get_by_mac(mac, 'dpid')
                if self.get_node(node_id) and self.get_node(dpid):
                    name = self.get_by_mac(mac, 'name')
                    port_name = self.get_by_mac(mac, 'port_name')
                    if not self.get_link(node_id, dpid):
                        self.add_link(
                            node_id, dpid, name, port_name, False)
                    if not self.get_link(dpid, node_id):
                        self.add_link(
                            dpid, node_id, port_name, name, False)
            sleep(1)

    def _check_clients(self):
        serve(UDP_PORT, UDP_TIMEOUT)
        while True:
            sleep(UDP_TIMEOUT)
            for node_id in list(self.get_graph()):
                if (node_id not in clients
                        and node_id not in self._switches.dps):
                    print(' *** WARNING in topology:',
                          node_id, 'is disconnected.')
                    self.delete_node(node_id)
