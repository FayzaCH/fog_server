from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning

from ryu.base.app_manager import RyuApp
from ryu.lib.hub import spawn, sleep

from keystoneauth1.session import Session
from keystoneauth1.identity.v3 import Password
from gnocchiclient.client import Client
from gnocchiclient.exceptions import Conflict, NotFound

from model import NodeType
from logger import console, file
from common import *
import config


_os_verify = getenv('OPENSTACK_VERIFY_CERT', '').upper()
if _os_verify not in ('TRUE', 'FALSE'):
    console.warning('OPENSTACK:VERIFY_CERT parameter invalid or missing from '
                    'conf.yml. '
                    'Defaulting to False')
    file.warning('OPENSTACK:VERIFY_CERT parameter (%s) invalid or missing '
                 'from conf.yml', _os_verify)
    _os_verify = 'FALSE'
OS_VERIFY_CERT = _os_verify == 'TRUE'

OS_URL = getenv('OPENSTACK_URL', '')
if not OS_URL:
    console.warning('OPENSTACK:URL parameter missing from conf.yml')
    file.warning('OPENSTACK:URL parameter missing from conf.yml')

OS_AUTH_PORT = getenv('OPENSTACK_AUTH_PORT', '')
if not OS_AUTH_PORT:
    console.warning('OPENSTACK:AUTH_PORT parameter missing from conf.yml')
    file.warning('OPENSTACK:AUTH_PORT parameter missing from conf.yml')

OS_GNOCCHI_PORT = getenv('OPENSTACK_GNOCCHI_PORT', '')
if not OS_GNOCCHI_PORT:
    console.warning('OPENSTACK:GNOCCHI_PORT parameter missing from conf.yml')
    file.warning('OPENSTACK:GNOCCHI_PORT parameter missing from conf.yml')

OS_USERNAME = getenv('OPENSTACK_USERNAME', '')
if not OS_USERNAME:
    console.warning('OPENSTACK:USERNAME parameter missing from conf.yml')
    file.warning('OPENSTACK:USERNAME parameter missing from conf.yml')

OS_PASSWORD = getenv('OPENSTACK_PASSWORD', '')
if not OS_PASSWORD:
    console.warning('OPENSTACK:PASSWORD parameter missing from conf.yml')
    file.warning('OPENSTACK:PASSWORD parameter missing from conf.yml')

OS_USER_DOMAIN_ID = getenv('OPENSTACK_USER_DOMAIN_ID', '')
if not OS_USER_DOMAIN_ID:
    console.warning('OPENSTACK:USER_DOMAIN_ID parameter missing from conf.yml')
    file.warning('OPENSTACK:USER_DOMAIN_ID parameter missing from conf.yml')

OS_USER_ID = getenv('OPENSTACK_USER_ID', '')
if not OS_USER_ID:
    console.warning('OPENSTACK:USER_ID parameter missing from conf.yml')
    file.warning('OPENSTACK:USER_ID parameter missing from conf.yml')

OS_PROJECT_ID = getenv('OPENSTACK_PROJECT_ID', '')
if not OS_PROJECT_ID:
    console.warning('OPENSTACK:PROJECT_ID parameter missing from conf.yml')
    file.warning('OPENSTACK:PROJECT_ID parameter missing from conf.yml')

OS_ARCHIVE_POLICY = getenv('OPENSTACK_ARCHIVE_POLICY', '')


