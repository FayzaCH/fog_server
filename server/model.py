'''
    Model classes used to represent various networking concepts, such as nodes, 
    their types and their specs, interfaces and their specs, links and their 
    specs, Classes of Service (CoS) and their requirements, application hosting 
    requests, their attempts, and their responses.

    Classes:
    --------
    Model: Base class for all model classes.

    InterfaceSpecs: Network interface specs at given timestamp.

    Interface: Network interface (port).

    NodeSpecs: Network node specs at given timestamp.

    Node: Network node.

    LinkSpecs: Network link specs at given timestamp.

    Link: Network link.

    CoSSpecs: Set of minimum specs required to host network applications 
    belonging to Class of Service.

    CoS: Class of Service.

    Request: Network application hosting request.

    Attempt: Network application hosting request attempt.

    Response: Network application hosting response.
'''


from copy import copy
from time import time
from enum import Enum
from datetime import datetime

from networkx import DiGraph
from networkx.exception import NetworkXError

from consts import HREQ, RREQ, DREQ, DRES, FAIL


class Model:
    '''
        Base class for all model classes.

        Methods:
        --------
        as_dict(flat, _prefix): Converts object to dictionary and returns it. 
        If flat is False, nested objects will become nested dictionaries; 
        otherwise, all attributes in nested objects will be in root dictionary.

        insert(): Insert as a row in the corresponding database table. 

        update(): Update corresponding database table row.

        select(cls, fields, groups, orders, as_obj, **kwargs): Select row(s) 
        from the corresponding database table.

        select_page(page, page_size, fields, orders, as_obj, **kwargs): Select 
        page_size row(s) of page from the corresponding database table.

        as_csv(cls, abs_path, fields, orders, _suffix, **kwargs): Convert the 
        corresponding database table to a CSV file.

        columns(): Returns the list of columns in the corresponding database 
        table.
    '''

    def as_dict(self, flat: bool = False, _prefix: str = ''):
        '''
            Converts object to a dictionary and returns it. If flat is False, 
            nested objects will become nested dictionaries; otherwise, all 
            attributes in nested objects will be in root dictionary.

            To avoid name conflicts when flat is True, nested attribute name 
            will be prefixed: <parent_attribute_name>_<nested_attribute_name> 
            (example: cos.id will become cos_id).
        '''

        if flat and _prefix:
            _prefix += '_'
        return {_prefix + str(key): copy(val)
                for key, val in self.__dict__.items()}

    # the following methods are for database operations

    def insert(self):
        '''
            Insert as a row in the corresponding database table.

            Returns True if inserted, False if not.
        '''

        from dblib import insert
        return insert(self)

    def update(self, _id: tuple = ('id',)):
        '''
            Update the corresponding database table row.

            Return True if updated, False if not.
        '''

        from dblib import update
        return update(self, _id)

    @classmethod
    def select(cls, fields: tuple = ('*',), groups: tuple = None,
               orders: tuple = None, as_obj: bool = True, **kwargs):
        '''
            Select row(s) from the corresponding database table.

            Filters can be applied through args and kwargs. Example:

                >>> CoS.select(fields=('id', 'name'), as_obj=False, id=('=', 1))

            as_obj should only be set to True if fields is (*).

            Returns list of rows if selected, None if not.
        '''

        from dblib import select
        return select(cls, fields, groups, orders, as_obj, **kwargs)

    @classmethod
    def select_page(cls, page: int, page_size: int, fields: tuple = ('*',),
                    orders: tuple = None, as_obj: bool = True, **kwargs):
        '''
            Select page_size row(s) of page from the corresponding database 
            table.

            Filters can be applied through args and kwargs. Example:

                >>> Request.select_page(1, 15, fields=('id', 'host'), as_obj=False, host=('=', '10.0.0.2'))

            as_obj should only be set to True if fields is (*).

            Returns list of rows if selected, None if not.
        '''

        from dblib import select_page
        return select_page(cls, page, page_size, fields, orders, as_obj,
                           **kwargs)

    @classmethod
    def as_csv(cls, abs_path: str = '', fields: tuple = ('*',),
               orders: tuple = None, _suffix: str = '', **kwargs):
        '''
            Convert the corresponding database table to a CSV file.

            Filters can be applied through args and kwargs. Example:

                >>> Request.as_csv(abs_path='/home/data.csv', fields=('id', 'host'), host=('=', '10.0.0.2'))

            Returns True if converted, False if not.
        '''

        from dblib import as_csv
        return as_csv(cls, abs_path, fields, orders, _suffix, **kwargs)

    @classmethod
    def columns(cls):
        '''
            Returns the list of columns in the corresponding database table.
        '''

        from dblib import _get_columns
        return _get_columns(cls)


