# Sgurr Web

Sgurr Web is a browser chess experience backed by the Sgurr UCI engine
(v6.0 by default, with earlier releases selectable). FastAPI validates chess
state, owns the engine process, serves the
production frontend and allowlisted media, and exposes a small JSON API. The
same frontend can also run from VS Code Live Server during development.

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
    styles.css             @import manifest; ordering IS the cascade
    styles/                12 CSS partials (base, intro, menu, board, core, …)
    js/                    17 native ES modules; main.js is the entry point
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
`clocks`, `themes`, …) import from those. `styles.css` is an `@import`
manifest whose partial order defines the cascade — keep it stable when adding
sections, and note that relative `url()`s inside `styles/*.css` need a `../`
hop to reach `assets/`.

The browser owns the current FEN and move list. The backend validates moves
with `python-chess`, asks Sgurr for engine moves over UCI, parses
`info ... score ...` lines, and returns updated state. The browser uses
commercially permissive Chessnut pieces, procedural game/UI cues, and an
allowlist of documented music and result sounds.

## 1. Build The Sgurr Engine

Use the MSYS2 `clang64` shell on Windows:

```bash
cd "/c/Coding/Sgurr/sgurr_cpp"
/c/msys64/clang64/bin/clang++ -std=c++20 -O3 -march=native -DNDEBUG -static \
  -Wall -Wextra main.cpp board.cpp evaluation.cpp search.cpp nnue.cpp \
  -o sgr_v6_0.exe
```

Quick UCI check:

```bash
./sgr_v6_0.exe uci
```

Then enter `uci`, `isready`, `position startpos`, `go movetime 500`, and
`quit`. You should see `uciok`, `readyok`, an `info ... score ...` line, and a
`bestmove`.

## 2. Install Backend Dependencies

From Anaconda Prompt:

```bat
cd /d "C:\Coding\Sgurr"
conda create -n sgurr-web python=3.11 -y
conda activate sgurr-web
python -m pip install --upgrade pip
python -m pip install -r web\backend\requirements.txt
```

For a reproducible release build, install the audited exact versions instead:

```bat
python -m pip install -r web\backend\requirements.lock.txt
```

The default engine path is `sgurr_cpp\sgr_v6_0.exe`. Override it before
starting Uvicorn when necessary:

```bat
set SGURR_ENGINE_EXE=C:\path\to\sgr_v6_0.exe
set SGR_EVALFILE=C:\path\to\gen5.nnue
```

## 3. Start Sgurr Web

From the repository root, with the Conda environment active:

```bat
cd /d "C:\Coding\Sgurr"
conda activate sgurr-web
python -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8000
```

Open the complete site at <http://127.0.0.1:8000>. The health endpoint is
<http://127.0.0.1:8000/health>. This one-process, same-origin setup is the
recommended production shape and does not require CORS.

## 4. Optional Split Frontend Development

VS Code Live Server is supported. Alternatively, open a second prompt:

```bat
cd /d "C:\Coding\Sgurr\web\frontend"
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

Sgurr owns one persistent UCI process, so use one Uvicorn worker per engine
instance. If the frontend and API are genuinely on different origins, list the
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

Before exposing the service publicly, also configure HTTPS, process
supervision, request logging, backups of release records, and infrastructure
rate limiting for the engine endpoint.

## 6. Tests

The browser suite requires Node.js 18 or newer. It intercepts backend requests,
so it does not need a running engine:

```bat
cd /d "C:\Coding\Sgurr\web"
npm.cmd ci
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

Run backend tests from the repository root:

```bat
cd /d "C:\Coding\Sgurr"
conda activate sgurr-web
python -m unittest discover -s web\backend -p "test_*.py"
```

The browser suite covers the intro/menu handoff, both human sides, board
orientation, human/engine exchange, self-play, board editor entry, and
missing-engine behaviour. Backend tests cover draw rules and production
configuration boundaries.

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
POST /api/new
POST /api/load-fen
POST /api/player-move
POST /api/premove-sequence
POST /api/engine-move
```

`/api/engine-move` sends UCI clock arguments when clock state is supplied and
falls back to `go movetime <milliseconds>` for fixed-search callers. It parses
`bestmove` plus the latest centipawn or mate score.

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
- responsive backend recovery without refreshing the browser.

Accounts, online multiplayer, cloud infrastructure, training dashboards,
transformer work, ONNX, and quantisation remain outside this web layer.

## Troubleshooting

If `/health` reports `"engine_exists": false`, build
`sgurr_cpp\sgr_v6_0.exe` or set `SGURR_ENGINE_EXE`.

If the browser reports a backend error, keep the backend terminal visible. The
frontend polls the backend periodically and should recover without a refresh.

If a production request returns `400 Invalid host header`, add the public
hostname to `SGURR_ALLOWED_HOSTS`. If a split frontend reports a CORS failure,
add its exact origin to `SGURR_ALLOWED_ORIGINS`; do not use `*`.

If engine search times out, lower the move time or increase the local padding:

```bat
set SGURR_TIMEOUT_PADDING=10
```