RESOURCE_TYPES = {
    'fog_node': {
        'def': {
            'name': 'fog_node',
            'attributes': {
                'node_id': {
                    'max_length': 255,
                    'min_length': 0,
                    'required': True,
                    'type': 'string'
                },
                'node_type': {
                    'max_length': 255,
                    'min_length': 0,
                    'required': True,
                    'type': 'string'
                },
                'label': {
                    'max_length': 255,
                    'min_length': 0,
                    'required': False,
                    'type': 'string'
                }
            }
        },
        'metrics': ['cpu.count', 'cpu.free', 'memory.total', 'memory.free',
                    'disk.total', 'disk.free'],
        'units': ['', '', 'MB', 'MB', 'GB', 'GB']
    },
    'fog_port': {
        'def': {
            'name': 'fog_port',
            'attributes': {
                'node_id': {
                    'max_length': 255,
                    'min_length': 0,
                    'required': True,
                    'type': 'string'
                },
                'name': {
                    'max_length': 255,
                    'min_length': 0,
                    'required': True,
                    'type': 'string'
                },
                'num': {
                    'max': 4294967295,
                    'min': -1,
                    'required': False,
                    'type': 'number'
                },
                'mac': {
                    'max_length': MAC_LEN,
                    'min_length': 0,
                    'required': False,
                    'type': 'string'
                },
                'ipv4': {
                    'max_length': IP_LEN,
                    'min_length': 0,
                    'required': False,
                    'type': 'string'
                }
            }
        },
        'metrics': ['capacity', 'bandwidth.up.free', 'bandwidth.down.free'],
        'units': ['Mbit/s', 'Mbit/s', 'Mbit/s']
    },
    'fog_link': {
        'def': {
            'name': 'fog_link',
            'attributes': {
                'src_node': {
                    'max_length': 255,
                    'min_length': 0,
                    'required': True,
                    'type': 'string'
                },
                'src_port': {
                    'max_length': 255,
                    'min_length': 0,
                    'required': True,
                    'type': 'string'
                },
                'dst_node': {
                    'max_length': 255,
                    'min_length': 0,
                    'required': True,
                    'type': 'string'
                },
                'dst_port': {
                    'max_length': 255,
                    'min_length': 0,
                    'required': True,
                    'type': 'string'
                }
            }
        },
        'metrics': ['capacity', 'bandwidth.free', 'delay', 'jitter', 'loss.rate'],
        'units': ['Mbit/s', 'Mbit/s', 's', 's', '']
    }
}


