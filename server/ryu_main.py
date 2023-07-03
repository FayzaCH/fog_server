from logging import getLogger, WARNING

from ryu.base.app_manager import RyuApp, require_app
from ryu.lib.hub import spawn, sleep
from ryu.controller.ofp_handler import OFPHandler
from ryu.topology.switches import Switches
from ryu.controller.dpset import DPSet
from ryu.app.wsgi import WSGIApplication

from ryu_apps import *
from ryu_main_api import RyuMainAPI
import dblib


require_app('ryu.app.rest_topology')

# hide WSGI messages on console
getLogger('ryu.lib.hub').setLevel(WARNING)


class RyuMain(RyuApp):
    '''
        Main Ryu app to launch with 'ryu run' or 'ryu-manager' commands. 
        Launches all custom Ryu apps defined in ryu_apps directory for flow 
        management, topology discovery, network monitoring, host selection 
        (among others).
    '''

    _CONTEXTS = {
        OFP_HANDLER: OFPHandler,
        SWITCHES: Switches,
        WSGI: WSGIApplication,
        SIMPLE_ARP: SimpleARP,
        NETWORK_MONITOR: NetworkMonitor,
        NETWORK_DELAY_DETECTOR: NetworkDelayDetector,
        DELAY_MONITOR: DelayMonitor,
        TOPOLOGY: Topology,
        TOPOLOGY_STATE: TopologyState,
        METRICS: Metrics,
        LOGGING: Logging,

        DPSET: DPSet,
        FLOW_MANAGER: FlowManager
    }
    if not STP_ENABLED:
        _CONTEXTS[SIMPLE_SWITCH_SP_13] = SimpleSwitchSP13
    if PROTO_SEND_TO == SEND_TO_ORCHESTRATOR:
        _CONTEXTS[PROTOCOL] = Protocol

    def __init__(self, *args, **kwargs):
        super(RyuMain, self).__init__(*args, **kwargs)
        self.switches = kwargs['switches']
        self.wsgi = kwargs['wsgi']
        self.wsgi.register(RyuMainAPI, {'ryu_main': self})
        if not STP_ENABLED:
            self.simple_switch_sp_13 = kwargs[SIMPLE_SWITCH_SP_13]
        self.simple_arp = kwargs[SIMPLE_ARP]
        self.network_monitor = kwargs[NETWORK_MONITOR]
        self.network_delay_detector = kwargs[NETWORK_DELAY_DETECTOR]
        self.delay_monitor = kwargs[DELAY_MONITOR]
        self.topology = kwargs[TOPOLOGY]
        self.topology_state = kwargs[TOPOLOGY_STATE]
        if PROTO_SEND_TO == SEND_TO_ORCHESTRATOR:
            self.protocol = kwargs[PROTOCOL]
        self.metrics = kwargs[METRICS]
        self.logging = kwargs[LOGGING]

        self.dpset = kwargs['dpset']
        self.flowmanager = kwargs[FLOW_MANAGER]
        self.flowmanager.wsgi = self.wsgi
        self.flowmanager.dpset = kwargs['dpset']

        # spawn(self._test)

    def _test(self):
        from pprint import pprint
        while True:
            sleep(1)
            '''
            print(self.simple_switch_sp_13._net)
            print()
            pprint(self.simple_switch_sp_13._outs)
            print()
            #'''
            '''
            pprint(self.simple_arp.arp_table)
            print()
            pprint(self.simple_arp._reverse_arp_table)
            print()
            pprint(self.simple_arp._in_ports)
            print()
            #'''
            '''
            pprint(self.topology._graph)
            print()
            pprint(self.topology._graph.nodes)
            print()
            pprint(self.topology._graph.edges)
            print()
            pprint(self.topology._src_port_to_dst)
            print()
            pprint(self.topology._num_to_name)
            print()
            pprint(self.topology._interfaces)
            print()
            #'''
            '''
            pprint(self.network_monitor.port_stats)
            print()
            pprint(self.network_monitor.port_features)
            print()
            pprint(self.network_monitor.port_speed)
            print()
            pprint(self.network_monitor.free_bandwidth)
            print()
            for src in self.network_monitor.loss_rate:
                for dst in self.network_monitor.loss_rate[src]:
                    loss = self.network_monitor.loss_rate[src][dst]
                    print(src, '-->', dst, round(loss * 100, 2), '%')
            print()
            pprint(self.network_monitor._loss_rate_at_port)
            print()
            #'''
            '''
            for src in self.network_delay_detector.lldp_latency:
                for dst in self.network_delay_detector.lldp_latency[src]:
                    lat = self.network_delay_detector.lldp_latency[src][dst]
                    print(src, '-->', dst, round(lat * 1000, 2), 'ms')
            print()
            for dpid in self.network_delay_detector.echo_latency:
                lat = self.network_delay_detector.echo_latency[dpid]
                print(dpid, '<-->', 'ctrl', round(lat * 1000, 2), 'ms')
            print()
            for src in self.network_delay_detector.delay:
                for dst in self.network_delay_detector.delay[src]:
                    lat = self.network_delay_detector.delay[src][dst]
                    print(src, '-->', dst, round(lat * 1000, 2), 'ms')
            print()
            #'''
            '''
            for ip, delay in self.delay_monitor.delay.items():
                print(ip, ':', round(delay * 1000, 2), 'ms')
            print()
            for mac, delay in self.delay_monitor._mac_delay.items():
                print(mac, ':', round(delay * 1000, 2), 'ms')
            print()
            pprint(self.delay_monitor._ip_2_mac)
            print()
            #'''
