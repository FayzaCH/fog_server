'''
    Main module of the server component. It can be launched through CLI or 
    used programmatically through the serve(...) method. It runs the RyuMain 
    app using the 'ryu run' command (or 'ryu-manager' if not found) with 
    the --observe-links option. 
'''


from os import getenv
from os.path import abspath, dirname, exists, join
from subprocess import run

import config


try:
    OFP_PORT = int(getenv('CONTROLLER_OFP_PORT', None))
except:
    print(' *** WARNING in server: '
          'CONTROLLER:OFP_PORT parameter invalid or missing from conf.yml. '
          'Defaulting to 6633.')
    OFP_PORT = 6633

try:
    API_PORT = int(getenv('ORCHESTRATOR_API_PORT', None))
except:
    print(' *** WARNING in server: '
          'ORCHESTRATOR:API_PORT parameter invalid or missing from conf.yml. '
          'Defaulting to 8080.')
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
        RYU_MANAGER_PATH = join(RYU_PATH, 'bin', 'ryu-manager')
        cmd[0] = (
            RYU_MANAGER_PATH if exists(RYU_MANAGER_PATH) else 'ryu-manager')
        del cmd[1]
        try:
            run(cmd)

        except FileNotFoundError:
            print(' *** ERROR in server.serve: '
                  'ryu and ryu-manager not found. Make sure Ryu is installed '
                  'and added to system PATH. Or configure RYU:PATH parameter '
                  'in conf.yml if Ryu is installed from source.')

    except Exception as e:
        print(' *** ERROR in server.serve:', e.__class__.__name__, e)


if __name__ == '__main__':
    serve()
