#!/usr/bin/env bash
#
# Pool calibration for a release, with an early stop once the interval is tight.
#
# The ledger holds pool-anchored ratings only, so a release without a gauntlet
# has no row. v8.2 currently carries an NPS-INFERRED 3041 on the website and in
# the README -- the only unsolved number on that ladder. This replaces it with
# a measured one.
#
# The inference is well founded (v8.1 predicted +18.4 from its speed gain and
# measured +20.9 pooled), which is exactly why it is worth checking: a second
# confirmation makes the ~70-per-doubling rule something this project can lean
# on, and a contradiction would be more valuable still.
#
# Gauntlet against pool-2026-07-B (8 engines, 2105-3055 CCRL Blitz anchored) at
# 10+0.1, exactly as every previous calibration. Ordo then solves over ALL
# accumulated calib-*.pgn, so every Sgurr version stays on one internally
# consistent scale.
#
# EARLY STOP. Every CHECK_EVERY seconds the monitor concatenates the accumulated
# PGNs, runs Ordo, and reads the engine's 95% interval. If it reaches +/-TARGET_ERR the
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

# Resolve the repository root from this script's own location, so a clone
# anywhere works. Hardcoding an absolute path meant the script only ran on the
# machine it was written on.
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BM="$ROOT/benchmarks"

# Windows-style path for the embedded python calls. Windows Python cannot open
# an MSYS "/c/..." path, and the failure is silent in the worst way: the pool
# list comes back EMPTY and fastchess is launched with no opponents at all,
# which looks like a crash rather than a bad path.
WIN_BM=$(cygpath -m "$BM")
CPP="$ROOT/sgurr_cpp"
FC="$BM/tools/fastchess.exe"
ORDO="$BM/tools/ordo.exe"
# Calibration uses its OWN, much larger book. testing/book.epd holds 150
# positions and is wired into datagen, SPRT, SPSA and every dataset manifest,
# so it must not be swapped out; this is a separate file used only here.
#
# Why a bigger book matters for a rating, measured on the 2026-08-09 run:
# Sgurr's score varies by opening from 9% to 80%, and the between-opening
# variance is 2.96x what chance alone predicts. That is a real effect, so the
# 150 openings are a SAMPLE of opening space whose uncertainty does not shrink
# by playing more games at the same positions. It contributed
# sqrt(0.01724/150) = 1.07 percentage points, about +/-15 Elo at 95%, while
# the run was quoting +/-5.4. The quoted interval was counting coin-flip noise
# and ignoring the opening draw.
#
# Uncertainty falls as sqrt(openings): 150 -> +/-15, 600 -> +/-7.5,
# 1350 -> +/-5, 3750 -> +/-3. 1500 positions puts the opening term near +/-5,
# below the sampling term, which is where it stops dominating the answer.
BOOK="${BOOK_FILE:-$ROOT/testing/book_calib.epd}"
NET=$(cygpath -m "$ROOT/nets/gen8.nnue")

# Version and binary are arguments so this does not have to be copied per
# release -- two near-identical runner scripts is how run_v60_decomp and
# run_tonight started drifting apart.
#   usage: tools/run_calibrate.sh [version] [exe-name] [openings-seed]
VERSION="${1:-v8.2}"
REL_EXE="$CPP/${2:-sgr_v8_2.exe}"
ENGINE_NAME="Sgurr-$VERSION"

# Opening-book shuffle seed -- fastchess spells this `-srand`, NOT `-seeds`.
#
# Read the difference carefully, because getting it wrong does not fail:
#   -srand SEED   seed for opening book randomisation        <- this one
#   -seeds N      in a gauntlet, the first N engines play against all others
#
# Passing the openings seed as `-seeds 2` on 2026-08-05 quietly promoted
# Blunder-7.4.0 to a second seeded engine, so it ran its own gauntlet against
# the field alongside Sgurr: of the first 68 games, only 40 involved the engine
# under test. Nothing errored, the log looked normal, and the scheduled total
# (93,750) was the only visible tell. Those games were discarded.
#
# Note what this seed can and cannot buy. book.epd holds 150 positions, so at
# 5,000+ games every opening has already been played ~36 times over -- changing
# the seed changes the ORDER, not the diversity. It does not make a resumed run
# sample fresh ground, because there is no fresh ground in a 150-position book.
SEED="${3:-1}"

# Early-stop threshold. Ordo's interval shrinks as 1/sqrt(games): from +/-9.6 at
# 5,000 games, +/-5 needs ~18,500 and +/-1 needs ~460,000. Setting this to 1 is
# therefore a way of DISABLING the early stop, not a target to expect.
TARGET_ERR="${5:-5}"

STAMP=$(date +%Y-%m-%d_%H%M)
OUT="$ROOT/runs/calibrate/${VERSION}_$STAMP"
PGN="$BM/games/calib-$VERSION-$(date +%Y-%m-%d).pgn"

