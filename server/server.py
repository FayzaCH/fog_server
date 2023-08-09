'''
    Main module of the server component. It can be launched through CLI or 
    used programmatically through the serve(...) method. It runs the RyuMain 
    app using the 'ryu run' command (or 'ryu-manager' if not found) with 
    the --observe-links option. 
'''


from os import getenv
from os.path import abspath, dirname, exists, join
from subprocess import run
from logging import INFO, WARNING

from logger import console, file
import config


_controller_verbose = getenv('CONTROLLER_VERBOSE', '').upper()
if _controller_verbose not in ('TRUE', 'FALSE'):
    _controller_verbose = 'FALSE'
CONTROLLER_VERBOSE = _controller_verbose == 'TRUE'

console.setLevel(INFO if CONTROLLER_VERBOSE else WARNING)

try:
    OFP_PORT = int(getenv('CONTROLLER_OFP_PORT', None))
except:
    console.warning('CONTROLLER:OFP_PORT parameter invalid or missing from '
                    'conf.yml. '
                    'Defaulting to 6633')
    file.warning('CONTROLLER:OFP_PORT parameter invalid or missing from '
                 'conf.yml', exc_info=True)
    OFP_PORT = 6633

try:
    API_PORT = int(getenv('ORCHESTRATOR_API_PORT', None))
except:
    console.warning('CONTROLLER:API_PORT parameter invalid or missing from '
                    'conf.yml. '
                    'Defaulting to 8080')
    file.warning('CONTROLLER:API_PORT parameter invalid or missing from '
                 'conf.yml', exc_info=True)
    API_PORT = 8080

RYU_PATH = getenv('CONTROLLER_PATH', '')
RYU_BIN_PATH = join(RYU_PATH, 'bin', 'ryu')

RYU_MAIN_PATH = dirname(abspath(__file__)) + '/ryu_main.py'


def serve():
    cmd = [RYU_BIN_PATH if exists(RYU_BIN_PATH) else 'ryu', 'run',
           RYU_MAIN_PATH, '--observe-links', '--ofp-tcp-listen-port',
           str(OFP_PORT), '--wsapi-port', str(API_PORT)]
    try:
        run(cmd)

    except FileNotFoundError:
        file.exception('ryu not found')
        RYU_MANAGER_PATH = join(RYU_PATH, 'bin', 'ryu-manager')
        cmd[0] = (
            RYU_MANAGER_PATH if exists(RYU_MANAGER_PATH) else 'ryu-manager')
        del cmd[1]
        try:
            run(cmd)

        except FileNotFoundError:
            console.error('ryu and ryu-manager not found. Make sure Ryu is '
                          'installed and added to system PATH. Or configure '
                          'RYU:PATH parameter in conf.yml if Ryu is installed '
                          'from source')
            file.exception('ryu-manager not found')

    except Exception as e:
        console.error('%s %s', e.__class__.__name__, str(e))
        file.exception(e.__class__.__name__)


if __name__ == '__main__':
    serve()
