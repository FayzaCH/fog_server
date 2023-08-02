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

2.1. Add a node and its interfaces

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
    }]
}

2.2. Delete a node

DELETE /node/{id}

3. Specs REST API

3.1. Update node specs and its interfaces specs

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

4. Request REST API

4.1. Add a request, its attempts and its responses

POST /request
JSON request body: {
  * 'id': <str>,
  * 'src': <str>,
  * 'cos_id': <int>,
  * 'data': <str>, # will be encoded to bytes
  * 'result': <str>, # will be encoded to bytes
  * 'host': <str>,
  * 'state': <int>,
  * 'hreq_at': <float>,
  * 'dres_at': <float>,
  * 'attempts': [{
      * 'attempt_no': <int>,
      * 'host': <str>,
      * 'state': <int>,
      * 'hreq_at': <float>,
      * 'hres_at': <float>,
        'rres_at': <float>,
      * 'dres_at': <float>,
        'responses: [{
         ** host: <str>,
         ** cpu: <float>,
         ** ram: <float>,
         ** disk: <float>,
         ** timestamp: <float>
        }]
    }]
}

================
'''


from os import getenv
from time import time
from json import load

from ryu.app.wsgi import route, Response as HTTPResponse, ControllerBase

from networkx import draw
from matplotlib.pyplot import savefig, clf

from model import NodeType, Request, Attempt, Response, Path, CoS
from ryu_apps.common import (DECOY_IP, DECOY_MAC, MONITOR_PERIOD,
                             PROTO_SEND_TO, STP_ENABLED, ORCHESTRATOR_PATHS)
from ryu_apps.protocol import PROTO_RETRIES, PROTO_TIMEOUT
from ryu_apps.topology import UDP_PORT, UDP_TIMEOUT
from consts import ROOT_PATH, SEND_TO_ORCHESTRATOR
import config


node_algo = PROTO_SEND_TO
path_algo = 'STP'
path_weight = 'STP'
if PROTO_SEND_TO == SEND_TO_ORCHESTRATOR:
    from ryu_apps.common import NODE_ALGO
    node_algo = NODE_ALGO
    if not STP_ENABLED:
        path_algo = 'SHORTEST'
        path_weight = 'HOP'
        if ORCHESTRATOR_PATHS:
            from ryu_apps.common import PATH_ALGO, PATH_WEIGHT
            path_algo = PATH_ALGO
            path_weight = PATH_WEIGHT


NETWORK_ADDRESS = getenv('NETWORK_ADDRESS', None)
if not NETWORK_ADDRESS:
    print(' *** ERROR in ryu_main_api: '
          'NETWORK:ADDRESS parameter missing from conf.yml.')
    exit()

_sim_on = getenv('SIMULATOR_ACTIVE', '').upper()
if _sim_on not in ('TRUE', 'FALSE'):
    print(' *** WARNING in ryu_main_api: '
          'SIMULATOR:ACTIVE parameter invalid or missing from conf.yml. '
          'Defaulting to False.')
    _sim_on = 'FALSE'
SIM_ON = _sim_on == 'TRUE'

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

    @route('root', '/')
    def root(self, _):
        return 'API is working!'

    @route('config', '/config', methods=['GET'])
    def get_config(self, req):
        return HTTPResponse(content_type='application/json', json={
            'CONTROLLER_DECOY_MAC': DECOY_MAC,
            'CONTROLLER_DECOY_IP': DECOY_IP,
            'ORCHESTRATOR_UDP_PORT': UDP_PORT,
            'ORCHESTRATOR_UDP_TIMEOUT': UDP_TIMEOUT,
            'NETWORK_ADDRESS': NETWORK_ADDRESS,
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
                return HTTPResponse(status=HTTP_EXISTS)

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
            queue[-1][1]['threshold'] = float(json['threshold']) if (
                'threshold' in json) else None

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

                queue.append((self._set_main_interface, {
                    'node_id': json['id'],
                    'main_interface': str(json['main_interface']),
                }))

        except (KeyError, TypeError, ValueError) as e:
            print(e)
            return HTTPResponse(str(e), status=HTTP_BAD_REQUEST)

        except Exception as e:
            print(' *** ERROR in ryu_main_api.add_node:',
                  e.__class__.__name__, e)
            return HTTPResponse(status=HTTP_INTERNAL)

        # once POST data is parsed and validated, call functions in queue
        for func, kwargs in queue:
            if func(**kwargs) == False:
                # if error, undo everything by deleting node
                # this will also delete interfaces and links
                self.ryu_main.topology.delete_node(json['id'])
                return HTTPResponse(status=HTTP_INTERNAL)

    @route('node', '/node/{id}', methods=['DELETE'])
    def delete_node(self, _, id):
        self.ryu_main.topology.delete_node(id)

    @route('node_specs', '/node_specs/{id}', methods=['PUT'])
    def update_node_specs(self, req, id):
        # check if resource exists
        #  could be a host
        if not self.ryu_main.topology.get_node(id):
            try:
                # or a switch
                # (id is dpid but converted from hexadecimal to decimal)
                id = int(id, 16)
            except (TypeError, ValueError):
                return HTTPResponse(status=HTTP_NOT_FOUND)
            if not self.ryu_main.topology.get_node(id):
                return HTTPResponse(status=HTTP_NOT_FOUND)

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
            queue[-1][1]['cpu_free'] = float(json['cpu_free']) if (
                'cpu_free' in json) else None
            queue[-1][1]['memory_total'] = float(json['memory_total']) if (
                'memory_total' in json) else None
            queue[-1][1]['memory_free'] = float(json['memory_free']) if (
                'memory_free' in json) else None
            queue[-1][1]['disk_total'] = float(json['disk_total']) if (
                'disk_total' in json) else None
            queue[-1][1]['disk_free'] = float(json['disk_free']) if (
                'disk_free' in json) else None

            if 'interfaces' in json:
                for interface in json['interfaces']:
                    queue.append((self._update_interface_specs, {
                        'node_id': id,
                        'name': str(interface['name']),
                    }))
                    queue[-1][1]['timestamp'] = timestamp
                    queue[-1][1]['capacity'] = float(
                        interface['capacity']) if (
                            'capacity' in interface) else None
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
            return HTTPResponse(status=HTTP_BAD_REQUEST)

        # once PUT data is parsed and validated, call functions in queue
        for func, kwargs in queue:
            func(**kwargs)

    @route('request', '/request', methods=['POST'])
    def add_request(self, req):
        try:
            json = req.json
            req_id = str(json['id'])
            src = str(json['src'])
            if STP_ENABLED:
                # TODO path is STP path
                pass
            else:
                if ORCHESTRATOR_PATHS:
                    # TODO paths are from protocol
                    pass
                else:
                    # TODO path is from simple_switch_sp_13
                    pass
            Request(req_id, src, CoS.select(id=('=', int(json['cos_id'])))[0],
                    str(json['data']).encode(), str(json['result']).encode(),
                    str(json['host']), None, int(json['state']),
                    float(json['hreq_at']), float(json['dres_at'])).insert()
            for attempt in json['attempts']:
                attempt_no = int(attempt['attempt_no'])
                if PROTO_SEND_TO == SEND_TO_ORCHESTRATOR:
                    # TODO rres_at is from protocol
                    rres_at = None
                else:
                    rres_at = float(attempt['rres_at'])
                Attempt(req_id, src, attempt_no, str(attempt['host']), None,
                        int(attempt['state']), float(attempt['hreq_at']),
                        float(attempt['hres_at']), rres_at,
                        float(attempt['dres_at'])).insert()
                if 'responses' in attempt:
                    for response in attempt['responses']:
                        host = str(response['host'])
                        Response(req_id, src, attempt_no, host, node_algo,
                                 float(response['cpu']),
                                 float(response['ram']),
                                 float(response['disk']),
                                 float(response['timestamp'])).insert()

        except (KeyError, TypeError, ValueError) as e:
            print(e.__class__.__name__, e)
            return HTTPResponse(status=HTTP_BAD_REQUEST)

        Request.as_csv()
        Attempt.as_csv()
        Response.as_csv()

    # for testing
    @route('test', '/topology_png')
    def topology(self, _):
        clf()
        draw(self.ryu_main.topology.get_graph(), with_labels=True)
        savefig(ROOT_PATH + '/data/' + str(time()) + '.png')

    def _add_node(self, **kwargs):
        return self.ryu_main.topology.add_node(
            kwargs['id'], kwargs['state'], kwargs['type'],
            kwargs.get('label', None), kwargs.get('threshold', None))

    def _add_interface(self, **kwargs):
        return self.ryu_main.topology.add_interface(
            kwargs['node_id'], kwargs['name'], kwargs.get('num', None),
            kwargs.get('mac', None), kwargs.get('ipv4', None))

    def _set_main_interface(self, **kwargs):
        return self.ryu_main.topology.set_main_interface(
            kwargs['node_id'], kwargs['main_interface'])

    def _update_node_specs(self, **kwargs):
        return self.ryu_main.topology_state.update_node_specs(
            kwargs['id'],
            kwargs.get('cpu_count', None), kwargs.get('cpu_free', None),
            kwargs.get('memory_total', None), kwargs.get('memory_free', None),
            kwargs.get('disk_total', None), kwargs.get('disk_free', None),
            kwargs.get('timestamp', time()))

    def _update_interface_specs(self, **kwargs):
        return self.ryu_main.topology_state.update_interface_specs(
            kwargs['node_id'], kwargs['name'],
            kwargs.get('capacity', None),
            kwargs.get('bandwidth_up', None),
            kwargs.get('bandwidth_down', None),
            kwargs.get('tx_packets', None),
            kwargs.get('rx_packets', None),
            kwargs.get('timestamp', time()))
