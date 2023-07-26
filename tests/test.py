from pprint import pprint
from urllib3 import disable_warnings
from urllib3.exceptions import InsecureRequestWarning

from keystoneauth1.session import Session
from keystoneauth1.identity.v3 import Password
from gnocchiclient.client import Client

from context import *


if not OS_VERIFY_CERT:
    disable_warnings(InsecureRequestWarning)
client = Client(1, Session(Password(auth_url=OS_URL + ':' + OS_AUTH_PORT,
                                    username=OS_USERNAME, password=OS_PASSWORD,
                                    user_domain_id=OS_USER_DOMAIN_ID,
                                    project_id=OS_PROJECT_ID),
                           verify=OS_VERIFY_CERT))

try:
    nodes = client.resource.list('fog_node')
except:
    nodes = []
#pprint(nodes)
'''
for resource in nodes:
    for metric in resource['metrics'].values():
        client.metric.delete(metric)
    client.resource.delete(resource['id'])
#'''

try:
    ports = client.resource.list('fog_port')
except:
    ports = []
#pprint(ports)
'''
for resource in ports:
    for metric in resource['metrics'].values():
        client.metric.delete(metric)
    client.resource.delete(resource['id'])
#'''

try:
    links = client.resource.list('fog_link')
except:
    links = []
#pprint(links)
'''
for resource in links:
    for metric in resource['metrics'].values():
        client.metric.delete(metric)
    client.resource.delete(resource['id'])
#'''

#types = client.resource_type.list()
# pprint(types)

'''
try:
    client.resource_type.delete('fog_node')
except:
    pass
try:
    client.resource_type.delete('fog_port')
except:
    pass
try:
    client.resource_type.delete('fog_link')
except:
    pass
#'''

for node in nodes:
    print(node['original_resource_id'] + '.cpu.count')
    for measure in client.metric.get_measures(node['metrics']['cpu.count']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '), measure[2])
    print()
    print(node['original_resource_id'] + '.memory.free')
    for measure in client.metric.get_measures(node['metrics']['memory.free']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2], 2), 'MB')
    print()
    print(node['original_resource_id'] + '.disk.free')
    for measure in client.metric.get_measures(node['metrics']['disk.free']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2], 2), 'GB')    

for port in ports:
    print(port['original_resource_id'] + '.capacity')
    for measure in client.metric.get_measures(port['metrics']['capacity']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2], 2), 'Mbps')
    print()
    print(port['original_resource_id'] + '.bandwidth.up.free')
    for measure in client.metric.get_measures(port['metrics']['bandwidth.up.free']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2], 2), 'Mbps')
    print()
    print(port['original_resource_id'] + 'bandwidth.down.free')
    for measure in client.metric.get_measures(port['metrics']['bandwidth.down.free']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2], 2), 'Mbps')

for link in links:
    print(link['original_resource_id'] + '.capacity')
    for measure in client.metric.get_measures(link['metrics']['capacity']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2], 2), 'Mbps')
    print()
    print(link['original_resource_id'] + '.bandwidth')
    for measure in client.metric.get_measures(link['metrics']['bandwidth.free']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2], 2), 'Mbps')
    print()
    print(link['original_resource_id'] + '.delay')
    for measure in client.metric.get_measures(link['metrics']['delay']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2] * 1000, 2), 'ms')
    print()
    print(link['original_resource_id'] + '.jitter')
    for measure in client.metric.get_measures(link['metrics']['jitter']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2] * 1000, 2), 'ms')
    print()
    print(link['original_resource_id'] + '.loss.rate')
    for measure in client.metric.get_measures(link['metrics']['loss.rate']):
        print(measure[0].strftime('%m/%d/%Y, %H:%M:%S  '),
              round(measure[2] * 100, 2), '%')
