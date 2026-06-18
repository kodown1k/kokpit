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

Opcjonalna ochrona przed przekroczeniem budżetu zasobów. Ustaw zmienną środowiskową przed startem demona lub w pliku `.env`:

```bash
ENVELOPE_ENABLED=1 kokpit-collectord
```

Po włączeniu proposer automatycznie ogranicza akcje do bezpiecznego zakresu.

### Pasek poleceń (command bar)

W dashboardzie (pole tekstowe u dołu) obsługiwane frazy:

| Fraza | Efekt |
|---|---|
| `cicho na 30 min` | renice+ionice wszystkich procesów nieinteraktywnych, TTL 30 min |
| `zwolnij wszystko` | aggressive throttle CPU governor + GPU power limit, TTL domyślny |
| `max` | usuwa wszystkie aktywne ograniczenia (natychmiastowe cofnięcie) |

Proposer jest deterministyczny — ta sama fraza zawsze produkuje ten sam zestaw akcji.

### Gest drag-to-cap (glify)

Na dashboardzie: przeciągnij glyf zasobu (CPU/GPU/RAM) w lewo lub w prawo, żeby ustawić cap procentowy. Zwolnij, żeby zatwierdzić. Akcja jest odwracalna (TTL jak pozostałe).
