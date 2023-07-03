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
        update_node_specs(id, cpu, ram, disk, timestamp): Update specs (CPU, 
        RAM, disk) of node identified by ID at given timestamp.

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

        self._no_update = {}
        spawn(self._update_delay_jitter)
        spawn(self._update_bandwidth_loss_rate)
        spawn(self._update_node_state)
        spawn(self._update_link_state)
        spawn(self._check_update)

    def update_node_specs(self, id, cpu: int = None, ram: float = None,
                          disk: float = None, timestamp: float = 0):
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
            if cpu != None:
                node.set_cpu(cpu)
            if ram != None:
                node.set_ram(ram)
            if disk != None:
                node.set_disk(disk)
            return True
        return False

    def update_interface_specs(self, node_id, ref, bandwidth_up: float = None,
                               bandwidth_down: float = None,
                               tx_packets: int = None, rx_packets: int = None,
                               timestamp: float = 0):
        '''
            Update specs (bandwidth_up, bandwidth_down, tx_packets, rx_packets) 
            of interface identified by name and attached to node identified by 
            node_id at given timestamp.
        '''

        interface = self._topology.get_interface(node_id, ref)
        if interface:
            interface.set_timestamp(timestamp)
            # None values are used to differentiate from 0
            # None means don't update
            if bandwidth_up != None:
                interface.set_bandwidth_up(bandwidth_up)
            if bandwidth_down != None:
                interface.set_bandwidth_down(bandwidth_down)
            if tx_packets != None:
                interface.set_tx_packets(tx_packets)
            if rx_packets != None:
                interface.set_rx_packets(rx_packets)
            # if specs are updated through API
            # don't update specs from other apps
            self._no_update[node_id] = time()
            self.update_link_specs_at_port(node_id, ref, bandwidth_up, None,
                                           tx_packets, timestamp)

    def update_link_specs(self, src_id, dst_id, bandwidth: float = None,
                          delay: float = None, jitter: float = None,
                          loss_rate: float = None, timestamp: float = 0):
        '''
            Update specs (bandwidth, delay, jitter, loss rate) of link between 
            nodes identified by src_id and dst_id at given timestamp.

            Returns True if updated, False if not.
        '''

        link = self._topology.get_link(src_id, dst_id)
        if link:
            link.set_timestamp(timestamp)
            # None values are used to differentiate from 0
            # None means don't update
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

    def update_link_specs_at_port(self, src_id, port_ref,
                                  bandwidth_up: float = None,
                                  loss_rate: float = None,
                                  tx_packets: int = None,
                                  timestamp: float = 0):
        '''
            Update specs (bandwidth, delay, jitter, loss rate) of link 
            connected to port identified by port_ref (which can be name or 
            number) and attached to node identified by src_id at given 
            timestamp.

            Returns True if updated, False if not.
        '''

        link = self._topology.get_link_at_port(src_id, port_ref)
        if link:
            dst = link.dst_port
            if bandwidth_up != None:
                # link bandwidth is min of src port up bandwidth and dst port
                # down bandwidth
                link.set_bandwidth(
                    min(bandwidth_up, dst.get_bandwidth_down()))
            if loss_rate != None:
                link.set_loss_rate(loss_rate)
            elif tx_packets != None:
                try:
                    link.set_loss_rate(max(
                        0, (tx_packets - dst.get_rx_packets()) / tx_packets))
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
        # update link bandwidth and loss rate from network_monitor
        while True:
            sleep(MONITOR_PERIOD)

            bandwidths = self._network_monitor.free_bandwidth
            loss_rates = self._network_monitor._loss_rate_at_port
            port_stats = self._network_monitor.port_stats
            for dpid, ports in list(bandwidths.items()):
                if dpid not in self._no_update:
                    for port_no, (bw_up, bw_down) in list(ports.items()):
                        port = self._topology.get_interface(dpid, port_no)
                        if port:
                            port.set_bandwidth_up(bw_up)
                            port.set_bandwidth_down(bw_down)
                            key = (dpid, port_no)
                            stat = port_stats.get(key, None)
                            tx_packets = stat[-1][2] if stat else None
                            rx_packets = stat[-1][3] if stat else None
                            if stat:
                                port.set_tx_packets(tx_packets)
                                port.set_rx_packets(rx_packets)
                            self.update_link_specs_at_port(
                                dpid, port_no, bw_up,
                                loss_rates.get(key, None), tx_packets)

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
            for id, timestamp in list(self._no_update.items()):
                if now - timestamp > period:
                    self._no_update.pop(id, None)
