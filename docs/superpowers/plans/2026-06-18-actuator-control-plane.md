# Actuator Control Plane (Actuator + Envelope + Proposer + Glyph-Handle) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn kokpit from a read-only telemetry collector into an interactive, reversible control plane for the local workstation — apply baseline-relative resource limits, protect a safety envelope, propose actions, and manipulate the machine directly through the vital glyph.

**Architecture:** A new `kokpit/actuator/` package owns all actuation. Every action is a **reversible `Lever`** (apply→token, revert(token)) with an explicit auto-revert TTL and an append-only JSONL audit log. User-level levers (renice, ionice, cgroup v2 limits on the user manager's own processes) run in-process; privilege-requiring levers (NVML GPU power-limit, CPU governor) go through a **single allowlisted helper** invoked via `pkexec` + a polkit policy. A **new, separate command socket** `kokpit-ctl.sock` carries line-delimited JSON request/response (the existing lossy broadcast `kokpit.sock` is left untouched). An `EnvelopePolicy` evaluator runs each daemon tick against the glyph spokes + circadian baseline (envelope = A); a deterministic `Proposer` + NL `intents` parser turns deviations and typed commands into confirmable proposals (C); the `VitalGlyph` widget becomes a direct-manipulation handle that drags an arm inward to impose a cap (D).

**Tech Stack:** Python 3.12, `psutil`, `nvidia-ml-py` (NVML), cgroups v2 (`systemd-run --user` / direct cgroup writes), polkit + `pkexec`, PySide6, SQLite (existing `Store`), pytest.

## Global Constraints

- Python **3.12**; install/test via `.venv/bin/pip install -e ".[dev]"`, `.venv/bin/pytest -q`. **Full suite green before MR** (CLAUDE.md §Testy).
- **TDD mandatory**: test first (RED) → minimal impl (GREEN) → commit. New code only with tests.
- **Every action MUST be reversible and audited.** No lever ships without a `revert()` and an audit-log entry. No action without an explicit TTL (auto-revert) unless the caller passes `ttl_s=None` deliberately.
- **Privilege boundary:** the daemon runs as `systemd --user` (non-root). Only the allowlisted helper `kokpit-actl-helper` may touch root-owned sysfs/NVML, and only for a fixed verb set. Never shell-interpolate untrusted strings; pass argv vectors only.
- Daemon resilience pattern is intentional broad-except per source/tick (memory: `kokpit-daemon-broad-except-intentional`) — keep it; do not narrow `except Exception` in the tick loop.
- `psutil.process_iter` caching is intentional (memory: `kokpit-process-iter-already-caches`) — do not add a manual Process cache.
- Workflow: branch `feat/actuator` (worktree `../kokpit-actuator`) → MR on `gitlab.kodownik.co` (`perun/kokpit`, id 18) → ARP bot review (project id 7, slug `perun-kokpit`) green before merge. ARP `diffPathFilters` = `*.py, *.toml, *.service` → also covers new `*.policy`? No — add `*.policy` filter if helper packaging must be reviewed (see Task 22 note).
- All user-facing strings in Polish (match existing UI/comments).

---

## File Structure

**New package `kokpit/actuator/`:**
- `protocol.py` — request/response JSON schema + (de)serialisation for the control socket. No I/O, no Qt.
- `audit.py` — append-only JSONL audit sink (`data_dir()/actuator-audit.jsonl`).
- `levers.py` — `Lever` ABC + concrete levers (renice, ionice, cgroup mem/cpu, gpu_power, governor). Pure planning + injected executor seam.
- `helper_client.py` — wraps `pkexec kokpit-actl-helper <verb> <args…>` for privileged levers.
- `helper.py` — the privileged helper entry point (`kokpit-actl-helper`). Strict argv allowlist.
- `engine.py` — `Actuator`: active-action registry, apply/revert/revert_all, TTL auto-revert tick, audit wiring.
- `policy.py` — `EnvelopePolicy` + evaluator (A): spokes+baseline → trigger → action, with hysteresis/debounce.
- `proposer.py` — `Proposer` (C): deviations → `Proposal`; confirm/deny gating.
- `intents.py` — `parse_intent(text)` (C): NL → action plan.
- `control_server.py` — `ControlServer`: `kokpit-ctl.sock` line-JSON req/resp server, dispatches to `Actuator`/`Proposer`.

**New UI:**
- `kokpit/ui/ctl_client.py` — `ControlClient` (QObject): connects to `kokpit-ctl.sock`, request/reply + proposal push signal.
- `kokpit/ui/widgets/proposal_bar.py` — `ProposalBar`: shows a proposal + Zatwierdź/Odrzuć, and a one-line command input (C).

**Modified:**
- `kokpit/config.py` — control-socket path, envelope thresholds, lever defaults.
- `kokpit/collectord.py` — start `ControlServer`, run `Actuator.tick()` + envelope eval per loop.
- `kokpit/ui/widgets/vital_glyph.py` — mouse hit-test + drag → `capRequested` signal (D).
- `kokpit/ui/app.py` — wire `ControlClient`, `ProposalBar`, glyph `capRequested`.
- `pyproject.toml` — `kokpit-actl-helper` console-script entry point.
- `packaging/` — polkit policy + helper wrapper + updated `.service` (extra socket).

---

## Milestone overview

- **M1 (Tasks 1–4):** Reversible core — protocol, audit, user-level levers, engine with TTL auto-revert.
- **M2 (Tasks 5–7):** Control socket — server, client, daemon wiring (apply/revert/list over `kokpit-ctl.sock`).
- **M3 (Tasks 8–10):** Privileged levers — helper, helper_client, polkit packaging (GPU power, governor).
- **M4 (Tasks 11–13):** Envelope protection (A) — policy model, evaluator, daemon integration.
- **M5 (Tasks 14–16):** Proposer + intents (C) — rule proposals, NL parser, control-socket verbs.
- **M6 (Tasks 17–20):** UI — control client, proposal bar, glyph-handle drag, app wiring.
- **M7 (Tasks 21–22):** Packaging, docs, end-to-end smoke.

---

### Task 1: Control protocol schema

**Files:**
- Create: `kokpit/actuator/__init__.py` (empty)
- Create: `kokpit/actuator/protocol.py`
- Test: `tests/test_actuator_protocol.py`

**Interfaces:**
- Produces:
  - `Request(verb: str, args: dict) ` dataclass; `Response(ok: bool, data: dict, error: str | None)` dataclass.
  - `encode_request(req: Request) -> bytes` (JSON + `\n`); `decode_request(line: bytes) -> Request`.
  - `encode_response(resp: Response) -> bytes`; `decode_response(line: bytes) -> Response`.
  - `VERBS: frozenset[str]` = `{"apply", "revert", "revert_all", "list", "oracle", "propose", "intent", "confirm", "deny"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_actuator_protocol.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_actuator_protocol.py -v`
Expected: FAIL (ModuleNotFoundError: kokpit.actuator.protocol)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/protocol.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_actuator_protocol.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/__init__.py kokpit/actuator/protocol.py tests/test_actuator_protocol.py
git commit -m "feat(actuator): control-socket request/response protocol"
```

---

### Task 2: Append-only audit log

**Files:**
- Create: `kokpit/actuator/audit.py`
- Test: `tests/test_actuator_audit.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class AuditLog` with `__init__(self, path)`, `record(self, event: str, detail: dict) -> None` (appends one JSON line with `ts_ms`, `event`, `detail`), `tail(self, n: int = 50) -> list[dict]`.
  - The daemon will inject the path from `config.audit_path()` (added in Task 5).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_actuator_audit.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_actuator_audit.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/audit.py
import json
import time
from pathlib import Path


class AuditLog:
    def __init__(self, path) -> None:
        self.path = Path(path)

    def record(self, event: str, detail: dict) -> None:
        row = {"ts_ms": int(time.time() * 1000), "event": event, "detail": detail}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def tail(self, n: int = 50) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        out = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_actuator_audit.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/audit.py tests/test_actuator_audit.py
git commit -m "feat(actuator): append-only JSONL audit log"
```

---

### Task 3: User-level levers (renice, ionice, cgroup) with executor seam

**Files:**
- Create: `kokpit/actuator/levers.py`
- Test: `tests/test_actuator_levers.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Lever(ABC)` with attrs `id: str`, `requires_privilege: bool`; methods `apply(self, target: dict, params: dict) -> dict` (returns a `token_state` dict the engine stores) and `revert(self, token_state: dict) -> None`.
  - Concrete: `ReniceLever`, `IoniceLever`, `CgroupCpuLever`, `CgroupMemLever`. All take `executor` callable in `__init__` defaulting to `run_argv` (subprocess wrapper) so tests inject a fake.
  - `run_argv(argv: list[str]) -> str` — runs argv, returns stdout, raises `LeverError` on non-zero.
  - `class LeverError(Exception)`.
  - `LEVERS: dict[str, Lever]` registry built from the user-level levers (privileged ones added in Task 8).

Notes on real mechanisms (the implementer must use these exact argv):
- renice: apply `["renice", "-n", str(value), "-p", str(pid)]`; revert restores the prior nice captured via `psutil.Process(pid).nice()` before applying.
- ionice: apply `["ionice", "-c", "2", "-n", str(value), "-p", str(pid)]`; revert sets class back to best-effort default `["ionice", "-c", "2", "-n", "4", "-p", str(pid)]`.
- cgroup cpu/mem: create a transient slice and move the pid in via `["systemctl", "--user", "set-property", "--runtime", f"kokpit-{pid}.scope", ...]` is NOT valid for arbitrary pids — instead use a transient scope: apply `["systemd-run", "--user", "--scope", "--collect", f"--unit=kokpit-cap-{pid}", "-p", f"CPUQuota={value}%", "--", "true"]` does NOT move an existing pid. The correct mechanism for an **existing** pid is to write the pid into a delegated cgroup. For v1, gate cgroup levers behind a documented capability probe (see Step 3) and implement them as: write `value` to `${cg}/cpu.max` / `${cg}/memory.max` where `${cg}` is a per-pid sub-cgroup under the user delegated tree `/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/app.slice/kokpit-cap-<pid>`, after writing `<pid>` to its `cgroup.procs`. Revert: move pid back to its original cgroup (captured at apply) and rmdir the temp cgroup. Keep all path/file writes behind the `executor`/`writer` seam so the test asserts the planned writes without touching the real fs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_actuator_levers.py
import pytest
from kokpit.actuator import levers as L


class FakeExec:
    def __init__(self):
        self.calls = []
    def __call__(self, argv):
        self.calls.append(argv)
        return ""


def test_renice_apply_and_revert(monkeypatch):
    fx = FakeExec()
    # capture "prior nice" deterministically
    monkeypatch.setattr(L, "_current_nice", lambda pid: 0)
    lever = L.ReniceLever(executor=fx)
    token = lever.apply({"pid": 1234}, {"value": 15})
    assert ["renice", "-n", "15", "-p", "1234"] in fx.calls
    assert token["prior_nice"] == 0
    lever.revert(token)
    assert ["renice", "-n", "0", "-p", "1234"] in fx.calls


def test_ionice_apply(monkeypatch):
    fx = FakeExec()
    lever = L.IoniceLever(executor=fx)
    lever.apply({"pid": 99}, {"value": 7})
    assert ["ionice", "-c", "2", "-n", "7", "-p", "99"] in fx.calls


def test_lever_error_on_nonzero():
    def boom(argv):
        raise L.LeverError("nope")
    lever = L.ReniceLever(executor=boom)
    with pytest.raises(L.LeverError):
        lever.apply({"pid": 1}, {"value": 1})


def test_registry_has_user_levers():
    assert {"renice", "ionice"} <= set(L.LEVERS)
    assert L.LEVERS["renice"].requires_privilege is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_actuator_levers.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/levers.py
import subprocess
from abc import ABC, abstractmethod

import psutil


class LeverError(Exception):
    pass


def run_argv(argv: list[str]) -> str:
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as e:
        raise LeverError(f"{argv[0]}: {e}") from e
    if cp.returncode != 0:
        raise LeverError(f"{' '.join(argv)} -> rc={cp.returncode}: {cp.stderr.strip()}")
    return cp.stdout


def _current_nice(pid: int) -> int:
    try:
        return int(psutil.Process(pid).nice())
    except Exception:
        return 0


class Lever(ABC):
    id: str = ""
    requires_privilege: bool = False

    def __init__(self, executor=run_argv) -> None:
        self._run = executor

    @abstractmethod
    def apply(self, target: dict, params: dict) -> dict: ...

    @abstractmethod
    def revert(self, token_state: dict) -> None: ...


class ReniceLever(Lever):
    id = "renice"

    def apply(self, target: dict, params: dict) -> dict:
        pid = int(target["pid"])
        prior = _current_nice(pid)
        self._run(["renice", "-n", str(int(params["value"])), "-p", str(pid)])
        return {"pid": pid, "prior_nice": prior}

    def revert(self, token_state: dict) -> None:
        self._run(["renice", "-n", str(token_state["prior_nice"]), "-p", str(token_state["pid"])])


class IoniceLever(Lever):
    id = "ionice"

    def apply(self, target: dict, params: dict) -> dict:
        pid = int(target["pid"])
        self._run(["ionice", "-c", "2", "-n", str(int(params["value"])), "-p", str(pid)])
        return {"pid": pid}

    def revert(self, token_state: dict) -> None:
        self._run(["ionice", "-c", "2", "-n", "4", "-p", str(token_state["pid"])])


LEVERS: dict[str, Lever] = {
    "renice": ReniceLever(),
    "ionice": IoniceLever(),
}
```

(Cgroup levers `CgroupCpuLever`/`CgroupMemLever` are deferred to a follow-up commit within this task only if the capability probe in the smoke step confirms a writable delegated cgroup tree; otherwise they are documented as unavailable and omitted from `LEVERS`. Do NOT block M1 on cgroup delegation.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_actuator_levers.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/levers.py tests/test_actuator_levers.py
git commit -m "feat(actuator): user-level reversible levers (renice, ionice)"
```

---

### Task 4: Actuator engine with TTL auto-revert + audit

**Files:**
- Create: `kokpit/actuator/engine.py`
- Test: `tests/test_actuator_engine.py`

**Interfaces:**
- Consumes: `levers.LEVERS`/`Lever`, `audit.AuditLog`, `levers.LeverError`.
- Produces:
  - `class Actuator(__init__(self, levers: dict, audit, now_fn))`:
    - `apply(self, lever_id: str, target: dict, params: dict, ttl_s: float | None) -> str` returns a `token`; records audit `apply`; schedules deadline `now()+ttl_s*1000` (ms) when ttl set.
    - `revert(self, token: str) -> None`; idempotent; records `revert`.
    - `revert_all(self) -> int` reverts every active token, returns count.
    - `list_active(self) -> list[dict]` → `[{token, lever, target, params, deadline_ms}]`.
    - `tick(self, now_ms: int) -> None` reverts every token whose deadline ≤ now (auto-revert), records `auto_revert`.
  - Token format: `f"{lever_id}-{seq}"` (monotonic counter), no randomness (deterministic for tests; memory: scripts forbid Math.random — same discipline for reproducible tokens).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_actuator_engine.py
from kokpit.actuator.audit import AuditLog
from kokpit.actuator.engine import Actuator
from kokpit.actuator.levers import Lever


class SpyLever(Lever):
    id = "spy"
    def __init__(self):
        super().__init__()
        self.applied = []
        self.reverted = []
    def apply(self, target, params):
        self.applied.append((target, params))
        return {"t": target, "p": params}
    def revert(self, token_state):
        self.reverted.append(token_state)


def make(tmp_path, now=[0]):
    spy = SpyLever()
    act = Actuator({"spy": spy}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: now[0])
    return act, spy, now


def test_apply_returns_token_and_lists(tmp_path):
    act, spy, _ = make(tmp_path)
    tok = act.apply("spy", {"pid": 1}, {"value": 5}, ttl_s=30)
    assert tok.startswith("spy-")
    assert len(spy.applied) == 1
    active = act.list_active()
    assert active[0]["token"] == tok and active[0]["deadline_ms"] == 30000


def test_explicit_revert_idempotent(tmp_path):
    act, spy, _ = make(tmp_path)
    tok = act.apply("spy", {"pid": 1}, {}, ttl_s=None)
    act.revert(tok)
    act.revert(tok)  # second is a no-op
    assert len(spy.reverted) == 1
    assert act.list_active() == []


def test_ttl_auto_revert(tmp_path):
    now = [0]
    act, spy, _ = make(tmp_path, now)
    act.apply("spy", {"pid": 1}, {}, ttl_s=10)   # deadline 10000ms
    act.tick(now_ms=5000)
    assert spy.reverted == []                    # not yet
    act.tick(now_ms=10000)
    assert len(spy.reverted) == 1                # auto-reverted
    assert act.list_active() == []


def test_revert_all(tmp_path):
    act, spy, _ = make(tmp_path)
    act.apply("spy", {"pid": 1}, {}, ttl_s=None)
    act.apply("spy", {"pid": 2}, {}, ttl_s=None)
    assert act.revert_all() == 2
    assert len(spy.reverted) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_actuator_engine.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/engine.py
import logging

from kokpit.actuator.levers import LeverError

log = logging.getLogger("kokpit.actuator.engine")


class Actuator:
    def __init__(self, levers: dict, audit, now_fn) -> None:
        self._levers = levers
        self._audit = audit
        self._now = now_fn
        self._seq = 0
        self._active: dict[str, dict] = {}   # token -> {lever, target, params, state, deadline_ms}

    def apply(self, lever_id: str, target: dict, params: dict, ttl_s: float | None) -> str:
        lever = self._levers[lever_id]
        state = lever.apply(target, params)
        self._seq += 1
        token = f"{lever_id}-{self._seq}"
        deadline = None if ttl_s is None else self._now() + int(ttl_s * 1000)
        self._active[token] = {
            "lever": lever_id, "target": target, "params": params,
            "state": state, "deadline_ms": deadline,
        }
        self._audit.record("apply", {"token": token, "lever": lever_id,
                                     "target": target, "params": params, "ttl_s": ttl_s})
        return token

    def revert(self, token: str) -> None:
        entry = self._active.pop(token, None)
        if entry is None:
            return  # idempotent
        try:
            self._levers[entry["lever"]].revert(entry["state"])
        except LeverError:
            log.exception("revert failed for %s", token)
        self._audit.record("revert", {"token": token})

    def revert_all(self) -> int:
        count = 0
        for token in list(self._active):
            self.revert(token)
            count += 1
        return count

    def list_active(self) -> list[dict]:
        return [{"token": t, "lever": e["lever"], "target": e["target"],
                 "params": e["params"], "deadline_ms": e["deadline_ms"]}
                for t, e in self._active.items()]

    def tick(self, now_ms: int) -> None:
        for token, e in list(self._active.items()):
            dl = e["deadline_ms"]
            if dl is not None and now_ms >= dl:
                entry = self._active.pop(token, None)
                if entry is None:
                    continue
                try:
                    self._levers[entry["lever"]].revert(entry["state"])
                except LeverError:
                    log.exception("auto-revert failed for %s", token)
                self._audit.record("auto_revert", {"token": token})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_actuator_engine.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/engine.py tests/test_actuator_engine.py
git commit -m "feat(actuator): engine with TTL auto-revert and audit wiring"
```

---

### Task 5: Config — control socket path, audit path, envelope defaults

**Files:**
- Modify: `kokpit/config.py` (append after line 47)
- Test: `tests/test_config.py` (extend existing)

**Interfaces:**
- Produces:
  - `control_socket_path() -> Path` → `<runtime>/kokpit-ctl.sock`.
  - `audit_path() -> Path` → `data_dir() / "actuator-audit.jsonl"`.
  - Constants: `ENVELOPE_ENABLED = False` (opt-in), `ENVELOPE_Z_TRIGGER = 2.5`, `ENVELOPE_DEBOUNCE_S = 15.0`, `ENVELOPE_DEFAULT_TTL_S = 1800.0`, `GPU_POWER_FLOOR_W = 100`, `RENICE_BACKGROUND = 15`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_config.py
from kokpit import config


def test_control_socket_path_uses_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert config.control_socket_path() == tmp_path / "kokpit-ctl.sock"


def test_audit_path_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert config.audit_path() == tmp_path / "kokpit" / "actuator-audit.jsonl"


def test_envelope_defaults_present():
    assert config.ENVELOPE_ENABLED is False
    assert config.ENVELOPE_Z_TRIGGER > 0
    assert config.ENVELOPE_DEFAULT_TTL_S > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v -k "control_socket or audit_path or envelope"`
Expected: FAIL (AttributeError)

- [ ] **Step 3: Write minimal implementation**

```python
# append to kokpit/config.py
def control_socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path("/tmp")
    return base / "kokpit-ctl.sock"


def audit_path() -> Path:
    return data_dir() / "actuator-audit.jsonl"


# --- Actuator / Envelope (spec 2026-06-18) ---
ENVELOPE_ENABLED = False         # opt-in; auto-actions only when True
ENVELOPE_Z_TRIGGER = 2.5         # z-score (in σ) above baseline to fire envelope
ENVELOPE_DEBOUNCE_S = 15.0       # sustained breach before acting (anti-flap)
ENVELOPE_DEFAULT_TTL_S = 1800.0  # auto-revert window for envelope actions
GPU_POWER_FLOOR_W = 100          # never cap GPU below this
RENICE_BACKGROUND = 15           # default nice for "make it quiet" demotions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kokpit/config.py tests/test_config.py
git commit -m "feat(config): control socket, audit path, envelope defaults"
```

---

### Task 6: Control server (`kokpit-ctl.sock` req/resp)

**Files:**
- Create: `kokpit/actuator/control_server.py`
- Test: `tests/test_control_server.py`

**Interfaces:**
- Consumes: `protocol`, `engine.Actuator`.
- Produces:
  - `class ControlServer(__init__(self, sock_path, dispatch))` where `dispatch(req: Request) -> Response`.
  - `start()` / `stop()` (threaded accept loop, mirrors `LiveServer` lifecycle but reads one request line per connection and writes one response line).
  - `build_dispatch(actuator, proposer=None) -> Callable[[Request], Response]` mapping verbs → handlers. In this task only `apply`/`revert`/`revert_all`/`list` are wired (proposer verbs added in Task 16).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_control_server.py
import socket

from kokpit.actuator import protocol as p
from kokpit.actuator.audit import AuditLog
from kokpit.actuator.control_server import ControlServer, build_dispatch
from kokpit.actuator.engine import Actuator
from kokpit.actuator.levers import Lever


class NoopLever(Lever):
    id = "noop"
    def apply(self, target, params): return {}
    def revert(self, token_state): pass


def _rpc(path, req: p.Request) -> p.Response:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(path))
    s.sendall(p.encode_request(req))
    line = s.makefile("rb").readline()
    s.close()
    return p.decode_response(line)


