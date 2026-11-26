"""What a terminal pane talks to (no Qt): a local shell or an SSH session, one interface.

    start(cols, rows)   connect / start the program, then read on a thread: on_data(bytes) for output,
                        on_exit(message) when it ends
    write(bytes)        what the user types (and the terminal's replies)
    resize(cols, rows)  the pane changed size (SIGWINCH / ConPTY resize / SSH window-change)
    close()

Local shells on Windows go through ConPTY, Windows' own pseudo console (pywinpty), so PowerShell, WSL and full-screen
programs behave as in Windows Terminal. On Linux (tests) a real pseudo terminal (os.openpty).

SSH is paramiko (PR7-F's and PR7-E's library): known host keys in <data>/known_hosts (a new key asks, a changed key
refuses, as PuTTY), a key file or a password (from Credential Manager, else asked), keep-alive, a command after
connecting, and local port forwarding (ssh -L). `ask(kind, payload)` is how a backend asks the user from its thread
("hostkey", "password", "passphrase")."""

from __future__ import annotations

import os
import select
import socket
import struct
import subprocess
import sys
import threading
import time

from . import sessions


class Backend:
    def __init__(self):
        self.on_data = lambda data: None
        self.on_exit = lambda message: None
        self.alive = False
        self.description = ""

    def start(self, cols: int, rows: int):
        raise NotImplementedError

    def write(self, data: bytes):
        raise NotImplementedError

    def resize(self, cols: int, rows: int):
        pass

    def close(self):
        pass


# ==================================================================== local shells
class LocalBackend(Backend):
    def __init__(self, argv: list[str], cwd: str | None = None, env: dict | None = None):
        super().__init__()
        self.argv, self.cwd = argv, cwd or os.path.expanduser("~")
        self.env = env
        self.description = os.path.basename(argv[0])
        self.proc = None
        self.fd = None

    def start(self, cols: int, rows: int):
        if sys.platform == "win32":
            from winpty import PtyProcess
            env = dict(os.environ if self.env is None else self.env)
            env.setdefault("TERM", "xterm-256color")
            self.proc = PtyProcess.spawn(subprocess.list2cmdline(self.argv), cwd=self.cwd, env=env,
                                         dimensions=(rows, cols))
            self.alive = True
            threading.Thread(target=self._read_windows, daemon=True).start()
            return
        master, slave = os.openpty()
        self._winsize(slave, cols, rows)
        env = dict(os.environ if self.env is None else self.env)
        env.update({"TERM": "xterm-256color", "COLUMNS": str(cols), "LINES": str(rows)})
        def controlling_tty():                  # in the child, after its new session: the pty is its terminal
            import fcntl
            import termios
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        self.proc = subprocess.Popen(self.argv, stdin=slave, stdout=slave, stderr=slave, cwd=self.cwd, env=env,
                                     start_new_session=True, close_fds=True, preexec_fn=controlling_tty)
        os.close(slave)
        self.fd = master
        self.alive = True
        threading.Thread(target=self._read_posix, daemon=True).start()

    @staticmethod
    def _winsize(fd, cols, rows):
        import fcntl
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _read_posix(self):
        fd = self.fd                              # close() may clear self.fd meanwhile
        while True:
            try:
                r, _, _ = select.select([fd], [], [], 0.5)
                if not r:
                    if self.proc.poll() is not None:
                        break
                    continue
                data = os.read(fd, 65536)
            except (OSError, ValueError, TypeError):
                break
            if not data:
                break
            self.on_data(data)
        self.alive = False
        code = self.proc.wait()
        self.on_exit(f"The program ended (exit code {code}).")

    def _read_windows(self):
        while True:
            try:
                text = self.proc.read(65536)
            except EOFError:
                break
            except Exception:  # noqa: BLE001 - the console went away
                break
            if text:
                self.on_data(text.encode("utf-8", "surrogateescape") if isinstance(text, str) else text)
            elif not self.proc.isalive():
                break
            else:
                time.sleep(0.01)
        self.alive = False
        code = self.proc.exitstatus if self.proc is not None else None
        self.on_exit(f"The program ended (exit code {code}).")

    def write(self, data: bytes):
        if not self.alive:
            return
        try:
            if sys.platform == "win32":
                self.proc.write(data.decode("utf-8", "replace"))
            else:
                os.write(self.fd, data)
        except OSError:
            pass

    def resize(self, cols: int, rows: int):
        try:
            if sys.platform == "win32":
                if self.proc is not None:
                    self.proc.setwinsize(rows, cols)
            elif self.fd is not None:
                self._winsize(self.fd, cols, rows)
        except Exception:  # noqa: BLE001 - it ended meanwhile
            pass

    def close(self):
        self.alive = False
        try:
            if sys.platform == "win32":
                if self.proc is not None:
                    self.proc.terminate(force=True)
            elif self.proc is not None:
                self.proc.terminate()
                try:
                    self.proc.wait(2)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                if self.fd is not None:
                    os.close(self.fd)
                    self.fd = None
        except Exception:  # noqa: BLE001 - already gone
            pass


