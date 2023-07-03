''' 
================
    REST API
================

Note: * required field
      ** required for optional field
      URL {param} always required

1. Configuration REST API

1.1. Get configuration

GET /config

2. Node REST API

2.1. Add a node

POST /node
JSON request body: {
  * 'id': <Any>,
  * 'state': <bool>,
  * 'type': <str>,
    'label': <str>,
    'interfaces': [{
     ** 'name': <str>,
        'num': <int>,
        'mac': <str>,
        'ipv4': <str>,
        'link': {
         ** 'dst_id': <Any>,
         ** 'dst_port_name': <str>,
         ** 'state': <bool>,
        }
    }]
}

2.2. Delete a node

DELETE /node/{id}

3. Specs REST API

3.1. Update node specs

PUT /node_specs/{id}
JSON request body: {
    'timestamp': <float>,
    'cpu_count': <int>,
    'memory_free': <float>,
    'disk_free': <float>,
    'interfaces': [{
     ** 'name': <str>,
        'bandwidth_up': <float>,
        'bandwidth_down': <float>,
        'tx_packets': <int>,
        'rx_packets': <int>
    }]
}

================
'''


from os import getenv
from time import time
from json import load

from ryu.app.wsgi import route, Response, ControllerBase

from networkx import draw
from matplotlib.pyplot import savefig, clf

from model import NodeType
from ryu_apps.common import (DECOY_IP, DECOY_MAC, MONITOR_PERIOD,
                             PROTO_SEND_TO, STP_ENABLED)
from ryu_apps.protocol import PROTO_RETRIES, PROTO_TIMEOUT
from ryu_apps.topology import UDP_PORT, UDP_TIMEOUT
from consts import ROOT_PATH
import config


SIM_ON = getenv('SIMULATOR_ACTIVE', False) == 'True'

# simulated exec time interval
try:
    SIM_EXEC_MIN = float(getenv('SIMULATOR_EXEC_MIN', None))
    try:
        SIM_EXEC_MAX = float(getenv('SIMULATOR_EXEC_MAX', None))
        if SIM_EXEC_MAX < SIM_EXEC_MIN:
            print(' *** WARNING in ryu_main_api: '
                  'SIMULATOR:EXEC_MIN and SIMULATOR:EXEC_MAX parameters invalid. '
                  'Defaulting to [0s, 1s].')
            SIM_EXEC_MIN = 0
            SIM_EXEC_MAX = 1
    except:
        print(' *** WARNING in ryu_main_api: '
              'SIMULATOR:EXEC_MAX parameter invalid or missing from conf.yml. '
              'Defaulting to [0s, 1s].')
        SIM_EXEC_MIN = 0
        SIM_EXEC_MAX = 1
except:
    print(' *** WARNING in ryu_main_api: '
          'SIMULATOR:EXEC_MIN parameter invalid or missing from conf.yml. '
          'Defaulting to [0s, 1s].')
    SIM_EXEC_MIN = 0
    SIM_EXEC_MAX = 1

HTTP_SUCCESS = 200
HTTP_EXISTS = 303
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_INTERNAL = 500


