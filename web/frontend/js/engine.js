import { clearPremoveQueueState, engineToMove, updateGameOverReveal } from "./board.js";
import { START_FEN, apiUrl } from "./config.js";
import { requestEngineMove, scheduleWatchMove, startGame } from "./game.js";
import { recordCompletedEncounter } from "./memory.js";
import { updateOpeningState } from "./openings.js";
import { setThinkingState } from "./personality.js";
import { recordReviewPly } from "./review.js";
import { app, refs } from "./state.js";
import { closeAllModals } from "./themes.js";
import { addEvalHistoryPoint, render, renderBackend, renderMenu } from "./ui.js";

async function apiGet(path) {
  const response = await fetch(apiUrl(path));
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || response.statusText);
  }
  return data;
}

async function apiPost(path, body) {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || response.statusText);
  }
  return data;
}

function applyServerState(data, { keepEval = false } = {}) {
  // Whether this payload carried its own evaluation, as opposed to inheriting
  // the previous one via keepEval. js/review.js needs the distinction.
  const freshEval = Boolean(data.latest_eval);
  const wasGameOver = app.gameOver;
  const previousEval = app.latestEval;
  app.fen = data.fen;
  app.startFen = data.start_fen || app.startFen || START_FEN;
  app.turn = data.turn;
  app.legalMoves = data.legal_moves || [];
  app.premoveMoves = data.premove_moves || [];
  app.basePremoveMoves = [...app.premoveMoves];
  app.moves = data.moves || [];
  app.moveRows = data.move_rows || [];
  app.lastMoveInfo = data.last_move ? { ...data.last_move } : app.lastMoveInfo;
  app.lastMove = data.last_move?.uci || app.lastMove;
  app.latestEval = keepEval && !data.latest_eval ? previousEval : data.latest_eval;
  if (data.latest_eval) {
    addEvalHistoryPoint(data.latest_eval, app.moves.length);
  }
  app.material = data.material;
  app.canMate = data.can_mate || { white: true, black: true };
  app.gameOver = Boolean(data.game_over);
  if (!app.gameOver || !wasGameOver) {
    app.resultSoundPlayed = false;
  }
  app.result = data.result;
  app.winner = data.winner;
  app.reason = data.reason;
  app.inCheck = Boolean(data.in_check);
  app.error = "";
  updateOpeningState();
  recordReviewPly({ freshEval });
  if (app.gameOver && !wasGameOver) {
    recordCompletedEncounter();
  }
  updateGameOverReveal(wasGameOver);
}

function setBusy(value, thinking = false) {
  app.busy = value;
  setThinkingState(thinking);
  render();
}

function setError(error) {
  const message = error.message || String(error);
  app.error = message;
  app.status = message;
  app.busy = false;
  clearPremoveQueueState();
  setThinkingState(false, { cool: false });
  app.coreMessage = "Signal interrupted";
  app.coreLineMode = "system";
  render();
}

function selectedEngineId() {
  return app.engines[app.selectedEngineIndex]?.id ?? null;
}

function applyEngineSelection() {
  const list = app.engines;
  if (!list.length) return;
  app.selectedEngineIndex = ((app.selectedEngineIndex % list.length) + list.length) % list.length;
  const sel = list[app.selectedEngineIndex];
  app.engineLabel = sel.label;
  app.engineSubtitle = sel.subtitle || "";
  localStorage.setItem("sgurrEngineIndex", String(app.selectedEngineIndex));
}

function engineChoiceMessage(sel) {
  return `Opponent: ${sel.label}`
    + (sel.available === false ? " — binary missing, build it first!" : "");
}

// Pick an opponent outright rather than stepping to it. The gallery hands back
// an index into app.engines (not the displayed order, which is sorted by
// rating), so selection stays correct however the list is presented.
function setEngineIndex(index) {
  if (!app.engines.length) {
    return;
  }
  app.selectedEngineIndex = index;
  applyEngineSelection();
  app.menuMessage = engineChoiceMessage(app.engines[app.selectedEngineIndex]);
  renderEngineGallery();
  render();
}

