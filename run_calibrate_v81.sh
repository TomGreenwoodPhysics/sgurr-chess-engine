#!/usr/bin/env bash
#
# Pool calibration for v8.1, with an early stop once the interval is tight.
#
# v8.1 has a measured SELF-PLAY result (+21.2 +/-8.7 vs v8.0, 2026-08-03) but
# no pool-anchored rating, and the ledger holds pool ratings only. Self-play
# gains have compressed against the pool before (METHODOLOGY 6: RFP 0.68x, the
# gen8 net 0.81x), so the pooled figure is NOT simply 3006 + 21. This measures
# it rather than assuming it.
#
# Gauntlet against pool-2026-07-B (8 engines, 2105-3055 CCRL Blitz anchored) at
# 10+0.1, exactly as every previous calibration. Ordo then solves over ALL
# accumulated calib-*.pgn, so every Sgurr version stays on one internally
# consistent scale.
#
# EARLY STOP. Every CHECK_EVERY seconds the monitor concatenates the accumulated
# PGNs, runs Ordo, and reads v8.1's 95% interval. If it reaches +/-TARGET_ERR the
# gauntlet is stopped, because more games past that point buy nothing worth
# waiting for. For scale: v8.0 reached +/-11 at 3,329 games and error shrinks as
# 1/sqrt(n), so +/-5 needs roughly 16,000 -- some hours beyond this window. The
# stop is a safety net against running longer than useful, not an expectation.
#
# The round cap is deliberately generous so the run does NOT finish early and
# leave the machine idle. Stop it whenever with Ctrl+C or:
#     taskkill /IM fastchess.exe /F
# The PGN stays valid and Ordo can be re-run over it at any time.

set -u

ROOT=/c/Coding/Sgurr
BM="$ROOT/benchmarks"
CPP="$ROOT/sgurr_cpp"
FC="$BM/tools/fastchess.exe"
ORDO="$BM/tools/ordo.exe"
BOOK="$ROOT/testing/book.epd"
NET="C:/Coding/Sgurr/nets/gen8.nnue"

VERSION="v8.1"
ENGINE_NAME="Sgurr-$VERSION"
REL_EXE="$CPP/sgr_v8_1.exe"

STAMP=$(date +%Y-%m-%d_%H%M)
OUT="$ROOT/runs/calibrate_v81/$STAMP"
PGN="$BM/games/calib-$VERSION-$(date +%Y-%m-%d).pgn"

# ---- knobs -----------------------------------------------------------------
TC=10+0.1              # the pool's control, unchanged since pool-2026-07-A
CONCURRENCY=7
ROUNDS=500             # 8 opponents x2 games x 500 = up to 8,000 games (~9 h)
TARGET_ERR=5           # stop once Ordo reports +/- this or tighter
CHECK_EVERY=900        # seconds between Ordo checks
MIN_GAMES=400          # do not even solve before this many v8.1 games
# ----------------------------------------------------------------------------

mkdir -p "$OUT" "$BM/games"
export SGR_EVALFILE="$NET"

echo "v8.1 pool calibration  ->  $OUT"
date
echo