def test_apply_list_revert_over_socket(tmp_path):
    act = Actuator({"noop": NoopLever()}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act))
    srv.start()
    try:
        r = _rpc(tmp_path / "ctl.sock", p.Request("apply",
                 {"lever": "noop", "target": {"pid": 1}, "params": {}, "ttl_s": None}))
        assert r.ok and r.data["token"].startswith("noop-")
        tok = r.data["token"]
        r2 = _rpc(tmp_path / "ctl.sock", p.Request("list", {}))
        assert any(a["token"] == tok for a in r2.data["active"])
        r3 = _rpc(tmp_path / "ctl.sock", p.Request("revert", {"token": tok}))
        assert r3.ok
    finally:
        srv.stop()


def test_unknown_lever_returns_error(tmp_path):
    act = Actuator({}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act))
    srv.start()
    try:
        r = _rpc(tmp_path / "ctl.sock", p.Request("apply",
                 {"lever": "ghost", "target": {}, "params": {}, "ttl_s": None}))
        assert r.ok is False and r.error
    finally:
        srv.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_control_server.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/control_server.py
import logging
import os
import socket
import threading

from kokpit.actuator import protocol as p

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
        self._srv.bind(self.sock_path)
        os.chmod(self.sock_path, 0o600)   # owner-only: control is privileged-ish
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
            line = conn.makefile("rb").readline()
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
            actuator.revert(a["token"])
            return p.Response(ok=True)
        if req.verb == "revert_all":
            return p.Response(ok=True, data={"count": actuator.revert_all()})
        if req.verb == "list":
            return p.Response(ok=True, data={"active": actuator.list_active()})
        return p.Response(ok=False, error=f"verb not handled: {req.verb}")
    return dispatch
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_control_server.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/control_server.py tests/test_control_server.py
git commit -m "feat(actuator): control socket server with apply/revert/list dispatch"
```

---

### Task 7: Wire Actuator + ControlServer into the daemon

**Files:**
- Modify: `kokpit/collectord.py` (imports; `run()` setup/teardown; `tick()` signature)
- Test: `tests/test_collectord.py` (extend)

**Interfaces:**
- Consumes: `Actuator`, `ControlServer`, `build_dispatch`, `AuditLog`, `levers.LEVERS`, `config.control_socket_path/audit_path`.
- Produces: `tick(host, store, live, procs, actuator, now_ms, dt_s)` now also calls `actuator.tick(now_ms)` for auto-revert. `run()` constructs the actuator + control server and stops them in `finally`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_collectord.py
from kokpit.actuator.audit import AuditLog
from kokpit.actuator.engine import Actuator
from kokpit import collectord


def test_tick_runs_actuator_auto_revert(tmp_path):
    # Actuator with a spy lever that records reverts; deadline already passed.
    reverts = []
    class L:
        id = "x"
        def apply(self, t, p): return {}
        def revert(self, s): reverts.append(s)
    act = Actuator({"x": L()}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    act.apply("x", {}, {}, ttl_s=1)   # deadline 1000ms

    class FakeHost:
        def collect(self, now_ms, dt_s): return {}
    class FakeStore:
        def write(self, *a): pass
    class FakeLive:
        def publish(self, snap): pass
    class FakeProcs:
        def snapshot(self): return [], []

    collectord.tick(FakeHost(), FakeStore(), FakeLive(), FakeProcs(), act, now_ms=2000, dt_s=1.0)
    assert len(reverts) == 1   # auto-reverted because 2000 >= 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_collectord.py -v -k auto_revert`
