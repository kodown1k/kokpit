from kokpit.actuator.intents import parse_intent


def test_quiet_default_ttl():
    a = parse_intent("zrób cicho")
    assert a["verb"] == "apply" and a["lever"] == "governor"
    assert a["params"]["name"] == "powersave" and a["ttl_s"] == 1800


def test_quiet_with_minutes():
    a = parse_intent("cicho na 15 min")
    assert a["ttl_s"] == 900


def test_release_all():
    assert parse_intent("zwolnij wszystko") == {"verb": "revert_all"}
    assert parse_intent("release all") == {"verb": "revert_all"}


def test_cap_gpu():
    a = parse_intent("cap gpu 180W")
    assert a["lever"] == "gpu_power" and a["params"]["watts"] == 180


def test_unrecognised_returns_none():
    assert parse_intent("ugabuga") is None