// The opponent ladder. Sorted by rating so the progression from the
// hand-crafted eval up to the current release reads at a glance, with each
// card's bar scaled across the span of the field.
function renderEngineGallery() {
  const gallery = refs.engineGallery;
  if (!gallery) {
    return;
  }
  gallery.innerHTML = "";

  if (!app.engines.length) {
    const empty = document.createElement("p");
    empty.className = "engine-empty";
    empty.textContent = "Engine list unavailable — is the backend running?";
    gallery.appendChild(empty);
    return;
  }

  const ordered = app.engines
    .map((engine, index) => ({ engine, index }))
    .sort((a, b) => (b.engine.rating ?? 0) - (a.engine.rating ?? 0));
  const ratings = ordered.map((entry) => entry.engine.rating).filter(Number.isFinite);
  const strongest = ratings.length ? Math.max(...ratings) : 0;
  const weakest = ratings.length ? Math.min(...ratings) : 0;
  const span = strongest - weakest;

  for (const { engine, index } of ordered) {
    const button = document.createElement("button");
    button.type = "button";
    const selected = index === app.selectedEngineIndex;
    button.className = `engine-card${selected ? " active" : ""}`
      + (engine.available === false ? " unavailable" : "");
    button.setAttribute("aria-pressed", String(selected));

    const head = document.createElement("div");
    head.className = "engine-card-head";
    const name = document.createElement("strong");
    name.textContent = engine.label;
    head.appendChild(name);
    if (engine.rating === strongest && ratings.length) {
      const badge = document.createElement("span");
      badge.className = "engine-badge";
      badge.textContent = "STRONGEST";
      head.appendChild(badge);
    }
    if (engine.available === false) {
      const badge = document.createElement("span");
      badge.className = "engine-badge missing";
      badge.textContent = "NOT BUILT";
      head.appendChild(badge);
    }

    const tech = document.createElement("small");
    tech.className = "engine-card-tech";
    tech.textContent = engine.tech || engine.subtitle || "";

    const meter = document.createElement("div");
    meter.className = "engine-meter";
    const rating = document.createElement("span");
    rating.className = "engine-rating-value";
    rating.textContent = Number.isFinite(engine.rating) ? `~${engine.rating}` : "—";
    const track = document.createElement("span");
    track.className = "engine-meter-track";
    const fill = document.createElement("span");
    fill.className = "engine-meter-fill";
    // Floor the bar at 12% so the weakest entry still reads as a bar rather
    // than an empty track.
    const ratio = span > 0 && Number.isFinite(engine.rating)
      ? (engine.rating - weakest) / span
      : 1;
    fill.style.width = `${(12 + ratio * 88).toFixed(1)}%`;
    track.appendChild(fill);
    meter.append(rating, track);

    button.append(head, tech, meter);
    button.addEventListener("click", () => {
      setEngineIndex(index);
      closeAllModals();
    });
    gallery.appendChild(button);
  }
}

function cycleEngine(direction) {
  if (app.engines.length > 1) {
    app.selectedEngineIndex += direction;
    applyEngineSelection();
    app.menuMessage = engineChoiceMessage(app.engines[app.selectedEngineIndex]);
    renderEngineGallery();
  } else {
    app.menuMessage = app.engines.length === 1
      ? `Only one engine available: ${app.engines[0].label}`
      : "Engine list unavailable (is the backend running?)";
  }
  render();
}

async function fetchEngines() {
  try {
    const data = await apiGet("/api/engines");
    if (Array.isArray(data.engines) && data.engines.length) {
      app.engines = data.engines;
      applyEngineSelection();
      renderEngineGallery();
      render();
    }
  } catch {
    // keep the built-in fallback label if the list can't be fetched
  }
}

async function refreshHealth() {
  const previousBackendOk = app.backendOk;
  const previousEngineExists = app.engineExists;
  const previousError = app.error;
  try {
    const health = await apiGet("/health");
    app.backendOk = Boolean(health.ok);
    app.engineExists = Boolean(health.engine_exists);
    app.backendDetail = app.engineExists ? "engine found" : "build sgr_v6_0.exe";
    if (app.error === "Backend unavailable" || /fetch/i.test(app.error)) {
      app.error = "";
      app.status = app.mode === "menu" ? "Choose a side" : "Backend reconnected";
      app.coreMessage = app.mode === "menu" ? "Opponent core online" : "Backend reconnected";
    }
    const healthChanged = previousBackendOk !== app.backendOk
      || previousEngineExists !== app.engineExists
      || previousError !== app.error;
    if (healthChanged) {
      render();
    } else {
      renderMenu();
      renderBackend();
    }

    if (app.pendingStartSide !== undefined && app.backendOk && app.engineExists) {
      const side = app.pendingStartSide;
      app.pendingStartSide = undefined;
      await startGame(side);
    } else if (engineToMove() && app.humanSide !== null) {
      await requestEngineMove();
    } else if (engineToMove() && app.humanSide === null && !app.watchPaused) {
      scheduleWatchMove();
    }

    return true;
  } catch {
    app.backendOk = false;
    app.engineExists = false;
    app.backendDetail = "unavailable";
    if (app.mode === "game") {
      app.error = "Backend unavailable";
      app.status = "Backend unavailable";
    }
    render();
    return false;
  }
}

export {
  apiGet,
  apiPost,
  applyServerState,
  setBusy,
  setError,
  selectedEngineId,
  applyEngineSelection,
  cycleEngine,
  setEngineIndex,
  renderEngineGallery,
  fetchEngines,
  refreshHealth,
};
