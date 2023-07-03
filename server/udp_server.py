'''
    Basic UDP server that keeps track of connected clients.
'''


from time import time, sleep
from socketserver import UDPServer, DatagramRequestHandler
from threading import Thread


clients = {}


def _check_clients(timeout: float = 3):
    while True:
        sleep(timeout)
        t = time()
        for id in list(clients):
            if t - clients[id] > timeout:
                del clients[id]


class UDPHandler(DatagramRequestHandler):
    def handle(self):
        clients[self.rfile.readline().strip().decode()] = time()


def serve(port: int = 7070, timeout: float = 3):
    Thread(target=_check_clients, args=(timeout,)).start()
    Thread(target=UDPServer(('', port),
                            UDPHandler).serve_forever).start()


if __name__ == '__main__':
    serve()
