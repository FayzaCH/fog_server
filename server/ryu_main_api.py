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
    'cpu_free': <float>,
    'memory_total': <float>,
    'memory_free': <float>,
    'disk_total': <float>,
    'disk_free': <float>,
    'interfaces': [{
     ** 'name': <str>,
        'capacity': <float>,
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
  * 'data': <bytes>,
    'result': <bytes>,
    'host': <str>,
  * 'state': <int>,
  * 'hreq_at': <float>,
    'dres_at': <float>,
  * 'attempts': [{
      * 'attempt_no': <int>,
        'host': <str>,
      * 'state': <int>,
      * 'hreq_at': <float>,
        'hres_at': <float>,
        'rres_at': <float>,
        'dres_at': <float>,
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

from networkx import draw, shortest_path
from matplotlib.pyplot import savefig, clf

from model import NodeType, Request, Attempt, Response, Path, CoS
from ryu_apps.common import (DECOY_IP, DECOY_MAC, MONITOR_PERIOD,
                             PROTO_SEND_TO, STP_ENABLED, ORCHESTRATOR_PATHS,
                             NODE_ALGO, PATH_ALGO, PATH_WEIGHT, get_path)
from ryu_apps.protocol import PROTO_RETRIES, PROTO_TIMEOUT
from ryu_apps.topology import UDP_PORT, UDP_TIMEOUT
from consts import ROOT_PATH, SEND_TO_ORCHESTRATOR
import config


#  config
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

# HTTP codes
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
        self._topology = self.ryu_main.topology

    @route('root', '/')
    def root(self, _):
        return 'API is working!'

    @route('config', '/config', methods=['GET'])
    def get_config(self, _):
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
        try:
            json = req.json
            # check if node already exists
            id = self._get_post(json, 'id', required=True)
            if self._topology.get_node(id):
                return HTTPResponse(status=HTTP_EXISTS)

            # check if required data fields available with correct types
            # and add function and kwargs to queue
            queue.append((self._add_node, {
                'id': id,
                'state': self._get_post(json, 'state', bool, True),
                'type': NodeType(self._get_post(json, 'type', str, True)),
            }))

            # check if optional data fields available with correct types
            # and add to kwargs
            kwargs = queue[-1][1]
            kwargs['label'] = self._get_post(json, 'label', str)
            kwargs['threshold'] = self._get_post(json, 'threshold', float)

            # node can be added with interfaces
            if 'interfaces' in json:
                for interface in json['interfaces']:
                    # required data fields for interfaces
                    queue.append((self._add_interface, {
                        'node_id': id,
                        'name': self._get_post(interface, 'name', str, True),
                    }))

                    # optional data fields for interfaces
                    kwargs = queue[-1][1]
                    kwargs['num'] = self._get_post(interface, 'num', int)
                    kwargs['mac'] = self._get_post(interface, 'mac', str)
                    kwargs['ipv4'] = self._get_post(interface, 'ipv4', str)

                queue.append((self._set_main_interface, {
                    'node_id': id,
                    'main_interface':
                        self._get_post(json, 'main_interface', str),
                }))

        except (KeyError, TypeError, ValueError) as e:
            return HTTPResponse(text=e.__class__.__name__+' '+str(e),
                                status=HTTP_BAD_REQUEST)

        except Exception as e:
            print(' *** ERROR in ryu_main_api.add_node:',
                  e.__class__.__name__, e)
            return HTTPResponse(status=HTTP_INTERNAL)

        # once POST data is parsed and validated, call functions in queue
        for func, kwargs in queue:
            res = func(**kwargs)
            if not res:
                print(' *** ERROR in ryu_main_api.add_node:', func.__name__,
                      'returned False.')
                # if error, undo everything by deleting node
                # this will also delete interfaces and links
                self._topology.delete_node(id)
                return HTTPResponse(status=HTTP_INTERNAL)

    @route('node', '/node/{id}', methods=['DELETE'])
    def delete_node(self, _, id):
        self._topology.delete_node(id)

    @route('node_specs', '/node_specs/{id}', methods=['PUT'])
    def update_node_specs(self, req, id):
        # check if resource exists
        #  could be a host
        if not self._topology.get_node(id):
            try:
                # or a switch
                # (id is dpid but converted from hexadecimal to decimal)
                id = int(id, 16)
            except (TypeError, ValueError):
                return HTTPResponse(status=HTTP_NOT_FOUND)
            if not self._topology.get_node(id):
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
            timestamp = self._get_post(json, 'timestamp', float, ret=time())
            kwargs = queue[-1][1]
            kwargs['timestamp'] = timestamp
            kwargs['cpu_count'] = self._get_post(json, 'cpu_count', int)
            kwargs['cpu_free'] = self._get_post(json, 'cpu_free', float)
            kwargs['memory_total'] = self._get_post(
                json, 'memory_total', float)
            kwargs['memory_free'] = self._get_post(json, 'memory_free', float)
            kwargs['disk_total'] = self._get_post(json, 'disk_total', float)
            kwargs['disk_free'] = self._get_post(json, 'disk_free', float)

            if 'interfaces' in json:
                for interface in json['interfaces']:
                    queue.append((self._update_interface_specs, {
                        'node_id': id,
                        'name': self._get_post(interface, 'name', str, True),
                    }))
                    kwargs = queue[-1][1]
                    kwargs['timestamp'] = timestamp
                    kwargs['capacity'] = self._get_post(
                        interface, 'capacity', float)
                    kwargs['bandwidth_up'] = self._get_post(
                        interface, 'bandwidth_up', float)
                    kwargs['bandwidth_down'] = self._get_post(
                        interface, 'bandwidth_down', float)
                    kwargs['tx_packets'] = self._get_post(
                        interface, 'tx_packets', int)
                    kwargs['rx_packets'] = self._get_post(
                        interface, 'rx_packets', int)

        except (KeyError, TypeError, ValueError) as e:
            return HTTPResponse(text=e.__class__.__name__+' '+str(e),
                                status=HTTP_BAD_REQUEST)

        except Exception as e:
            print(' *** ERROR in ryu_main_api.update_node_specs:',
                  e.__class__.__name__, e)
            return HTTPResponse(status=HTTP_INTERNAL)

        # once PUT data is parsed and validated, call functions in queue
        for func, kwargs in queue:
            func(**kwargs)

    @route('request', '/request', methods=['POST'])
    def add_request(self, req):
        try:
            json = req.json
            print(json)
            req_id = self._get_post(json, 'id', str, True)
            src = self._get_post(json, 'src', str, True)
            req_host = self._get_post(json, 'host')
            data = self._get_post(json, 'data', required=True)
            if isinstance(data, str):
                data = data.encode()
            elif not isinstance(data, bytes):
                raise TypeError('data must be bytes')
            result = self._get_post(json, 'result')
            if isinstance(result, str):
                result = result.encode()
            elif result and not isinstance(result, bytes):
                raise TypeError('result must be bytes')
            Request(
                req_id, src, CoS.select(
                    id=('=', self._get_post(json, 'cos_id', int, True)))[0],
                data, result, req_host,
                self._get_path(src, req_host, req_id),
                self._get_post(json, 'state', int, True),
                self._get_post(json, 'hreq_at', float, True),
                self._get_post(json, 'dres_at', float)).insert()
            for attempt in json['attempts']:
                attempt_no = self._get_post(attempt, 'attempt_no', int, True)
                att_host = self._get_post(attempt, 'host')
                if PROTO_SEND_TO == SEND_TO_ORCHESTRATOR:
                    try:
                        rres_at = self.ryu_main.protocol.requests[
                            (src, req_id)].attempts[attempt_no].rres_at
                    except:
                        rres_at = None
                else:
                    rres_at = self._get_post(attempt, 'rres_at', float)
                Attempt(req_id, src, attempt_no, att_host,
                        self._get_path(src, att_host, req_id, attempt_no),
                        self._get_post(attempt, 'state', int, True),
                        self._get_post(attempt, 'hreq_at', float, True),
                        self._get_post(attempt, 'hres_at', float), rres_at,
                        self._get_post(attempt, 'dres_at', float)).insert()
                if 'responses' in attempt:
                    for response in attempt['responses']:
                        res_host = self._get_post(response, 'host', str, True)
                        Response(req_id, src, attempt_no, res_host, NODE_ALGO,
                                 self._get_post(response, 'cpu', float, True),
                                 self._get_post(response, 'ram', float, True),
                                 self._get_post(response, 'disk', float, True),
                                 self._get_post(
                                     response, 'timestamp', float, True)).insert()
                        path, bws, dels, jits, loss, ts = self._get_path(
                            src, res_host, specs=True)
                        Path(req_id, src, attempt_no, res_host,
                             path, PATH_ALGO, bws, dels, jits, loss,
                             PATH_WEIGHT, None, ts).insert()

        except (KeyError, TypeError, ValueError) as e:
            return HTTPResponse(text=e.__class__.__name__+' '+str(e),
                                status=HTTP_BAD_REQUEST)

        Request.as_csv()
        Attempt.as_csv()
        Response.as_csv()
        Path.as_csv()

    # for testing
    @route('test', '/topology_png')
    def topology(self, _):
        clf()
        draw(self._topology.get_graph(), with_labels=True)
        savefig(ROOT_PATH + '/data/' + str(time()) + '.png')

    def _get_post(self, json, key, type=None, required=False, ret=None):
        try:
            value = json[key]
            if type and not isinstance(value, type):
                raise TypeError(key + ' must be ' + type.__name__)
            return value
        except (KeyError, TypeError) as e:
            if required:
                raise e
            else:
                return ret

    def _add_node(self, **kwargs):
        return self._topology.add_node(
            kwargs['id'], kwargs['state'], kwargs['type'],
            kwargs.get('label', None), kwargs.get('threshold', None))

    def _add_interface(self, **kwargs):
        return self._topology.add_interface(
            kwargs['node_id'], kwargs['name'], kwargs.get('num', None),
            kwargs.get('mac', None), kwargs.get('ipv4', None))

    def _set_main_interface(self, **kwargs):
        return self._topology.set_main_interface(
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

    def _get_path(self, src_ip: str, dst_ip: str, req_id: str = None,
                  attempt_no: int = None, specs: bool = False):
        try:
            path = []
            if STP_ENABLED or not ORCHESTRATOR_PATHS:
                # if STP enabled
                #   only one path, shortest path
                # if STP disabled and orchestrator paths disabled
                #   path is from simple_switch_sp_13, also shortest path
                graph = self._topology.get_graph()
                src = self._topology.get_by_ip(src_ip, 'node_id')
                if src in graph.nodes:
                    dst = self._topology.get_by_ip(dst_ip, 'node_id')
                    if dst in graph.nodes:
                        path = shortest_path(graph, src, dst, weight=None)
            else:
                # if STP disabled and orchestrator paths enabled
                # path is from protocol
                if req_id and not attempt_no:
                    path = self.ryu_main.protocol.requests[(
                        src_ip, req_id)].path
                if req_id and attempt_no:
                    path = self.ryu_main.protocol.requests[(
                        src_ip, req_id)].attempts[attempt_no].path
            if path:
                return get_path(path, specs)
        except Exception as e:
            print(' *** ERROR in ryu_main_api._get_path: ',
                  e.__class__.__name__, e)
        if specs:
            return None, None, None, None, None, None
        return None
