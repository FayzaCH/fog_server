from os import getenv

from ryu.base.app_manager import lookup_service_brick
from ryu.lib.hub import sleep

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


SERVICE_LOOKUP_INTERVAL = 1


def get_app(app_name):
    app = lookup_service_brick(app_name)
    while not app:
        sleep(SERVICE_LOOKUP_INTERVAL)
        app = lookup_service_brick(app_name)
    return app
