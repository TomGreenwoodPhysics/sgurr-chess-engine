# Sgurr Web

Sgurr Web is a browser chess experience backed by the Sgurr UCI engine.
Every canonical release from the classical evaluation up to v8.2 is
selectable as an opponent, newest first, and v8.2 is the default. FastAPI
validates chess state, owns the engine process, serves the production
frontend and allowlisted media, and exposes a small JSON API. The same
frontend can also run from VS Code Live Server during development.

The opponent ladder is defined by `ENGINE_SPECS` in `backend/main.py`; its
ratings are the pool-2026-07-B Ordo solve copied from
`../benchmarks/ledger.md`, so adding a version there puts it in the picker.

## Structure

```text
web/
  backend/
    main.py                FastAPI app, static serving, and chess endpoints
    sgurr_uci.py           persistent UCI subprocess wrapper
    requirements.txt       development-compatible dependency ranges
    requirements.lock.txt  audited release dependency pins
  frontend/
    index.html             static browser UI (loads js/main.js + styles.css)
    search-lab/            guided search walkthrough + live depth stream
    inside-sgurr/           exact browser-side Gen8 accumulator explorer
    styles.css             @import manifest; ordering IS the cascade
    styles/                12 CSS partials (base, intro, menu, board, core, ...)
    js/                    19 native ES modules; main.js is the entry point
    assets/                web-owned images and Chessnut pieces
  licenses/                Python dependency licence texts
  tests/e2e/               deterministic Playwright smoke tests
  playwright.config.js
  package.json
```

The frontend is plain ES modules and CSS with no build step. `js/main.js`
wires DOM events and boots the app; shared state lives in `js/state.js`
(`app` and `refs`) and constants in `js/config.js`; feature modules
(`board`, `game`, `engine`, `ui`, `audio`, `intro`, `personality`, `editor`,
`clocks`, `themes`, ...) import from those. `styles.css` is an `@import`
manifest whose partial order defines the cascade, keep it stable when adding
sections, and note that relative `url()`s inside `styles/*.css` need a `../`
hop to reach `assets/`.

The browser owns the current FEN and move list. The backend validates moves
with `python-chess`, asks Sgurr for engine moves over UCI, parses
`info ... score ...` lines, and returns updated state. The browser uses
commercially permissive Chessnut pieces, procedural game/UI cues, and an
allowlist of documented music and result sounds.

## 1. Build The Sgurr Engine

Use the MSYS2 `clang64` shell on Windows, from the repository root:

```bash
cd sgurr_cpp
./build.sh -r -o sgr_v8_2.exe     # release build; see BUILD.md for the recipe
```

The backend looks for the binary each `ENGINE_SPECS` entry names, so build
whichever releases you want selectable. Only the default (`sgr_v8_2.exe`) is
needed to play; the rest degrade to unavailable entries in the picker.

Quick UCI check:

```bash
./sgr_v8_2.exe uci
```

Then enter `uci`, `isready`, `position startpos`, `go movetime 500`, and
`quit`. You should see `uciok`, `readyok`, an `info ... score ...` line, and a
`bestmove`.

## 2. Install Backend Dependencies

From Anaconda Prompt:

```bat
cd /d "<repo>"
conda create -n sgurr-web python=3.11 -y
conda activate sgurr-web
python -m pip install --upgrade pip
python -m pip install -r web\backend\requirements.txt
```

For a reproducible release build, install the audited exact versions instead:

```bat
python -m pip install -r web\backend\requirements.lock.txt
```

The default engine path is `sgurr_cpp\sgr_v8_2.exe` with `nets\gen8.nnue`.
Override it before starting Uvicorn when necessary:

```bat
set SGURR_ENGINE_EXE=C:\path\to\sgr_v8_2.exe
set SGR_EVALFILE=C:\path\to\gen8.nnue
```

## 3. Start Sgurr Web

From the repository root, with the Conda environment active:

```bat
cd /d "<repo>"
conda activate sgurr-web
python -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8000
```

