#!/usr/bin/env bash
#
# Measure a release against the anchored calibration pool at 10+0.1.
# Ordo combines every calibration PGN to keep releases on one rating scale.
#
# The monitor stops the gauntlet once the 95% interval reaches TARGET_ERR.
# Error falls with the square root of games, so tight targets can take hours.
# The round cap is high enough to avoid leaving the machine idle too soon.
# Stop with Ctrl+C or `taskkill /IM fastchess.exe /F`.
# Partial PGNs remain valid for later solves.

set -u

# Resolve the repository root from this script so clones work anywhere.
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BM="$ROOT/benchmarks"

# Embedded Windows Python needs a Windows-style repository path.
WIN_BM=$(cygpath -m "$BM")
CPP="$ROOT/sgurr_cpp"
FC="$BM/tools/fastchess.exe"
ORDO="$BM/tools/ordo.exe"
# Calibration uses a larger book than datagen and SPRT.
# Reusing a small set understates uncertainty caused by opening choice.
# A Sgurr-filtered book would also bias the sample toward its own evaluation.
# The generic 8moves_v3 book provides 34,700 game-derived opening lines.
# Its provenance is recorded with the external pool assets.
BOOK="${BOOK_FILE:-$ROOT/testing/8moves_v3.pgn}"
case "$BOOK" in
    *.pgn) BOOK_FORMAT=pgn ;;
    *)     BOOK_FORMAT=epd ;;
esac
NET=$(cygpath -m "$ROOT/nets/gen8.nnue")

# Arguments keep one runner reusable across releases.
# Usage  tools/run_calibrate.sh [version] [exe-name] [openings-seed]
VERSION="${1:-v8.2}"
REL_EXE="$CPP/${2:-sgr_v8_2.exe}"
ENGINE_NAME="Sgurr-$VERSION"

# Use `-srand` for the opening shuffle seed.
# `-seeds` changes which engines head the gauntlet and silently changes games.
SEED="${3:-1}"

# Ordo error falls with the square root of games. A target of 1 disables the
# practical early stop because it would need roughly 460,000 games.
TARGET_ERR="${5:-5}"

STAMP=$(date +%Y-%m-%d_%H%M)
OUT="$ROOT/runs/calibrate/${VERSION}_$STAMP"
PGN="$BM/games/calib-$VERSION-$(date +%Y-%m-%d).pgn"

# Run settings
TC=10+0.1              # Pool control used since pool-2026-07-A
CONCURRENCY=7

# Give every engine the same 256 MB hash to match CCRL conditions.
# Engine defaults vary enough to distort ratings against the anchors.
# All pool engines advertise support for this value.
HASH=256
ROUNDS="${4:-500}"     # Eight opponents make 16 games per round
CHECK_EVERY=1800       # Seconds between checks, plus Ordo solve time
MIN_GAMES=400          # Wait for this many games before solving

mkdir -p "$OUT" "$BM/games"
export SGR_EVALFILE="$NET"

# shellcheck source=testing/gauntlet_lib.sh
. "$ROOT/testing/gauntlet_lib.sh"

# Derive process names from the current binary and pool roster.
# This keeps the cleanup sweep in sync with every engine the run can leave behind.
ENGINE_PROCS="$(basename "$REL_EXE" .exe) $(python -c "
import json, os
p = json.load(open(r'$WIN_BM/pool.json'))
print(' '.join(os.path.splitext(os.path.basename(e['cmd']))[0] for e in p['engines']))
")"

# Clean up on Ctrl+C so the next timed run starts on an idle machine.
# shellcheck disable=SC2086
trap 'echo; echo "interrupted -- stopping engines"; stop_gauntlet $ENGINE_PROCS; assert_engines_stopped $ENGINE_PROCS; exit 130' INT TERM

echo "$ENGINE_NAME pool calibration  ->  $OUT"
date
echo