class InterfaceSpecs(Model):
    '''
        Network interface specs.

        Attributes:
        -----------
        capacity: Total interface capacity. Default is 0.

        bandwidth_up: Free egress bandwidth. Default is 0.

        bandwidth_down: Free ingress bandwidth. Default is 0.

        tx_packets: Number of transmitted packets. Default is 0.

        rx_packets: Number of received packets. Default is 0.

        timestamp: Default is time of update.
    '''

    def __init__(self, capacity: float = 0, bandwidth_up: float = 0,
                 bandwidth_down: float = 0, tx_packets: int = 0,
                 rx_packets: int = 0, timestamp: float = 0):
        self.capacity = capacity
        self.bandwidth_up = bandwidth_up
        self.bandwidth_down = bandwidth_down
        self.tx_packets = tx_packets
        self.rx_packets = rx_packets
        self.timestamp = timestamp if timestamp else time()


class Interface(Model):
    '''
        Network interface (port).

        Recommendation: use the provided getters and setters for specs in case 
        their structure changes in future updates.

        Attributes:
        -----------
        name: Interface name.

        num: Interface number.

        mac: Interface MAC address.

        ipv4: Interface IP address.

        specs: InterfaceSpecs object.
    '''

    def __init__(self, name: str, num: int = None, mac: str = None,
                 ipv4: str = None, specs: InterfaceSpecs = None):
        self.name = name
        self.num = num
        self.mac = mac
        self.ipv4 = ipv4
        self.specs = specs if specs else InterfaceSpecs()

    def as_dict(self, flat: bool = False, _prefix: str = ''):
        d = super().as_dict(flat, _prefix)
        if not flat:
            d['specs'] = self.specs.as_dict()
        else:
            if _prefix:
                _prefix += '_'
            del d[_prefix + 'specs']
            d.update(self.specs.as_dict(flat, _prefix=_prefix+'specs'))
        return d

    # the following methods serve for access to the interface specs no matter
    # how they are implemented (whether they are attributes in the object, are
    # objects themselves within an Iterable, etc.)

    def get_capacity(self):
        return self.specs.capacity

    def set_capacity(self, capacity: float = 0):
        self.specs.capacity = capacity
        self.set_timestamp()

    def get_bandwidth_up(self):
        return self.specs.bandwidth_up

    def set_bandwidth_up(self, bandwidth_up: float = 0):
        self.specs.bandwidth_up = bandwidth_up
        self.set_timestamp()

    def get_bandwidth_down(self):
        return self.specs.bandwidth_down

    def set_bandwidth_down(self, bandwidth_down: float = 0):
        self.specs.bandwidth_down = bandwidth_down
        self.set_timestamp()

    def get_tx_packets(self):
        return self.specs.tx_packets

    def set_tx_packets(self, tx_packets: int = 0):
        self.specs.tx_packets = tx_packets
        self.set_timestamp()

    def get_rx_packets(self):
        return self.specs.rx_packets

    def set_rx_packets(self, rx_packets: int = 0):
        self.specs.rx_packets = rx_packets
        self.set_timestamp()

    def get_timestamp(self):
        return self.specs.timestamp

    def set_timestamp(self, timestamp: float = 0):
        self.specs.timestamp = timestamp if timestamp else time()


class NodeType(Enum):
    '''
        Network node type enumeration.

        Attributes:
        -----------
        SERVER: 'SERVER'.

        VM: 'VM'.

        IOT_OBJECT: 'IOT_OBJECT'.

        GATEWAY: 'GATEWAY'.

        SWITCH: 'SWITCH'.

        ROUTER: 'ROUTER'.
    '''

    SERVER = 'SERVER'
    VM = 'VM'
    IOT_OBJECT = 'IOT_OBJECT'
    GATEWAY = 'GATEWAY'
    SWITCH = 'SWITCH'
    ROUTER = 'ROUTER'


