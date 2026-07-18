#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/compliant-social-bot}"
BOOT_DELAY_SECONDS="${BOOT_DELAY_SECONDS:-20}"
BOOT_LOG="${BOOT_LOG:-$PROJECT_DIR/data/termux-boot.log}"

mkdir -p "$(dirname "$BOOT_LOG")"
{
    printf '%s boot_start project=%s delay=%s\n' "$(date -Iseconds)" "$PROJECT_DIR" "$BOOT_DELAY_SECONDS"
    sleep "$BOOT_DELAY_SECONDS"

    if [[ ! -x "$PROJECT_DIR/deploy/termux/workerctl" ]]; then
        printf '%s boot_error reason=workerctl_missing\n' "$(date -Iseconds)"
        exit 1
    fi

    cd "$PROJECT_DIR"
    deploy/termux/workerctl start
    printf '%s boot_complete\n' "$(date -Iseconds)"
} >>"$BOOT_LOG" 2>&1
