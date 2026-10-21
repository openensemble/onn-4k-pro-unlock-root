#!/system/bin/sh
# Source from pause/restore. Never stop an engine whose update state is unknown.
ensure_idle() {
    case "$(/system/bin/getprop init.svc.update_engine)" in
        running)
            status=$(/system/bin/timeout 4 /system/bin/update_engine_client --follow 2>&1 || true)
            last_status=$(printf '%s\n' "$status" | grep 'onStatusUpdate(' | tail -n 1)
            case "$last_status" in
                *'onStatusUpdate(UPDATE_STATUS_IDLE (0), 0)'*) ;;
                *) echo 'Update engine is busy or unknown; no pause applied.'; return 2 ;;
            esac
            ;;
        stopped) ;;
        *) echo 'Unexpected update engine state; no pause applied.'; return 2 ;;
    esac
}

wait_engine() {
    attempt=0
    while [ "$(/system/bin/getprop init.svc.update_engine)" != "$1" ]; do
        attempt=$((attempt + 1))
        [ "$attempt" -lt 10 ] || return 3
        sleep 1
    done
}
