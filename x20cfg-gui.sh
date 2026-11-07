#!/usr/bin/env bash
# Start the x20cfg GUI: sets up/refreshes the venv, checks system deps, launches.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
VENV=.venv
PY=${PYTHON:-python3}

die() { echo "x20cfg: $*" >&2; exit 1; }

command -v "$PY" >/dev/null || die "python3 not found"

# GTK4/libadwaita bindings come from the system (PyGObject is painful to build via pip).
if ! "$PY" -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); import cairo' 2>/dev/null; then
    cat >&2 <<'EOF'
x20cfg: GTK4 / libadwaita Python bindings are missing. Install them with:
  Arch:          sudo pacman -S python-gobject python-cairo gtk4 libadwaita
  Debian/Ubuntu: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1
  Fedora:        sudo dnf install python3-gobject python3-cairo gtk4 libadwaita
EOF
    exit 1
fi

# The venv sees system site-packages so it can use the system's gi/cairo.
if [ ! -x "$VENV/bin/python" ]; then
    echo "x20cfg: creating virtualenv in $VENV"
    "$PY" -m venv --system-site-packages "$VENV"
fi

# (Re)install the package whenever pyproject.toml changes.
STAMP="$VENV/.x20cfg-installed"
if [ ! -f "$STAMP" ] || [ pyproject.toml -nt "$STAMP" ]; then
    echo "x20cfg: installing into $VENV"
    if "$VENV/bin/python" -m pip install --quiet --editable . ; then
        touch "$STAMP"
    else
        echo "x20cfg: pip install failed, running from source instead" >&2
    fi
fi

# The config channel needs the controller connected over Bluetooth (any mode KeyLinker supports).
if ! grep -qsi '^HID_UNIQ=98:b6:' /sys/class/hidraw/*/device/uevent && [ -z "${X20_ADDR:-}" ]; then
    echo "x20cfg: warning: no X20 connected over Bluetooth yet (the GUI will retry on Reload)" >&2
fi

export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m x20cfg gui "$@"
