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

### Zakres skanu bota: `diffPathFilters` (NIE `.gitlab/ai-review.yml`)

To, jakie pliki bot recenzuje, ustala **`analyzerConfig.diffPathFilters` w panelu per-projekt** (`PUT /api/projects/7`), a **nie** `.gitlab/ai-review.yml` w repo — ten plik robi wyłącznie PRD/docs-gen, nie scope code-review. Nie idź w ślepy zaułek z plikiem w repo.

- Filtry to **include-globi** przekazywane jako `git diff -- <glob…>`; regex backendu (`^[A-Za-z0-9*?/.\-_]+$`) **nie** dopuszcza `:(exclude)`/`!`, więc „wyklucz X" robi się przez **whitelistę reszty**.
- Default ARP zawiera `*.md` → dlatego markdown (plany/spec w `docs/`) był recenzowany jak kod (szum).
- **Ustawione dla kokpit:** `['*.py', '*.toml', '*.service']` — Python + pyproject + systemd unit; markdown wypada. Commit zmieniający tylko `docs/**.md` → bot daje `mr_analyze:no_diff` (zielono, zero findings).
- Zmiana: `PUT /api/projects/7` z **pełnym** `analyzerConfig` (PUT replace'uje: `costCeilingUsd`, `maxTurns`, `allowedTools`, `diffPathFilters`). Auth z `~/.secrets` (`PANEL`, `PANEL_AUTH_TOKEN`).
- **Actuator packaging (`*.policy`, `*.sh`) NIE jest w `diffPathFilters`** — obecny filtr to `['*.py', '*.toml', '*.service']`. Pliki `packaging/co.kodownik.kokpit.actl.policy` i `packaging/install-actl-helper.sh` są wrażliwe bezpieczeństwowo (polkit), ale bot ich nie recenzuje. Dodaj `*.policy` i `*.sh` do filtrów przez `PUT /api/projects/7` jeśli chcesz pokrycie bota — w przeciwnym razie recenzuj ręcznie przy każdej zmianie.

## Testy

`.venv/bin/pytest -q` — pełny zestaw musi być zielony przed MR. TDD dla nowego kodu (testy first, RED → GREEN).