# ==================================================================== SSH
class HostKeyRefused(Exception):
    pass


class SSHBackend(Backend):
    def __init__(self, session: sessions.Session, ask=None, known_hosts: str | None = None):
        super().__init__()
        self.session = session
        self.ask = ask or (lambda kind, payload: None)
        self.known_hosts = known_hosts or sessions.known_hosts()
        self.description = session.target()
        self.transport = None
        self.channel = None
        self.forward_sockets: list[socket.socket] = []

    # ------------------------------------------------------------ connecting
    def host_name(self) -> str:
        s = self.session
        return s.host if (s.port or 22) == 22 else f"[{s.host}]:{s.port}"

    def check_host_key(self, key):
        """PuTTY's rule: a known key goes through, a new one asks (fingerprint shown), a changed one is refused."""
        import base64
        import hashlib
        import paramiko
        hk = paramiko.HostKeys()
        if os.path.exists(self.known_hosts):
            try:
                hk.load(self.known_hosts)
            except (OSError, paramiko.SSHException):
                pass
        name = self.host_name()
        known = hk.lookup(name)
        if known is not None and key.get_name() in known:
            if known[key.get_name()] == key:
                return
            raise ConnectionError(f"The server's key has CHANGED since you last connected ({name}). If you didn't "
                                  "change the server, someone may be in between: not connecting.")
        fp = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if not self.ask("hostkey", (name, key.get_name(), fp)):
            raise HostKeyRefused("The server's key wasn't accepted.")
        hk.add(name, key.get_name(), key)
        os.makedirs(os.path.dirname(self.known_hosts) or ".", exist_ok=True)
        hk.save(self.known_hosts)

    def connect(self):
        """Connect, check the host key, then sign in (in that order: no password goes to a server not yet trusted)."""
        import paramiko
        s = self.session
        try:
            sock = socket.create_connection((s.host, s.port or 22), timeout=15)
        except OSError as e:
            raise ConnectionError(f"Couldn't connect to {s.host}: {e}")
        t = paramiko.Transport(sock)
        t.banner_timeout = 15
        try:
            t.start_client(timeout=15)
            self.check_host_key(t.get_remote_server_key())
            self._auth(t)
        except (ConnectionError, HostKeyRefused):
            t.close()
            raise
        except paramiko.AuthenticationException:
            t.close()
            raise ConnectionError("The server didn't accept the sign-in.")
        except (socket.error, paramiko.SSHException, EOFError) as e:
            t.close()
            raise ConnectionError(f"Couldn't connect to {s.host}: {e}")
        self.transport = t
        return t

    def _auth(self, t):
        import paramiko
        s = self.session
        user = s.user or os.environ.get("USERNAME") or os.environ.get("USER") or ""
        saved = sessions.secret(s.id)
        if s.auth == "agent":
            for k in paramiko.Agent().get_keys():
                try:
                    t.auth_publickey(user, k)
                    return
                except paramiko.AuthenticationException:
                    continue
            raise paramiko.AuthenticationException("no agent key was accepted")
        if s.auth == "key":
            path = os.path.expanduser(s.key_file)
            try:
                key = paramiko.PKey.from_path(path, saved.encode() if saved else None)
            except (paramiko.PasswordRequiredException, TypeError):   # newer paramiko: TypeError from cryptography
                phrase = self.ask("passphrase", s)
                if phrase is None:
                    raise ConnectionError("No passphrase given for the key.")
                try:
                    key = paramiko.PKey.from_path(path, phrase.encode())
                except (ValueError, TypeError, paramiko.SSHException):
                    raise ConnectionError("That passphrase doesn't open the key.")
            except (OSError, ValueError, paramiko.SSHException) as e:
                raise ConnectionError(f"The key file couldn't be read: {e}")
            t.auth_publickey(user, key)
            return
        password = saved or self.ask("password", s)
        if password is None:
            raise ConnectionError("No password given.")
        try:
            self._password(t, user, password)
        except paramiko.AuthenticationException:
            if not saved:
                raise
            password = self.ask("password", s)              # the saved one is out of date: ask once
            if password is None:
                raise
            self._password(t, user, password)

    @staticmethod
    def _password(t, user, password):
        import paramiko
        try:
            t.auth_password(user, password)
        except paramiko.BadAuthenticationType as e:          # servers that only do keyboard-interactive
            if "keyboard-interactive" not in e.allowed_types:
                raise
            t.auth_interactive(user, lambda title, instr, prompts: [password for _ in prompts])

    def start(self, cols: int, rows: int):
        t = self.transport or self.connect()
        if self.session.keepalive:
            t.set_keepalive(int(self.session.keepalive))
        self.channel = ch = t.open_session()
        ch.get_pty(term="xterm-256color", width=cols, height=rows)
        ch.invoke_shell()
        self.alive = True
        for f in self.session.forwards:
            self._forward(f)
        if self.session.command:
            ch.send((self.session.command + "\r").encode())
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        ch = self.channel
        while True:
            try:
                data = ch.recv(65536)
            except (OSError, EOFError):
                break
            if not data:
                break
            self.on_data(data)
        self.alive = False
        code = ch.recv_exit_status() if ch.exit_status_ready() else None
        self.on_exit("The connection closed." if code is None else f"The session ended (exit code {code}).")

    def write(self, data: bytes):
        if self.alive and self.channel is not None:
            try:
                self.channel.sendall(data)
            except OSError:
                pass

    def resize(self, cols: int, rows: int):
        if self.channel is not None and self.alive:
            try:
                self.channel.resize_pty(width=cols, height=rows)
            except Exception:  # noqa: BLE001 - closing
                pass

    def close(self):
        self.alive = False
        for s in self.forward_sockets:
            try:
                s.close()
            except OSError:
                pass
        if self.transport is not None:
            self.transport.close()

    # ------------------------------------------------------------ ssh -L
    def _forward(self, f: sessions.Forward):
        lhost, _, lport = f.here.rpartition(":")
        rhost, _, rport = f.there.split()[0].rpartition(":")
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((lhost or "127.0.0.1", int(lport)))
        srv.listen(8)
        self.forward_sockets.append(srv)
        transport = self.transport

        def serve():
            while self.alive:
                try:
                    conn, peer = srv.accept()
                except OSError:
                    return
                try:
                    chan = transport.open_channel("direct-tcpip", (rhost or "localhost", int(rport)), peer)
                except Exception:  # noqa: BLE001 - the far side refused
                    conn.close()
                    continue
                threading.Thread(target=_pump, args=(conn, chan), daemon=True).start()
        threading.Thread(target=serve, daemon=True).start()


def _pump(sock: socket.socket, chan):
    try:
        while True:
            r, _, _ = select.select([sock, chan], [], [], 1.0)
            if sock in r:
                data = sock.recv(32768)
                if not data:
                    break
                chan.sendall(data)
            if chan in r:
                data = chan.recv(32768)
                if not data:
                    break
                sock.sendall(data)
    except OSError:
        pass
    finally:
        chan.close()
        sock.close()