Open the complete site at <http://127.0.0.1:8000>. The health endpoint is
<http://127.0.0.1:8000/health>. This one-process, same-origin setup is the
recommended production shape and does not require CORS.

## 4. Optional Split Frontend Development

VS Code Live Server is supported. Alternatively, open a second prompt:

```bat
cd /d "<repo>\web\frontend"
conda activate sgurr-web
python -m http.server 5173
```

Then open <http://127.0.0.1:5173>. On localhost, a frontend served from a port
other than `8000` automatically uses `http://127.0.0.1:8000` for the API. To
use another backend port:

```text
http://127.0.0.1:5173?api=http://127.0.0.1:8001
```

API configuration precedence is:

1. the `?api=` query parameter;
2. `<meta name="sgurr-api-base">` in `frontend/index.html`;
3. the `sgurrApiBase` local-storage value;
4. same-origin in production, or port `8000` for local split development.

Use `same-origin` as an explicit configured value when needed.

## 5. Production Configuration

Put Uvicorn behind an HTTPS reverse proxy and keep it bound to a private/local
interface. For a single public origin, use strict same-origin settings:

```bat
set SGURR_ALLOWED_ORIGINS=none
set SGURR_ALLOWED_HOSTS=play.example.com
python -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Each Uvicorn worker owns its own engine processes, so run one worker for the
hosted demo. If the frontend and API are genuinely on different origins, list the
frontend origins explicitly:

```bat
set SGURR_ALLOWED_ORIGINS=https://play.example.com,https://preview.example.com
set SGURR_ALLOWED_HOSTS=api.example.com
```

Wildcards are rejected. `SGURR_ALLOWED_ORIGINS` entries are complete origins
without paths. `SGURR_ALLOWED_HOSTS` entries are hostnames without schemes or
ports. Local origins for ports `4173`, `5173`, and `5500` are enabled only when
`SGURR_ALLOWED_ORIGINS` is unset.

`/health` does not expose the executable path. Set
`SGURR_EXPOSE_ENGINE_PATH=true` only for private local diagnostics. The server
publishes frontend assets plus a fixed allowlist of repository-level music and
result sounds; it never mounts the repository root as a static directory.

Before exposing a non-container deployment publicly, also configure HTTPS,
process supervision, request logging, and request limits.

### Free hosted demo

The root `Dockerfile` builds scalar Linux versions of v8.2 and the trace
engine, verifies the committed NNUE, and runs one Uvicorn worker:

```bash
docker build -t sgurr-web .
docker run --rm -p 8000:10000 sgurr-web
```

The container enables `SGURR_PUBLIC_DEMO`. It exposes v8.2 only, permits one
search at a time, caps engine and Search Network work, and disables continuous
self-play. Historical opponents and deeper Search Network choices remain
visible as local-only options. Normal local development is unchanged.

The root `render.yaml` defines a free Frankfurt Web Service using this image,
the `/ready` health check, and deployment after CI passes. Create a Blueprint
from the repository in Render; no environment variables are required.

## 6. Tests

The browser suite requires Node.js 18 or newer. It intercepts backend requests,
so it does not need a running engine:

```bat
cd /d "<repo>\web"
npm.cmd ci
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

Run backend tests from the repository root:

```bat
cd /d "<repo>"
conda activate sgurr-web
python -m unittest discover -s web\backend -p "test_*.py"
```

The browser suite covers the intro/menu handoff, both human sides, board
orientation, human/engine exchange, self-play, board editor entry, Inside
Sgurr's exact NNUE output, public-demo controls, and missing-engine behaviour. Backend tests cover draw rules,
production configuration, request limits, concurrency, and rate limiting. CI
also builds the Linux container and exercises the real engine and trace paths.

## Release And Licensing Records

The web asset set has recorded commercial-compatible terms. Preserve these
records with every release:

- [`../docs/THIRD_PARTY_ASSETS.md`](../docs/THIRD_PARTY_ASSETS.md): media provenance and
  the explicit list of excluded legacy sounds;
