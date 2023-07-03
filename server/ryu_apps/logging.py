from ryu.base.app_manager import RyuApp
from ryu.lib.hub import spawn, sleep

from common import *


MONITOR_VERBOSE = getenv('MONITOR_VERBOSE', False) == 'True'


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
            Print node specs (CPU, RAM, disk) on console.
        '''

        header = False
        for node in list(self._topology.get_nodes().values()):
            if not header:
                print()
                print(' node              | cpu    ram (MB)    disk (GB)')
                header = True
            print(' {:<17} | {:>3}    {:>8}    {:>9}'.format(
                node.label, node.get_cpu(), round(node.get_ram(), 2),
                round(node.get_disk(), 2)))
        if header:
            print()

    def show_link_stats(self):
        '''
            Print link specs (bandwidth, delay, jitter, loss rate, state) 
            on console.
        '''

        header = False
        for src_id, src_links in list(self._topology.get_links().items()):
            src = self._topology.get_node(src_id)
            if src:
                for dst_id, link in list(src_links.items()):
                    dst = self._topology.get_node(dst_id)
                    if dst:
                        if not header:
                            print()
                            print('               src ---> dst               |'
                                  ' bandwidth (Mbit/s)    delay (ms)    '
                                  'jitter (ms)    loss rate (%) |   state')
                            header = True
                        print(' {:>17} ---> {:<17} | {:>18}    {:>10}    '
                              '{:>11}    {:>13} |   {}'.format(
                                  src.label, dst.label,
                                  round(link.get_bandwidth(), 2),
                                  round(link.get_delay() * 1000, 2),
                                  round(link.get_jitter() * 1000, 2),
                                  round(link.get_loss_rate() * 100, 2),
                                  link.state))
        if header:
            print()
