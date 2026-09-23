import { TIME_CONTROLS } from "./config.js";
import { makeSnapshot } from "./history.js";
import { app } from "./state.js";

const KEY = "sgurrSavedGame";
let cached;
window.addEventListener("storage", (event) => { if (event.key === KEY || event.key === null) cached = undefined; });

function validSnapshot(value) {
  return value && typeof value.fen === "string" && value.fen.length <= 128
    && typeof value.startFen === "string" && value.startFen.length <= 128
    && ["white", "black"].includes(value.turn)
    && ["legalMoves", "premoveMoves", "moves", "moveRows", "evalHistory"].every((key) => Array.isArray(value[key]))
    && value.moves.length <= 512 && value.moves.every((move) => /^[a-h][1-8][a-h][1-8][qrbn]?$/.test(move))
    && value.moveRows.every((row) => row && Number.isInteger(row.number) && typeof row.white === "string" && typeof row.black === "string")
    && ["white", "black"].every((side) => Number.isFinite(value.clocks?.[side]) && value.clocks[side] >= 0);
}

function readSavedGame() {
  if (cached !== undefined) return cached;
  cached = null;
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw || raw.length > 8_000_000) return null;
    const value = JSON.parse(raw);
    if (value?.version !== 1 || !validSnapshot(value.snapshot) || value.snapshot.gameOver !== false || value.snapshot.clockFlagged !== null
      || !["white", "black", null].includes(value.side)
      || typeof value.engineId !== "string"
      || !TIME_CONTROLS.some((control) => control.key === value.timeKey)) return null;
    value.history = Array.isArray(value.history) ? value.history.filter(validSnapshot) : [];
    value.redo = Array.isArray(value.redo) ? value.redo.filter(validSnapshot) : [];
    cached = value;
  } catch { /* A damaged or inaccessible save must not prevent starting a game. */ }
  return cached;
}

function clearSavedGame() {
  cached = null;
  try { localStorage.removeItem(KEY); } catch { /* Storage can be unavailable. */ }
}

function saveCurrentGame() {
  // Do not overwrite a game with an editor position or an incomplete new-game request.
  if (app.mode !== "game" || !app.history.length || app.restoringGame) return;
  if (app.gameOver) { clearSavedGame(); return; }
  if (app.review.active) return;
  cached = {
    version: 1, snapshot: makeSnapshot(), side: app.humanSide,
    engineId: app.engines[app.selectedEngineIndex]?.id || "v9.1",
    timeKey: TIME_CONTROLS[app.timeIndex].key,
    history: app.history, redo: app.redoStack, review: app.review.plies,
    manualFlip: app.manualFlip, origin: app.gameOrigin,
    watchPaused: app.watchPaused, engineAutoPaused: app.engineAutoPaused,
  };
  try { localStorage.setItem(KEY, JSON.stringify(cached)); }
  catch { /* Keep the in-memory save if browser storage is full or disabled. */ }
}

export { readSavedGame, saveCurrentGame, clearSavedGame };
