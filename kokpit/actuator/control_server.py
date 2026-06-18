import logging
import os
import socket
import threading

from kokpit.actuator import protocol as p
from kokpit.actuator.intents import parse_intent

log = logging.getLogger("kokpit.actuator.control")


class ControlServer:
    def __init__(self, sock_path, dispatch) -> None:
        self.sock_path = str(sock_path)
        self._dispatch = dispatch
        self._srv: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old_umask = os.umask(0o177)  # restrict socket perms from the moment of bind
        try:
            self._srv.bind(self.sock_path)
        finally:
            os.umask(old_umask)
        os.chmod(self.sock_path, 0o600)   # belt-and-suspenders: owner-only
        self._srv.listen(8)
        self._srv.settimeout(0.5)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(2.0)
            with conn.makefile("rb") as f:
                line = f.readline()
            try:
                req = p.decode_request(line)
                resp = self._dispatch(req)
            except ValueError as e:
                resp = p.Response(ok=False, error=str(e))
            except Exception as e:  # handler crash must not kill the server
                log.exception("dispatch failed")
                resp = p.Response(ok=False, error=f"internal: {e}")
            conn.sendall(p.encode_response(resp))
        except OSError:
            pass
        finally:
            conn.close()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._srv:
            self._srv.close()
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass


def build_dispatch(actuator, proposer=None):
    def dispatch(req: p.Request) -> p.Response:
        a = req.args
        if req.verb == "apply":
            try:
                token = actuator.apply(a["lever"], a.get("target", {}),
                                       a.get("params", {}), a.get("ttl_s"))
            except KeyError as e:
                return p.Response(ok=False, error=f"unknown lever or arg: {e}")
            return p.Response(ok=True, data={"token": token})
        if req.verb == "revert":
            if "token" not in a:
                return p.Response(ok=False, error="missing arg: token")
            actuator.revert(a["token"])
            return p.Response(ok=True)
        if req.verb == "revert_all":
            return p.Response(ok=True, data={"count": actuator.revert_all()})
        if req.verb == "list":
            return p.Response(ok=True, data={"active": actuator.list_active()})
        if req.verb == "intent":
            plan = parse_intent(a.get("text", ""))
            if plan is None:
                return p.Response(ok=False, error="nie rozumiem polecenia")
            if plan["verb"] == "revert_all":
                return p.Response(ok=True, data={"count": actuator.revert_all()})
            token = actuator.apply(plan["lever"], plan["target"], plan["params"], plan["ttl_s"])
            return p.Response(ok=True, data={"token": token})
        if req.verb == "propose":
            if proposer is None:
                return p.Response(ok=True, data={"proposals": []})
            return p.Response(ok=True, data={"proposals":
                              [{"id": pr.id, "text": pr.text} for pr in proposer.pending()]})
        if req.verb == "confirm":
            prop = proposer.take(a["id"]) if proposer else None
            if prop is None:
                return p.Response(ok=False, error="brak takiej propozycji")
            ac = prop.action
            token = actuator.apply(ac["lever"], ac["target"], ac["params"], ac["ttl_s"])
            return p.Response(ok=True, data={"token": token})
        if req.verb == "deny":
            if proposer:
                proposer.take(a["id"])
            return p.Response(ok=True)
        return p.Response(ok=False, error=f"verb not handled: {req.verb}")
    return dispatch
