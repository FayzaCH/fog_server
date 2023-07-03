'''
    Loads conf.yml parameters as environment variables.
'''


from os import environ
from os.path import dirname, abspath
from yaml import safe_load


CONF = dirname(dirname(abspath(__file__))) + '/conf.yml'


try:
    with open(CONF, 'r') as f:
        config = safe_load(f)
        for sect, params in config.items():
            for param, value in params.items():
                if value != None:
                    environ[sect + '_' + param] = str(value)

except Exception as e:
    print(' *** ERROR in config:', e.__class__.__name__, e)
    exit()
