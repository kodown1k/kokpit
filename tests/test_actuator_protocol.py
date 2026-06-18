import pytest
from kokpit.actuator import protocol as p


def test_request_roundtrip():
    req = p.Request(verb="apply", args={"lever": "renice", "pid": 1234, "value": 10, "ttl_s": 1800})
    line = p.encode_request(req)
    assert line.endswith(b"\n")
    back = p.decode_request(line)
    assert back == req


def test_response_roundtrip():
    resp = p.Response(ok=True, data={"token": "abc"}, error=None)
    assert p.decode_response(p.encode_response(resp)) == resp


def test_unknown_verb_rejected():
    with pytest.raises(ValueError):
        p.decode_request(b'{"verb": "rm_rf", "args": {}}\n')


def test_malformed_json_rejected():
    with pytest.raises(ValueError):
        p.decode_request(b'not json\n')


# --- decode_response robustness (IMPORTANT #3) ---

def test_decode_response_malformed_json_raises_value_error():
    with pytest.raises(ValueError):
        p.decode_response(b"not json\n")


def test_decode_response_empty_line_raises_value_error():
    with pytest.raises(ValueError):
        p.decode_response(b"")
