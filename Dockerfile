# syntax=docker/dockerfile:1

FROM debian:bookworm-slim AS engine-build

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY sgurr_cpp/build_linux.sh sgurr_cpp/main.cpp sgurr_cpp/board.cpp \
    sgurr_cpp/board.hpp sgurr_cpp/evaluation.cpp sgurr_cpp/evaluation.hpp \
    sgurr_cpp/search.cpp sgurr_cpp/search.hpp sgurr_cpp/nnue.cpp \
    sgurr_cpp/nnue.hpp sgurr_cpp/move.hpp sgurr_cpp/
COPY nets/gen8.nnue nets/gen8.nnue

RUN echo "896eb832d74776a42375e7fa152b4e032fff1cf85ba2e529b420fe2d1b4b74bf  nets/gen8.nnue" \
        | sha256sum --check --strict \
    && bash sgurr_cpp/build_linux.sh /out \
    && output="$(printf 'uci\nisready\nposition startpos\ngo depth 2\nquit\n' \
        | SGR_EVALFILE=/src/nets/gen8.nnue timeout 20s /out/sgr_v8_2 2>&1)" \
    && printf '%s\n' "$output" | grep -q 'info string nnue: loaded' \
    && printf '%s\n' "$output" | grep -q '^uciok$' \
    && printf '%s\n' "$output" | grep -q '^readyok$' \
    && printf '%s\n' "$output" | grep -q '^bestmove ' \
    && trace="$(printf 'uci\nisready\nposition startpos\ngo depth 2\nquit\n' \
        | SGR_EVALFILE=/src/nets/gen8.nnue timeout 20s /out/sgr_trace 2>&1)" \
    && printf '%s\n' "$trace" | grep -q 'info string nnue: loaded' \
    && printf '%s\n' "$trace" | grep -q 'info string trace {"e":"start"' \
    && printf '%s\n' "$trace" | grep -q '^bestmove '

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SGURR_ENGINE_EXE=/app/sgurr_cpp/sgr_v8_2 \
    SGURR_TRACE_ENGINE_EXE=/app/sgurr_cpp/sgr_trace \
    SGURR_ALLOWED_ORIGINS=none \
    SGURR_PUBLIC_DEMO=1 \
    SGURR_NETWORK_TIMEOUT_SECONDS=30 \
    SGURR_TRACE_MAX_CONCURRENT=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system sgurr \
    && useradd --system --gid sgurr --home-dir /app sgurr

WORKDIR /app
COPY web/backend/requirements.lock.txt web/backend/requirements.lock.txt
RUN python -m pip install --no-cache-dir -r web/backend/requirements.lock.txt

COPY web/backend/ web/backend/
COPY web/frontend/ web/frontend/
COPY web/licenses/ web/licenses/
COPY nets/gen8.nnue nets/gen8.nnue
COPY --from=engine-build /out/sgr_v8_2 sgurr_cpp/sgr_v8_2
COPY --from=engine-build /out/sgr_trace sgurr_cpp/sgr_trace
COPY assets/music/menu-theme.ogg assets/music/game-pulse.mp3 assets/music/game-urgent.mp3 assets/music/
COPY assets/sounds/clock-flag.ogg assets/sounds/clock-warning.ogg \
    assets/sounds/result-draw-neutral.ogg assets/sounds/result-draw.ogg \
    assets/sounds/result-human-explosion.ogg assets/sounds/result-human-splat.ogg \
    assets/sounds/result-human-victory.ogg assets/sounds/result-sgurr-alien.ogg \
    assets/sounds/result-sgurr-burble.ogg assets/sounds/result-sgurr-energy.ogg \
    assets/sounds/
COPY LICENSE LICENSE
COPY docs/THIRD_PARTY_NOTICES.md docs/THIRD_PARTY_NOTICES.md

USER sgurr

EXPOSE 10000
CMD ["sh", "-c", "exec python -m uvicorn web.backend.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
