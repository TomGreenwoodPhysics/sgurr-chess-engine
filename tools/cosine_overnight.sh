#!/usr/bin/env bash
# Overnight: retrain the v9.1 SCReLU net with a cosine learning-rate schedule,
# race it against v9.1, and calibrate it in the pool if it wins.
#
# The shipped gen9_screlu.nnue trained at a constant 1e-3 because
# mainline_screlu_train.sh never passed --schedule cosine. This run changes
# that flag and nothing else. Prediction: benchmarks/v91_cosine_prediction.md.
#
#   tools/cosine_overnight.sh           run, skipping stages already done
#   tools/cosine_overnight.sh --check   preflight and builds only, no training or games
#
# Results land in runs/cosine/SUMMARY.txt.
set -u

ROOT=/c/coding/Sgurr
CPP=$ROOT/sgurr_cpp
RUN=$ROOT/runs/cosine
LOG=$RUN/overnight.log
PY=$ROOT/.venv/Scripts/python.exe
FC=$ROOT/benchmarks/tools/fastchess.exe
BOOK=$ROOT/testing/8moves_v3.pgn
CLANG=/c/msys64/clang64/bin/clang++
DATA=$ROOT/data/gen9_102m/all.bin
DATA_SHA=fb42bb334652ed60b702a53553a976ea5e5fdd6af1930bbd43dfe700ce339f60

REF_NET=$ROOT/nets/gen9_screlu.nnue
COS_NET=$ROOT/nets/gen9_screlu_cos.nnue
S1_NET=$ROOT/nets/gen9_screlu_cos_s1.nnue
REF_EXE=sprt_v91_ref.exe
COS_EXE=sprt_v91_cos.exe
S1_EXE=sprt_v91_cos_s1.exe
SELFCHECK=selfcheck_v91.exe
V91_EXE=sprt_bundle.exe          # the binary pool-calibrated as v9.1
REF_EVALSUM=156878               # nnue_selfcheck on gen9_screlu, as in CI

SPRT_ROUNDS=1500                 # 3,000-game cap
CAL_VERSION=v9.1-cos
CAL_ROUNDS=300                   # 3,000-game cap, five opponents
CAL_TARGET=10

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

mkdir -p "$RUN"
unset SGR_EVALFILE   # every engine here has its net baked in; the env var would override it
say()  { echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
die()  { say "STOP: $*"; say "=== stopped, needs a human ==="; exit 1; }

# Stop our own engines only, never anything matched by window title.
stop_engines() {
    for p in fastchess.exe $REF_EXE $COS_EXE; do
        taskkill //IM "$p" //F >/dev/null 2>&1
    done
    sleep 3
}

# "loaded <path>" line for an exe, empty if it fell back to the hand-crafted eval.
loaded_net() { printf 'uci\nquit\n' | "$CPP/$1" 2>&1 | grep -ao 'nnue: loaded [^ ]*' | head -1; }
bench_nodes() { "$CPP/$1" bench 2>/dev/null | grep -aE '^nodes' | awk '{print $2}'; }
bench_nps()   { "$CPP/$1" bench 11 2>/dev/null | grep -aoE 'nps [0-9]+' | awk '{print $2}'; }

# Count games whose ending is not a mate or a draw by rule: forfeits, time
# losses, crashes. Prints "total abnormal". METHODOLOGY 9: check endings before
# reading a rating.
endings() {
    local f=$1 tmp=$RUN/endings.tmp
    grep -aoE 'Finished game [0-9]+ \([^)]*\): [^{]*\{[^}]*\}' "$f" \
        | sed -E 's/.*\{(.*)\}$/\1/' > "$tmp"
    local total bad
    total=$(wc -l < "$tmp" | tr -d ' ')
    bad=$(grep -cvE 'mates$|^Draw by ' "$tmp")
    echo "$total $bad"
}

train() {  # out seed log
    say "training $(basename "$1") (seed $2): cosine 1e-3 -> 1e-5, 22 epochs, lambda 0.8, 5% holdout"
    ( cd "$ROOT" && "$PY" -u nnue/train.py --data "$DATA" --out "$1" \
        --screlu --lambda_ 0.8 --epochs 22 --schedule cosine --lr_min 1e-5 \
        --val_frac 0.05 --seed "$2" --loader memory ) >>"$3" 2>&1
    [ -f "$1" ] || die "training produced no net, see $3"
    say "trained: $(tail -2 "$3" | head -1)"
}

build_engine() {  # exe net version
    say "building $1 with $(basename "$2") baked in"
    ( cd "$CPP" && ./build.sh -r -o "$1" --version "$3" \
        -DSGR_DEFAULT_NET="\"$(cygpath -m "$2")\"" ) >>"$LOG" 2>&1 || die "build of $1 failed"
    local got
    got=$(loaded_net "$1")
    case "$got" in
        *"$(basename "$2")") say "  $1: $got" ;;
        *) die "$1 did not load $(basename "$2") (got '${got:-hand-crafted eval}')" ;;
    esac
}