class NodeSpecs(Model):
    '''
        Network node specs at given timestamp.

        Attributes:
        -----------
        cpu_count: Number of CPUs. Default is 0.

        cpu_free: Amount of free CPU. Default is 0.

        memory_total: Total size of RAM. Default is 0.

        memory_free: Size of free RAM. Default is 0.

        disk_total: Total size of disk. Default is 0.

        disk_free: Size of free disk. Default is 0.

        timestamp: Default is time of update.
    '''

    def __init__(self, cpu_count: int = 0, cpu_free: float = 0,
                 memory_total: float = 0, memory_free: float = 0,
                 disk_total: float = 0, disk_free: float = 0,
                 timestamp: float = 0):
        self.cpu_count = cpu_count
        self.cpu_free = cpu_free
        self.memory_total = memory_total
        self.memory_free = memory_free
        self.disk_total = disk_total
        self.disk_free = disk_free
        self.timestamp = timestamp if timestamp else time()


class Node(Model):
    '''
        Network node.

        Recommendation: use the provided getters and setters for specs in case 
        their structure changes in future updates.

        Attributes:
        -----------
        id: Node ID (by default MAC address).

        state: Node state boolean; True is up, False is down.

        type: NodeType object.

        label: Node name. Default is empty.

        interfaces: Dict of Interface objects (keys are interface names).

        specs: NodeSpecs object.
    '''

    def __init__(self, id, state: bool, type: NodeType, label: str = None,
                 interfaces: dict = None, specs: NodeSpecs = None):
        self.id = id
        self.state = state
        self.type = type
        self.label = label
        self.interfaces = interfaces if interfaces else {}
        self.main_interface = None  # Interface object
        self.specs = specs if specs else NodeSpecs()
        # float (gross value; to get percentage, multiply by 100)
        self.threshold = 1

    def as_dict(self, flat: bool = False):
        d = super().as_dict(flat)
        d['type'] = self.type.value
        if not flat:
            try:
                d['main_interface'] = self.main_interface.as_dict()
            except:
                pass
            d['specs'] = self.specs.as_dict()
            for name, intf in self.interfaces.items():
                d['interfaces'][name] = intf.as_dict()
        else:
            del d['main_interface']
            try:
                d.update(self.main_interface.as_dict(
                    flat, _prefix='main_interface'))
            except:
                pass
            del d['specs']
            d.update(self.specs.as_dict(flat, _prefix='specs'))
            del d['interfaces']
            for name, intf in self.interfaces.items():
                d.update(intf.as_dict(flat,
                                      _prefix='interfaces_'+name))
        return d

    # the following methods serve for access to the node specs no matter how
    # they are implemented (whether they are attributes in the object, are
    # objects themselves within an Iterable, etc.)

    def get_cpu_count(self):
        return self.specs.cpu_count

    def set_cpu_count(self, cpu_count: int = 0):
        self.specs.cpu_count = cpu_count
        self.set_timestamp()

    def get_cpu_free(self):
        return self.specs.cpu_free

    def set_cpu_free(self, cpu_free: int = 0):
        self.specs.cpu_free = cpu_free
        self.set_timestamp()

    def get_memory_total(self):
        return self.specs.memory_total

    def set_memory_total(self, memory_total: float = 0):
        self.specs.memory_total = memory_total
        self.set_timestamp()

    def get_memory_free(self):
        return self.specs.memory_free

    def set_memory_free(self, memory_free: float = 0):
        self.specs.memory_free = memory_free
        self.set_timestamp()

    def get_disk_total(self):
        return self.specs.disk_total

    def set_disk_total(self, disk_total: float = 0):
        self.specs.disk_total = disk_total
        self.set_timestamp()

    def get_disk_free(self):
        return self.specs.disk_free

    def set_disk_free(self, disk_free: float = 0):
        self.specs.disk_free = disk_free
        self.set_timestamp()

    def get_timestamp(self):
        return self.specs.timestamp

    def set_timestamp(self, timestamp: float = 0):
        self.specs.timestamp = timestamp if timestamp else time()


