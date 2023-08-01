from ryu.base.app_manager import RyuApp
from ryu.lib.hub import spawn, sleep

from common import *
import config


_monitor_verbose = getenv('MONITOR_VERBOSE', '').upper()
if _monitor_verbose not in ('TRUE', 'FALSE'):
    _monitor_verbose = 'FALSE'
MONITOR_VERBOSE = _monitor_verbose == 'TRUE'


class Logging(RyuApp):
    '''
        Ryu app for displaying various information on the controller's 
        console, such as node and link specs. 

        Requirements:
        -------------
        Topology app: for network topology.

        Methods:
        --------
        show_node_stats(): Print node specs (CPU, RAM, disk) on console.

        show_link_stats(): Print link specs (bandwidth, delay, jitter, loss 
        rate, state) on console.
    '''

    def __init__(self, *args, **kwargs):
        super(Logging, self).__init__(*args, **kwargs)
        self.name = LOGGING

        self._topology = get_app(TOPOLOGY)

        if MONITOR_VERBOSE:
            spawn(self._log)

    def _log(self):
        while True:
            sleep(MONITOR_PERIOD)
            self.show_node_stats()
            self.show_link_stats()

    def show_node_stats(self):
        '''
            Print nodes (ID, label) and their specs (CPU, RAM, disk) 
            on console.
        '''

        header = False
        for node in list(self._topology.get_nodes().values()):
            if not header:
                print()
                print('           Node ID |          Label |'
                      '   CPUs   Free CPUs   RAM (MB)   Free RAM (MB)'
                      '   Disk (GB)   Free disk (GB)')
                header = True
            print(' {:>17} | {:>14} |'
                  '   {:>4}   {:>9}   {:>8}   {:>13}'
                  '   {:>9}   {:>14}'.format(
                      node.id, node.label, node.get_cpu_count(),
                      round(node.get_cpu_free(), 2),
                      round(node.get_memory_total(), 2),
                      round(node.get_memory_free(), 2),
                      round(node.get_disk_total(), 2),
                      round(node.get_disk_free(), 2)))
        if header:
            print()

    def show_link_stats(self):
        '''
            Print links (src, dst) and their specs (capacity, bandwidth, 
            delay, jitter, loss rate, state) on console.
        '''

        _states = {
            True: 'UP',
            False: 'DOWN'
        }
        header = False
        for src_id, src_links in list(self._topology.get_links().items()):
            src = self._topology.get_node(src_id)
            if src:
                for dst_id, link in list(src_links.items()):
                    dst = self._topology.get_node(dst_id)
                    if dst:
                        if not header:
                            print()
                            print('            SRC -> DST            |'
                                  '   Capacity (Mbps)   Bandwidth (Mbps)'
                                  '   Delay (ms)   Jitter (ms)   Loss (%)'
                                  '   |   State')
                            header = True
                        print(' {:>14} -> {:<14} |   {:>15}   {:>16}'
                              '   {:>10}   {:>11}   {:>8}   |   {}'.format(
                                  src.label, dst.label,
                                  round(link.get_capacity(), 2),
                                  round(link.get_bandwidth(), 2),
                                  round(link.get_delay() * 1000, 2),
                                  round(link.get_jitter() * 1000, 2),
                                  round(link.get_loss_rate() * 100, 2),
                                  _states.get(link.state, 'N/A')))
        if header:
            print()
