from os.path import dirname, abspath


# protocol states
HREQ = 1    # host request
HRES = 2    # host response
RREQ = 3    # resource reservation request
RRES = 4    # resource reservation response
RACK = 5    # resource reservation acknowledgement
RCAN = 6    # resource reservation cancellation
DREQ = 7    # data exchange request
DRES = 8    # data exchange response
DACK = 9    # data exchange acknowledgement
DCAN = 10    # data exchange cancellation
DWAIT = 11  # data exchange wait
FAIL = 0

# misc. consts
REQ_ID_LEN = 10
MAC_LEN = 17
IP_LEN = 15
BROADCAST_MAC = 'ff:ff:ff:ff:ff:ff'
BROADCAST_IP = '255.255.255.255'
DEFAULT_IP = '0.0.0.0'
SEND_TO_BROADCAST = 'BROADCAST'
SEND_TO_ORCHESTRATOR = 'ORCHESTRATOR'
SEND_TO_NONE = 'NONE'
ROOT_PATH = dirname(dirname(abspath(__file__)))