class LinkSpecs(Model):
    '''
        Network link specs at given timestamp.

        Attributes:
        -----------
        capacity: Total link capacity. Default is 0.

        bandwidth: Free bandwidth. Default is 0.

        delay: Default is inf.

        jitter: Default is inf.

        loss_rate: Default is 1 (gross value; to get percentage, 
        multiply by 100). 

        timestamp: Default is time of update.
    '''

    def __init__(self, capacity: float = 0, bandwidth: float = 0,
                 delay: float = float('inf'), jitter: float = float('inf'),
                 loss_rate: float = 1, timestamp: float = 0):
        self.capacity = capacity
        self.bandwidth = bandwidth
        self.delay = delay
        self.jitter = jitter
        self.loss_rate = loss_rate
        self.timestamp = timestamp if timestamp else time()


class Link(Model):
    '''
        Network link.    

        Recommendation: use the provided getters and setters for specs in case 
        their structure changes in future updates.

        Attributes:
        -----------
        src_port: Interface object.

        dst_port: Interface object.

        state: Link state boolean; True is up, False is down.

        specs: LinkSpecs object.
    '''

    def __init__(self, src_port: Interface, dst_port: Interface,
                 state: bool, specs: LinkSpecs = None):
        self.src_port = src_port
        self.dst_port = dst_port
        self.state = state
        self.specs = specs if specs else LinkSpecs()

    def as_dict(self, flat: bool = False):
        d = super().as_dict(flat)
        if not flat:
            d['src_port'] = self.src_port.as_dict()
            d['dst_port'] = self.dst_port.as_dict()
            d['specs'] = self.specs.as_dict()
        else:
            del d['src_port']
            d.update(self.src_port.as_dict(flat, _prefix='src_port'))
            del d['dst_port']
            d.update(self.dst_port.as_dict(flat, _prefix='dst_port'))
            del d['specs']
            d.update(self.specs.as_dict(flat, _prefix='specs'))
        return d

    # the following methods serve for access to the node specs no matter how
    # they are implemented (whether they are attributes in the object, are
    # objects themselves within an Iterable, etc.)

    def get_capacity(self):
        return self.specs.capacity

    def set_capacity(self, capacity: float = 0):
        self.specs.capacity = capacity
        self.set_timestamp()

    def get_bandwidth(self):
        return self.specs.bandwidth

    def set_bandwidth(self, bandwidth: float = 0):
        self.specs.bandwidth = bandwidth
        self.set_timestamp()

    def get_delay(self):
        return self.specs.delay

    def set_delay(self, delay: float = float('inf')):
        self.specs.delay = delay
        self.set_timestamp()

    def get_jitter(self):
        return self.specs.jitter

    def set_jitter(self, jitter: float = float('inf')):
        self.specs.jitter = jitter
        self.set_timestamp()

    def get_loss_rate(self):
        return self.specs.loss_rate

    def set_loss_rate(self, loss_rate: float = 1):
        self.specs.loss_rate = loss_rate
        self.set_timestamp()

    def get_timestamp(self):
        return self.specs.timestamp

    def set_timestamp(self, timestamp: float = 0):
        self.specs.timestamp = timestamp if timestamp else time()