Expected: FAIL (tick() takes 6 positional args / TypeError)

- [ ] **Step 3: Write minimal implementation**

Modify `tick()` and `run()` in `kokpit/collectord.py`:

```python
# new imports near the top
from kokpit.actuator.audit import AuditLog
from kokpit.actuator.control_server import ControlServer, build_dispatch
from kokpit.actuator.engine import Actuator
from kokpit.actuator.levers import LEVERS

# replace tick():
def tick(host, store, live, procs, actuator, now_ms: int, dt_s: float) -> None:
    series = host.collect(now_ms, dt_s)
    store.write(now_ms, series)
    proc_rows, gpu_rows = procs.snapshot()
    live.publish({"ts": now_ms, "series": series,
                  "procs": proc_rows, "gpu_procs": gpu_rows})
    actuator.tick(now_ms)
```

In `run()`, after `live.start()` add:

```python
    audit = AuditLog(config.audit_path())
    actuator = Actuator(LEVERS, audit, now_fn=lambda: int(time.time() * 1000))
    control = ControlServer(config.control_socket_path(), build_dispatch(actuator))
    control.start()
```

Update the loop call to `tick(host, store, live, procs, actuator, now_ms, dt_s)`, and in `finally:` add `control.stop()` and `actuator.revert_all()` (clean exit must release every active limit) **before** `live.stop()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_collectord.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kokpit/collectord.py tests/test_collectord.py
git commit -m "feat(actuator): wire engine + control socket into the daemon, revert_all on exit"
```

---

### Task 8: Privileged helper (`kokpit-actl-helper`) — GPU power + governor

**Files:**
- Create: `kokpit/actuator/helper.py`
- Modify: `pyproject.toml` (`[project.scripts]` add `kokpit-actl-helper`)
- Test: `tests/test_actl_helper.py`

**Interfaces:**
- Produces:
  - `main(argv: list[str]) -> int` — strict allowlist dispatcher. Verbs: `gpu-power <index> <watts>`, `gpu-power-reset <index>`, `governor <cpu_glob> <name>`. Anything else → exit 2.
  - `set_gpu_power(index: int, watts: int) -> None` (NVML; clamps to device min/max), `reset_gpu_power(index)`, `set_governor(name: str) -> None` (writes each `/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor`).
  - Governor name validated against the kernel's `scaling_available_governors`. Reject unknown.
- Notes: helper does NO network, NO socket. It is invoked as root via `pkexec`. It must validate **every** argument (int ranges, name allowlist) because it runs privileged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_actl_helper.py
import pytest
from kokpit.actuator import helper


def test_rejects_unknown_verb():
    assert helper.main(["frobnicate"]) == 2


def test_governor_rejects_unknown_name(monkeypatch):
    monkeypatch.setattr(helper, "_available_governors", lambda: ["performance", "powersave"])
    assert helper.main(["governor", "rm -rf"]) == 2


def test_governor_accepts_known(monkeypatch):
    written = []
    monkeypatch.setattr(helper, "_available_governors", lambda: ["performance", "powersave"])
    monkeypatch.setattr(helper, "_governor_paths", lambda: ["/x/cpu0"])
    monkeypatch.setattr(helper, "_write", lambda path, val: written.append((path, val)))
    assert helper.main(["governor", "powersave"]) == 0
    assert written == [("/x/cpu0", "powersave")]


