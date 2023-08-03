from os import getenv
from time import time

from ryu.base.app_manager import lookup_service_brick
from ryu.lib.hub import sleep

from selection import NODE_ALGORITHMS, PATH_ALGORITHMS, PATH_WEIGHTS
from consts import *
import config


# =====================
#     RYU APP NAMES
# =====================


SWITCHES = 'switches'
OFP_HANDLER = 'ofp_handler'
WSGI = 'wsgi'
SIMPLE_SWITCH_SP_13 = 'simple_switch_sp_13'
SIMPLE_ARP = 'simple_arp'
TOPOLOGY = 'topology'
TOPOLOGY_STATE = 'topology_state'
NETWORK_MONITOR = 'network_monitor'
NETWORK_DELAY_DETECTOR = 'network_delay_detector'
DELAY_MONITOR = 'delay_monitor'
PROTOCOL = 'protocol'
METRICS = 'metrics'
LOGGING = 'logging'

DPSET = 'dpset'
FLOW_MANAGER = 'flowmanager'


# ==============
#     CONFIG
# ==============


DECOY_MAC = getenv('CONTROLLER_DECOY_MAC', None)
if DECOY_MAC == None:
    print(' *** ERROR in common: '
          'CONTROLLER:DECOY_MAC parameter missing from conf.yml.')
    exit()

DECOY_IP = getenv('CONTROLLER_DECOY_IP', None)
if DECOY_IP == None:
    print(' *** ERROR in common: '
          'CONTROLLER:DECOY_IP parameter missing from conf.yml.')
    exit()

_stp_enabled = getenv('NETWORK_STP_ENABLED', '').upper()
if _stp_enabled not in ('TRUE', 'FALSE'):
    print(' *** WARNING in common: '
          'NETWORK:STP_ENABLED parameter invalid or missing from conf.yml. '
          'Defaulting to False.')
    _stp_enabled = 'FALSE'
STP_ENABLED = _stp_enabled == 'TRUE'

_orch_paths = getenv('ORCHESTRATOR_PATHS', '').upper()
if _orch_paths not in ('TRUE', 'FALSE'):
    print(' *** WARNING in common: '
          'ORCHESTRATOR:PATHS parameter invalid or missing from conf.yml. '
          'Defaulting to False.')
    _orch_paths = 'FALSE'
ORCHESTRATOR_PATHS = _orch_paths == 'TRUE'

_proto_send_to = getenv('PROTOCOL_SEND_TO', None)
if (_proto_send_to == None
        or (_proto_send_to != SEND_TO_BROADCAST
            and _proto_send_to != SEND_TO_ORCHESTRATOR
            and _proto_send_to != SEND_TO_NONE)
        or (_proto_send_to == SEND_TO_BROADCAST
            and not STP_ENABLED)):
    print(' *** WARNING in common: '
          'PROTOCOL:SEND_TO parameter invalid or missing from conf.yml. '
          'Defaulting to ' + SEND_TO_NONE + ' (protocol will not be used).')
    _proto_send_to = SEND_TO_NONE
PROTO_SEND_TO = _proto_send_to

# algorithms
_node_algo = PROTO_SEND_TO
_path_algo = 'STP'
_path_weight = None
if PROTO_SEND_TO == SEND_TO_ORCHESTRATOR:
    _node_algo = getenv('ORCHESTRATOR_NODE_ALGORITHM', None)
    if _node_algo not in NODE_ALGORITHMS:
        _node_algo = list(NODE_ALGORITHMS.keys())[0]
        print(' *** WARNING in common: '
              'ORCHESTRATOR:NODE_ALGORITHM parameter invalid or missing from '
              'conf.yml. '
              'Defaulting to ' + _node_algo + '.')
    if not STP_ENABLED:
        _path_algo = 'SHORTEST'
        if ORCHESTRATOR_PATHS:
            _path_algo = getenv('ORCHESTRATOR_PATH_ALGORITHM', None)
            if _path_algo not in PATH_ALGORITHMS:
                _path_algo = list(PATH_ALGORITHMS.keys())[0]
                print(' *** WARNING in common: '
                      'ORCHESTRATOR:PATH_ALGORITHM parameter invalid or missing from '
                      'conf.yml. '
                      'Defaulting to ' + _path_algo + '.')
            _path_weight = getenv('ORCHESTRATOR_PATH_WEIGHT', None)
            if _path_weight not in PATH_WEIGHTS[_path_algo]:
                _path_weight = PATH_WEIGHTS[_path_algo][0]
                print(' *** WARNING in common: '
                      'ORCHESTRATOR:PATH_WEIGHT parameter invalid or missing from '
                      'conf.yml. '
                      'Defaulting to ' + _path_weight + '.')
NODE_ALGO = _node_algo
PATH_ALGO = _path_algo
PATH_WEIGHT = _path_weight

try:
    MONITOR_PERIOD = float(getenv('MONITOR_PERIOD', None))
except:
    print(' *** WARNING in common: '
          'MONITOR:PERIOD parameter invalid or missing from conf.yml. '
          'Defaulting to 1s.')
    MONITOR_PERIOD = 1

try:
    _monitor_samples = float(getenv('MONITOR_SAMPLES', None))
    if _monitor_samples < 2:
        print(' *** WARNING in common: '
              'MONITOR:SAMPLES parameter cannot be less than 2. '
              'Defaulting to 2 samples.')
        _monitor_samples = 2
    MONITOR_SAMPLES = _monitor_samples
except:
    print(' *** WARNING in common: '
          'MONITOR:SAMPLES parameter invalid or missing from conf.yml. '
          'Defaulting to 2 samples.')
    MONITOR_SAMPLES = 2


# =============
#     UTILS
# =============


SERVICE_LOOKUP_INTERVAL = 1


def get_app(app_name):
    '''
        Returns Ryu app by name. Blocks program until required app loads.
    '''

    app = lookup_service_brick(app_name)
    while not app:
        sleep(SERVICE_LOOKUP_INTERVAL)
        app = lookup_service_brick(app_name)
    return app


def get_path(path, specs=False):
    '''
        Returns path with Node IDs converted to host IPs and switch DPIDs.

        If specs is True, also returns lists of bandwidths, delays, jitters,
        loss rates, and timestamp.
    '''

    topology = get_app(TOPOLOGY)
    try:
        _path = [topology.get_link(path[0], path[1]).src_port.ipv4]
        if specs:
            bandwidths = []
            delays = []
            jitters = []
            loss_rates = []
            timestamp = time()
        len_path = len(path)
        for i in range(1, len_path):
            if i < len_path - 1:
                _path.append(f'{path[i]:x}')
            link = topology.get_link(path[i-1], path[i])
            if i == len_path - 1:
                _path.append(link.dst_port.ipv4)
            if specs:
                bandwidths.append(link.get_bandwidth())
                delays.append(link.get_delay())
                jitters.append(link.get_jitter())
                loss_rates.append(link.get_loss_rate())
        if specs:
            return (_path, bandwidths, delays, jitters, loss_rates, timestamp)
        return _path
    except Exception as e:
        print(' *** ERROR in common.get_path: ',
              e.__class__.__name__, e)
    if specs:
        return None, None, None, None, None, None
    return None
