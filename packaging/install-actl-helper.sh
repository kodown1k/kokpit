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
echo "Installed. Test:  pkexec kokkit-actl-helper governor performance"
