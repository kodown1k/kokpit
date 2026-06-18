#!/usr/bin/env bash
set -euo pipefail
# Installs the kokpit actuator privileged helper + polkit policy. Run with sudo.
HERE="$(cd "$(dirname "$0")" && pwd)"
REAL_HOME=$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)
VENV_HELPER="${VENV_HELPER:-$REAL_HOME/Code/kokpit/.venv/bin/kokpit-actl-helper}"

install -m 0755 /dev/stdin /usr/local/bin/kokpit-actl-helper <<EOF
#!/usr/bin/env bash
exec "$VENV_HELPER" "\$@"
EOF

install -m 0644 "$HERE/co.kodownik.kokpit.actl.policy" \
  /usr/share/polkit-1/actions/co.kodownik.kokpit.actl.policy
echo "Installed. Test:  pkexec kokpit-actl-helper governor performance"
