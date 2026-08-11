from kokpit.actuator.audit import AuditLog


def test_record_and_tail(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("apply", {"lever": "renice", "pid": 10})
    log.record("revert", {"token": "t1"})
    rows = log.tail()
    assert [r["event"] for r in rows] == ["apply", "revert"]
    assert rows[0]["detail"]["pid"] == 10
    assert isinstance(rows[0]["ts_ms"], int)


def test_tail_limit(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(10):
        log.record("apply", {"i": i})
    assert [r["detail"]["i"] for r in log.tail(3)] == [7, 8, 9]


def test_tail_missing_file_is_empty(tmp_path):
    assert AuditLog(tmp_path / "nope.jsonl").tail() == []


def test_tail_skips_corrupted_trailing_line(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.record("apply", {"lever": "renice", "pid": 10})
    with path.open("ab") as f:
        f.write(b"\x00" * 64)
    rows = log.tail()
    assert [r["event"] for r in rows] == ["apply"]