selfcheck() {  # net
    local out
    out=$("$CPP/$SELFCHECK" "$1" 2>&1 | tail -1)
    say "  selfcheck $(basename "$1"): $out"
    echo "$out" | grep -q 'PASS' || die "selfcheck failed on $1"
}

say "=== cosine overnight $([ $CHECK_ONLY = 1 ] && echo '(check only)') ==="

# --- preflight -----------------------------------------------------------
busy=$(powershell -NoProfile -Command "(Get-Process fastchess,datagen -ErrorAction SilentlyContinue | Measure-Object).Count" 2>/dev/null | tr -d '\r ')
[ "${busy:-0}" = "0" ] || die "$busy fastchess/datagen process(es) already running"
for f in "$PY" "$FC" "$BOOK" "$CLANG" "$DATA" "$REF_NET" "$CPP/$V91_EXE"; do
    [ -e "$f" ] || die "missing $f"
done
"$PY" -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" \
    || die "torch cannot see the GPU"
if [ -f "$RUN/.data_ok" ]; then
    say "dataset hash already verified"
else
    say "verifying the gen9 dataset hash"
    got=$(sha256sum "$DATA" | awk '{print $1}')
    [ "$got" = "$DATA_SHA" ] || die "dataset hash $got, expected $DATA_SHA"
    touch "$RUN/.data_ok"
fi

# --- selfcheck binary, proven against the shipped net first --------------
if [ ! -f "$CPP/$SELFCHECK" ]; then
    say "building $SELFCHECK"
    ( cd "$CPP" && "$CLANG" -std=c++20 -O3 -march=native -DNDEBUG -static \
        nnue_selfcheck.cpp board.cpp evaluation.cpp search.cpp nnue.cpp -o "$SELFCHECK" ) \
        >>"$LOG" 2>&1 || die "selfcheck build failed"
fi
selfcheck "$REF_NET"
"$CPP/$SELFCHECK" "$REF_NET" 2>&1 | grep -q "evalsum=$REF_EVALSUM " \
    || die "selfcheck evalsum on gen9_screlu is not $REF_EVALSUM; the build does not match CI"

# --- reference engine: must search exactly like the calibrated v9.1 ------
[ -f "$CPP/$REF_EXE" ] || build_engine "$REF_EXE" "$REF_NET" 9.1
ref_nodes=$(bench_nodes "$REF_EXE")
v91_nodes=$(bench_nodes "$V91_EXE")
[ -n "$ref_nodes" ] && [ "$ref_nodes" = "$v91_nodes" ] \
    || die "$REF_EXE benches $ref_nodes nodes, $V91_EXE $v91_nodes: the reference is not v9.1"
say "reference is bench-identical to the calibrated v9.1 ($ref_nodes nodes)"

if [ $CHECK_ONLY = 1 ]; then
    say "=== check passed: ready for the overnight run ==="
    exit 0
fi

# --- 1. train the candidate ---------------------------------------------
if [ -f "$COS_NET" ]; then
    say "$(basename "$COS_NET") already trained, reusing"
else
    train "$COS_NET" 0 "$RUN/train_s0.log"
fi
selfcheck "$COS_NET"

# --- 2. candidate engine -------------------------------------------------
[ -f "$CPP/$COS_EXE" ] || build_engine "$COS_EXE" "$COS_NET" 9.1-cos
say "nps: ref $(bench_nps "$REF_EXE"), cosine $(bench_nps "$COS_EXE") (same architecture, should match)"

# --- 3. SPRT against v9.1 ------------------------------------------------
if grep -aq 'Finished match' "$RUN/sprt.txt" 2>/dev/null; then
    say "SPRT already finished, reusing"
else
    say "SPRT: cosine vs v9.1, 8+0.08, [0, 5], up to $((SPRT_ROUNDS * 2)) games"
    stop_engines
    "$FC" -engine cmd="$CPP/$COS_EXE" name=cosine -engine cmd="$CPP/$REF_EXE" name=v91 \
        -each tc=8+0.08 option.Hash=256 -rounds $SPRT_ROUNDS -repeat -concurrency 7 \
        -openings file="$BOOK" format=pgn order=random -recover \
        -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
        -pgnout file="$(cygpath -m "$RUN/sprt.pgn")" \
        >"$RUN/sprt.txt" 2>&1
    stop_engines