class RyuMainAPI(ControllerBase):
    '''
        Controller for RyuMain app that handles routing of, and responding 
        to REST API requests.
    '''

    def __init__(self, req, link, data, **config):
        super(RyuMainAPI, self).__init__(req, link, data, **config)
        self.ryu_main = data['ryu_main']

    # this route is used by gui_topology
    # @route('root', '/')
    def root(self, _):
        return 'API is working!'

    @route('config', '/config', methods=['GET'])
    def get_config(self, req):
        return Response(content_type='application/json', json={
            'CONTROLLER_DECOY_MAC': DECOY_MAC,
            'CONTROLLER_DECOY_IP': DECOY_IP,
            'ORCHESTRATOR_UDP_PORT': UDP_PORT,
            'ORCHESTRATOR_UDP_TIMEOUT': UDP_TIMEOUT,
            'NETWORK_STP_ENABLED': STP_ENABLED,
            'PROTOCOL_SEND_TO': PROTO_SEND_TO,
            'PROTOCOL_TIMEOUT': PROTO_TIMEOUT,
            'PROTOCOL_RETRIES': PROTO_RETRIES,
            'SIMULATOR_ACTIVE': SIM_ON,
            'SIMULATOR_EXEC_MIN': SIM_EXEC_MIN,
            'SIMULATOR_EXEC_MAX': SIM_EXEC_MAX,
            'MONITOR_PERIOD': MONITOR_PERIOD,
            'DATABASE_COS': load(open(ROOT_PATH + '/cos.json')),
        })

    @route('node', '/node', methods=['POST'])
    def add_node(self, req):
        # queue for functions to be called after POST data validation
        # structure: [(func, kwargs), ...]
        queue = []
        json = req.json
        try:
            # check if node already exists
            if self.ryu_main.topology.get_node(json['id']):
                return Response(status=HTTP_EXISTS)

            # check if required data fields available with correct types
            # and add function and kwargs to queue
            queue.append((self._add_node, {
                'id': json['id'],
                'state': bool(json['state']),
                'type': NodeType(json['type']),
            }))

            # check if optional data fields available with correct types
            # and add to kwargs
            queue[-1][1]['label'] = str(json['label']) if (
                'label' in json) else None

            # node can be added with interfaces
            if 'interfaces' in json:
                for interface in json['interfaces']:
                    #  required data fields for interfaces
                    queue.append((self._add_interface, {
                        'node_id': json['id'],
                        'name': str(interface['name']),
                    }))

                    # optional data fields for interfaces
                    try:
                        queue[-1][1]['num'] = int(interface['num'])
                    except (KeyError, TypeError, ValueError):
                        queue[-1][1]['num'] = None
                    queue[-1][1]['mac'] = str(interface['mac']) if (
                        'mac' in interface) else None
                    queue[-1][1]['ipv4'] = str(interface['ipv4']) if (
                        'ipv4' in interface) else None

                    # interface can be added with link
                    if 'link' in interface:
                        link = interface['link']
                        # check if dst node and port exist
                        dst_id = link['dst_id']
                        if self.ryu_main.topology.get_node(dst_id):
                            dst_port_name = str(link['dst_port_name'])
                            if self.ryu_main.topology.get_interface(
                                    dst_id, dst_port_name):
                                # required data fields for link
                                queue.append((self._add_link, {
                                    'src_id': json['id'],
                                    'dst_id': dst_id,
                                    'src_port_name': str(interface['name']),
                                    'dst_port_name': dst_port_name,
                                    'state': bool(link['state']),
                                }))

                            else:
                                return Response(dst_port_name,
                                                status=HTTP_NOT_FOUND)

                        else:
                            return Response(dst_id, status=HTTP_NOT_FOUND)

        except (KeyError, TypeError, ValueError) as e:
            return Response(str(e), status=HTTP_BAD_REQUEST)

        except Exception as e:
            print(' *** ERROR in ryu_main_api.add_node:',
                  e.__class__.__name__, e)
            return Response(status=HTTP_INTERNAL)

        # once POST data is parsed and validated, call functions in queue
        for func, kwargs in queue:
            if func(**kwargs) == False:
                # if error, undo everything by deleting node
                # this will also delete interfaces and links
                self.ryu_main.topology.delete_node(json['id'])
                return Response(status=HTTP_INTERNAL)

    @route('node', '/node/{id}', methods=['DELETE'])
    def delete_node(self, _, id):
        self.ryu_main.topology.delete_node(id)

    @route('ryu_main', '/node_specs/{id}', methods=['PUT'])
    def update_node_specs(self, req, id):
        #  check if resource exists
        if not self.ryu_main.topology.get_node(id):
            try:
                id = int(id)
            except (TypeError, ValueError):
                return Response(status=HTTP_NOT_FOUND)
            if not self.ryu_main.topology.get_node(id):
                return Response(status=HTTP_NOT_FOUND)

        # queue for functions to be called after PUT data validation
        #  structure: [(func, kwargs), ...]
        queue = []
        try:
            # check if required data fields available with correct types
            # and add function and kwargs to queue
            queue.append((self._update_node_specs, {
                'id': id,
            }))

            # check if optional data fields available with correct types
            # and add to kwargs
            json = req.json
            timestamp = float(json['timestamp']) if (
                'timestamp' in json) else time()
            queue[-1][1]['timestamp'] = timestamp
            queue[-1][1]['cpu_count'] = int(json['cpu_count']) if (
                'cpu_count' in json) else None
            queue[-1][1]['memory_free'] = float(json['memory_free']) if (
                'memory_free' in json) else None
            queue[-1][1]['disk_free'] = float(json['disk_free']) if (
                'disk_free' in json) else None

            if 'interfaces' in json:
                for interface in json['interfaces']:
                    queue.append((self._update_interface_specs, {
                        'node_id': id,
                        'name': str(interface['name']),
                    }))
                    queue[-1][1]['timestamp'] = timestamp
                    queue[-1][1]['bandwidth_up'] = float(
                        interface['bandwidth_up']) if (
                            'bandwidth_up' in interface) else None
                    queue[-1][1]['bandwidth_down'] = float(
                        interface['bandwidth_down']) if (
                            'bandwidth_down' in interface) else None
                    queue[-1][1]['tx_packets'] = int(
                        interface['tx_packets']) if (
                            'tx_packets' in interface) else None
                    queue[-1][1]['rx_packets'] = int(
                        interface['rx_packets']) if (
                            'rx_packets' in interface) else None

        except (KeyError, TypeError, ValueError):
            return Response(status=HTTP_BAD_REQUEST)

        # once PUT data is parsed and validated, call functions in queue
        for func, kwargs in queue:
            func(**kwargs)

    # for testing
    @route('test', '/topology_png')
    def topology(self, _):
        clf()
        draw(self.ryu_main.topology.get_graph(), with_labels=True)
        savefig(ROOT_PATH + '/data/' + str(time()) + '.png')

    def _add_node(self, **kwargs):
        return self.ryu_main.topology.add_node(
            kwargs['id'], kwargs['state'], kwargs['type'],
            kwargs.get('label', None))

    def _add_interface(self, **kwargs):
        return self.ryu_main.topology.add_interface(
            kwargs['node_id'], kwargs['name'], kwargs.get('num', None),
            kwargs.get('mac', None), kwargs.get('ipv4', None))

    def _add_link(self, **kwargs):
        return self.ryu_main.topology.add_link(
            kwargs['src_id'], kwargs['dst_id'], kwargs['src_port_name'],
            kwargs['dst_port_name'], kwargs['state'])

    def _update_node_specs(self, **kwargs):
        return self.ryu_main.topology_state.update_node_specs(
            kwargs['id'], kwargs.get('cpu_count', None),
            kwargs.get('memory_free', None), kwargs.get('disk_free', None),
            kwargs.get('timestamp', time()))

    def _update_interface_specs(self, **kwargs):
        return self.ryu_main.topology_state.update_interface_specs(
            kwargs['node_id'], kwargs['name'],
            kwargs.get('bandwidth_up', None),
            kwargs.get('bandwidth_down', None),
            kwargs.get('tx_packets', None),
            kwargs.get('rx_packets', None),
            kwargs.get('timestamp', time()))
