from kokpit.collectord import tick


class FakeHost:
    def collect(self, now_ms, dt_s):
        return {"cpu.thread.0.util": 12.0}


class FakeStore:
    def __init__(self):
        self.written = []
    def write(self, ts_ms, samples):
        self.written.append((ts_ms, samples))


class FakeLive:
    def __init__(self):
        self.published = []
    def publish(self, snapshot):
        self.published.append(snapshot)


class FakeProcs:
    def top(self):
        return [{"pid": 1, "name": "x", "cpu": 1.0, "rss": 1.0, "vram": 0.0}]


def test_tick_writes_and_publishes():
    store, live = FakeStore(), FakeLive()
    tick(FakeHost(), store, live, FakeProcs(), now_ms=5000, dt_s=1.0)
    assert store.written == [(5000, {"cpu.thread.0.util": 12.0})]
    snap = live.published[0]
    assert snap["ts"] == 5000
    assert snap["series"] == {"cpu.thread.0.util": 12.0}
    assert snap["procs"][0]["pid"] == 1
