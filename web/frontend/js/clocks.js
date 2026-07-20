import { playSound } from "./audio.js";
import { clearPremoveQueueState, updateGameOverReveal } from "./board.js";
import { TIME_CONTROLS } from "./config.js";
import { recordCompletedEncounter } from "./memory.js";
import { updateOpeningState } from "./openings.js";
import { setThinkingState } from "./personality.js";
import { app } from "./state.js";
import { title } from "./utils.js";

function currentTimeControl() {
  app.timeIndex = (app.timeIndex + TIME_CONTROLS.length) % TIME_CONTROLS.length;
  return TIME_CONTROLS[app.timeIndex];
}

function playerName(colour) {
  if (app.humanSide === null) {
    return colour === "white" ? "Sgurr White" : "Sgurr Black";
  }
  return app.humanSide === colour ? "Human" : "Sgurr";
}

function colourIsEngine(colour) {
  return app.mode === "game" && (app.humanSide === null || app.humanSide !== colour);
}

function playerCardMarkup(colour) {
  if (app.humanSide === null) {
    return `<strong>Sgurr ${title(colour)}</strong><small>ENGINE SIDE</small>`;
  }

  if (app.humanSide === colour) {
    return "<strong>You</strong><small>LOCAL PLAYER</small>";
  }

  const engineLabel = app.engineLabel || 'Sgurr v6.0 "Banachdaich"';
  const engineSubtitle = app.engineSubtitle || "GEN5 NNUE + REFINED SEARCH · ~2807";
  return `<strong>${engineLabel}</strong><small>${engineSubtitle} &middot; ${colour.toUpperCase()}</small>`;
}

function visibleClock(colour) {
  return app.clocks[colour] ?? currentTimeControl().baseSeconds;
}

function activeClockColour() {
  if (app.mode !== "game" || app.gameOver || app.watchPaused) {
    return null;
  }
  return app.turn;
}

function clockIsRunning() {
  return app.mode === "game" && !app.gameOver && !app.watchPaused && app.clockFlagged === null;
}

function resetClocks() {
  const control = currentTimeControl();
  app.clocks = {
    white: control.baseSeconds,
    black: control.baseSeconds,
  };
  app.clockFlagged = null;
  app.clockCueSecond = null;
  app.clockLastTick = performance.now();
}

function applyIncrement(colour) {
  const control = currentTimeControl();
  app.clocks[colour] = Math.max(0, app.clocks[colour]) + control.incrementSeconds;
  if (colour === app.humanSide && app.clocks[colour] > 10) {
    app.clockCueSecond = null;
  }
}

function playClockWarning(colour) {
  if (app.humanSide !== colour) {
    return;
  }
  const remaining = app.clocks[colour];
  if (remaining > 10 || remaining <= 0) {
    if (remaining > 10) {
      app.clockCueSecond = null;
    }
    return;
  }
  const second = Math.ceil(remaining);
  if (second === app.clockCueSecond) {
    return;
  }
  app.clockCueSecond = second;
  playSound("clock_warning", {
    volume: second <= 3 ? 0.62 : 0.34,
    rate: second <= 3 ? 1.15 : 1,
  });
}

function flagOnTime(colour) {
  const wasGameOver = app.gameOver;
  const opponent = colour === "white" ? "black" : "white";
  const opponentCanMate = app.canMate[opponent] !== false;
  app.clocks[colour] = 0;
  app.clockFlagged = colour;
  app.resultSoundPlayed = false;
  clearPremoveQueueState();
  app.gameOver = true;
  app.winner = opponentCanMate ? opponent : null;
  app.result = opponentCanMate ? (colour === "white" ? "0-1" : "1-0") : "1/2-1/2";
  app.reason = opponentCanMate ? "time_forfeit" : "timeout_insufficient_material";
  app.status = opponentCanMate
    ? `${title(colour)} loses on time`
    : `Draw: ${title(colour)} ran out of time, but checkmate is impossible`;
  app.error = "";
  app.busy = false;
  setThinkingState(false, { cool: false });
  app.searchToken += 1;
  clearTimeout(app.watchTimer);
  playSound("clock_flag", { volume: 0.78 });
  updateOpeningState();
  recordCompletedEncounter();
  updateGameOverReveal(wasGameOver);
}

function syncClock() {
  if (!clockIsRunning()) {
    app.clockLastTick = performance.now();
    return;
  }

  const now = performance.now();
  if (app.clockLastTick === null) {
    app.clockLastTick = now;
    return;
  }

  const elapsed = (now - app.clockLastTick) / 1000;
  app.clockLastTick = now;

  const colour = activeClockColour();
  if (!colour) {
    return;
  }

  app.clocks[colour] = Math.max(0, app.clocks[colour] - elapsed);
  playClockWarning(colour);
  if (app.clocks[colour] <= 0) {
    flagOnTime(colour);
  }
}

export {
  currentTimeControl,
  playerName,
  colourIsEngine,
  playerCardMarkup,
  visibleClock,
  activeClockColour,
  clockIsRunning,
  resetClocks,
  applyIncrement,
  playClockWarning,
  flagOnTime,
  syncClock,
};
