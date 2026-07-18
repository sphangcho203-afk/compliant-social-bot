#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOOT_DIR="$HOME/.termux/boot"
TARGET="$BOOT_DIR/compliant-social-bot"

mkdir -p "$BOOT_DIR"
cat >"$TARGET" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
PROJECT_DIR="$ROOT_DIR" exec "$ROOT_DIR/deploy/termux/boot-start.sh"
EOF
chmod +x "$TARGET" "$ROOT_DIR/deploy/termux/boot-start.sh" "$ROOT_DIR/deploy/termux/workerctl"

echo "boot_launcher=$TARGET"
echo "Install and open the Termux:Boot app once, then disable battery optimization for Termux and Termux:Boot."
echo "The worker remains in dry-run mode unless workerctl is explicitly started with --live."
