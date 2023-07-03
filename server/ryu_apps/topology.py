from ryu.base.app_manager import RyuApp
from ryu.controller.handler import set_ev_cls
from ryu.lib.hub import spawn, sleep
from ryu.topology.event import *

from networkx import DiGraph
from networkx.exception import NetworkXError

from model import Node, NodeType, Interface, Link
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


class Topology(RyuApp):
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

        self._graph = DiGraph()
        self._src_port_to_dst = {}  # maps src id and port name to dst id
        self._num_to_name = {}  # maps node id and port number to port name
        self._host_ports = {}  # maps host mac to host port object
        self._interfaces = {}  # maps host interface mac to dict containing
        # node_id, name, ipv4, dpid, port_name, and port_no

        spawn(self._add_host_links)
        spawn(self._check_clients)

    def get_graph(self):
        '''
            Returns NetworkX DiGraph object.
        '''

        return self._graph

    def get_node(self, id) -> Node:
        '''
            Returns Node object identified by id, None if it doesn't exist.
        '''

        return self.get_graph().nodes.get(id, {}).get('node', None)

    def add_node(self, id, state: bool, type: NodeType, label: str = None):
        '''
            Create Node object and add it to topology graph.
        '''

        self.get_graph().add_node(id, node=Node(id, state, type, label))

    def delete_node(self, id):
        '''
            Delete node identified by id from topology graph (also deletes 
            associated interfaces and links).
        '''

        try:
            node = self.get_node(id)
            if node:
                for interface in list(node.interfaces.values()):
                    self._interfaces.pop(interface.mac, None)

            self.get_graph().remove_node(id)

        except NetworkXError:
            pass

        self._src_port_to_dst.pop(id, None)

    def get_interface(self, node_id, ref) -> Interface:
        '''
            Returns Interface object identified by ref (which can be either 
            interface name or number) and attached to node identified by 
            node_id, None if it doesn't exist.
        '''

        node = self.get_node(node_id)
        if node:
            return node.interfaces.get(
                self._num_to_name.get(node_id, {}).get(ref, ref), None)

    def add_interface(self, node_id, name: str, num: int = None,
                      mac: str = None, ipv4: str = None):
        '''
            Create Interface object and add it to interfaces dict of Node 
            object identified by node_id.

            Returns True if added, False if not.
        '''

        node = self.get_node(node_id)
        if node:
            node.interfaces[name] = Interface(name, num, mac, ipv4)
            self._num_to_name.setdefault(node_id, {})
            self._num_to_name[node_id][num] = name
            if mac:
                self._interfaces.setdefault(mac, {})
                self._interfaces[mac]['node_id'] = node_id
                self._interfaces[mac]['name'] = name
                self._interfaces[mac]['ipv4'] = ipv4
                spawn(self._set_main_interface, node, mac, ipv4)
            return True
        return False

    def delete_interface(self, node_id, name: str):
        '''
            Delete interface identified by name and attached to node identified 
            by node_id (also deletes associated links).
        '''

        node = self.get_node(node_id)
        if node:
            node.interfaces.pop(name, None)
            dst = self.get_dst_at_port(node_id, name)
            if dst:
                dst_id = dst.id
                self.delete_link(node_id, dst_id)
                self.delete_link(dst_id, node_id)

    def get_link(self, src_id, dst_id) -> Link:
        '''
            Returns Link object connecting nodes identified by src_id and 
            dst_id, None if it doesn't exist.
        '''

        return self.get_graph(
        ).succ.get(src_id, {}).get(dst_id, {}).get('link', None)

    def add_link(self, src_id, dst_id, src_port_name: str, dst_port_name: str,
                 state: bool):
        '''
            Create Link object and add it to topology graph.

            Returns True if added, False if not.
        '''

        src_port = self.get_interface(src_id, src_port_name)
        if src_port:
            dst_port = self.get_interface(dst_id, dst_port_name)
            if dst_port:
                self.get_graph().add_edge(src_id, dst_id,
                                          link=Link(src_port, dst_port, state))
                src_port_num = src_port.num
                self._src_port_to_dst.setdefault(src_id, {})
                self._src_port_to_dst[src_id][src_port_name] = dst_id
                self._src_port_to_dst[src_id][src_port_num] = dst_id
                return True
        return False

    def delete_link(self, src_id, dst_id):
        '''
            Delete link connecting nodes identified by src_id and dst_id from 
            topology graph.
        '''

        try:
            self.get_graph().remove_edge(src_id, dst_id)

        except NetworkXError:
            pass

        self._src_port_to_dst.pop(src_id, None)

    def get_nodes(self, as_dict: bool = False):
        '''
            Returns dict of all nodes with their IDs as keys (values are Node 
            objects by default, or dicts if as_dict is True).
        '''

        nodes = {}
        for id in list(self.get_graph()):
            node = self.get_node(id)
            if node:
                if not as_dict:
                    nodes[id] = self.get_node(id)
                else:
                    nodes[id] = self.get_node(id).as_dict()
        return nodes

    def get_dst_at_port(self, src_id, port_ref):
        '''
            Returns destination Node object found at the end of the link 
            connected to port identified by port_ref (which can be port name 
            or port number) and attached to node identified by src_id, None 
            if it doesn't exist.
        '''

        return self.get_node(
            self._src_port_to_dst.get(src_id, {}).get(port_ref, None))

    def get_by_mac(self, mac: str, attr: str):
        '''
            Returns value of attribute attr of interface identified by mac 
            (attr can be 'node_id', 'name', 'ipv4', 'dpid', 'port_name', 
            or 'port_no'), None if it doesn't exist.
        '''

        return self._interfaces.get(mac, {}).get(attr, None)

    def get_links(self):
        '''
            Returns nested dict of Link objects with source node ID and 
            destination node ID as keys.
        '''

        links = {}
        graph = self.get_graph()
        for src_id in list(graph):
            for dst_id in list(graph.succ.get(src_id, {})):
                link = self.get_link(src_id, dst_id)
                if link:
                    links.setdefault(src_id, {})
                    links[src_id][dst_id] = link
        return links

    def get_link_at_port(self, src_id, port_ref):
        '''
            Returns one-way Link object connected to port identified by 
            port_ref (which can be port name or port number) and attached to 
            node identified by src_id, None if it doesn't exist.
        '''

        dst = self.get_dst_at_port(src_id, port_ref)
        if dst:
            return self.get_link(src_id, dst.id)
        return None

    def get_links_at_port(self, src_id, port_ref):
        '''
            Returns tuple of Link objects connected to a port identified by 
            port_ref (which can be port name or port number) and attached 
            to node identified by src_id, None if they don't exist.
        '''

        dst = self.get_dst_at_port(src_id, port_ref)
        if dst:
            dst_id = dst.id
            return (self.get_link(src_id, dst_id),
                    self.get_link(dst_id, src_id))
        return None, None

    def _set_main_interface(self, node: Node, mac: str, ipv4: str):
        retries = 100
        while retries:
            if mac in self._host_ports:
                port = self._host_ports[mac]
                self._interfaces[mac]['dpid'] = port.dpid
                self._interfaces[mac]['port_name'] = port.name.decode()
                self._interfaces[mac]['port_no'] = port.port_no
                if not node.main_interface:
                    node.main_interface = (mac, ipv4)
                return
            retries -= 1
            sleep(1)

    @set_ev_cls(EventSwitchEnter)
    def _switch_enter_handler(self, ev):
        switch = ev.switch
        datapath = switch.dp
        dpid = datapath.id
        self.add_node(dpid, datapath.is_active,
                      NodeType(NodeType.SWITCH), f'{dpid:x}')
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
        self._host_ports[host.mac] = host.port

    @set_ev_cls(EventHostDelete)
    def _host_delete_handler(self, ev):
        self._host_ports.pop(ev.host.mac, None)

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
