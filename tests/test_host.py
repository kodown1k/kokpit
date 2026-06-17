from kokpit.host import LocalHost


class GoodSource:
    name = "good"
    def sample(self, now_ms, dt_s):
        return {"good.x": 1.0}


class BoomSource:
    name = "boom"
    def sample(self, now_ms, dt_s):
        raise RuntimeError("nope")


def test_collect_merges_and_isolates_errors():
    host = LocalHost([GoodSource(), BoomSource()])
    out = host.collect(now_ms=0, dt_s=1.0)
    assert out == {"good.x": 1.0}     # błąd BoomSource nie wywala zbioru
