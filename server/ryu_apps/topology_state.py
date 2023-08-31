from time import time

from ryu.base.app_manager import RyuApp
from ryu.lib.hub import spawn, sleep

from common import *


class TopologyState(RyuApp):
    '''
        Ryu app for updating specs of topology's nodes, interfaces and links
        by injecting most recent measures collected by various monitoring apps
        (NetworkMonitor, NetworkDelayDetector, DelayMonitor), as well as
        measures received from clients through REST API, into data structures
        in Topology app.

        Requirements:
        -------------
        Topology app: for network graph.

        NetworkMonitor app: for bandwidth.

        NetworkDelayDetector app: for switch link delays.

        DelayMonitor app: for host link delays.

        Methods:
        --------
        update_node_specs(id, cpu_count, cpu_free, memory_total, memory_free,
        disk_total, disk_free, timestamp): Update specs (CPU, RAM, disk) of
        node identified by ID at given timestamp.

        update_interface_specs(node_id, ref, bandwidth_up, bandwidth_down,
        tx_packets, rx_packets, timestamp): Update specs (bandwidth_up,
        bandwidth_down, tx_packets, rx_packets) of interface identified by ref
        (which can be name or number) and attached to node identified by
        node_id at given timestamp.

        update_link_specs(src_id, dst_id, bandwidth, delay, jitter, loss_rate,
        timestamp): Update specs (bandwidth, delay, jitter, loss rate) of link
        between nodes identified by src_id and dst_id at given timestamp.

        update_link_specs_at_port(self, src_id, port_ref, bandwidth_up,
        loss_rate, tx_packets, timestamp): Update specs (bandwidth, delay,
        jitter, loss rate) of link connected to port identified by port_ref
        (which can be name or number) and attached to node identified by src_id
        at given timestamp.
    '''

    def __init__(self, *args, **kwargs):
        super(TopologyState, self).__init__(*args, **kwargs)
        self.name = TOPOLOGY_STATE

        self._topology = get_app(TOPOLOGY)
        self._network_monitor = get_app(NETWORK_MONITOR)
        self._network_delay_detector = get_app(NETWORK_DELAY_DETECTOR)
        self._delay_monitor = get_app(DELAY_MONITOR)

        self._block_app_update = {}
        self._port_stats = {}
        self._iperf3_update = {}
        spawn(self._update_delay_jitter)
        spawn(self._update_bandwidth_loss_rate)
        spawn(self._update_node_state)
        spawn(self._update_link_state)
        spawn(self._check_update)

    def _save_stats(self, _dict, key, value, length):
        _dict.setdefault(key, [])
        _dict[key].append(value)
        if len(_dict[key]) > length:
            _dict[key].pop(0)

    def update_node_specs(self, id, cpu_count: int = None,
                          cpu_free: float = None, memory_total: float = None,
                          memory_free: float = None, disk_total: float = None,
                          disk_free: float = None, timestamp: float = 0):
        '''
            Update specs (CPU, RAM, disk) of node identified by ID at given
            timestamp (default, 0, means current timestamp).

            Returns True if updated, False if not.
        '''

        node = self._topology.get_node(id)
        if node:
            node.set_timestamp(timestamp)
            # None values are used to differentiate from 0
            # None means don't update
            if cpu_count != None:
                node.set_cpu_count(cpu_count)
            if cpu_free != None:
                node.set_cpu_free(cpu_free)
            if memory_total != None:
                node.set_memory_total(memory_total)
            if memory_free != None:
                node.set_memory_free(memory_free)
            if disk_total != None:
                node.set_disk_total(disk_total)
            if disk_free != None:
                node.set_disk_free(disk_free)
            return True
        return False

    def update_interface_specs(self, node_id, name: str,
                               capacity: float = None,
                               bandwidth_up: float = None,
                               bandwidth_down: float = None,
                               tx_packets: int = None, rx_packets: int = None,
                               tx_bytes: int = None, rx_bytes: int = None,
                               timestamp: float = 0, _recv_bps: float = None):
        '''
            Update specs (capacity, bandwidth_up, bandwidth_down, tx_packets,
            rx_packets, tx_bytes, rx_bytes) of interface identified by name 
            and attached to node identified by node_id at given timestamp.
        '''

        interface = self._topology.get_interface(node_id, name)
        if interface:
            key = (node_id, name)
            # stop specs from updating through ryu apps
            self._block_app_update[key] = time()
            interface.set_timestamp(timestamp)
            # None values are used to differentiate from 0
            # None means don't update
            if key not in self._iperf3_update:
                if capacity != None:
                    interface.set_capacity(capacity)
                if bandwidth_up != None:
                    interface.set_bandwidth_up(bandwidth_up)
                if bandwidth_down != None:
                    interface.set_bandwidth_down(bandwidth_down)
            if tx_packets != None:
                interface.set_tx_packets(tx_packets)
            if rx_packets != None:
                interface.set_rx_packets(rx_packets)
            if tx_bytes != None:
                interface.set_tx_bytes(tx_bytes)
            if rx_bytes != None:
                interface.set_rx_bytes(rx_bytes)
            self._update_link_specs_at_port(node_id, name, tx_packets,
                                            rx_packets, tx_bytes, rx_bytes,
                                            timestamp, _recv_bps)

    def update_link_specs(self, src_id, dst_id, capacity: float = None,
                          bandwidth: float = None, delay: float = None,
                          jitter: float = None, loss_rate: float = None,
                          timestamp: float = 0):
        '''
            Update specs (capacity, bandwidth, delay, jitter, loss rate) of
            link between nodes identified by src_id and dst_id at given
            timestamp.

            Returns True if updated, False if not.
        '''

        link = self._topology.get_link(src_id, dst_id)
        if link:
            link.set_timestamp(timestamp)
            # None values are used to differentiate from 0
            # None means don't update
            if capacity != None:
                link.set_capacity(capacity)
            if bandwidth != None:
                link.set_bandwidth(bandwidth)
            if delay != None:
                link.set_delay(delay)
            if jitter != None:
                link.set_jitter(jitter)
            if loss_rate != None:
                link.set_loss_rate(loss_rate)
            return True
        return False

    def _update_link_specs_at_port(self, src_id, port_name: str,
                                   tx_packets: int = None,
                                   rx_packets: int = None,
                                   tx_bytes: int = None,
                                   rx_bytes: int = None,
                                   timestamp: float = 0,
                                   _recv_bps: float = None):
        '''
            Update specs (capacity, bandwidth, delay, jitter, loss rate) of
            link connected to port identified by port_ref (which can be name
            or number) and attached to node identified by src_id at given
            timestamp.

            Returns True if updated, False if not.
        '''

        key = (src_id, port_name)
        self._save_stats(self._port_stats, key,
                         (tx_packets, rx_packets, tx_bytes, rx_bytes),
                         MONITOR_SAMPLES)
        link = self._topology.get_link_at_port(src_id, port_name)
        if link:
            src = link.src_port
            dst = link.dst_port
            dst_key = (self._topology.get_dst_at_port(src_id, port_name).id,
                       dst.name)

            if _recv_bps != None:
                self._iperf3_update[dst_key] = time()
                dst_cap = _recv_bps / 10**6
                dst.set_capacity(dst_cap)
                if dst_key in self._port_stats:
                    tmp = self._port_stats[dst_key]
                    up_pre = 0
                    down_pre = 0
                    if len(tmp) > 1:
                        up_pre = tmp[-2][2]
                        down_pre = tmp[-2][3]
                    up_speed = ((tmp[-1][2] - up_pre) / MONITOR_PERIOD) * 8
                    down_speed = ((tmp[-1][3] - down_pre) / MONITOR_PERIOD) * 8
                    dst.set_bandwidth_up(
                        max(0, (dst_cap - up_speed * 8/10**6)))
                    dst.set_bandwidth_down(
                        max(0, (dst_cap - down_speed * 8/10**6)))

            # link capacity is min of src port capacity and dst port
            # capacity
            link.set_capacity(min(src.get_capacity(), dst.get_capacity()))
            # link bandwidth is min of src port up bandwidth and dst port
            # down bandwidth
            link.set_bandwidth(min(src.get_bandwidth_up(),
                                   dst.get_bandwidth_down()))

            if tx_packets != None:
                try:
                    re_tx_packets = (tx_packets
                                     - self._port_stats[key][0][0])
                    re_rx_packets = (dst.get_rx_packets()
                                     - self._port_stats[dst_key][0][1])
                    link.set_loss_rate(max(
                        0, (re_tx_packets - re_rx_packets) / re_tx_packets))
                except:
                    link.set_loss_rate(1)
            link.set_timestamp(timestamp)
            return True
        return False

    def _update_delay_jitter(self):
        # update link delay and jitter from network_delay_detector
        # and delay_monitor
        while True:
            sleep(MONITOR_PERIOD)
            delays = self._network_delay_detector.delay
            jitters = self._network_delay_detector.jitter
            for src_id, dsts in list(delays.items()):
                for dst_id, delay in list(dsts.items()):
                    self.update_link_specs(
                        src_id, dst_id, delay=delay,
                        jitter=jitters.get(src_id, {}).get(dst_id, None))
            delays = self._delay_monitor._mac_delay
            jitters = self._delay_monitor._mac_jitter
            for mac, delay in list(delays.items()):
                node_id = self._topology.get_by_mac(mac, 'node_id')
                dpid = self._topology.get_by_mac(mac, 'dpid')
                delay_1_way = delay / 2
                jitter = jitters.get(mac, None)
                jitter_1_way = jitter / 2 if jitter != None else None
                self.update_link_specs(node_id, dpid, delay=delay_1_way,
                                       jitter=jitter_1_way)
                self.update_link_specs(dpid, node_id, delay=delay_1_way,
                                       jitter=jitter_1_way)

    def _update_bandwidth_loss_rate(self):
        # update link capacity, bandwidth and loss rate from network_monitor
        while True:
            sleep(MONITOR_PERIOD)
            features = self._network_monitor.port_features
            bandwidths = self._network_monitor.free_bandwidth
            port_stats = self._network_monitor.port_stats
            for dpid, ports in list(bandwidths.items()):
                for port_no, (bw_up, bw_down) in list(ports.items()):
                    port = self._topology.get_interface(dpid, port_no)
                    if port:
                        name = port.name
                        key = (dpid, name)
                        if key not in self._block_app_update:
                            feature = features.get(dpid, {}).get(port_no, None)
                            capacity = feature[2] / 10**3 if feature else None
                            port.set_capacity(capacity)
                            port.set_bandwidth_up(bw_up)
                            port.set_bandwidth_down(bw_down)
                            stat = port_stats.get((dpid, port_no), None)
                            if stat:
                                tx_packets = stat[-1][2]
                                rx_packets = stat[-1][3]
                                port.set_tx_packets(tx_packets)
                                port.set_rx_packets(rx_packets)
                            else:
                                tx_packets = None
                                rx_packets = None
                            self._update_link_specs_at_port(
                                dpid, name, tx_packets, rx_packets)

    def _update_node_state(self):
        # TODO update node state
        while True:
            sleep(MONITOR_PERIOD)

    def _update_link_state(self):
        link_states = {
            'Down': False,
            'Blocked': False,
            'Live': True,
        }
        while True:
            sleep(MONITOR_PERIOD)
            feats = self._network_monitor.port_features
            for dpid, ports in list(feats.items()):
                for port_no, feat in list(ports.items()):
                    link1, link2 = self._topology.get_links_at_port(dpid,
                                                                    port_no)
                    state = link_states[feat[1]]
                    if link1:
                        link1.state = state
                    if link2:
                        link2.state = state

    def _check_update(self):
        # check if node interfaces (mainly switch ports) specs are updating
        # through API
        period = MONITOR_PERIOD + 1
        while True:
            sleep(period)
            now = time()
            for key, timestamp in list(self._block_app_update.items()):
                if now - timestamp > period:
                    self._block_app_update.pop(key, None)
            for key, timestamp in list(self._iperf3_update.items()):
                if now - timestamp > period:
                    self._iperf3_update.pop(key, None)
