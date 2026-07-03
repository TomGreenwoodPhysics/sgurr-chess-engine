# fastchess setup

The Python harness in this folder works out of the box, but for high game
throughput **fastchess** is the better tool: faster, supports the
lower-variance pentanomial SPRT, and handles concurrency, clocks, and crashes
robustly. (`cutechess-cli` is the older equivalent; the SPRT flags are nearly
identical.)

## Install

fastchess: https://github.com/Disservin/fastchess

Grab a release binary, or build from source:

    git clone https://github.com/Disservin/fastchess
    cd fastchess && make -j

On Windows the release `.exe` is the easiest path, or build under MSYS2/MinGW.

## Run an SPRT (new vs previous version)

    fastchess \
      -engine cmd=./ruk_new  name=new \
      -engine cmd=./ruk_base name=base \
      -each tc=8+0.08 \
      -rounds 5000 -repeat -concurrency 8 \
      -openings file=book.epd format=epd order=random \
      -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
      -ratinginterval 20 -pgnout games.pgn

Flags:

- `-engine cmd=... name=...`: the two engines; `new` is the patch, `base` the
  last accepted build.
- `-each tc=8+0.08`: 8 seconds + 0.08s/move increment for both sides.
- `-rounds 5000 -repeat`: up to 5000 opening pairs; `-repeat` plays each
  opening once with each colour. SPRT normally stops long before the cap.
- `-concurrency 8`: parallel games. Set near the physical core count, leaving
  one core free.
- `-openings file=book.epd format=epd order=random`: the balanced book in this
  folder (EPD = one FEN per line).
- `-sprt elo0=0 elo1=5 alpha=0.05 beta=0.05`: the same non-regression test the
  Python harness runs.
- `-pgnout games.pgn`: save games for spotting tactical/eval issues.

Every `ratinginterval` games fastchess prints the running score, an Elo
estimate with error bars, and the LLR with its bounds, then `Finished match`
with the SPRT verdict.

## Notes specific to Ruk

- Ruk has no UCI options, so no `option.Hash=...` etc. is needed.
- Ruk does not currently clear its transposition table on `ucinewgame`, so
  games within one process share TT state. Both engines are affected equally,
  but clearing it would remove a minor source of noise.
- Use the same book and TC as the Python harness so numbers are comparable
  across the two tools.

## cutechess-cli equivalent

    cutechess-cli \
      -engine cmd=./ruk_new  name=new  proto=uci \
      -engine cmd=./ruk_base name=base proto=uci \
      -each tc=8+0.08 \
      -rounds 5000 -repeat -concurrency 8 \
      -openings file=book.epd format=epd order=random \
      -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
      -ratinginterval 20
