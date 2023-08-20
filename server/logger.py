from logging import getLogger, StreamHandler, FileHandler, Formatter, DEBUG
from os import makedirs

from consts import ROOT_PATH


try:
    makedirs(ROOT_PATH + '/data', mode=0o777)
except FileExistsError:
    pass

LOG_FILE = ROOT_PATH + '/data/app.log'
FILE_LEVEL = DEBUG


# console logger (root)
console = getLogger('fog_server_console')

# config console logger
_stream_handler = StreamHandler()
_stream_handler.setFormatter(
    Formatter(' *** %(levelname)s in %(module)s - %(message)s'))
console.addHandler(_stream_handler)
console.propagate = False


# file logger
file = getLogger('fog_server_file')

# config file logger
try:
    _file_handler = FileHandler(LOG_FILE)
except Exception as e:
    console.error('File logging disabled due to %s. '
                  'Check that data directory is present.',
                  e.__class__.__name__)
    file.disabled = True
else:
    _file_handler.setLevel(FILE_LEVEL)
    _file_handler.setFormatter(
        Formatter('%(asctime)s - %(levelname)s in %(module)s - %(message)s'))
    file.setLevel(FILE_LEVEL)
    file.addHandler(_file_handler)
    file.propagate = False
