#!/usr/bin/env bash
#
# Measure a release against the anchored calibration pool in pool.json.
# Ordo solves every calibration PGN from that pool, so versions measured on it
# share one scale. Games from earlier pools are never mixed in.
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
# The release network is explicit so a new release cannot silently be
# calibrated with the previous generation's net.
NET_SOURCE="${NET_FILE:-$ROOT/nets/gen8.nnue}"
NET=$(cygpath -m "$NET_SOURCE")
if [ ! -f "$NET_SOURCE" ]; then
    echo "ABORT: calibration net not found: $NET_SOURCE" >&2
    exit 1
fi

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

# Time control, hash and games directory come from pool.json, so a pool is
# defined in one place. Hash is the same for every engine, as CCRL requires.
# Each pool keeps its games in its own directory and is solved on those alone:
# mixing pools mixes conditions. CALIB_GAMES_DIR redirects smoke tests.
read -r POOL_ID TC HASH GAMES_DIR <<< "$(python -c "
import json
p=json.load(open(r'$WIN_BM/pool.json'))
print(p['pool_id'], p['time_control'], p['hash_mb'], p['games_dir'])
" | tr -d '\r')"
[ -n "${GAMES_DIR:-}" ] || { echo "ABORT: pool.json has no games_dir" >&2; exit 1; }
GAMES="$BM/${CALIB_GAMES_DIR:-$GAMES_DIR}"
# A pool that extends an earlier one under identical conditions lists the
# earlier games directory in include_games, and the solve reads both.
SOLVE_DIRS="$GAMES $(python -c "
import json
p=json.load(open(r'$WIN_BM/pool.json'))
print(' '.join(r'$BM/'+d for d in p.get('include_games', [])))
" | tr -d '\r')"
# Keep every interrupted or resumed run as a separate append-only input to
# Ordo. A date-only filename could overwrite an earlier run from the same day.
PGN="$GAMES/calib-$VERSION-$STAMP.pgn"
CONCURRENCY=7
ROUNDS="${4:-500}"     # Each round is two games against every pool engine
CHECK_EVERY="${CALIB_CHECK_EVERY:-1800}"   # Seconds between solves, plus solve time
MIN_GAMES="${CALIB_MIN_GAMES:-400}"        # Wait for this many games before solving

mkdir -p "$OUT" "$GAMES"
export SGR_EVALFILE="$NET"

# Anchor every pool engine at its rating in pool.json, and nothing else.
python - "$WIN_BM/pool.json" <<'EOF' | tr -d '\r' > "$OUT/anchors.txt"
import json, sys
for e in json.load(open(sys.argv[1]))["engines"]:
    print(f'"{e["name"]}",{e["ccrl_blitz"]}')
EOF

# shellcheck source=testing/gauntlet_lib.sh
. "$ROOT/testing/gauntlet_lib.sh"

# Build the cleanup list from the current binary and pool roster.
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
    echo "pool      : $POOL_ID   games in $GAMES"
    echo "tc        : $TC   hash $HASH   concurrency $CONCURRENCY"
    echo "stop when : +/-$TARGET_ERR   (checked every $((CHECK_EVERY/60)) min after $MIN_GAMES games)"
    echo "pgn       : $PGN"
    echo "seed      : $SEED   (openings shuffle; change it when continuing a run)"
    echo
    echo "bench 13  : $("$REL_EXE" bench 13 2>/dev/null | grep '^nodes')"
} | tee "$OUT/manifest.txt"
echo

