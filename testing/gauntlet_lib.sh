#!/usr/bin/env bash
#
# Shared helpers for the fastchess runner scripts. Source it:
#
#     . "$ROOT/testing/gauntlet_lib.sh"
#
# Why this exists
# ---------------
# Killing fastchess does NOT stop the games. fastchess shuts its engines down by
# sending them `quit`; a forced kill skips that entirely, and every engine it had
# running is orphaned mid-search with no parent and no clock to run out.
#
# Observed 2026-08-03: stopping a calibration gauntlet with Stop-Process left
# THIRTEEN pool engines spinning at 83% CPU, each having accumulated ~4,000
# seconds. They were still going long after the run "ended".
#
# That is worse than noisy. METHODOLOGY.md 8 rule 5 requires an idle machine for
# timed measurements, so a pile of invisible orphans silently corrupts whatever
# is measured next -- and a scoreline taken under 83% background load looks
# exactly like a real one.
#
# Not all engines do this. Sgurr exits cleanly when its stdin closes; Blunder,
# Zahak and Igel busy-loop instead. Do not assume a well-behaved engine.

# stop_gauntlet [extra_process_names...]
#
# Stop fastchess AND everything it launched. Safe to call when nothing is
# running, and safe to call twice.
stop_gauntlet() {
    # Capture the child PIDs BEFORE killing the parent. Once fastchess dies its
    # children are reparented, so the ppid link that identifies them is gone --
    # this has to happen first or there is nothing left to match on.
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

    # Belt and braces: sweep by name too. A child that had already been
    # reparented before we looked, or one started between the capture and the
    # kill, would otherwise survive.
    local name
    for name in "$@"; do
        taskkill //IM "${name}.exe" //F >/dev/null 2>&1
    done

    sleep 2
}

# assert_engines_stopped [names...]
# Report anything still alive, so a failure to clean up is visible rather than
# left for the next run to trip over.
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