class Topology(Model):
    '''
        Network topology graph.

        Attributes:
        -----------
        ...

        Methods:
        --------
        get_graph(): Returns NetworkX DiGraph object.

        get_node(id): Returns Node object identified by id.

        add_node(id, state, type, label, threshold): Create Node object and 
        add it to topology graph.

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

        get_by_ip(ipv4, attr): Returns value of attribute attr of interface 
        identified by ipv4 (attr can be 'node_id', 'name', 'mac', 'dpid', 
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

    def __init__(self):
        self._graph = DiGraph()
        self._src_port_to_dst = {}  # maps src id and port name to dst id
        self._num_to_name = {}  # maps node id and port number to port name
        self._interfaces = {}  # maps host interface mac to dict containing
        # node_id, name, ipv4, dpid, port_name, and port_no
        self._ips = {}  # maps host interface ipv4 to dict containing
        # node_id, name, mac, dpid, port_name, and port_no

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

    def add_node(self, id, state: bool, type: NodeType, label: str = None,
                 threshold: float = None):
        '''
            Create Node object and add it to topology graph.
        '''

        node = Node(id, state, type, label)
        if threshold == None:
            threshold = 1
        node.threshold = threshold
        self.get_graph().add_node(id, node=node)
        return True

    def delete_node(self, id):
        '''
            Delete node identified by id from topology graph (also deletes 
            associated interfaces and links).
        '''

        try:
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
            if ipv4:
                self._ips.setdefault(ipv4, {})
                self._ips[ipv4]['node_id'] = node_id
                self._ips[ipv4]['name'] = name
                self._ips[ipv4]['mac'] = mac
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

    def get_by_ip(self, ipv4: str, attr: str):
        '''
            Returns value of attribute attr of interface identified by ipv4 
            (attr can be 'node_id', 'name', 'mac', 'dpid', 'port_name', 
            or 'port_no'), None if it doesn't exist.
        '''

        return self._ips.get(ipv4, {}).get(attr, None)

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

    def set_main_interface(self, node_id, name: str):
        node = self.get_node(node_id)
        if node:
            node.main_interface = node.interfaces.get(name, None)
            return True
        return False


class CoSSpecs(Model):
    '''
        Set of minimum specs required to host network applications belonging 
        to Class of Service.

        Attributes:
        -----------
        max_response_time: Default is inf.

        min_concurrent_users: Default is 0.

        min_requests_per_second: Default is 0.

        min_bandwidth: Default is 0.

        max_delay: Default is inf.

        max_jitter: Default is inf (gross value; to get percentage, 
        multiply by 100).

        max_loss_rate: Default is 1.

        min_cpu: Default is 0.

        min_ram: Default is 0.

        min_disk: Default is 0.
    '''

    def __init__(self,
                 max_response_time: float = float('inf'),
                 min_concurrent_users: float = 0,
                 min_requests_per_second: float = 0,
                 min_bandwidth: float = 0,
                 max_delay: float = float('inf'),
                 max_jitter: float = float('inf'),
                 max_loss_rate: float = 1,
                 min_cpu: float = 0,
                 min_ram: float = 0,
                 min_disk: float = 0):
        self.max_response_time = max_response_time
        self.min_concurrent_users = min_concurrent_users
        self.min_requests_per_second = min_requests_per_second
        self.min_bandwidth = min_bandwidth
        self.max_delay = max_delay
        self.max_jitter = max_jitter
        self.max_loss_rate = max_loss_rate
        self.min_cpu = min_cpu
        self.min_ram = min_ram
        self.min_disk = min_disk


class CoS(Model):
    '''
        Class of Service.

        Recommendation: use provided getters and setters for specs in case 
        their structure changes in future updates.

        Attributes:
        -----------
        id: CoS ID.

        name: CoS name.

        specs: CoSSpecs object.
    '''

    def __init__(self, id: int, name: str, specs: CoSSpecs = None):
        self.id = id
        self.name = name
        self.specs = specs if specs else CoSSpecs()

    def as_dict(self, flat: bool = False, _prefix: str = ''):
        d = super().as_dict(flat, _prefix)
        if not flat:
            d['specs'] = self.specs.as_dict()
        else:
            if _prefix:
                _prefix += '_'
            del d[_prefix + 'specs']
            d.update(self.specs.as_dict(flat, _prefix=_prefix+'specs'))
        return d

    # the following methods serve for access to the CoS specs no matter how
    # they are implemented (whether they are attributes in the object, are
    # objects themselves within an Iterable, etc.)

    def get_max_response_time(self):
        return self.specs.max_response_time

    def set_max_response_time(self, max_response_time: float = float('inf')):
        self.specs.max_response_time = max_response_time

    def get_min_concurrent_users(self):
        return self.specs.min_concurrent_users

    def set_min_concurrent_users(self, min_concurrent_users: float = 0):
        self.specs.min_concurrent_users = min_concurrent_users

    def get_min_requests_per_second(self):
        return self.specs.min_requests_per_second

    def set_min_requests_per_second(self, min_requests_per_second: float = 0):
        self.specs.min_requests_per_second = min_requests_per_second

    def get_min_bandwidth(self):
        return self.specs.min_bandwidth

    def set_min_bandwidth(self, bandwidth: float = 0):
        self.specs.min_bandwidth = bandwidth

    def get_max_delay(self):
        return self.specs.max_delay

    def set_max_delay(self, delay: float = float('inf')):
        self.specs.max_delay = delay

    def get_max_jitter(self):
        return self.specs.max_jitter

    def set_max_jitter(self, max_jitter: float = float('inf')):
        self.specs.max_jitter = max_jitter

    def get_max_loss_rate(self):
        return self.specs.max_loss_rate

    def set_max_loss_rate(self, max_loss_rate: float = 1):
        self.specs.max_loss_rate = max_loss_rate

    def get_min_cpu(self):
        return self.specs.min_cpu

    def set_min_cpu(self, cpu: float = 0):
        self.specs.min_cpu = cpu

    def get_min_ram(self):
        return self.specs.min_ram

    def set_min_ram(self, ram: float = 0):
        self.specs.min_ram = ram

    def get_min_disk(self):
        return self.specs.min_disk

    def set_min_disk(self, disk: float = 0):
        self.specs.min_disk = disk


class Request(Model):
    '''
       Network application hosting request.

        Recommendation: use provided getters and setters for specs in case 
        their structure changes in future updates.

        Attributes:
        -----------
        id: Request ID.

        src: Source Node/IP.

        cos: Required CoS.

        data: Input data bytes.

        result: Execution result bytes.

        host: Network application host IP address.

        path: Path to network application host.

        state: Request state, enumeration of HREQ (1) (waiting for host), RREQ 
        (3) (waiting for resources), DREQ (6) (waiting for data), DRES (7) 
        (finished), and FAIL (0) (failed).

        hreq_at: Host request timestamp (start of operation).

        dres_at: Data exchange response timestamp (end of operation).

        attempts: Dict of request Attempts (keys are attempt numbers).

        Methods:
        --------
        new_attempt(): Create new attempt.
    '''

    _states = {
        HREQ: 'waiting for host',
        RREQ: 'waiting for resources',
        DREQ: 'waiting for data',
        DRES: 'finished',
        FAIL: 'failed'
    }

    def __init__(self, id, src, cos: CoS, data: bytes, result: bytes = None,
                 host: str = None, path: list = None, state: int = None,
                 hreq_at: float = None, dres_at: float = None,
                 attempts: dict = None):
        self.id = id
        self.src = src
        self.cos = cos
        self.data = data
        self.result = result
        self.host = host
        self.path = path
        self.state = state
        self.hreq_at = hreq_at
        self.dres_at = dres_at
        self.attempts = attempts if attempts != None else {}
        self._attempt_no = 0
        self._late = False
        self._host_mac_ip = None

    def _t(self, x):
        return datetime.fromtimestamp(x) if x != None else x

    def __repr__(self):
        src = self.src
        if isinstance(src, Node):
            src = src.id
        return ('\nrequest(id=%s, src=%s, state=(%s), cos=%s, host=%s, '
                'hreq_at=%s, dres_at=%s)\n' % (
                    self.id, src,
                    self._states[self.state] if self.state in self._states
                    else str(self.state),
                    self.cos.name, self.host, self._t(self.hreq_at),
                    self._t(self.dres_at)))

    def as_dict(self, flat: bool = False):
        d = super().as_dict(flat)
        del d['_late']
        if not flat:
            d['cos'] = self.cos.as_dict()
            if isinstance(self.src, Node):
                d['src'] = self.src.as_dict()
            for attempt_no, attempt in self.attempts.items():
                d['attempts'][attempt_no] = attempt.as_dict()
        else:
            del d['cos']
            d.update(self.cos.as_dict(flat, _prefix='cos'))
            if isinstance(self.src, Node):
                del d['src']
                d.update(self.src.as_dict(flat, _prefix='src'))
            del d['attempts']
            for attempt_no, attempt in self.attempts.items():
                d.update(attempt.as_dict(flat,
                                         _prefix='attempts_'+str(attempt_no)))
        return d

    def new_attempt(self):
        '''
            Create a new attempt.

            Returns Attempt object.
        '''

        self._attempt_no += 1
        attempt = Attempt(self.id, self._attempt_no)
        self.attempts[self._attempt_no] = attempt
        return attempt

    # the following methods serve for access to the CoS specs no matter how
    # they are implemented (whether they are attributes in the object, are
    # objects themselves within an Iterable, etc.)

    def get_max_response_time(self):
        return self.cos.get_max_response_time()

    def get_min_requests_per_second(self):
        return self.cos.get_min_requests_per_second()

    def get_min_concurrent_users(self):
        return self.cos.get_min_concurrent_users()

    def get_min_bandwidth(self):
        return self.cos.get_min_bandwidth()

    def get_max_delay(self):
        return self.cos.get_max_delay()

    def get_max_jitter(self):
        return self.cos.get_max_jitter()

    def get_max_loss_rate(self):
        return self.cos.get_max_loss_rate()

    def get_min_cpu(self):
        return self.cos.get_min_cpu()

    def get_min_ram(self):
        return self.cos.get_min_ram()

    def get_min_disk(self):
        return self.cos.get_min_disk()


class Attempt(Model):
    '''
        Network application hosting request attempt.

        Attributes:
        -----------
        req_id: Request ID.

        src: Source IP.

        attempt_no: Attempt number.

        host: Network application host IP address.

        path: Path to network application host.

        state: Attempt state, enumeration of HREQ (1) (waiting for host), RREQ 
        (3) (waiting for resources), DREQ (6) (waiting for data), DRES (7) 
        (finished).

        hreq_at: Host request timestamp (start of operation).

        hres_at: First host response timestamp (intermediate step).

        rres_at: Resource reservation response timestamp (intermediate step).

        dres_at: Data exchange response timestamp (end of operation).

        responses: Dict of attempt Responses (keys are responding hosts IPs).
    '''

    def __init__(self, req_id, src: str, attempt_no: int, host: str = None,
                 path: list = None, state: int = None, hreq_at: float = None,
                 hres_at: float = None, rres_at: float = None,
                 dres_at: float = None, responses: dict = None):
        self.req_id = req_id
        self.src = src
        self.attempt_no = attempt_no
        self.host = host
        self.path = path
        self.state = state
        self.hreq_at = hreq_at
        self.hres_at = hres_at
        self.rres_at = rres_at
        self.dres_at = dres_at
        self.responses = responses if responses != None else {}


class Response(Model):
    '''
        Network application hosting response.

        Attributes:
        -----------
        req_id: Request ID.

        src: Source IP.

        attempt_no: Attempt number.

        host: Network application host IP address.

        algorithm: Node selection algorithm used (SIMPLE, etc.).

        cpu: Amount of CPU offered by host.

        ram: RAM size offered by host.

        disk: Disk size offered by host.

        timestamp: Response timestamp.

        paths: List of attempt Paths.
    '''

    def __init__(self, req_id, src: str, attempt_no: int, host: str,
                 algorithm: str, cpu: float, ram: float, disk: float,
                 timestamp: float = 0, paths: list = None):
        self.req_id = req_id
        self.src = src
        self.attempt_no = attempt_no
        self.host = host
        self.algorithm = algorithm
        self.cpu = cpu
        self.ram = ram
        self.disk = disk
        self.timestamp = timestamp if timestamp else time()
        self.paths = paths if paths != None else []


class Path(Model):
    '''
        Path to network application host.

        Attributes:
        -----------
        req_id: Request ID.

        src: Source node IP.

        attempt_no: Attempt number.

        host: Network application host IP address.

        path: Path to network application host.

        algorithm: Path selection algorithm used (DIJKSTRA, LEASTCOST, etc.)

        bandwidths: List of path links bandwidths (in Mbps).

        delays: List of path links delays (in seconds).

        jitters: List of path links jitters (in seconds).

        loss_rates: List of path links loss rates (gross values; to get 
        percentages, multiply by 100).

        weight_type: Path weight type (HOP, DELAY, COST, etc.).

        weight: Path weight value.

        timestamp: Path timestamp.
    '''

    def __init__(self, req_id, src: str, attempt_no: int, host: str,
                 path: list, algorithm: str, bandwidths: list, delays: list,
                 jitters: list, loss_rates: list, weight_type: str,
                 weight: float, timestamp: float = 0):
        self.req_id = req_id
        self.src = src
        self.attempt_no = attempt_no
        self.host = host
        self.path = path
        self.algorithm = algorithm
        self.bandwidths = bandwidths
        self.delays = delays
        self.jitters = jitters
        self.loss_rates = loss_rates
        self.weight_type = weight_type
        self.weight = weight
        self.timestamp = timestamp if timestamp else time()
