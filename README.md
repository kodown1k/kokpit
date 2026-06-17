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
