'''
    Loads conf.yml parameters as environment variables.
'''


from os import environ
from os.path import dirname, abspath
from yaml import safe_load

from logger import console, file


CONF = dirname(dirname(abspath(__file__))) + '/conf.yml'


try:
    with open(CONF, 'r') as f:
        config = safe_load(f)
        for sect, params in config.items():
            for param, value in params.items():
                if value != None:
                    environ[sect + '_' + param] = str(value)

except Exception as e:
    console.error('%s %s', e.__class__.__name__, str(e))
    file.exception(e.__class__.__name__)
    exit()
