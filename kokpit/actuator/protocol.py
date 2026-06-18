import json
from dataclasses import dataclass, field

VERBS = frozenset(
    {"apply", "revert", "revert_all", "list", "oracle", "propose", "intent", "confirm", "deny"}
)


@dataclass(frozen=True)
class Request:
    verb: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Response:
    ok: bool
    data: dict = field(default_factory=dict)
    error: str | None = None


def encode_request(req: Request) -> bytes:
    return (json.dumps({"verb": req.verb, "args": req.args}) + "\n").encode()


def decode_request(line: bytes) -> Request:
    try:
        obj = json.loads(line.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"malformed request: {e}") from e
    verb = obj.get("verb")
    if verb not in VERBS:
        raise ValueError(f"unknown verb: {verb!r}")
    args = obj.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    return Request(verb=verb, args=args)


def encode_response(resp: Response) -> bytes:
    return (json.dumps({"ok": resp.ok, "data": resp.data, "error": resp.error}) + "\n").encode()


def decode_response(line: bytes) -> Response:
    obj = json.loads(line.decode())
    return Response(ok=bool(obj["ok"]), data=obj.get("data") or {}, error=obj.get("error"))