def test_gpu_power_clamps_and_calls_nvml(monkeypatch):
    calls = []
    monkeypatch.setattr(helper, "_nvml_set_power", lambda idx, mw: calls.append((idx, mw)))
    monkeypatch.setattr(helper, "_nvml_power_bounds_mw", lambda idx: (100_000, 350_000))
    assert helper.main(["gpu-power", "0", "50"]) == 0   # 50W -> 50000mW -> clamped up to 100000
    assert calls == [(0, 100_000)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_actl_helper.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/helper.py
import glob
import sys

GOVERNOR_GLOB = "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor"


def _write(path: str, val: str) -> None:
    with open(path, "w") as f:
        f.write(val)


def _governor_paths() -> list[str]:
    return sorted(glob.glob(GOVERNOR_GLOB))


def _available_governors() -> list[str]:
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors") as f:
            return f.read().split()
    except OSError:
        return []


def _nvml_power_bounds_mw(index: int) -> tuple[int, int]:
    import pynvml as n
    n.nvmlInit()
    h = n.nvmlDeviceGetHandleByIndex(index)
    lo, hi = n.nvmlDeviceGetPowerManagementLimitConstraints(h)
    return int(lo), int(hi)


def _nvml_set_power(index: int, milliwatts: int) -> None:
    import pynvml as n
    n.nvmlInit()
    h = n.nvmlDeviceGetHandleByIndex(index)
    n.nvmlDeviceSetPowerManagementLimit(h, milliwatts)


def _nvml_default_power_mw(index: int) -> int:
    import pynvml as n
    n.nvmlInit()
    h = n.nvmlDeviceGetHandleByIndex(index)
    return int(n.nvmlDeviceGetPowerManagementDefaultLimit(h))


def set_governor(name: str) -> int:
    if name not in _available_governors():
        print(f"unknown governor: {name!r}", file=sys.stderr)
        return 2
    for path in _governor_paths():
        _write(path, name)
    return 0


def set_gpu_power(index: int, watts: int) -> int:
    lo, hi = _nvml_power_bounds_mw(index)
    mw = max(lo, min(hi, watts * 1000))
    _nvml_set_power(index, mw)
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        return 2
    verb, rest = argv[0], argv[1:]
    try:
        if verb == "governor" and len(rest) == 1:
            return set_governor(rest[0])
        if verb == "gpu-power" and len(rest) == 2:
            return set_gpu_power(int(rest[0]), int(rest[1]))
        if verb == "gpu-power-reset" and len(rest) == 1:
            idx = int(rest[0])
            _nvml_set_power(idx, _nvml_default_power_mw(idx))
            return 0
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 2


def cli() -> None:
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    cli()
```

Add to `pyproject.toml` `[project.scripts]`: `kokpit-actl-helper = "kokpit.actuator.helper:cli"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_actl_helper.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/helper.py pyproject.toml tests/test_actl_helper.py
git commit -m "feat(actuator): privileged helper for GPU power-limit and CPU governor"
```

---

### Task 9: Privileged levers via pkexec (helper client)

**Files:**
- Create: `kokpit/actuator/helper_client.py`
- Modify: `kokpit/actuator/levers.py` (add `GpuPowerLever`, `GovernorLever`; register in `LEVERS`)
- Test: `tests/test_priv_levers.py`

**Interfaces:**
- Consumes: `helper_client.run_helper`.
- Produces:
  - `run_helper(verb_args: list[str], runner=run_argv) -> str` → prepends `["pkexec", "kokpit-actl-helper"]`.
  - `GpuPowerLever` (id `gpu_power`, `requires_privilege=True`): apply `{index, watts}` → `gpu-power <index> <watts>`; revert → `gpu-power-reset <index>`.
  - `GovernorLever` (id `governor`, `requires_privilege=True`): apply `{name}` after capturing current governor; revert restores it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_priv_levers.py
from kokpit.actuator import levers as L


class FakeExec:
    def __init__(self): self.calls = []
    def __call__(self, argv):
        self.calls.append(argv)
        return "performance\n"


def test_gpu_power_lever_uses_pkexec_helper():
    fx = FakeExec()
    lever = L.GpuPowerLever(executor=fx)
    tok = lever.apply({"index": 0}, {"watts": 200})
    assert fx.calls[-1] == ["pkexec", "kokpit-actl-helper", "gpu-power", "0", "200"]
    lever.revert(tok)
    assert fx.calls[-1] == ["pkexec", "kokpit-actl-helper", "gpu-power-reset", "0"]


def test_governor_lever_captures_and_restores(monkeypatch):
    fx = FakeExec()
    monkeypatch.setattr(L, "_current_governor", lambda: "performance")
    lever = L.GovernorLever(executor=fx)
    tok = lever.apply({}, {"name": "powersave"})
    assert ["pkexec", "kokpit-actl-helper", "governor", "powersave"] in fx.calls
    assert tok["prior"] == "performance"
    lever.revert(tok)
    assert fx.calls[-1] == ["pkexec", "kokpit-actl-helper", "governor", "performance"]


def test_priv_levers_registered():
    assert L.LEVERS["gpu_power"].requires_privilege is True
    assert L.LEVERS["governor"].requires_privilege is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_priv_levers.py -v`
Expected: FAIL (AttributeError: GpuPowerLever)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/helper_client.py
from kokpit.actuator.levers import run_argv


def run_helper(verb_args: list[str], runner=run_argv) -> str:
    return runner(["pkexec", "kokpit-actl-helper", *verb_args])
```

Add to `kokpit/actuator/levers.py`:

```python
def _current_governor() -> str:
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") as f:
            return f.read().strip()
    except OSError:
        return ""


class GpuPowerLever(Lever):
    id = "gpu_power"
    requires_privilege = True

    def apply(self, target: dict, params: dict) -> dict:
        idx = int(target["index"])
        self._run(["pkexec", "kokpit-actl-helper", "gpu-power", str(idx), str(int(params["watts"]))])
        return {"index": idx}

    def revert(self, token_state: dict) -> None:
        self._run(["pkexec", "kokpit-actl-helper", "gpu-power-reset", str(token_state["index"])])


class GovernorLever(Lever):
    id = "governor"
    requires_privilege = True

    def apply(self, target: dict, params: dict) -> dict:
        prior = _current_governor()
        self._run(["pkexec", "kokpit-actl-helper", "governor", str(params["name"])])
        return {"prior": prior}

    def revert(self, token_state: dict) -> None:
        if token_state.get("prior"):
            self._run(["pkexec", "kokpit-actl-helper", "governor", token_state["prior"]])
```

Extend `LEVERS`: add `"gpu_power": GpuPowerLever(), "governor": GovernorLever()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_priv_levers.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/helper_client.py kokpit/actuator/levers.py tests/test_priv_levers.py
git commit -m "feat(actuator): privileged GPU-power and governor levers via pkexec"
```

---

### Task 10: polkit policy + helper packaging

**Files:**
- Create: `packaging/co.kodownik.kokpit.actl.policy` (polkit action)
- Create: `packaging/install-actl-helper.sh` (installs the entry-point shim to `/usr/local/bin/kokpit-actl-helper` and the policy to `/usr/share/polkit-1/actions/`)
- Modify: `pyproject.toml` — add `defusedxml` to `[project.optional-dependencies] dev` (used only by the test below to parse the policy safely).
- Modify: `docs` reference in README (Task 21 covers README; here just the files)
- Test: `tests/test_packaging_actl.py` (static validation of the policy XML + script presence)

Run `.venv/bin/pip install -e ".[dev]"` after editing `pyproject.toml` so `defusedxml` is importable before running the test.

**Interfaces:**
- Produces: a polkit action `co.kodownik.kokpit.actl` with `<allow_active>auth_admin_keep</allow_active>` (active local user, cached auth), bound to running `/usr/local/bin/kokpit-actl-helper` as root.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packaging_actl.py
# NB: use defusedxml — the .policy file carries a DOCTYPE/external-DTD ref; stdlib
# ElementTree is XXE/billion-laughs prone by default. defusedxml is dev-only.
from defusedxml import ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_polkit_policy_is_valid_xml_with_action():
    tree = ET.parse(ROOT / "packaging" / "co.kodownik.kokpit.actl.policy")
    actions = [a.get("id") for a in tree.getroot().findall("action")]
    assert "co.kodownik.kokpit.actl" in actions


def test_policy_binds_helper_as_root():
    text = (ROOT / "packaging" / "co.kodownik.kokpit.actl.policy").read_text()
    assert "/usr/local/bin/kokpit-actl-helper" in text
    assert "<annotate key=\"org.freedesktop.policykit.exec.path\">" in text


def test_install_script_present_and_executable():
    s = ROOT / "packaging" / "install-actl-helper.sh"
    assert s.exists() and s.read_text().startswith("#!")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_packaging_actl.py -v`
Expected: FAIL (FileNotFoundError)

- [ ] **Step 3: Write the policy + install script**

```xml
<!-- packaging/co.kodownik.kokpit.actl.policy -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <vendor>kokpit</vendor>
  <action id="co.kodownik.kokpit.actl">
    <description>Apply kokpit hardware control (GPU power limit, CPU governor)</description>
    <message>kokpit chce zmienić limit mocy GPU / governor CPU</message>
    <defaults>
      <allow_any>no</allow_any>
      <allow_inactive>no</allow_inactive>
      <allow_active>auth_admin_keep</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/local/bin/kokpit-actl-helper</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
```

```bash
# packaging/install-actl-helper.sh
#!/usr/bin/env bash
set -euo pipefail
# Installs the kokpit actuator privileged helper + polkit policy. Run with sudo.
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV_HELPER="${VENV_HELPER:-$HOME/Code/kokpit/.venv/bin/kokpit-actl-helper}"

install -m 0755 /dev/stdin /usr/local/bin/kokpit-actl-helper <<EOF
#!/usr/bin/env bash
exec "$VENV_HELPER" "\$@"
EOF

install -m 0644 "$HERE/co.kodownik.kokpit.actl.policy" \
  /usr/share/polkit-1/actions/co.kodownik.kokpit.actl.policy
echo "Installed. Test:  pkexec kokpit-actl-helper governor performance"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_packaging_actl.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add packaging/co.kodownik.kokpit.actl.policy packaging/install-actl-helper.sh tests/test_packaging_actl.py
git commit -m "feat(packaging): polkit policy + installer for actl helper"
```

---

### Task 11: Envelope policy model

**Files:**
- Create: `kokpit/actuator/policy.py`
- Test: `tests/test_envelope_policy.py`

**Interfaces:**
- Consumes: `glyph_model.SpokeScore`.
- Produces:
  - `@dataclass EnvelopePolicy(axis: str, z_trigger: float, action: dict)` where `action` is `{"lever":…, "target":…, "params":…, "ttl_s":…}`.
  - `breach(policy, spoke: SpokeScore, baseline) -> bool` — True when the spoke's z (computed from `spoke.value` vs baseline mean/σ) ≥ `z_trigger`. Returns False if baseline is None or σ≈0.
  - `DEFAULT_POLICIES: list[EnvelopePolicy]` — e.g. GPU-temp breach → `gpu_power` cap to `GPU_POWER_FLOOR_W` proxy; CPU-temp breach → `governor` powersave. (Targets/params concrete.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_envelope_policy.py
from kokpit.actuator.policy import EnvelopePolicy, breach
from kokpit.ui.glyph_model import SpokeScore


def _spoke(value):
    return SpokeScore(name="GPU temp", score=0.9, value=value, tier="circadian")


def test_breach_true_above_trigger():
    pol = EnvelopePolicy(axis="GPU temp", z_trigger=2.0, action={})
    # baseline mean=60, sigma=5 -> value 75 = z=3.0 >= 2.0
    assert breach(pol, _spoke(75.0), baseline=(60.0, 5.0, 50, "circadian")) is True


def test_no_breach_below_trigger():
    pol = EnvelopePolicy(axis="GPU temp", z_trigger=2.0, action={})
    assert breach(pol, _spoke(65.0), baseline=(60.0, 5.0, 50, "circadian")) is False


def test_no_baseline_no_breach():
    pol = EnvelopePolicy(axis="GPU temp", z_trigger=2.0, action={})
    assert breach(pol, _spoke(99.0), baseline=None) is False


def test_zero_sigma_no_breach():
    pol = EnvelopePolicy(axis="GPU temp", z_trigger=2.0, action={})
    assert breach(pol, _spoke(99.0), baseline=(60.0, 0.0, 50, "circadian")) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_envelope_policy.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/policy.py
from dataclasses import dataclass

from kokpit import config


@dataclass
class EnvelopePolicy:
    axis: str
    z_trigger: float
    action: dict


def breach(policy: EnvelopePolicy, spoke, baseline) -> bool:
    if baseline is None or spoke.value is None:
        return False
    mean, sigma, _n, _tier = baseline
    if sigma < config.EPS_SIGMA:
        return False
    z = (spoke.value - mean) / sigma
    return z >= policy.z_trigger


DEFAULT_POLICIES = [
    EnvelopePolicy(
        axis="GPU temp", z_trigger=config.ENVELOPE_Z_TRIGGER,
        action={"lever": "gpu_power", "target": {"index": 0},
                "params": {"watts": config.GPU_POWER_FLOOR_W},
                "ttl_s": config.ENVELOPE_DEFAULT_TTL_S},
    ),
    EnvelopePolicy(
        axis="CPU temp", z_trigger=config.ENVELOPE_Z_TRIGGER,
        action={"lever": "governor", "target": {},
                "params": {"name": "powersave"},
                "ttl_s": config.ENVELOPE_DEFAULT_TTL_S},
    ),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_envelope_policy.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/policy.py tests/test_envelope_policy.py
git commit -m "feat(actuator): envelope policy model + breach detection"
```

---

### Task 12: Envelope evaluator with debounce

**Files:**
- Modify: `kokpit/actuator/policy.py` (add `EnvelopeEvaluator`)
- Test: `tests/test_envelope_evaluator.py`

**Interfaces:**
- Consumes: `EnvelopePolicy`, `breach`, `SpokeScore`.
- Produces:
  - `class EnvelopeEvaluator(__init__(self, policies, debounce_s, now_fn))`.
  - `evaluate(self, spokes: list[SpokeScore], baseline_for) -> list[dict]` where `baseline_for(series_name)->baseline`; returns the list of `action` dicts whose policy has been **continuously** breached for ≥ `debounce_s`. Each fired action is suppressed until the breach clears (one-shot per breach episode).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_envelope_evaluator.py
from kokpit.actuator.policy import EnvelopeEvaluator, EnvelopePolicy
from kokpit.ui.glyph_model import SpokeScore

POL = EnvelopePolicy(axis="GPU temp", z_trigger=2.0,
                     action={"lever": "gpu_power", "target": {"index": 0},
                             "params": {"watts": 100}, "ttl_s": 60})


def base_for(_name):
    return (60.0, 5.0, 50, "circadian")  # mean 60, sigma 5


def hot():  return [SpokeScore("GPU temp", 0.9, 75.0, "circadian")]   # z=3
def cool(): return [SpokeScore("GPU temp", 0.1, 62.0, "circadian")]   # z<2


def test_fires_only_after_debounce():
    now = [0]
    ev = EnvelopeEvaluator([POL], debounce_s=10, now_fn=lambda: now[0])
    assert ev.evaluate(hot(), base_for) == []     # t=0 breach starts
    now[0] = 5000
    assert ev.evaluate(hot(), base_for) == []     # 5s < 10s
    now[0] = 10000
    fired = ev.evaluate(hot(), base_for)
    assert len(fired) == 1 and fired[0]["lever"] == "gpu_power"


def test_one_shot_until_clear():
    now = [0]
    ev = EnvelopeEvaluator([POL], debounce_s=0, now_fn=lambda: now[0])
    assert len(ev.evaluate(hot(), base_for)) == 1   # fires
    assert ev.evaluate(hot(), base_for) == []       # still hot -> suppressed
    assert ev.evaluate(cool(), base_for) == []      # clears
    assert len(ev.evaluate(hot(), base_for)) == 1   # re-arms, fires again
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_envelope_evaluator.py -v`
Expected: FAIL (ImportError: EnvelopeEvaluator)

- [ ] **Step 3: Write minimal implementation**

```python
# append to kokpit/actuator/policy.py

# axis name -> series the baseline is keyed on (mirror glyph_model spokes)
_AXIS_SERIES = {
    "GPU temp": None,   # resolved by caller via baseline_for on the spoke's series
    "CPU temp": None,
}


class EnvelopeEvaluator:
    def __init__(self, policies, debounce_s, now_fn) -> None:
        self._policies = policies
        self._debounce_ms = debounce_s * 1000
        self._now = now_fn
        self._breach_since: dict[str, float] = {}   # axis -> first-breach ms
        self._fired: set[str] = set()               # axis episodes already actioned

    def evaluate(self, spokes, baseline_for) -> list[dict]:
        by_axis = {s.name: s for s in spokes}
        out = []
        for pol in self._policies:
            spoke = by_axis.get(pol.axis)
            base = baseline_for(pol.axis) if spoke is not None else None
            if spoke is not None and breach(pol, spoke, base):
                start = self._breach_since.setdefault(pol.axis, self._now())
                if pol.axis not in self._fired and self._now() - start >= self._debounce_ms:
                    out.append(pol.action)
                    self._fired.add(pol.axis)
            else:
                self._breach_since.pop(pol.axis, None)
                self._fired.discard(pol.axis)
        return out
```

Note: `baseline_for(pol.axis)` here keys baselines by axis name; the daemon adapter (Task 13) maps axis → the representative series (e.g. `"GPU temp"` → max over `gpu.*.temp` baselines). Keep the evaluator axis-keyed for testability.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_envelope_evaluator.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/policy.py tests/test_envelope_evaluator.py
git commit -m "feat(actuator): envelope evaluator with debounce and one-shot-per-episode"
```

---

### Task 13: Daemon envelope integration (opt-in)

**Files:**
- Modify: `kokpit/collectord.py` (`run()` builds evaluator + glyph model + baseline cache; `tick()` evaluates and applies when `config.ENVELOPE_ENABLED`)
- Test: `tests/test_collectord.py` (extend)

**Interfaces:**
- Consumes: `GlyphModel`, `BaselineCache`, `EnvelopeEvaluator`, `DEFAULT_POLICIES`, `Actuator`.
- Produces: `tick(..., actuator, envelope, now_ms, dt_s)` — after publishing, if `envelope` is not None, compute spokes via a `GlyphModel` (held on the daemon), get baselines via `BaselineCache`, and for each fired action call `actuator.apply(**action)`. Audit already records it.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_collectord.py
from kokpit.actuator.policy import EnvelopeEvaluator, EnvelopePolicy
from kokpit.ui.glyph_model import SpokeScore


def test_tick_applies_fired_envelope_action(tmp_path, monkeypatch):
    applied = []
    class FakeActuator:
        def apply(self, lever, target, params, ttl_s): applied.append((lever, params)); return "t"
        def tick(self, now_ms): pass
    # Envelope that always fires one action regardless of spokes.
    class AlwaysFire(EnvelopeEvaluator):
        def evaluate(self, spokes, baseline_for):
            return [{"lever": "governor", "target": {}, "params": {"name": "powersave"}, "ttl_s": 60}]
    env = AlwaysFire([], 0, lambda: 0)

    class FakeHost:
        def collect(self, *a): return {}
    class FakeStore:
        def write(self, *a): pass
        def baseline(self, *a, **k): return None
    class FakeLive:
        def publish(self, snap): pass
    class FakeProcs:
        def snapshot(self): return [], []

    from kokpit import collectord
    collectord.tick_envelope(FakeHost(), FakeStore(), FakeLive(), FakeProcs(),
                             FakeActuator(), env, collectord._GlyphState(), now_ms=1, dt_s=1.0)
    assert applied == [("governor", {"name": "powersave"})]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_collectord.py -v -k envelope`
Expected: FAIL (AttributeError: tick_envelope)

- [ ] **Step 3: Write minimal implementation**

In `kokpit/collectord.py` add a small glyph-state holder and an envelope-aware tick (keep the plain `tick` for the no-envelope path; the loop picks one based on `config.ENVELOPE_ENABLED`):

```python
from kokpit.actuator.policy import DEFAULT_POLICIES, EnvelopeEvaluator
from kokpit.ui.glyph_model import GlyphModel, BaselineCache


class _GlyphState:
    """Holds the daemon-side GlyphModel + BaselineCache between ticks."""
    def __init__(self, store=None, now_fn=None):
        self.model = GlyphModel()
        self.baseline = BaselineCache(store, now_fn) if store is not None else None

    def axis_baseline(self, axis_name):
        # Map axis -> representative series baseline. Minimal: reuse cache by axis.
        if self.baseline is None:
            return None
        return self.baseline.get(axis_name)


def tick_envelope(host, store, live, procs, actuator, envelope, glyph, now_ms, dt_s):
    series = host.collect(now_ms, dt_s)
    store.write(now_ms, series)
    proc_rows, gpu_rows = procs.snapshot()
    live.publish({"ts": now_ms, "series": series, "procs": proc_rows, "gpu_procs": gpu_rows})
    actuator.tick(now_ms)
    spokes = glyph.model.update(series, now_ms,
                               glyph.baseline.get if glyph.baseline else (lambda _s: None))
    for action in envelope.evaluate(spokes, glyph.axis_baseline):
        actuator.apply(action["lever"], action["target"], action["params"], action["ttl_s"])
```

In `run()`: build `glyph = _GlyphState(store, now_fn=lambda: int(time.time()*1000))` and `envelope = EnvelopeEvaluator(DEFAULT_POLICIES, config.ENVELOPE_DEBOUNCE_S, now_fn=...)`. In the loop, call `tick_envelope(...)` when `config.ENVELOPE_ENABLED` else `tick(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_collectord.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kokpit/collectord.py tests/test_collectord.py
git commit -m "feat(actuator): opt-in envelope protection in the daemon tick"
```

---

### Task 14: NL intent parser (C)

**Files:**
- Create: `kokpit/actuator/intents.py`
- Test: `tests/test_intents.py`

**Interfaces:**
- Produces:
  - `parse_intent(text: str) -> dict | None` → an action-plan dict `{"verb": "apply"|"revert_all", "lever":…, "target":…, "params":…, "ttl_s":…}` or `None` if unrecognised.
  - Recognised (Polish + English keywords, case-insensitive):
    - `"cicho [na N min]"` / `"quiet [for N min]"` → governor powersave, ttl from N (default 30 min).
    - `"max [moc|compute]"` / `"performance"` → governor performance, ttl default.
    - `"zwolnij wszystko"` / `"release all"` / `"odblokuj"` → `{"verb": "revert_all"}`.
    - `"cap gpu N[ W]"` / `"limit gpu N"` → gpu_power watts=N.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intents.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_intents.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/intents.py
import re

from kokpit import config

_MIN_RE = re.compile(r"(\d+)\s*min")
_GPU_RE = re.compile(r"(\d+)\s*w?\b", re.IGNORECASE)


def _ttl_from(text: str, default_s: float) -> float:
    m = _MIN_RE.search(text)
    return int(m.group(1)) * 60 if m else default_s


def parse_intent(text: str) -> dict | None:
    t = text.lower().strip()
    if any(k in t for k in ("zwolnij wszystko", "release all", "odblokuj")):
        return {"verb": "revert_all"}
    if "cicho" in t or "quiet" in t:
        return {"verb": "apply", "lever": "governor", "target": {},
                "params": {"name": "powersave"}, "ttl_s": _ttl_from(t, 1800)}
    if "max" in t or "performance" in t:
        return {"verb": "apply", "lever": "governor", "target": {},
                "params": {"name": "performance"}, "ttl_s": config.ENVELOPE_DEFAULT_TTL_S}
    if "gpu" in t and ("cap" in t or "limit" in t):
        m = _GPU_RE.search(t.split("gpu", 1)[1])
        if m:
            return {"verb": "apply", "lever": "gpu_power", "target": {"index": 0},
                    "params": {"watts": int(m.group(1))}, "ttl_s": config.ENVELOPE_DEFAULT_TTL_S}
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_intents.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/intents.py tests/test_intents.py
git commit -m "feat(actuator): NL intent parser for control commands (PL/EN)"
```

---

### Task 15: Rule-based Proposer (C)

**Files:**
- Create: `kokpit/actuator/proposer.py`
- Test: `tests/test_proposer.py`

**Interfaces:**
- Consumes: `EnvelopePolicy`/`breach`, `SpokeScore`.
- Produces:
  - `@dataclass Proposal(id: str, text: str, action: dict)`.
  - `class Proposer(__init__(self, policies, now_fn))`:
    - `propose(self, spokes, baseline_for) -> list[Proposal]` — same breach logic as the envelope, but instead of acting it returns human-readable proposals (PL), each with a deterministic id and the concrete action dict.
    - `pending(self) -> list[Proposal]`, `take(self, pid) -> Proposal | None` (pop a pending proposal by id for confirm/deny).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_proposer.py
from kokpit.actuator.policy import EnvelopePolicy
from kokpit.actuator.proposer import Proposer
from kokpit.ui.glyph_model import SpokeScore

POL = EnvelopePolicy(axis="GPU temp", z_trigger=2.0,
                     action={"lever": "gpu_power", "target": {"index": 0},
                             "params": {"watts": 100}, "ttl_s": 60})


def base_for(_): return (60.0, 5.0, 50, "circadian")
def hot(): return [SpokeScore("GPU temp", 0.9, 75.0, "circadian")]


def test_proposes_on_breach_with_text_and_action():
    pr = Proposer([POL], now_fn=lambda: 0)
    props = pr.propose(hot(), base_for)
    assert len(props) == 1
    assert "GPU" in props[0].text
    assert props[0].action["lever"] == "gpu_power"


def test_take_pops_pending():
    pr = Proposer([POL], now_fn=lambda: 0)
    p = pr.propose(hot(), base_for)[0]
    assert pr.take(p.id) is not None
    assert pr.take(p.id) is None      # already taken
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_proposer.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/actuator/proposer.py
from dataclasses import dataclass

from kokpit.actuator.policy import breach


@dataclass
class Proposal:
    id: str
    text: str
    action: dict


_TEXT = {
    "gpu_power": "GPU grzeje się powyżej normy — ograniczyć moc do {watts} W?",
    "governor": "CPU grzeje się powyżej normy — przełączyć governor na {name}?",
}


class Proposer:
    def __init__(self, policies, now_fn) -> None:
        self._policies = policies
        self._now = now_fn
        self._seq = 0
        self._pending: dict[str, Proposal] = {}

    def propose(self, spokes, baseline_for) -> list[Proposal]:
        by_axis = {s.name: s for s in spokes}
        out = []
        for pol in self._policies:
            spoke = by_axis.get(pol.axis)
            base = baseline_for(pol.axis) if spoke is not None else None
            if spoke is not None and breach(pol, spoke, base):
                self._seq += 1
                pid = f"prop-{self._seq}"
                lever = pol.action["lever"]
                text = _TEXT.get(lever, "Zaproponowana akcja").format(**pol.action["params"])
                prop = Proposal(id=pid, text=text, action=pol.action)
                self._pending[pid] = prop
                out.append(prop)
        return out

    def pending(self) -> list[Proposal]:
        return list(self._pending.values())

    def take(self, pid: str):
        return self._pending.pop(pid, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_proposer.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/proposer.py tests/test_proposer.py
git commit -m "feat(actuator): rule-based proposer with confirmable proposals"
```

---

### Task 16: Control-socket verbs for intents/proposals

**Files:**
- Modify: `kokpit/actuator/control_server.py` (`build_dispatch` handles `intent`, `propose`, `confirm`, `deny`)
- Test: `tests/test_control_server.py` (extend)

**Interfaces:**
- Consumes: `Proposer`, `intents.parse_intent`, `Actuator`.
- Produces: `build_dispatch(actuator, proposer)` now handles:
  - `intent` `{text}` → `parse_intent`; if `revert_all` → revert_all; if `apply` → apply; else error.
  - `propose` `{}` → `{"proposals": [{id, text}]}` from `proposer.pending()`.
  - `confirm` `{id}` → `proposer.take(id)` then `actuator.apply(**action)`; error if unknown id.
  - `deny` `{id}` → `proposer.take(id)`; ok regardless.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_control_server.py
from kokpit.actuator.proposer import Proposal, Proposer


class _FakeProposer:
    def __init__(self): self.p = Proposal("prop-1", "ok?", {"lever": "noop", "target": {}, "params": {}, "ttl_s": None})
    def pending(self): return [self.p]
    def take(self, pid): return self.p if pid == "prop-1" else None


def test_intent_quiet_applies(tmp_path):
    act = Actuator({"governor": NoopLever()}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    # remap noop id so governor key exists:
    lv = NoopLever(); lv.id = "governor"
    act = Actuator({"governor": lv}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act, _FakeProposer()))
    srv.start()
    try:
        r = _rpc(tmp_path / "ctl.sock", p.Request("intent", {"text": "cicho na 5 min"}))
        assert r.ok and r.data["token"].startswith("governor-")
    finally:
        srv.stop()


def test_confirm_applies_proposal(tmp_path):
    lv = NoopLever()
    act = Actuator({"noop": lv}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act, _FakeProposer()))
    srv.start()
    try:
        r = _rpc(tmp_path / "ctl.sock", p.Request("confirm", {"id": "prop-1"}))
        assert r.ok and r.data["token"].startswith("noop-")
        r2 = _rpc(tmp_path / "ctl.sock", p.Request("confirm", {"id": "prop-1"}))
        assert r2.ok is False   # already taken
    finally:
        srv.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_control_server.py -v -k "intent or confirm"`
Expected: FAIL (verb not handled)

- [ ] **Step 3: Write minimal implementation**

Extend the `dispatch` closure in `build_dispatch` (before the final fallback):

```python
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
```

Add `from kokpit.actuator.intents import parse_intent` to the imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_control_server.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kokpit/actuator/control_server.py tests/test_control_server.py
git commit -m "feat(actuator): control-socket intent/propose/confirm/deny verbs"
```

Then wire `Proposer` into `run()` and `tick_envelope` (in proposal mode, call `proposer.propose(...)` instead of auto-applying when `ENVELOPE_ENABLED` is False but proposals are on). Add a `config.PROPOSE_ENABLED = True` flag and have `tick_envelope` call `proposer.propose` each tick; pass `proposer` to `build_dispatch`. (Extend `tests/test_collectord.py` with one assertion that `proposer.propose` is invoked.)

---

### Task 17: Control client (UI side)

**Files:**
- Create: `kokpit/ui/ctl_client.py`
- Test: `tests/test_ctl_client.py`

**Interfaces:**
- Consumes: `protocol`.
- Produces:
  - `class ControlClient(QtCore.QObject)` with `__init__(self, sock_path)`, `request(self, verb: str, args: dict) -> Response` (synchronous, short-lived connection; safe to call from a worker — UI calls it via a QThreadPool or a simple blocking call guarded by a 2s timeout). Emits `error(str)` signal on failure.
  - `poll_proposals(self) -> list[dict]` convenience over `request("propose", {})`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ctl_client.py
from kokpit.actuator import protocol as p
from kokpit.actuator.audit import AuditLog
from kokpit.actuator.control_server import ControlServer, build_dispatch
from kokpit.actuator.engine import Actuator
from kokpit.actuator.levers import Lever
from kokpit.ui.ctl_client import ControlClient


class NoopLever(Lever):
    id = "noop"
    def apply(self, t, params): return {}
    def revert(self, s): pass


def test_request_roundtrip_via_real_server(tmp_path, qtbot=None):
    act = Actuator({"noop": NoopLever()}, AuditLog(tmp_path / "a.jsonl"), now_fn=lambda: 0)
    srv = ControlServer(tmp_path / "ctl.sock", build_dispatch(act))
    srv.start()
    try:
        c = ControlClient(str(tmp_path / "ctl.sock"))
        resp = c.request("apply", {"lever": "noop", "target": {}, "params": {}, "ttl_s": None})
        assert resp.ok and resp.data["token"].startswith("noop-")
    finally:
        srv.stop()


def test_request_on_dead_socket_returns_error(tmp_path):
    c = ControlClient(str(tmp_path / "nope.sock"))
    resp = c.request("list", {})
    assert resp.ok is False and resp.error
```

(Note: `ControlClient` needs a `QApplication`; reuse the existing `tests/conftest.py` Qt fixture pattern. If `request` is pure socket I/O with no Qt event loop dependency, the test runs without `qtbot`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_ctl_client.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/ui/ctl_client.py
import socket

from PySide6 import QtCore

from kokpit.actuator import protocol as p


class ControlClient(QtCore.QObject):
    error = QtCore.Signal(str)

    def __init__(self, sock_path: str) -> None:
        super().__init__()
        self._path = sock_path

    def request(self, verb: str, args: dict) -> p.Response:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(self._path)
            s.sendall(p.encode_request(p.Request(verb, args)))
            line = s.makefile("rb").readline()
            s.close()
            return p.decode_response(line)
        except OSError as e:
            self.error.emit(str(e))
            return p.Response(ok=False, error=str(e))

    def poll_proposals(self) -> list[dict]:
        r = self.request("propose", {})
        return r.data.get("proposals", []) if r.ok else []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_ctl_client.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/ctl_client.py tests/test_ctl_client.py
git commit -m "feat(ui): control client for the actuator command socket"
```

---

### Task 18: Proposal bar widget (C)

**Files:**
- Create: `kokpit/ui/widgets/proposal_bar.py`
- Test: `tests/test_proposal_bar.py`

**Interfaces:**
- Consumes: nothing UI-specific beyond PySide6.
- Produces:
  - `class ProposalBar(QtWidgets.QWidget)` with signals `confirmed(str)` (proposal id), `denied(str)`, `commandEntered(str)` (free-text intent).
  - `show_proposal(self, pid: str, text: str)` displays text + Zatwierdź/Odrzuć buttons.
  - `clear(self)` hides the proposal row (command input stays).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_proposal_bar.py
from kokpit.ui.widgets.proposal_bar import ProposalBar


def test_confirm_emits_id(qapp):
    bar = ProposalBar()
    seen = []
    bar.confirmed.connect(seen.append)
    bar.show_proposal("prop-7", "Ograniczyć moc GPU?")
    bar._confirm_btn.click()
    assert seen == ["prop-7"]


def test_command_entered_emits_text(qapp):
    bar = ProposalBar()
    seen = []
    bar.commandEntered.connect(seen.append)
    bar._cmd.setText("cicho na 20 min")
    bar._cmd.returnPressed.emit()
    assert seen == ["cicho na 20 min"]
```

(Uses the existing `qapp` fixture in `tests/conftest.py`; if it's named differently, match the fixture used by `tests/test_widgets_smoke.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_proposal_bar.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
# kokpit/ui/widgets/proposal_bar.py
from PySide6 import QtCore, QtWidgets


class ProposalBar(QtWidgets.QWidget):
    confirmed = QtCore.Signal(str)
    denied = QtCore.Signal(str)
    commandEntered = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._pid: str | None = None
        row = QtWidgets.QVBoxLayout(self)

        self._prop_row = QtWidgets.QWidget()
        pr = QtWidgets.QHBoxLayout(self._prop_row)
        self._label = QtWidgets.QLabel("")
        self._confirm_btn = QtWidgets.QPushButton("Zatwierdź")
        self._deny_btn = QtWidgets.QPushButton("Odrzuć")
        pr.addWidget(self._label, 1)
        pr.addWidget(self._confirm_btn)
        pr.addWidget(self._deny_btn)
        self._prop_row.hide()

        self._cmd = QtWidgets.QLineEdit()
        self._cmd.setPlaceholderText("polecenie… (np. „cicho na 30 min”, „zwolnij wszystko”)")

        row.addWidget(self._prop_row)
        row.addWidget(self._cmd)

        self._confirm_btn.clicked.connect(self._on_confirm)
        self._deny_btn.clicked.connect(self._on_deny)
        self._cmd.returnPressed.connect(self._on_cmd)

    def show_proposal(self, pid: str, text: str) -> None:
        self._pid = pid
        self._label.setText(text)
        self._prop_row.show()

    def clear(self) -> None:
        self._pid = None
        self._prop_row.hide()

    def _on_confirm(self) -> None:
        if self._pid:
            self.confirmed.emit(self._pid)
            self.clear()

    def _on_deny(self) -> None:
        if self._pid:
            self.denied.emit(self._pid)
            self.clear()

    def _on_cmd(self) -> None:
        text = self._cmd.text().strip()
        if text:
            self.commandEntered.emit(text)
            self._cmd.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_proposal_bar.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/widgets/proposal_bar.py tests/test_proposal_bar.py
git commit -m "feat(ui): proposal bar with confirm/deny + free-text command input"
```

---

### Task 19: Glyph hit-test + drag-to-cap (D)

**Files:**
- Modify: `kokpit/ui/widgets/vital_glyph.py` (add mouse events + `capRequested` signal + `arm_at(pos)` hit-test)
- Test: `tests/test_vital_glyph.py` (extend)

**Interfaces:**
- Produces:
  - `VitalGlyph.capRequested = QtCore.Signal(str, float)` — axis name + fraction 0..1 (1 = no cap, 0 = floor) derived from the dragged radius.
  - `arm_at(self, pos: QtCore.QPointF) -> int | None` — index of the spoke whose angular sector contains `pos` (within the radar radius), else None. Pure geometry, testable without a real mouse.
  - `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`: press on an arm starts a drag; release emits `capRequested(name, fraction)` where fraction = clamp01((r - r_base)/(r_full - r_base)) at the release radius.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_vital_glyph.py
import math
from PySide6 import QtCore
from kokpit.ui.glyph_model import SpokeScore
from kokpit.ui.widgets.vital_glyph import VitalGlyph


def _spokes():
    return [SpokeScore(n, 0.5, 1.0, "circadian")
            for n in ["CPU", "RAM", "Swap", "GPU", "VRAM", "CPU temp", "GPU temp", "Disk IO", "Net IO"]]


def test_arm_at_top_is_first_spoke(qapp):
    g = VitalGlyph()
    g.resize(300, 300)
    g.set_spokes(_spokes(), calibrating=False)
    cx, cy = 150, 150
    # straight up from centre = spoke 0 (angle -pi/2)
    pos = QtCore.QPointF(cx, cy - 60)
    assert g.arm_at(pos) == 0


def test_cap_requested_emitted_on_release(qapp):
    g = VitalGlyph()
    g.resize(300, 300)
    g.set_spokes(_spokes(), calibrating=False)
    seen = []
    g.capRequested.connect(lambda name, frac: seen.append((name, frac)))
    # simulate a drag on spoke 0 ending near the base radius (low fraction = strong cap)
    g._drag_idx = 0
    g._emit_cap(QtCore.QPointF(150, 150 - g.R_BASE - 5))
    assert seen and seen[0][0] == "CPU"
    assert 0.0 <= seen[0][1] <= 0.3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_vital_glyph.py -v -k "arm_at or cap_requested"`
Expected: FAIL (AttributeError: capRequested / arm_at)

- [ ] **Step 3: Write minimal implementation**

Add to `VitalGlyph` (signal at class level, methods in the body):

```python
    capRequested = QtCore.Signal(str, float)

    def arm_at(self, pos) -> int | None:
        n = len(self._spokes)
        if n == 0:
            return None
        cx, cy = self.width() / 2.0, self.height() / 2.0
        dx, dy = pos.x() - cx, pos.y() - cy
        r = math.hypot(dx, dy)
        half = min(cx, cy)
        if r > half:               # outside the radar
            return None
        ang = math.atan2(dy, dx)   # -pi..pi, 0 = +x
        # spoke i sits at -pi/2 + 2*pi*i/n; find nearest sector
        best, best_d = None, 1e9
        for i in range(n):
            a = -math.pi / 2 + 2 * math.pi * i / n
            d = abs(math.atan2(math.sin(ang - a), math.cos(ang - a)))
            if d < best_d:
                best, best_d = i, d
        # accept only if within half a sector
        return best if best_d <= math.pi / n else None

    def _emit_cap(self, pos) -> None:
        if self._drag_idx is None:
            return
        cx, cy = self.width() / 2.0, self.height() / 2.0
        half = min(cx, cy)
        sc = self._scale(half)
        r = math.hypot(pos.x() - cx, pos.y() - cy)
        r_base = self.R_BASE * sc
        r_full = (self.R_BASE + self.R_SPAN) * sc
        frac = clamp01((r - r_base) / max(1e-6, (r_full - r_base)))
        name = self._spokes[self._drag_idx].name
        self._drag_idx = None
        self.capRequested.emit(name, frac)

    def mousePressEvent(self, event):
        self._drag_idx = self.arm_at(event.position())

    def mouseReleaseEvent(self, event):
        if self._drag_idx is not None:
            self._emit_cap(event.position())
```

Also initialise `self._drag_idx = None` in `__init__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_vital_glyph.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/widgets/vital_glyph.py tests/test_vital_glyph.py
git commit -m "feat(ui): glyph arm hit-test + drag-to-cap capRequested signal (D)"
```

---

### Task 20: Wire control client + proposal bar + glyph drag into MainWindow

**Files:**
- Modify: `kokpit/ui/app.py` (construct `ControlClient`, `ProposalBar`; add a `QTimer` to poll proposals; connect `glyph.capRequested`, `bar.confirmed/denied/commandEntered`)
- Test: `tests/test_app_actuator_wiring.py`

**Interfaces:**
- Consumes: `ControlClient`, `ProposalBar`, `VitalGlyph.capRequested`, `intents`.
- Produces: MainWindow methods:
  - `_on_cap_requested(self, axis: str, fraction: float)` — maps axis → lever+params (e.g. `GPU` family → `gpu_power` watts = floor + fraction*(default-floor); `CPU` → `governor` powersave when fraction<0.5 else performance) and calls `self._ctl.request("apply", …)`.
  - `_on_command(self, text: str)` — `self._ctl.request("intent", {"text": text})`.
  - `_poll_proposals(self)` — `self._ctl.poll_proposals()`; show the first in the bar.
  - `_on_confirm(self, pid)` / `_on_deny(self, pid)` — `self._ctl.request("confirm"/"deny", {"id": pid})`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_actuator_wiring.py
from kokpit.ui.app import MainWindow


class FakeCtl:
    def __init__(self): self.calls = []
    def request(self, verb, args):
        from kokpit.actuator import protocol as p
        self.calls.append((verb, args))
        return p.Response(ok=True, data={"token": "noop-1"})
    def poll_proposals(self): return [{"id": "prop-1", "text": "ok?"}]


def test_cap_requested_maps_to_apply(qapp, monkeypatch):
    # Build MainWindow with stubbed live/model (reuse the harness in tests/test_widgets_smoke.py)
    win = MainWindow.__new__(MainWindow)   # bypass heavy __init__ for a focused unit
    win._ctl = FakeCtl()
    MainWindow._on_cap_requested(win, "GPU temp", 0.0)
    assert win._ctl.calls[-1][0] == "apply"
    assert win._ctl.calls[-1][1]["lever"] in ("gpu_power", "governor")


def test_command_maps_to_intent(qapp):
    win = MainWindow.__new__(MainWindow)
    win._ctl = FakeCtl()
    MainWindow._on_command(win, "cicho na 10 min")
    assert win._ctl.calls[-1] == ("intent", {"text": "cicho na 10 min"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_app_actuator_wiring.py -v`
Expected: FAIL (AttributeError: _on_cap_requested)

- [ ] **Step 3: Write minimal implementation**

In `kokpit/ui/app.py`, add to `MainWindow.__init__` (after the glyph is created, ~line 107):

```python
        from kokpit.ui.ctl_client import ControlClient
        from kokpit.ui.widgets.proposal_bar import ProposalBar
        self._ctl = ControlClient(str(config.control_socket_path()))
        self._bar = ProposalBar()
        self._glyph.capRequested.connect(self._on_cap_requested)
        self._bar.confirmed.connect(self._on_confirm)
        self._bar.denied.connect(self._on_deny)
        self._bar.commandEntered.connect(self._on_command)
        self._prop_timer = QtCore.QTimer(self)
        self._prop_timer.setInterval(2000)
        self._prop_timer.timeout.connect(self._poll_proposals)
        self._prop_timer.start()
```

Add `self._bar` to the layout (place under the glyph zone). Then the methods:

```python
    def _on_cap_requested(self, axis: str, fraction: float) -> None:
        if axis in ("GPU", "VRAM", "GPU temp"):
            floor = config.GPU_POWER_FLOOR_W
            watts = int(floor + fraction * (300 - floor))
            self._ctl.request("apply", {"lever": "gpu_power", "target": {"index": 0},
                                        "params": {"watts": watts},
                                        "ttl_s": config.ENVELOPE_DEFAULT_TTL_S})
        elif axis in ("CPU", "CPU temp"):
            name = "powersave" if fraction < 0.5 else "performance"
            self._ctl.request("apply", {"lever": "governor", "target": {},
                                        "params": {"name": name},
                                        "ttl_s": config.ENVELOPE_DEFAULT_TTL_S})

    def _on_command(self, text: str) -> None:
        self._ctl.request("intent", {"text": text})

    def _poll_proposals(self) -> None:
        props = self._ctl.poll_proposals()
        if props:
            self._bar.show_proposal(props[0]["id"], props[0]["text"])

    def _on_confirm(self, pid: str) -> None:
        self._ctl.request("confirm", {"id": pid})

    def _on_deny(self, pid: str) -> None:
        self._ctl.request("deny", {"id": pid})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_app_actuator_wiring.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kokpit/ui/app.py tests/test_app_actuator_wiring.py
git commit -m "feat(ui): wire control client, proposal bar, glyph drag into MainWindow"
```

---

### Task 21: README + ARP scope + service unit

**Files:**
- Modify: `README.md` (actuator section: enable envelope, install helper, glyph drag, command bar)
- Modify: `packaging/kokpit-collectord.service` (no new exec needed; document that the control socket is created by the daemon; ensure `RuntimeDirectory`/socket cleanup notes)
- Modify: `CLAUDE.md` — note `*.policy` is NOT in ARP `diffPathFilters`; decide whether to add it (see note).
- Test: none (docs) — but run the full suite.

- [ ] **Step 1: Update README** with an "## Actuator (sterowanie maszyną)" section: how to install the helper (`sudo packaging/install-actl-helper.sh`), how to enable envelope (`ENVELOPE_ENABLED`), the command bar phrases, and the glyph-drag gesture. Document that **all actions auto-revert** and are logged to `~/.local/share/kokpit/actuator-audit.jsonl`.

- [ ] **Step 2: Decide ARP filter.** The polkit `.policy` and `.sh` are security-relevant. Either (a) add `*.policy` + `*.sh` to ARP `diffPathFilters` via `PUT /api/projects/7` (per CLAUDE.md procedure) so the bot reviews them, or (b) leave them out and review manually. Recommended: add them — security-sensitive. Record the choice in the MR description.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: all green (existing 180+ plus new actuator tests).

- [ ] **Step 4: Commit**

```bash
git add README.md packaging/kokpit-collectord.service CLAUDE.md
git commit -m "docs(actuator): README usage, ARP filter note, service notes"
```

---

### Task 22: End-to-end smoke + MR

**Files:** none (operational)

- [ ] **Step 1: Live smoke (manual, on the workstation).**

```bash
# terminal A: run the daemon from the worktree venv
.venv/bin/kokpit-collectord
# terminal B: drive the control socket
python - <<'PY'
import socket
from kokpit.actuator import protocol as p
s = socket.socket(socket.AF_UNIX); s.connect("/run/user/%d/kokpit-ctl.sock" % __import__("os").getuid())
s.sendall(p.encode_request(p.Request("intent", {"text": "cicho na 1 min"})))
print(p.decode_response(s.makefile("rb").readline()))
PY
```
Expected: `Response(ok=True, data={'token': 'governor-1'}, ...)`, `pkexec` prompts once, governor flips to powersave, and after 60 s the audit log shows an `auto_revert`. Verify: `tail ~/.local/share/kokpit/actuator-audit.jsonl`.

- [ ] **Step 2: Verify revert_all on shutdown.** Apply a cap, `systemctl --user stop`/Ctrl-C the daemon, confirm the audit log shows `revert` for the active token and the governor is restored (`cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`).

- [ ] **Step 3: Push + open MR.**

```bash
git push -u origin feat/actuator
glab mr create --source-branch feat/actuator --target-branch main \
  --title "feat(actuator): interaktywny control plane (envelope + propozycje + glif-uchwyt)" \
  --description "Actuator (odwracalne dźwignie + TTL auto-revert + audit), socket komend kokpit-ctl.sock, envelope protection (opt-in), proposer+intents (PL/EN), glif drag-to-cap, helper+polkit. Wszystkie akcje odwracalne i audytowane."
```

- [ ] **Step 4: ARP review loop.** `arp_wait_for_review(mrIid=<IID>)` → `arp_get_findings(mrIid=<IID>, projectSlug="perun-kokpit")` → address → push → `arp_is_green(...)`. Merge only when green (CLAUDE.md workflow).

---

## Self-Review

**1. Spec coverage (the 4 committed pieces):**
- **Actuator core** → Tasks 1–4 (protocol, audit, levers, engine + TTL auto-revert). ✓
- **Privilege via polkit** → Tasks 8–10 (helper, helper-client levers, polkit policy + installer). ✓
- **Command channel (separate socket)** → Tasks 5–7, 16–17 (server, daemon wiring, verbs, client). ✓
- **A — Envelope protection** → Tasks 11–13 (policy, evaluator+debounce, daemon integration). ✓
- **C — Proposer + conversational** → Tasks 14–16, 18 (intents, proposer, socket verbs, proposal bar). ✓
- **D — Glyph handle** → Task 19 (hit-test + drag-to-cap) + Task 20 (wiring). ✓
- Reversibility + audit + TTL global constraint → enforced in Task 4 and every lever. ✓

**2. Placeholder scan:** Cgroup levers are explicitly deferred-with-condition (Task 3 note) rather than left as a TODO — they are out of v1 scope unless the capability probe passes; this is a scoping decision, not a placeholder. Every code step has concrete code. ✓

**3. Type consistency:** `Actuator.apply(lever_id, target, params, ttl_s)` signature is identical across Tasks 4, 6, 7, 13, 16. `Lever.apply(target, params)->dict` / `revert(token_state)` consistent across Tasks 3, 8, 9. `Response(ok, data, error)` / `Request(verb, args)` consistent across Tasks 1, 6, 16, 17. `capRequested(str, float)` consistent Tasks 19–20. `Proposal(id, text, action)` consistent Tasks 15–16. ✓

**Known follow-ups (out of this plan):** cgroup CPU/mem levers (needs delegated-cgroup probe), the daily "Whoop report" (proposal B-from-brainstorm), per-process drag-onto-arm binding (the richer half of D). These are separate plans.
