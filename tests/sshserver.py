"""A real SSH server for the tests, on 127.0.0.1 (paramiko's server side): password or public-key sign-in, a shell
that understands `echo ...`, `size` (prints the window size it was told), `exit`, and ssh -L forwarding to local
ports. Test-only: PR7-TM itself never runs a server."""

from __future__ import annotations

import socket
import threading

import paramiko

USER, PASSWORD = "ari", "s3cret pass"


class _Server(paramiko.ServerInterface):
    def __init__(self, owner):
        self.owner = owner
        self.size = (80, 24)
        self.shell = threading.Event()
        self.direct: dict[int, tuple] = {}            # channel id -> where ssh -L wants to go

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if (username, password) == (USER, PASSWORD) else paramiko.AUTH_FAILED

    def check_auth_publickey(self, username, key):
        if self.owner.pubkey is not None and username == USER and key.asbytes() == self.owner.pubkey.asbytes():
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password,publickey"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pw, ph, modes):
        self.size = (width, height)
        self.owner.terms.append(term.decode() if isinstance(term, bytes) else term)
        return True

    def check_channel_window_change_request(self, channel, width, height, pw, ph):
        self.size = (width, height)
        return True

    def check_channel_shell_request(self, channel):
        self.shell.set()
        return True

    def check_channel_direct_tcpip_request(self, chanid, origin, destination):
        self.owner.forwards.append(destination)
        self.direct[chanid] = destination
        return paramiko.OPEN_SUCCEEDED


def _shell(chan, server):
    chan.sendall(b"Welcome to the test server\r\n$ ")
    line = b""
    while True:
        try:
            data = chan.recv(1024)
        except OSError:
            return
        if not data:
            return
        for b in data:
            c = bytes([b])
            if c in (b"\r", b"\n"):
                cmd = line.decode("utf-8", "replace").strip()
                line = b""
                chan.sendall(b"\r\n")
                if cmd == "exit":
                    chan.send_exit_status(0)
                    chan.close()
                    return
                if cmd.startswith("echo "):
                    chan.sendall(cmd[5:].encode() + b"\r\n")
                elif cmd == "size":
                    chan.sendall(f"{server.size[0]}x{server.size[1]}\r\n".encode())
                elif cmd == "colours":
                    chan.sendall(b"\x1b[32mgreen\x1b[0m \x1b[34mblue\x1b[0m\r\n")
                elif cmd:
                    chan.sendall(f"{cmd}: not found\r\n".encode())
                chan.sendall(b"$ ")
            elif c == b"\x7f":
                line = line[:-1]
                chan.sendall(b"\b \b")
            else:
                line += c
                chan.sendall(c)


class SSHServerThread:
    def __init__(self, pubkey=None):
        self.host_key = paramiko.ECDSAKey.generate()
        self.pubkey = pubkey
        self.terms: list[str] = []
        self.forwards: list = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.running = True
        self.transports = []
        self.servers = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        t = paramiko.Transport(conn)
        t.add_server_key(self.host_key)
        srv = _Server(self)
        try:
            t.start_server(server=srv)
        except Exception:  # noqa: BLE001 - a client that went away
            return
        self.transports.append(t)
        self.servers.append(srv)
        while t.is_active():
            chan = t.accept(timeout=1)
            if chan is None:
                continue
            if chan.get_id() in srv.direct:
                threading.Thread(target=self._relay, args=(chan, srv.direct[chan.get_id()]), daemon=True).start()
                continue
            if srv.shell.wait(5):
                threading.Thread(target=_shell, args=(chan, srv), daemon=True).start()

    def _relay(self, chan, dest):
        """Forwarded connections: the test target is an echo server on the destination port."""
        try:
            s = socket.create_connection((dest[0] if dest[0] != "localhost" else "127.0.0.1", dest[1]), timeout=5)
        except OSError:
            chan.close()
            return
        from pr7tm.backends import _pump
        _pump(s, chan)

    def stop(self):
        self.running = False
        self.sock.close()
        for t in self.transports:
            t.close()