# ---- knobs -----------------------------------------------------------------
TC=10+0.1              # the pool's control, unchanged since pool-2026-07-A
CONCURRENCY=7

# Hash, set EQUALLY for every engine including the one under test.
#
# CCRL's published testing conditions say so explicitly: "Hash size: should be
# set to the same value of either 128 or 256 MB for all engines in a match or
# tourney". The anchors earned their ratings under that rule, so replicating it
# is part of transferring those ratings honestly.
#
# Leaving it unset is not neutral, it hands each engine its own default, and
# those defaults are not comparable: in pool-2026-08-C they ranged from 8 MB
# (Bit-Genie, Jet) to 128 MB (Monolith), against Sgurr's 48. An engine running
# on a fraction of the memory CCRL rated it with underperforms its anchor,
# which inflates the engine under test. The 2026-08-09 default-hash run showed
# exactly that signature: the solve climbing monotonically to +24 Elo and the
# anchors disagreeing by 171 Elo. Those games are quarantined under
# benchmarks/games/_superseded/ and are NOT part of any solve.
#
# 256 rather than 128: both are permitted, 256 is the modern convention, and
# every engine in the pool accepts it (checked against each engine's advertised
# min/max before adopting). 14 concurrent processes x 256 MB is ~3.6 GB.
HASH=256
ROUNDS="${4:-500}"     # 8 opponents x2 games x ROUNDS; 500 -> 8,000 games (~9 h)
                       # TARGET_ERR is set from $5 above, next to the maths
CHECK_EVERY=1800       # seconds between Ordo checks (solve time adds to this)
MIN_GAMES=400          # do not even solve before this many of OUR games
# ----------------------------------------------------------------------------

mkdir -p "$OUT" "$BM/games"
export SGR_EVALFILE="$NET"

# shellcheck source=testing/gauntlet_lib.sh
. "$ROOT/testing/gauntlet_lib.sh"

# Every process this run can leave behind. Killing fastchess alone orphans its
# engines mid-search -- 13 of them once sat at 83% CPU after a "stopped" run.
#
# OUR engine's name is derived from the binary, never hardcoded. It was
# hardcoded to sgr_v8_1 while this script was already running v8.2, so the
# name-sweep backstop covered all eight POOL engines and not the seven copies
# of the engine under test -- the one process guaranteed to be in every game.
# The PID capture in stop_gauntlet happened to catch them, so the gap was
# invisible: a safety net with a hole exactly where the load would be.
# Derived from pool.json, never hardcoded. It listed the pool-B engines while
# pool-2026-08-C was running, so the sweep named eight processes none of which
# were in the match -- the same hole this comment already warned about, in the
# other direction. Deriving it means the list cannot drift from the roster.
ENGINE_PROCS="$(basename "$REL_EXE" .exe) $(python -c "
import json, os
p = json.load(open(r'$WIN_BM/pool.json'))
print(' '.join(os.path.splitext(os.path.basename(e['cmd']))[0] for e in p['engines']))
")"

# Ctrl+C must clean up too, or an interrupted run leaves the machine loaded and
# the next timed measurement is quietly invalid.
# shellcheck disable=SC2086
trap 'echo; echo "interrupted -- stopping engines"; stop_gauntlet $ENGINE_PROCS; assert_engines_stopped $ENGINE_PROCS; exit 130' INT TERM

echo "$ENGINE_NAME pool calibration  ->  $OUT"
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
p=json.load(open(r'$WIN_BM/pool.json'))
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

# ---- solve helper ----------------------------------------------------------
# Ordo over EVERY accumulated calibration PGN, which is what keeps all versions
# on one scale. Prints "<rating> <error>" for $ENGINE_NAME, or nothing if not
# solvable yet.
#
#   solve [threads]
#
# THE MONITOR MUST NOT COMPETE WITH THE GAMES. This ran at -n 5 (five threads)
# against a growing archive, and by the v8.2 run a single solve took ~10
# minutes: the checkpoints in console_v82.log are 25 minutes apart when
# CHECK_EVERY is 900s. So for ~40% of that run's wall time, five Ordo threads
# were competing with seven engines on eight physical cores -- a progress
# monitor loading the machine whose timings it was reporting. Both engines in a
# game slow together so it is roughly symmetric rather than one-sided, but
# METHODOLOGY 8 rule 5 asks for an idle machine and this quietly was not one.
#
# Two changes. Fewer threads, and BelowNormal priority so the engines preempt
# Ordo whenever they want a core: a checkpoint is informational, the games ARE
# the measurement, and the games win every time.
solve() {
    local threads="${1:-2}"
    local combined="$OUT/all_calib.pgn"
    : > "$combined"
    for p in "$BM"/games/calib-*.pgn; do
        [ -f "$p" ] && cat "$p" >> "$combined"
    done

    # Write to a scratch file and move it into place only on success. `-o`
    # truncates its target the moment Ordo starts, so a solve that is killed
    # mid-flight used to destroy the last good table as its first act -- which
    # is exactly what happened when a 10-minute solve was interrupted.
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
    # In a gauntlet our engine plays every game, appearing as either [White] or
    # [Black] -- exactly ONE mention per game, so this is the game count, not
    # half of it. Verified against calib-v8.0-2026-07-29-extended.pgn: 3,083
    # Event tags, 3,083 name mentions.
    #
    # Counted across EVERY PGN for this version, not just this run's file. The
    # PGN name carries the date, so a calibration stopped and resumed the next
    # day writes a second file -- and counting only the current one would report
    # a game count far below what Ordo actually solved over, which is the sort of
    # mismatch that makes a log look broken when it is fine.
    grep -ch "\"$ENGINE_NAME\"" "$BM"/games/calib-"$VERSION"-*.pgn 2>/dev/null \
        | awk '{s+=$1} END{print s+0}'
}