- [`../docs/THIRD_PARTY_NOTICES.md`](../docs/THIRD_PARTY_NOTICES.md): software licences
  and the `python-chess` distribution caveat;
- [`../docs/PROJECT_PROVENANCE.md`](../docs/PROJECT_PROVENANCE.md): engine, NNUE, and
  project ownership evidence plus the owner attestation;
- [`../LICENSE`](../LICENSE): terms for original Sgurr materials.

This documentation is release preparation, not legal advice. A hosted service
and a downloadable Python/backend bundle have different distribution
obligations.

## API Endpoints

```text
GET  /health
GET  /ready
GET  /api/capabilities
GET  /api/nnue/gen8/<verified-sha>.nnue
POST /api/new
POST /api/load-fen
POST /api/player-move
POST /api/premove-sequence
POST /api/engine-move
POST /api/search-trace
POST /api/search-network
```

The content-addressed NNUE route serves only the verified Gen8 network with an
immutable cache policy. Inside Sgurr checks the SHA-256 again in its worker
before parsing or evaluating it.

`/api/engine-move` sends UCI clock arguments when clock state is supplied and
falls back to `go movetime <milliseconds>` for fixed-search callers. It parses
`bestmove` plus the latest centipawn or mate score.

`/api/search-trace` accepts a legal FEN, an engine ID, and a bounded move time.
It starts an isolated engine process and streams one NDJSON object per completed
iterative-deepening pass, followed by the final move. It deliberately does not
reuse the persistent game process, so an open microscope cannot delay a game.

`/api/search-network` uses the separate `sgr_trace.exe` diagnostic build to
record bounded samples of real node activity across every iterative-deepening
pass up to a requested depth from 4 to
20. Build it with
`sgurr_cpp/build.sh -t`. The normal release binary contains no trace output or
trace overhead. The browser records at engine speed and then replays the node,
best-child, cutoff, pruning, quiescence, and transposition events at a chosen
cinematic speed or against the trace's real microsecond timestamps. In live
mode, small low-latency batches reach the radial viewer continuously from depth
1 to the selected horizon; sparse activity samples keep very deep iterations
visibly alive after each bounded structural-node sample is full.

## Included Experience

- legal click, drag, promotion, and multi-premove play;
- selectable human side and automatic orientation;
- Sgurr-vs-Sgurr watch mode;
- clocks, increments, flagging, and clock-based UCI search;
- board editor, FEN loading, drills, odds, undo/redo, and PGN export;
- themes, focus mode, opening recognition, blob memory/dialogue, music, and
  procedural interaction sounds;
- eval rail/trend, move list, material, captures, draw rules, and themed result
  sequences;
- a standalone Search Microscope with a real v8.2 walkthrough, an optional live
  completed-depth stream, and a glowing radial search web whose depth-from-root
  rings, timestamped traveling light, cutoffs, and transposition chords come
  from real engine events;
- an Inside Sgurr view that verifies and evaluates the shipped Gen8 network in
  a browser worker, then exposes both 384-lane accumulators as cortex, circuit,
  and move-delta views;
- responsive backend recovery without refreshing the browser.

Accounts, online multiplayer, cloud infrastructure, training dashboards,
transformer work, ONNX, and quantisation remain outside this web layer.

## Troubleshooting

If `/health` reports `"engine_exists": false`, build
`sgurr_cpp\sgr_v8_2.exe` or set `SGURR_ENGINE_EXE`.

If the browser reports a backend error, keep the backend terminal visible. The
frontend polls the backend periodically and should recover without a refresh.

If a production request returns `400 Invalid host header`, add the public
hostname to `SGURR_ALLOWED_HOSTS`. If a split frontend reports a CORS failure,
add its exact origin to `SGURR_ALLOWED_ORIGINS`; do not use `*`.

If engine search times out, lower the move time or increase the local padding:

```bat
set SGURR_TIMEOUT_PADDING=10
```