# Solve over every calibration PGN to keep versions on one scale.
# `solve [threads]` prints the current engine's rating and error when available.
# Checkpoints use few low-priority threads so they do not compete with games.
solve() {
    local threads="${1:-2}"
    local combined="$OUT/all_calib.pgn"
    # Every game in the pool's folders, except games against engines the pool
    # has since dropped (excluded_engines in pool.json). Theirs stay on disk.
    local d
    # shellcheck disable=SC2046
    python - "$WIN_BM/pool.json" "$(cygpath -m "$combined")" \
        $(for d in $SOLVE_DIRS; do cygpath -m "$d"; done) <<'EOF'
import glob, json, re, sys
pool, out, dirs = sys.argv[1], sys.argv[2], sys.argv[3:]
dropped = set(json.load(open(pool, encoding="utf-8")).get("excluded_engines", []))
with open(out, "w", encoding="utf-8") as combined:
    for d in dirs:
        for path in sorted(glob.glob(d + "/calib-*.pgn")):
            text = open(path, encoding="utf-8", errors="replace").read()
            for game in re.split(r"(?=\[Event )", text):
                players = set(re.findall(r'\[(?:White|Black) "([^"]+)"\]', game))
                if game.strip() and not players & dropped:
                    combined.write(game.rstrip("\n") + "\n\n")
EOF

    # Write to a scratch file because Ordo truncates its output before solving.
    # Replace the last table only after a successful solve.
    local new="$OUT/ordo.new"
    "$ORDO" -Q -p "$combined" -m "$OUT/anchors.txt" -W -s 1500 -n "$threads" -N 1 \
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
    local d
    for d in $SOLVE_DIRS; do
        grep -ch "\"$ENGINE_NAME\"" "$d"/calib-"$VERSION"-*.pgn 2>/dev/null
    done | awk '{s+=$1} END{print s+0}'
}

# Launch the gauntlet
# Run from benchmarks and give fastchess Windows or local relative paths.
CMD=("$(cygpath -m "$FC")" -tournament gauntlet -seeds 1 -srand "$SEED"
     -engine "cmd=$(cygpath -m "$REL_EXE")" "name=$ENGINE_NAME")
# CALIB_OPPONENTS (comma-separated names) limits the gauntlet to some pool
# engines, to top up a version that already has games against the rest.
# Every pool engine stays an anchor in the solve either way. An engine's
# `options` in pool.json are passed to it, for example to turn off its book.
OPPONENTS=$(CALIB_OPPONENTS="${CALIB_OPPONENTS:-}" python -c "
import json, os, sys
p = json.load(open(r'$WIN_BM/pool.json'))
want = [n for n in os.environ['CALIB_OPPONENTS'].split(',') if n]
names = [e['name'] for e in p['engines']]
unknown = [n for n in want if n not in names]
if unknown: sys.exit('unknown pool engine(s): ' + ', '.join(unknown))
for e in p['engines']:
    if not want or e['name'] in want:
        opts = ' '.join(f'option.{k}={v}' for k, v in e.get('options', {}).items())
        print(e['name'], e['cmd'], opts)
") || { echo "ABORT: CALIB_OPPONENTS names an engine that is not in pool.json" >&2; exit 1; }
OPPONENTS=${OPPONENTS//$'\r'/}
N_OPP=0
while read -r name cmd opts; do
    # Convert each pool binary to an absolute Windows path.
    [ -n "$name" ] || continue
    # shellcheck disable=SC2086
    CMD+=(-engine "cmd=$(cygpath -m "$BM/$cmd")" "name=$name" $opts)
    N_OPP=$((N_OPP + 1))
done <<< "$OPPONENTS"
echo "opponents : $(awk '{printf "%s%s ", $1, ($3 ? " [" $3 "]" : "")}' <<< "$OPPONENTS")" \
    | tee -a "$OUT/manifest.txt"
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

# Confirm that every early game includes the engine under test; accidental
# `-seeds` use creates a different gauntlet.
for _ in $(seq 60); do
    ev=$(grep -c '^\[Event' "$PGN" 2>/dev/null || true)
    [ "${ev:-0}" -ge 20 ] && break
    sleep 5
done
ev=$(grep -c '^\[Event' "$PGN" 2>/dev/null || true)
mine=$(grep -c "\"$ENGINE_NAME\"" "$PGN" 2>/dev/null || true)
ev=${ev:-0}
mine=${mine:-0}
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
    # Wake often enough that a finished gauntlet does not leave the machine
    # idle for the rest of a solve interval.
    waited=0
    while [ "$waited" -lt "$CHECK_EVERY" ] && kill -0 "$FC_PID" 2>/dev/null; do
        sleep 10
        waited=$((waited + 10))
    done
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
    echo "Compare versions within this solve only. The gap between two versions"
    echo "is anchor-independent; the absolute is only as good as the anchors."
} | tee "$OUT/RESULT.txt"