# ---- launch the gauntlet in the background ---------------------------------
# fastchess is a Windows binary and cannot resolve MSYS "/c/..." paths, so
# everything handed to it is either a Windows path (cygpath -m) or relative to
# its working directory. pipeline.py sidesteps this by running from benchmarks/
# with the relative paths pool.json already stores; this does the same.
CMD=("$(cygpath -m "$FC")" -tournament gauntlet -seeds 1 -srand "$SEED"
     -engine "cmd=$(cygpath -m "$REL_EXE")" "name=$ENGINE_NAME")
N_OPP=0
while read -r name cmd; do
    # Absolute Windows path per engine. The relative form pool.json stores works
    # for pipeline.py because Python launches fastchess with cwd=benchmarks; it
    # does NOT resolve when fastchess is started from an MSYS shell, and the
    # symptom is "process creation failed" on the first engine tried.
    [ -n "$name" ] && { CMD+=(-engine "cmd=$(cygpath -m "$BM/$cmd")" "name=$name"); N_OPP=$((N_OPP + 1)); }
done < <(python -c "
import json
p=json.load(open(r'$WIN_BM/pool.json'))
for e in p['engines']: print(e['name'], e['cmd'])
" | tr -d '\r')
# tr -d '\r' is load-bearing: Windows Python writes CRLF, so without it every
# engine path ends in a carriage return and fastchess reports
# "Engine binary does not exist: ...blunder-7.4.0.exe?" -- the '?' being the CR
# rendered back at you.
CMD+=(-each "tc=$TC" "option.Hash=$HASH" -rounds "$ROUNDS" -repeat
      -concurrency "$CONCURRENCY" -recover
      -openings "file=$(cygpath -m "$BOOK")" format=epd order=random
      -pgnout "file=$(cygpath -m "$PGN")" -ratinginterval 60)

# Opponent count is read from pool.json rather than hardcoded: it was fixed at
# 8 while pool-2026-08-C has 6, so the header claimed 80,000 games when the real
# cap was 60,000.
echo "=== gauntlet: $ENGINE_NAME vs $N_OPP pool engines, Hash=$HASH, up to $((ROUNDS*N_OPP*2)) games ==="
date
( cd "$BM" && "${CMD[@]}" ) > "$OUT/gauntlet.log" 2>&1 &
FC_PID=$!
echo "fastchess pid $FC_PID, log $OUT/gauntlet.log"
echo

# ---- structural check: is this actually a gauntlet? -------------------------
# In a gauntlet the engine under test plays EVERY game, so the count of [Event]
# tags and the count of games naming it must be equal. They were not on
# 2026-08-05: `-seeds 2`, meant as an openings seed, promoted a second engine to
# seed and 28 of the first 68 games did not involve Sgurr at all. fastchess did
# not complain, the log read normally, and the only tell was a scheduled total
# nobody had reason to check. Verify it in the first minutes instead.
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
        # shellcheck disable=SC2086
        stop_gauntlet $ENGINE_PROCS
        break
    fi
done

wait "$FC_PID" 2>/dev/null
echo
echo "=== gauntlet ended ==="
date

# Unconditional sweep. fastchess exiting normally usually shuts its engines
# down, but "usually" is not a property to rely on before an Ordo solve that
# takes minutes -- and the next thing to run deserves an idle machine.
# shellcheck disable=SC2086
stop_gauntlet $ENGINE_PROCS
# shellcheck disable=SC2086
assert_engines_stopped $ENGINE_PROCS

# ---- final solve -----------------------------------------------------------
# Five threads here, unlike the checkpoints: the games are over and the machine
# is idle, so there is nothing left to steal CPU from.
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