# Preflight
busy=$(powershell -c "(Get-Process datagen,fastchess -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r')
if [ "${busy:-0}" != "0" ]; then
    echo "ABORT: $busy datagen/fastchess process(es) already running." >&2
    echo "Timed game results under CPU load are invalid." >&2
    exit 1
fi

# Check every engine because launch failures otherwise become forfeits.
POOL_EXES=$(python -c "
import json,sys
p=json.load(open(r'$WIN_BM/pool.json'))
print(' '.join(r'$BM/'+e['cmd'] for e in p['engines']))
")
PY="$ROOT/.venv/Scripts/python.exe"; [ -f "$PY" ] || PY=python
# shellcheck disable=SC2086
if ! "$PY" "$ROOT/testing/engine_check.py" "$REL_EXE" $POOL_EXES; then
    echo "ABORT: engine pre-flight failed (see above)." >&2
    exit 1
fi

# Check move-format and position handling that a UCI handshake cannot prove.
# Non-compliant engines would forfeit games and distort the anchored rating.
# shellcheck disable=SC2086
if ! "$PY" "$ROOT/testing/engine_gate.py" "$REL_EXE" $POOL_EXES; then
    echo "ABORT: an engine is not UCI rules-compliant (see above)." >&2
    echo "       A forfeiting engine does not fail loudly, it produces a" >&2
    echo "       complete result with a wrong number. Remove it from the pool." >&2
    exit 1
fi

if ! printf 'uci\nquit\n' | "$REL_EXE" 2>&1 >/dev/null | grep -q "nnue: loaded"; then
    echo "ABORT: $REL_EXE is NOT loading the net -- it would play as HCE." >&2
    exit 1
fi
echo "preflight: $ENGINE_NAME and all $(python -c "import json;print(len(json.load(open(r'$WIN_BM/pool.json'))['engines']))") pool engines start; $ENGINE_NAME loads the net"
echo

{
    echo "run       : $STAMP"
    echo "commit    : $(cd "$ROOT" && git rev-parse HEAD)"
    echo "engine    : $REL_EXE  ($(printf 'uci\nquit\n' | "$REL_EXE" 2>/dev/null | sed -n 's/^id name //p'))"
    echo "net       : $NET"
    echo "pool      : $(python -c "import json;print(json.load(open(r'$WIN_BM/pool.json'))['pool_id'])")"
    echo "tc        : $TC   concurrency $CONCURRENCY"
    echo "stop when : +/-$TARGET_ERR   (checked every $((CHECK_EVERY/60)) min after $MIN_GAMES games)"
    echo "pgn       : $PGN"
    echo "seed      : $SEED   (openings shuffle; change it when continuing a run)"
    echo
    echo "bench 13  : $("$REL_EXE" bench 13 2>/dev/null | grep '^nodes')"
    echo "(v8.0/v8.1 are the same node tree: 13614729)"
} | tee "$OUT/manifest.txt"
echo

# Solve over every calibration PGN to keep versions on one scale.
# `solve [threads]` prints the current engine's rating and error when available.
# Checkpoints use few low-priority threads so they do not compete with games.
solve() {
    local threads="${1:-2}"
    local combined="$OUT/all_calib.pgn"
    : > "$combined"
    for p in "$BM"/games/calib-*.pgn; do
        [ -f "$p" ] && cat "$p" >> "$combined"
    done

    # Write to a scratch file because Ordo truncates its output before solving.
    # Replace the last table only after a successful solve.
    local new="$OUT/ordo.new"
    "$ORDO" -Q -p "$combined" -m "$BM/anchors.txt" -W -s 1500 -n "$threads" -N 1 \
            -o "$new" >/dev/null 2>&1 &
    local opid=$!
    ( sleep 1
      powershell -c "Get-Process ordo -ErrorAction SilentlyContinue | ForEach-Object { \$_.PriorityClass = 'BelowNormal' }" >/dev/null 2>&1
    ) &
    wait "$opid" 2>/dev/null

    [ -s "$new" ] && mv -f "$new" "$OUT/ordo.txt"
    grep -oE "$ENGINE_NAME\s*:\s*-?[0-9.]+\s+[0-9.]+" "$OUT/ordo.txt" 2>/dev/null \
        | tail -1 | awk '{print $(NF-1), $NF}'
}

games_so_far() {
    # The gauntlet engine appears once per game as White or Black.
    # Count all PGNs for this version so resumed runs match the Ordo input.
    grep -ch "\"$ENGINE_NAME\"" "$BM"/games/calib-"$VERSION"-*.pgn 2>/dev/null \
        | awk '{s+=$1} END{print s+0}'
}

# Launch the gauntlet
# Run from benchmarks and give fastchess Windows or local relative paths.
CMD=("$(cygpath -m "$FC")" -tournament gauntlet -seeds 1 -srand "$SEED"
     -engine "cmd=$(cygpath -m "$REL_EXE")" "name=$ENGINE_NAME")
N_OPP=0
while read -r name cmd; do
    # Convert each pool binary to an absolute Windows path.
    [ -n "$name" ] && { CMD+=(-engine "cmd=$(cygpath -m "$BM/$cmd")" "name=$name"); N_OPP=$((N_OPP + 1)); }
done < <(python -c "
import json
p=json.load(open(r'$WIN_BM/pool.json'))
for e in p['engines']: print(e['name'], e['cmd'])
" | tr -d '\r')
# Strip CRLF output from Windows Python so engine paths contain no carriage return.
CMD+=(-each "tc=$TC" "option.Hash=$HASH" -rounds "$ROUNDS" -repeat
      -concurrency "$CONCURRENCY" -recover
      -openings "file=$(cygpath -m "$BOOK")" "format=$BOOK_FORMAT" order=random
      -pgnout "file=$(cygpath -m "$PGN")" -ratinginterval 60)

# Read the opponent count from pool.json so the reported cap stays accurate.
echo "=== gauntlet: $ENGINE_NAME vs $N_OPP pool engines, Hash=$HASH, up to $((ROUNDS*N_OPP*2)) games ==="
date
( cd "$BM" && "${CMD[@]}" ) > "$OUT/gauntlet.log" 2>&1 &
FC_PID=$!
echo "fastchess pid $FC_PID, log $OUT/gauntlet.log"
echo

# Confirm that every early game includes the engine under test.
# This catches accidental `-seeds` use that creates a different gauntlet.
for _ in $(seq 60); do
    [ "$(grep -c '^\[Event' "$PGN" 2>/dev/null | head -1 || echo 0)" -ge 20 ] && break
    sleep 5
done
ev=$(grep -c '^\[Event' "$PGN" 2>/dev/null | head -1 || echo 0)
mine=$(grep -c "\"$ENGINE_NAME\"" "$PGN" 2>/dev/null | head -1 || echo 0)
if [ "$ev" -gt 0 ] && [ "$ev" -ne "$mine" ]; then
    echo "ABORT: $((ev - mine)) of the first $ev games do not involve $ENGINE_NAME." >&2
    echo "       That is not a gauntlet. Check -tournament and -seeds." >&2
    # shellcheck disable=SC2086
    stop_gauntlet $ENGINE_PROCS
    exit 1
fi
echo "structure: all $ev games so far involve $ENGINE_NAME -- gauntlet confirmed"
echo

# Monitor
while kill -0 "$FC_PID" 2>/dev/null; do
    sleep "$CHECK_EVERY"
    kill -0 "$FC_PID" 2>/dev/null || break

    n=$(games_so_far)
    if [ "${n:-0}" -lt "$MIN_GAMES" ]; then
        echo "[$(date +%H:%M)] $n games -- below $MIN_GAMES, not solving yet"
        continue
    fi

    read -r rating err <<< "$(solve)"
    if [ -z "${err:-}" ]; then
        echo "[$(date +%H:%M)] $n games -- Ordo has not placed $ENGINE_NAME yet"
        continue
    fi

    echo "[$(date +%H:%M)] $n games -- $ENGINE_NAME = $rating +/- $err"
    if awk -v e="$err" -v t="$TARGET_ERR" 'BEGIN{exit !(e<=t)}'; then
        echo "TARGET REACHED: +/-$err <= +/-$TARGET_ERR after $n games. Stopping."
        # shellcheck disable=SC2086
        stop_gauntlet $ENGINE_PROCS
        break
    fi
done

wait "$FC_PID" 2>/dev/null
echo
echo "=== gauntlet ended ==="
date

# Sweep unconditionally so the final solve starts without orphaned engines.
# shellcheck disable=SC2086
stop_gauntlet $ENGINE_PROCS
# shellcheck disable=SC2086
assert_engines_stopped $ENGINE_PROCS

# Final solve
# Use five threads now that games no longer need the CPU.
read -r rating err <<< "$(solve 5)"
n=$(games_so_far)
{
    echo
    echo "=============================================================="
    echo "  $ENGINE_NAME  =  ${rating:-?}  +/-  ${err:-?}     ($n games)"
    echo "=============================================================="
    echo
    echo "Full Ordo table: $OUT/ordo.txt"
    sed -n '1,20p' "$OUT/ordo.txt" 2>/dev/null
    echo
    echo "For the ledger row, compare against v8.0 IN THIS SAME SOLVE -- the"
    echo "gap is anchor-independent, the absolute is only as good as the"
    echo "anchors. The self-play measurement was +21.2 +/-8.7."
} | tee "$OUT/RESULT.txt"
