import selectors
import socket
import socketserver


DOCKER_SOCKET = "/var/run/docker.sock"


class DockerSocketProxy(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.connect(DOCKER_SOCKET)
        selector = selectors.DefaultSelector()
        try:
            self.request.setblocking(False)
            upstream.setblocking(False)
            selector.register(self.request, selectors.EVENT_READ, upstream)
            selector.register(upstream, selectors.EVENT_READ, self.request)
            while selector.get_map():
                for key, _ in selector.select():
                    source = key.fileobj
                    target = key.data
                    data = source.recv(65536)
                    if data:
                        target.sendall(data)
                    else:
                        selector.unregister(source)
                        try:
                            target.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass
        finally:
            selector.close()
            upstream.close()


class ThreadingProxyServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


with ThreadingProxyServer(("127.0.0.1", 23750), DockerSocketProxy) as server:
    server.serve_forever()