class Metrics(RyuApp):
    '''
        Ryu app for sending monitoring measures collected from various sources 
        (other Ryu apps, fog clients, etc.) periodically to OpenStack's 
        Ceilometer (Gnocchi time series database).

        Requirements:
        -------------
        Topology app: for Nodes, Interfaces, and Links and their specs.
    '''

    def __init__(self, *args, **kwargs):
        super(Metrics, self).__init__(*args, **kwargs)
        self.name = METRICS

        self._topology = get_app(TOPOLOGY)

        self._session = None
        self._client = None
        try:
            self._os_authenticate()
            self._archive_policies = [
                ap['name'] for ap in self._client.archive_policy.list()]
        except Exception as e:
            console.error('%s %s', e.__class__.__name__, str(e))
            file.exception(e.__class__.__name__)
        else:
            spawn(self._add_measures)

    def _add_measures(self):
        while True:
            sleep(MONITOR_PERIOD)
            measures = {}
            try:
                for node_id, node in self._topology.get_nodes().items():
                    if node.type == NodeType.SWITCH:
                        node_id = str(f'{node_id:x}')
                    self._ensure_resource('fog_node', {
                        'id': node_id,
                        'node_id': node_id,
                        'node_type': str(node.type.value),
                        'label': node.label
                    })
                    t = node.get_timestamp()
                    measures.update({
                        node_id: {
                            'cpu.count': [{
                                'timestamp': t,
                                'value': node.get_cpu_count()
                            }],
                            'cpu.free': [{
                                'timestamp': t,
                                'value': node.get_cpu_free()
                            }],
                            'memory.total': [{
                                'timestamp': t,
                                'value': node.get_memory_total()
                            }],
                            'memory.free': [{
                                'timestamp': t,
                                'value': node.get_memory_free()
                            }],
                            'disk.total': [{
                                'timestamp': t,
                                'value': node.get_disk_total()
                            }],
                            'disk.free': [{
                                'timestamp': t,
                                'value': node.get_disk_free()
                            }]
                        }
                    })

                    for iname, iface in node.interfaces.items():
                        port_id = node_id + '-' + iname
                        self._ensure_resource('fog_port', {
                            'id': port_id,
                            'node_id': node_id,
                            'name': iname,
                            'num': iface.num if iface.num != None else -1,
                            'mac': str(iface.mac),
                            'ipv4': str(iface.ipv4)
                        })
                        t = iface.get_timestamp()
                        measures.update({
                            port_id: {
                                'capacity': [{
                                    'timestamp': t,
                                    'value': iface.get_capacity()
                                }],
                                'bandwidth.up.free': [{
                                    'timestamp': t,
                                    'value': iface.get_bandwidth_up()
                                }],
                                'bandwidth.down.free': [{
                                    'timestamp': t,
                                    'value': iface.get_bandwidth_down()
                                }]
                            }
                        })

                for src_id, dsts in self._topology.get_links().items():
                    src = self._topology.get_node(src_id)
                    if src and src.type == NodeType.SWITCH:
                        src_id = str(f'{src_id:x}')
                    for dst_id, link in dsts.items():
                        dst = self._topology.get_node(dst_id)
                        if dst and dst.type == NodeType.SWITCH:
                            dst_id = str(f'{dst_id:x}')
                        link_id = src_id + '>' + dst_id
                        self._ensure_resource('fog_link', {
                            'id': link_id,
                            'src_node': src_id,
                            'dst_node': dst_id,
                            'src_port': link.src_port.name,
                            'dst_port': link.dst_port.name
                        })

                        t = link.get_timestamp()
                        # gnocchi can't read inf values so we change to -1
                        delay = link.get_delay()
                        if delay == float('inf'):
                            delay = -1
                        jitter = link.get_jitter()
                        if jitter == float('inf'):
                            jitter = -1
                        measures.update({
                            link_id: {
                                'capacity': [{
                                    'timestamp': t,
                                    'value': link.get_capacity()
                                }],
                                'bandwidth.free': [{
                                    'timestamp': t,
                                    'value': link.get_bandwidth()
                                }],
                                'delay': [{
                                    'timestamp': t,
                                    'value': delay
                                }],
                                'jitter': [{
                                    'timestamp': t,
                                    'value': jitter
                                }],
                                'loss.rate': [{
                                    'timestamp': t,
                                    'value': link.get_loss_rate()
                                }]
                            }
                        })

            except Exception as e:
                console.error('%s %s', e.__class__.__name__, str(e))
                file.exception(e.__class__.__name__)

            else:
                try:
                    self._client.metric.batch_resources_metrics_measures(
                        measures)

                except Exception as e:
                    console.error('%s %s', e.__class__.__name__, str(e))
                    file.exception(e.__class__.__name__)

    def _os_authenticate(self):
        if not OS_VERIFY_CERT:
            disable_warnings(InsecureRequestWarning)
        self._session = Session(Password(auth_url=OS_URL + ':' + OS_AUTH_PORT,
                                         username=OS_USERNAME,
                                         password=OS_PASSWORD,
                                         user_domain_id=OS_USER_DOMAIN_ID,
                                         project_id=OS_PROJECT_ID),
                                verify=OS_VERIFY_CERT)
        self._client = Client(1, self._session)

    def _os_ensure_resource_types(self):
        for type in RESOURCE_TYPES.values():
            try:
                self._client.resource_type.create(type['def'])
            except Conflict:
                # already exists
                pass

    def _os_ensure_metrics(self, resource_id: str, metrics: list, units: list):
        os_archive_policy = OS_ARCHIVE_POLICY
        if os_archive_policy not in self._archive_policies:
            console.warning('OPENSTACK:ARCHIVE_POLICY parameter invalid or '
                            'missing from conf.yml. '
                            'Defaulting to ceilometer-low')
            file.warning('OPENSTACK:ARCHIVE_POLICY parameter (%s) invalid or '
                         'missing from conf.yml', os_archive_policy)
            os_archive_policy = 'ceilometer-low'
        for i, name in enumerate(metrics):
            try:
                self._client.metric.create(
                    name=name, resource_id=resource_id, unit=units[i],
                    archive_policy_name=os_archive_policy)
            except Conflict:
                # already exists
                pass

    def _os_ensure_resource(self, resource_type: str, attributes: dict):
        attributes.update({
            'user_id': OS_USER_ID,
            'project_id': OS_PROJECT_ID
        })
        try:
            self._client.resource.create(resource_type, attributes)
        except NotFound:
            self._os_ensure_resource_types()
            self._client.resource.create(resource_type, attributes)
        except Conflict:
            # already exists
            pass

    def _ensure_resource(self, resource_type, attributes):
        self._os_ensure_resource(resource_type, attributes)
        self._os_ensure_metrics(attributes['id'],
                                RESOURCE_TYPES[resource_type]['metrics'],
                                RESOURCE_TYPES[resource_type]['units'])
