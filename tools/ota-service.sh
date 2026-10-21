#!/system/bin/sh
set -o pipefail
MODDIR=${0%/*}
# Magisk late_start: wait for package/settings services, then apply once.
attempt=0
while [ "$(/system/bin/getprop sys.boot_completed)" != 1 ]; do
    [ -f "$MODDIR/disable" ] && exit 0
    [ -f "$MODDIR/remove" ] && exit 0
    attempt=$((attempt + 1))
    [ "$attempt" -lt 180 ] || exit 1
    sleep 1
done
[ -f "$MODDIR/disable" ] && exit 0
[ -f "$MODDIR/remove" ] && exit 0
# Binder commands cannot inherit a log FD opened in Magisk's private directory.
# Pipe their output to tee instead of redirecting the commands into that file.
/system/bin/sh "$MODDIR/pause.sh" 2>&1 | tee "$MODDIR/last-run.log"
