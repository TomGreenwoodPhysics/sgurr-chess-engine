# fastchess setup (recommended for serious volume)

The Python harness in this folder works out of the box, but for high game
throughput use **fastchess** — the C++ tournament manager most engine authors
run. It's faster, supports the lower-variance pentanomial SPRT, and handles
concurrency, clocks, and crashes robustly. (`cutechess-cli` is the older
equivalent; the SPRT flags are nearly identical.)

## Install

fastchess: https://github.com/Disservin/fastchess

- Grab a release binary for your OS, or build from source:

      git clone https://github.com/Disservin/fastchess
      cd fastchess && make -j

On Windows, the release `.exe` is the easiest path, or build under MSYS2/MinGW
(the same toolchain you build Ruk with).

## Run an SPRT (new vs previous version)

    fastchess \
      -engine cmd=./ruk_new  name=new \
      -engine cmd=./ruk_base name=base \
      -each tc=8+0.08 \
      -rounds 5000 -repeat -concurrency 8 \
      -openings file=book.epd format=epd order=random \
      -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
      -ratinginterval 20 -pgnout games.pgn

What the flags do:

- `-engine cmd=... name=...` — the two engines. `new` is the patch, `base` is the
  last accepted build.
- `-each tc=8+0.08` — 8 seconds + 0.08s/move increment, applied to both. Change to
  whatever TC you're testing.
- `-rounds 5000 -repeat` — up to 5000 opening pairs; `-repeat` plays each opening
  once with each colour (so 10000 games max). SPRT will stop long before that.
- `-concurrency 8` — parallel games. Set near your physical core count; leave one
  core free.
- `-openings file=book.epd format=epd order=random` — the balanced book in this
  folder (EPD = one FEN per line, which fastchess reads directly).
- `-sprt elo0=0 elo1=5 alpha=0.05 beta=0.05` — the same non-regression test the
  Python harness runs. fastchess prints the LLR and stops on a bound.
- `-pgnout games.pgn` — save games (useful for spotting tactical/eval issues).

fastchess prints, every `ratinginterval` games, the running score, an Elo
estimate with error bars, and the LLR with its bounds — then `Finished match`
with the SPRT verdict.

## Notes specific to Ruk

- Ruk has no UCI options, so no `option.Hash=...` etc. is needed.
- For the cleanest results, make Ruk clear its transposition table on the
  `ucinewgame` command (it currently doesn't), so games within one process don't
  share TT state. It's a small change and removes a minor source of noise. Both
  engines are affected equally either way, so existing results are still valid.
- Use the **same book and same TC** as the Python harness so numbers are
  comparable across the two tools.

## cutechess-cli equivalent

If you already have cutechess-cli, the same test is:

    cutechess-cli \
      -engine cmd=./ruk_new  name=new  proto=uci \
      -engine cmd=./ruk_base name=base proto=uci \
      -each tc=8+0.08 \
      -rounds 5000 -repeat -concurrency 8 \
      -openings file=book.epd format=epd order=random \
      -sprt elo0=0 elo1=5 alpha=0.05 beta=0.05 \
      -ratinginterval 20