# kokpit — instrukcje projektowe

Backend kolektora telemetrii (CPU/GPU/RAM/dyski/sieć/procesy/temperatury → SQLite + live NDJSON socket). Python 3.12, `psutil`, `nvidia-ml-py`, SQLite WAL, pytest. Szczegóły architektury: `docs/superpowers/specs/2026-06-17-kokpit-design.md` i `README.md`.

## GitLab + ai-review-panel (ARP)

Ten projekt jest hostowany na **gitlab.kodownik.co** i podpięty pod **ai-review-panel** (bot review'ujący MR-y).

- **GitLab:** `perun/kokpit`, project id **18**, remote `ssh://git@gitlab.kodownik.co:2424/perun/kokpit.git`
- **ARP:** zarejestrowany jako project id **7**, slug **`perun-kokpit`**, webhook aktywny (eventy MR + note). Bot postuje jako `perun` (używa `GITLAB_PAT`).

## Domyślny workflow: MR + review bota ARP

Domyślnie, kończąc zmianę:

1. **Sam tworzę MR** — commit → push brancha → utworzenie merge requesta (przez `glab` lub MCP `create_merge_request`). Nie czekam aż zrobi to ktoś inny.
2. **Czekam na review bota** — `arp_wait_for_review(mrIid=<IID>)` (event-driven SSE; multi-agent review bywa dłuższy niż domyślne okno — w razie `timeout` wołam ponownie albo sprawdzam audit-log panelu).
3. **Poprawiam wg findings bota** — `arp_get_findings(mrIid=<IID>, projectSlug="perun-kokpit")` → adresuję uwagi w kodzie → push (kolejny event re-triggeruje review). `arp_is_green(mrIid=<IID>, projectSlug="perun-kokpit")` mówi, czy review jest „zielony" (terminalny, zero blokujących findings).

Cel: branch wchodzi do `main` dopiero gdy review bota jest zielony (albo findings są świadomie odrzucone z uzasadnieniem).

## Testy

`.venv/bin/pytest -q` — pełny zestaw musi być zielony przed MR. TDD dla nowego kodu (testy first, RED → GREEN).