fi
SPRT_ELO=$(grep -aE '^Elo:' "$RUN/sprt.txt" | tail -1)
SPRT_GAMES=$(grep -aE '^Games:' "$RUN/sprt.txt" | tail -1)
if   grep -aq 'H1 was accepted' "$RUN/sprt.txt"; then VERDICT=H1
elif grep -aq 'H0 was accepted' "$RUN/sprt.txt"; then VERDICT=H0
else VERDICT="no decision"; fi
read -r s_total s_bad <<< "$(endings "$RUN/sprt.txt")"
say "SPRT: $VERDICT | $SPRT_ELO | $SPRT_GAMES"
say "SPRT endings: $s_total games, $s_bad not a mate or a rule draw"

# --- 4. pool calibration, only on a clean H1 -----------------------------
CAL_NOTE="not run"
if [ "$VERDICT" != H1 ]; then
    CAL_NOTE="skipped: SPRT verdict was $VERDICT"
elif [ "$s_bad" -gt $(( s_total / 100 )) ]; then
    CAL_NOTE="skipped: $s_bad abnormal endings in the SPRT, look at them first"
else
    if [ -f "$RUN/.calibrated" ]; then
        say "calibration already ran, reusing"
    else
        say "calibrating $CAL_VERSION against pool-2026-08-D, target +/-$CAL_TARGET"
        stop_engines
        ( cd "$ROOT" && NET_FILE="$COS_NET" ./tools/run_calibrate.sh \
            "$CAL_VERSION" "$COS_EXE" 1 $CAL_ROUNDS $CAL_TARGET ) >>"$RUN/calibrate.log" 2>&1
        stop_engines
        touch "$RUN/.calibrated"
    fi
    CAL_DIR=$(ls -td "$ROOT"/runs/calibrate/${CAL_VERSION}_* 2>/dev/null | head -1)
    if [ -n "$CAL_DIR" ]; then
        ORDO="$CAL_DIR/ordo.txt"; [ -s "$ORDO" ] || ORDO="$CAL_DIR/ordo.new"
        read -r c_total c_bad <<< "$(endings "$CAL_DIR/gauntlet.log")"
        CAL_NOTE="$CAL_DIR ($c_total games, $c_bad abnormal endings)"
        say "calibration done: $CAL_NOTE"
    else
        CAL_NOTE="calibration produced no run directory, see $RUN/calibrate.log"
        say "$CAL_NOTE"
    fi
fi

# --- 5. second seed, for a seed-luck check in the morning ----------------
if [ -f "$S1_NET" ]; then
    say "$(basename "$S1_NET") already trained, reusing"
else
    train "$S1_NET" 1 "$RUN/train_s1.log"
fi
selfcheck "$S1_NET"
[ -f "$CPP/$S1_EXE" ] || build_engine "$S1_EXE" "$S1_NET" 9.1-cos-s1

# --- summary -------------------------------------------------------------
{
    echo "Cosine retrain of the v9.1 net, $(date '+%Y-%m-%d %H:%M')"
    echo "Prediction: benchmarks/v91_cosine_prediction.md (+15, band +5 to +30)"
    echo "Recipe as logged: $(grep -a '^schedule:' "$RUN/train_s0.log" 2>/dev/null | tail -1)"
    echo
    echo "Validation loss, final epoch (same 5% holdout, not a selection criterion):"
    echo "  shipped, constant lr : $(grep -aE 'epoch +22/22' "$ROOT/runs/sgurr_x/mainline_screlu.log" | tail -1)"
    echo "  cosine, seed 0       : $(grep -aE 'epoch +22/22' "$RUN/train_s0.log" 2>/dev/null | tail -1)"
    echo "  cosine, seed 1       : $(grep -aE 'epoch +22/22' "$RUN/train_s1.log" 2>/dev/null | tail -1)"
    echo
    echo "SPRT cosine vs v9.1, 8+0.08, [0, 5]: $VERDICT"
    echo "  $SPRT_ELO"
    echo "  $SPRT_GAMES"
    echo "  endings: $s_total games, $s_bad abnormal"
    echo
    echo "Pool calibration: $CAL_NOTE"
    if [ -n "${ORDO:-}" ] && [ -s "${ORDO:-}" ]; then
        grep -aE 'Sgurr-v9\.1(-cos)? ' "$ORDO"
        awk '/Sgurr-v9\.1-cos /{c=$4} /Sgurr-v9\.1 /{r=$4} END{if(c&&r) printf "  same-solve gap: %+.1f\n", c-r}' "$ORDO"
    fi
    echo
    echo "Seed 1 net and engine ready: $S1_EXE (not yet played)"
} > "$RUN/SUMMARY.txt"
cat "$RUN/SUMMARY.txt" | tee -a "$LOG"
say "=== done ==="
