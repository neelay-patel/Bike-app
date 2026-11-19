#!/bin/sh
# Run the backend on this Mac as a login service (launchd), so it starts when you log in, restarts if it stops,
# and doesn't depend on a terminal window. Until the backend is hosted (docs/hosting.md).
#
#   scripts/mac-server.sh install    # set up and start (run again after moving the repo)
#   scripts/mac-server.sh restart    # after a code change
#   scripts/mac-server.sh status     # running? answering?
#   scripts/mac-server.sh logs       # follow the log (data/backend/server.log)
#   scripts/mac-server.sh uninstall  # stop it and remove the service
set -eu

LABEL=com.neelaypatel.rideapp.backend
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$REPO/data/backend/server.log"
TARGET="gui/$(id -u)"

case "${1:-status}" in
install)
    [ -x "$REPO/.venv/bin/python" ] || { echo "No .venv in $REPO (see CLAUDE.md, Commands)"; exit 1; }
    mkdir -p "$HOME/Library/LaunchAgents" "$REPO/data/backend"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$REPO/.venv/bin/python</string>
        <string>-m</string><string>backend</string>
        <string>serve</string><string>--host</string><string>0.0.0.0</string>
    </array>
    <key>WorkingDirectory</key><string>$REPO</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardOutPath</key><string>$LOG</string>
    <key>StandardErrorPath</key><string>$LOG</string>
    <key>EnvironmentVariables</key>
    <dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
</dict>
</plist>
EOF
    launchctl bootout "$TARGET/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$TARGET" "$PLIST"
    echo "Installed: starts at login, restarts if it stops. Log: $LOG"
    ;;
restart)
    launchctl kickstart -k "$TARGET/$LABEL"
    echo "Restarted."
    ;;
status)
    if launchctl print "$TARGET/$LABEL" >/dev/null 2>&1; then
        launchctl print "$TARGET/$LABEL" | grep -E "^\s*(state|pid|last exit code) =" || true
    else
        echo "Not installed (scripts/mac-server.sh install)."
    fi
    if curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health; then echo "Answering on port 8000."; else echo "Not answering on port 8000."; fi
    ;;
logs)
    tail -n 50 -f "$LOG"
    ;;
uninstall)
    launchctl bootout "$TARGET/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed. Run the server by hand with: .venv/bin/python -m backend serve --host 0.0.0.0"
    ;;
*)
    echo "usage: $0 install|restart|status|logs|uninstall"; exit 1
    ;;
esac
