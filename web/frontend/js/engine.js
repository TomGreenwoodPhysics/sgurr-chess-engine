import { clearPremoveQueueState, engineToMove, updateGameOverReveal } from "./board.js";
import { START_FEN, apiUrl } from "./config.js";
import { requestEngineMove, scheduleWatchMove, startGame } from "./game.js";
import { recordCompletedEncounter } from "./memory.js";
import { updateOpeningState } from "./openings.js";
import { setThinkingState } from "./personality.js";
import { app } from "./state.js";
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

function cycleEngine(direction) {
  if (app.engines.length > 1) {
    app.selectedEngineIndex += direction;
    applyEngineSelection();
    const sel = app.engines[app.selectedEngineIndex];
    app.menuMessage = `Opponent: ${sel.label}`
      + (sel.available === false ? " — binary missing, build it first!" : "");
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
  fetchEngines,
  refreshHealth,
};