# ---- preflight -------------------------------------------------------------
busy=$(powershell -c "(Get-Process datagen,fastchess -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r')
if [ "${busy:-0}" != "0" ]; then
    echo "ABORT: $busy datagen/fastchess process(es) already running." >&2
    echo "Timed game results under CPU load are invalid." >&2
    exit 1
fi

# Verify OUR engine and every pool engine. A pool engine that cannot spawn
# forfeits every game it plays, which inflates Sgurr's score against it and
# drags the whole Ordo solve off its anchors -- a wrong rating that looks fine.
POOL_EXES=$(python -c "
import json,sys
p=json.load(open(r'$BM/pool.json'))
print(' '.join(r'$BM/'+e['cmd'] for e in p['engines']))
")
PY="$ROOT/.venv/Scripts/python.exe"; [ -f "$PY" ] || PY=python
# shellcheck disable=SC2086
if ! "$PY" "$ROOT/testing/engine_check.py" "$REL_EXE" $POOL_EXES; then
    echo "ABORT: engine pre-flight failed (see above)." >&2
    exit 1
fi

if ! printf 'uci\nquit\n' | "$REL_EXE" 2>&1 >/dev/null | grep -q "nnue: loaded"; then
    echo "ABORT: $REL_EXE is NOT loading the net -- it would play as HCE." >&2
    exit 1
fi
echo "preflight: v8.1 and all 8 pool engines start; v8.1 loads the net"
echo

{
    echo "run       : $STAMP"
    echo "commit    : $(cd "$ROOT" && git rev-parse HEAD)"
    echo "engine    : $REL_EXE  ($(printf 'uci\nquit\n' | "$REL_EXE" 2>/dev/null | sed -n 's/^id name //p'))"
    echo "net       : $NET"
    echo "pool      : $(python -c "import json;print(json.load(open(r'$BM/pool.json'))['pool_id'])")"
    echo "tc        : $TC   concurrency $CONCURRENCY"
    echo "stop when : +/-$TARGET_ERR   (checked every $((CHECK_EVERY/60)) min after $MIN_GAMES games)"
    echo "pgn       : $PGN"
    echo
    echo "v8.1 bench 13: $("$REL_EXE" bench 13 2>/dev/null | grep '^nodes')"
    echo "(v8.0 shipped binary is the same tree: 13614729)"
} | tee "$OUT/manifest.txt"
echo

# ---- solve helper ----------------------------------------------------------
# Ordo over EVERY accumulated calibration PGN, which is what keeps all versions
# on one scale. Prints "<rating> <error>" for v8.1, or nothing if not solvable
# yet.
solve() {
    local combined="$OUT/all_calib.pgn"
    : > "$combined"
    for p in "$BM"/games/calib-*.pgn; do
        [ -f "$p" ] && cat "$p" >> "$combined"
    done
    "$ORDO" -Q -p "$combined" -m "$BM/anchors.txt" -W -s 1500 -n 5 -N 1 \
            -o "$OUT/ordo.txt" >/dev/null 2>&1
    grep -oE "$ENGINE_NAME\s*:\s*-?[0-9.]+\s+[0-9.]+" "$OUT/ordo.txt" 2>/dev/null \
        | tail -1 | awk '{print $(NF-1), $NF}'
}

games_so_far() {
    # In a gauntlet our engine plays every game, appearing as either [White] or
    # [Black] -- exactly ONE mention per game, so this is the game count, not
    # half of it. Verified against calib-v8.0-2026-07-29-extended.pgn: 3,083
    # Event tags, 3,083 name mentions.
    grep -c "\"$ENGINE_NAME\"" "$PGN" 2>/dev/null || echo 0
}

# ---- launch the gauntlet in the background ---------------------------------
CMD=("$FC" -tournament gauntlet -seeds 1
     -engine "cmd=$REL_EXE" "name=$ENGINE_NAME")
while read -r name cmd; do
    [ -n "$name" ] && CMD+=(-engine "cmd=$BM/$cmd" "name=$name")
done < <(python -c "
import json
p=json.load(open(r'$BM/pool.json'))
for e in p['engines']: print(e['name'], e['cmd'])
")
CMD+=(-each "tc=$TC" -rounds "$ROUNDS" -repeat
      -concurrency "$CONCURRENCY" -recover
      -openings "file=$BOOK" format=epd order=random
      -pgnout "file=$PGN" -ratinginterval 60)

echo "=== gauntlet: $ENGINE_NAME vs 8 pool engines, up to $((ROUNDS*16)) games ==="
date
"${CMD[@]}" > "$OUT/gauntlet.log" 2>&1 &
FC_PID=$!
echo "fastchess pid $FC_PID, log $OUT/gauntlet.log"
echo

# ---- monitor ---------------------------------------------------------------
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
        taskkill //IM fastchess.exe //F >/dev/null 2>&1
        break
    fi
done

wait "$FC_PID" 2>/dev/null
echo
echo "=== gauntlet ended ==="
date

# ---- final solve -----------------------------------------------------------
read -r rating err <<< "$(solve)"
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
