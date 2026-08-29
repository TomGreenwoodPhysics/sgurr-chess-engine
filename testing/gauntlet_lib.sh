#!/usr/bin/env bash
#
# Shared cleanup helpers for fastchess runner scripts.
# Source with `. "$ROOT/testing/gauntlet_lib.sh"`.
#
# A forced fastchess kill can orphan engines that ignore closed stdin.
# Those processes load the machine and invalidate later timed measurements.

# stop_gauntlet [extra_process_names...]
#
# Stop fastchess and its engines. This is safe to call more than once.
stop_gauntlet() {
    # Capture child PIDs before the parent dies and they are reparented.
    local kids
    kids=$(powershell -c '
        $fc = @(Get-CimInstance Win32_Process -Filter "Name=''fastchess.exe''" -ErrorAction SilentlyContinue)
        if ($fc.Count -gt 0) {
            $ids = $fc | ForEach-Object { $_.ProcessId }
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object { $ids -contains $_.ParentProcessId } |
                ForEach-Object { $_.ProcessId }
        }' 2>/dev/null | tr -d '\r')

    taskkill //IM fastchess.exe //F >/dev/null 2>&1

    local pid
    for pid in $kids; do
        case "$pid" in
            ''|*[!0-9]*) continue ;;
        esac
        taskkill //PID "$pid" //F >/dev/null 2>&1
    done

    # Sweep by name to catch children missed by the PID capture.
    local name
    for name in "$@"; do
        taskkill //IM "${name}.exe" //F >/dev/null 2>&1
    done

    sleep 2
}

# assert_engines_stopped [names...]
# Report anything still alive after cleanup.
assert_engines_stopped() {
    local left
    left=$(powershell -c "
        \$n = @('fastchess'$(printf ",'%s'" "$@"))
        (Get-Process -Name \$n -ErrorAction SilentlyContinue | ForEach-Object { \$_.Name }) -join ', '
    " 2>/dev/null | tr -d '\r')

    if [ -n "$left" ]; then
        echo "WARNING: still running after cleanup: $left" >&2
        echo "         kill them before any further timed measurement." >&2
        return 1
    fi

    echo "cleanup: no fastchess or engine processes remain"
    return 0
}
