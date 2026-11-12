#!/bin/bash
# One-time setup on the ops computer (docs/PUSH_ALERTS.md): make the push key (kept, never printed) and
# start the 2-minute timer. Safe to run again: an existing key is kept and the timer is re-installed.
set -e
OPS="$HOME/Babdoduk-ops"
UNITS="$HOME/.config/systemd/user"
"$HOME/.local/bin/node" "$OPS/scripts/push/keygen.js"
mkdir -p "$UNITS"
cp "$OPS/scripts/push/babdoduk-push.service" "$OPS/scripts/push/babdoduk-push.timer" "$UNITS/"
systemctl --user daemon-reload
systemctl --user enable --now babdoduk-push.timer
systemctl --user is-active babdoduk-push.timer
