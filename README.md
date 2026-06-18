# kokpit — kolektor telemetrii (backend)

Demon `kokpit-collectord` zbiera CPU/GPU/RAM/dyski/sieć/procesy/temperatury co 1 s
do SQLite (`~/.local/share/kokpit/kokpit.db`) i publikuje żywy snapshot przez
Unix socket (`$XDG_RUNTIME_DIR/kokpit.sock`, NDJSON).

## Instalacja

```bash
cd ~/Code/kokpit
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

## Autostart (systemd --user)

```bash
mkdir -p ~/.config/systemd/user
cp packaging/kokpit-collectord.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kokpit-collectord
# żeby historia żyła także po wylogowaniu ("co działo się w nocy"):
loginctl enable-linger "$USER"
journalctl --user -u kokpit-collectord -f
```

**Nota:** Jeśli zainstalowałeś kokpit w innej ścieżce niż `~/Code/kokpit`,
musisz edytować `~/.config/systemd/user/kokpit-collectord.service` i zmienić
`ExecStart` na odpowiednią ścieżkę (np. `%h/my-projects/kokpit/.venv/bin/kokpit-collectord`).
Potem `systemctl --user daemon-reload`.

## Podgląd live (smoke, bez UI)

```bash
.venv/bin/python -c "import socket; s=socket.socket(socket.AF_UNIX); \
s.connect('$XDG_RUNTIME_DIR/kokpit.sock'); \
print(s.makefile().readline())"
```

## Actuator (sterowanie maszyną)

Actuator pozwala wydawać polecenia sterujące bezpośrednio z dashboardu lub przez gniazdo poleceń (`$XDG_RUNTIME_DIR/kokpit-ctl.sock`, NDJSON).

**WAŻNE: wszystkie akcje automatycznie się cofają** po wygaśnięciu TTL — nie ma trwałych zmian. Każda operacja jest zapisywana do `~/.local/share/kokpit/actuator-audit.jsonl`.

### Instalacja pomocnika uprzywilejowanego

Akcje wymagające wyższych uprawnień (zmiana governor CPU, limit mocy GPU) działają przez polkit. Zainstaluj pomocnika raz jako root:

```bash
sudo packaging/install-actl-helper.sh
```

Skrypt instaluje binarny helper i plik polityki polkit (`co.kodownik.kokpit.actl.policy`). Akcje user-level (renice, ionice) nie wymagają pomocnika.

### Włączenie ochrony koperty (envelope protection)

Opcjonalna ochrona: gdy oś telemetrii odchyli się znacząco powyżej swojego circadian baseline (z-score ≥ `ENVELOPE_Z_TRIGGER`, utrzymane przez `ENVELOPE_DEBOUNCE_S`), actuator sam nakłada odwracalne ograniczenie (np. cap mocy GPU, governor powersave).

`ENVELOPE_ENABLED` to **stała w `kokpit/config.py`** (domyślnie `False`), nie zmienna środowiskowa — żeby włączyć, ustaw `ENVELOPE_ENABLED = True` w configu i zrestartuj demona. Proposer (`PROPOSE_ENABLED`, domyślnie `True`) działa niezależnie: zamiast działać sam, wystawia propozycje, które zatwierdzasz w UI.

### Pasek poleceń (command bar)

W dashboardzie (pole tekstowe u dołu) obsługiwane frazy (PL/EN, dopasowanie po granicy słowa):

| Fraza | Efekt |
|---|---|
| `cicho [na N min]` / `quiet` | governor → `powersave`, TTL = N min (domyślnie 30 min) |
| `max` / `performance` | governor → `performance`, TTL domyślny |
| `cap gpu N` / `limit gpu N` | limit mocy GPU = N W, TTL domyślny |
| `zwolnij wszystko` / `release all` / `odblokuj` | cofa **wszystkie** aktywne ograniczenia natychmiast (`revert_all`) |

Parser intencji jest deterministyczny — ta sama fraza zawsze produkuje ten sam plan akcji.

### Gest drag-to-cap (glif)

Na radarze Vital-Signs: chwyć ramię osi (np. GPU, CPU) i przeciągnij je **promieniście do środka** — im bliżej środka, tym mocniejszy cap (ramię GPU → limit mocy GPU; ramię CPU → governor). Zwolnij, żeby zatwierdzić. Akcja jest odwracalna (TTL jak pozostałe) i audytowana.
