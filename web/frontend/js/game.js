import { playMoveSound, playSound } from "./audio.js";
import { animationPieceForMove, boardInteractionAvailable, canQueuePremove, cleanupDrag, clearGameOverRevealTimer, clearMoveAnimations, clearPremoveQueueState, engineToMove, engineTurnAvailable, hasPremoves, hidePromotion, humanCanMove, humanMoveAnimationDurationMs, legalFrom, moveAnimationDurationMs, preparePendingMoveAnimation, projectPremovePieces, queueMoveAnimation, showPromotion, startActiveMoveAnimation, triggerCaptureAbsorb } from "./board.js";
import { applyIncrement, currentTimeControl, resetClocks, syncClock } from "./clocks.js";
import { START_FEN } from "./config.js";
import { handleEditorSquare } from "./editor.js";
import { apiPost, applyServerState, selectedEngineId, setBusy, setError } from "./engine.js";
import { applySnapshot, recordSnapshot } from "./history.js";
import { blobMemoryGreeting } from "./memory.js";
import { coreMoveLine, setThinkingState } from "./personality.js";
import { resetReview } from "./review.js";
import { app, refs } from "./state.js";
import { closeAllModals, openModal } from "./themes.js";
import { render, setStatus } from "./ui.js";
import { parseFenPieces, pieceColor, title } from "./utils.js";

function cancelLiveGameWork() {
  clearTimeout(app.watchTimer);
  app.searchToken += 1;
  app.busy = false;
  setThinkingState(false, { cool: false });
  app.gameOverRevealAt = null;
  clearGameOverRevealTimer();
  app.engineAutoPaused = false;
  clearPremoveQueueState();
  clearMoveAnimations();
  cleanupDrag();
}

function returnToMainMenu() {
  syncClock();
  cancelLiveGameWork();
  app.mode = "menu";
  app.focusMode = false;
  app.clockLastTick = null;
  app.selected = null;
  app.error = "";
  render();
}

function resetLocalGame(side) {
  app.fen = START_FEN;
  app.startFen = START_FEN;
  app.turn = "white";
  app.legalMoves = [];
  app.premoveMoves = [];
  app.basePremoveMoves = [];
  clearPremoveQueueState();
  app.moves = [];
  app.moveRows = [];
  app.lastMove = null;
  app.lastMoveInfo = null;
  app.latestEval = null;
  app.evalHistory = [{ ply: 0, cp: 0, display: "0.0" }];
  app.material = null;
  app.canMate = { white: true, black: true };
  app.gameOver = false;
  app.result = null;
  app.winner = null;
  app.reason = null;
  app.inCheck = false;
  app.gameOverRevealAt = null;
  clearGameOverRevealTimer();
  app.selected = null;
  app.watchPaused = false;
  app.manualFlip = false;
  app.engineAutoPaused = false;
  resetClocks();
  app.history = [];
  app.redoStack = [];
  app.status = "Game started";
  app.coreMessage = blobMemoryGreeting(side);
  app.coreLineMode = app.memory.games && side !== null ? "memory" : "system";
  app.coreDialogueLastPly = -99;
  app.coreDialogueLastKey = "";
  app.coreThinkingIndex = 0;
  app.currentOpening = null;
  app.openingAnnouncedKey = "";
  app.openingAnnouncedDepth = 0;
  app.memoryRecorded = false;
  resetReview();
  app.focusMode = false;
  app.humanSide = side;
  app.pendingAnimation = null;
  app.activeAnimation = null;
  app.resultSoundPlayed = false;
  cleanupDrag();
}

async function startGame(side) {
  clearTimeout(app.watchTimer);
  app.pendingStartSide = undefined;
  refs.movetimeSelect.value = currentTimeControl().key;
  resetLocalGame(side);
  app.mode = "game";
  app.menuMessage = "";
  setBusy(true, false);

  try {
    const data = await apiPost("/api/new", { human_side: side || "white" });
    applyServerState(data);
    recordSnapshot();
    app.status = side === null ? "Watching Sgurr vs itself" : `You are ${title(side)}`;
    playSound("game_start");
    setBusy(false, false);
    render();
    if (engineToMove()) {
      side === null ? scheduleWatchMove(150) : await requestEngineMove();
    }
  } catch (error) {
    app.mode = "menu";
    app.pendingStartSide = side;
    app.menuMessage = "Waiting for backend";
    setError(error);
  }
}

async function startFromFen(fen, side, statusMessage = "Loaded FEN") {
  clearTimeout(app.watchTimer);
  setBusy(true, false);

  try {
    const data = await apiPost("/api/load-fen", { fen });
    resetLocalGame(side);
    app.mode = "game";
    applyServerState(data);
    recordSnapshot();
    app.status = statusMessage;
    playSound("game_start");
    setBusy(false, false);
    render();
    if (engineToMove()) {
      side === null ? scheduleWatchMove(150) : await requestEngineMove();
    }
  } catch (error) {
    setBusy(false, false);
    throw error;
  }
}

async function rematchGame() {
  const side = app.humanSide;
  const startFen = app.startFen || START_FEN;
  if (startFen === START_FEN) {
    await startGame(side);
    return;
  }

  try {
    await startFromFen(startFen, side, "Rematch from custom position");
  } catch (error) {
    setError(error);
  }
}

function openFenModal() {
  refs.fenInput.value = app.fen === START_FEN ? "" : app.fen;
  refs.fenSideSelect.value = app.humanSide === null ? "watch" : app.humanSide || "white";
  refs.fenError.textContent = "";
  openModal(refs.fenModal);
  refs.fenInput.focus();
}

async function loadFenFromModal() {
  const fen = refs.fenInput.value.trim();
  if (!fen) {
    refs.fenError.textContent = "Enter a FEN first.";
    return;
  }

  const sideValue = refs.fenSideSelect.value;
  const side = sideValue === "watch" ? null : sideValue;
  clearTimeout(app.watchTimer);
  setBusy(true, false);

  try {
    closeAllModals();
    await startFromFen(fen, side, "Loaded FEN");
  } catch (error) {
    setBusy(false, false);
    refs.fenError.textContent = error.message || String(error);
    openModal(refs.fenModal);
  }
}

async function makePlayerMove(
  uci,
  { animate = true, projectedPremoves = null, playAudio = true } = {},
) {
  const token = (app.searchToken += 1);
  const movingSide = app.turn;
  const previousPieces = parseFenPieces(app.fen);
  syncClock();
  if (app.gameOver) {
    render();
    return;
  }

  app.selected = null;
  if (projectedPremoves) {
    app.premoves = projectedPremoves.map((premove) => ({ ...premove }));
  }
  hidePromotion();
  setBusy(true, false);

  try {
    const data = await apiPost("/api/player-move", {
      fen: app.fen,
      start_fen: app.startFen,
      moves: app.moves,
      move: uci,
    });
    const movingPiece = animationPieceForMove(
      data.last_move?.uci,
      previousPieces,
      parseFenPieces(data.fen),
    );
    if (token !== app.searchToken || app.mode !== "game") {
      setBusy(false, false);
      render();
      return;
    }
    applyServerState(data, { keepEval: true });
    app.premoves = projectedPremoves
      ? projectedPremoves.slice(1).map((premove) => ({ ...premove }))
      : [];
    app.coreMessage = coreMoveLine(data.last_move, { byHuman: true });
    queueMoveAnimation(data.last_move?.uci, movingPiece, {
      animate,
      duration: humanMoveAnimationDurationMs(),
      easing: "cubic-bezier(0.18, 0.86, 0.24, 1)",
    });
    preparePendingMoveAnimation();
    applyIncrement(movingSide);
    app.clockLastTick = performance.now();
    app.engineAutoPaused = false;
    recordSnapshot();
    app.status = "Move played";
    if (playAudio || app.gameOver) {
      playMoveSound(data.last_move, { byHuman: true });
    }
    triggerCaptureAbsorb(data.last_move, previousPieces, { byHuman: true });
    app.busy = false;
    setThinkingState(false, { cool: false });
    if (hasPremoves()) {
      await refreshPremoveProjection({ cancelOnFailure: true });
    }
    render();
    startActiveMoveAnimation();
    if (!app.gameOver) {
      await requestEngineMove();
    } else {
      render();
    }
  } catch (error) {
    clearPremoveQueueState();
    if (token !== app.searchToken || app.mode !== "game") {
      return;
    }
    setError(error);
  }
}

function engineClockPayload() {
  const control = currentTimeControl();
  return {
    wtime_ms: Math.max(1, Math.round(app.clocks.white * 1000)),
    btime_ms: Math.max(1, Math.round(app.clocks.black * 1000)),
    winc_ms: Math.round(control.incrementSeconds * 1000),
    binc_ms: Math.round(control.incrementSeconds * 1000),
    movestogo: control.key === "classical_90_30" ? 240 : 120,
  };
}

async function requestEngineMove(force = false) {
  if (force) {
    app.engineAutoPaused = false;
  }
  if (!(force ? engineTurnAvailable() : engineToMove())) {
    render();
    return;
  }

  clearTimeout(app.watchTimer);
  const movingSide = app.turn;
  const previousPieces = parseFenPieces(app.fen);
  syncClock();
  if (app.gameOver) {
    render();
    return;
  }

  const token = (app.searchToken += 1);
  setBusy(true, true);
  try {
    const data = await apiPost("/api/engine-move", {
      fen: app.fen,
      start_fen: app.startFen,
      moves: app.moves,
      engine: selectedEngineId(),
      ...engineClockPayload(),
    });
    syncClock();
    if (token !== app.searchToken || app.mode !== "game" || app.gameOver) {
      setBusy(false, false);
      render();
      return;
    }
    hidePromotion();
    const enginePiece = animationPieceForMove(
      data.last_move?.uci,
      previousPieces,
      parseFenPieces(data.fen),
    );
    const queuedPremoves = app.premoves.map((premove) => ({ ...premove }));
    const queuedPremove = queuedPremoves[0] || null;
    app.premoveRequestToken += 1;
    applyServerState(data);
    const premoveLegal = Boolean(
      queuedPremove &&
      !app.gameOver &&
      app.humanSide !== null &&
      app.turn === app.humanSide &&
      app.legalMoves.includes(queuedPremove.uci),
    );
    app.premoves = premoveLegal ? queuedPremoves : [];
    queueMoveAnimation(data.last_move?.uci, enginePiece, { animate: true });
    preparePendingMoveAnimation();
    applyIncrement(movingSide);
    app.clockLastTick = performance.now();
    app.engineAutoPaused = false;
    recordSnapshot();
    const searchInfo = data.latest_eval;
    if (searchInfo?.nodes && searchInfo?.time_ms) {
      app.lastSearchStats = {
        nps: (searchInfo.nodes / Math.max(searchInfo.time_ms, 1)) * 1000,
        depth: searchInfo.depth ?? null,
        timeMs: searchInfo.time_ms,
      };
    }
    app.coreMessage = coreMoveLine(data.last_move, { byHuman: false });
    app.status = app.gameOver
      ? app.result || "Game over"
      : premoveLegal
        ? `Executing premove: ${queuedPremove.uci}`
        : queuedPremove
          ? "Premove sequence cancelled: position changed"
      : app.humanSide === null
        ? "Watching Sgurr vs itself"
        : "Your move";
    playMoveSound(data.last_move, { byHuman: false });
    triggerCaptureAbsorb(data.last_move, previousPieces, { byHuman: false });
    app.busy = false;
    setThinkingState(false);
    render();
    startActiveMoveAnimation();
    if (premoveLegal) {
      const delay = app.animationMode === "Off" ? 0 : moveAnimationDurationMs() + 100;
      if (delay > 0) {
        await new Promise((resolve) => window.setTimeout(resolve, delay));
      }
      if (
        token === app.searchToken &&
        app.mode === "game" &&
        !app.gameOver &&
        app.turn === app.humanSide &&
        app.premoves[0]?.uci === queuedPremove.uci &&
        app.legalMoves.includes(queuedPremove.uci)
      ) {
        await makePlayerMove(queuedPremove.uci, {
          animate: false,
          projectedPremoves: queuedPremoves,
          playAudio: false,
        });
      }
      return;
    }
    if (queuedPremove && !app.gameOver) {
      playSound("illegal");
    }
    if (app.humanSide === null && !app.watchPaused && !app.gameOver) {
      scheduleWatchMove();
    }
  } catch (error) {
    if (token !== app.searchToken || app.mode !== "game") {
      return;
    }
    setError(error);
  }
}

function scheduleWatchMove(delay = 350) {
  clearTimeout(app.watchTimer);
  if (app.humanSide !== null || app.watchPaused || !engineToMove()) {
    return;
  }
  app.watchTimer = setTimeout(() => requestEngineMove(), delay);
}

function afterHistoryChange(message) {
  clearTimeout(app.watchTimer);
  app.selected = null;
  app.engineAutoPaused = true;
  app.pendingAnimation = null;
  app.activeAnimation = null;
  app.status = message;
  app.coreMessage = message;
  app.coreLineMode = "system";
  app.error = "";
  render();
}

function undoPly() {
  if (app.busy || app.thinking || app.mode !== "game") {
    return;
  }
  if (app.history.length <= 1) {
    setStatus("At the start");
    return;
  }

  const current = app.history.pop();
  app.redoStack.push(current);
  applySnapshot(app.history[app.history.length - 1]);
  afterHistoryChange(`Move ${app.moves.length} - back`);
}

function redoPly() {
  if (app.busy || app.thinking || app.mode !== "game") {
    return;
  }
  if (!app.redoStack.length) {
    setStatus("At the latest move");
    return;
  }

  const snapshot = app.redoStack.pop();
  app.history.push(snapshot);
  applySnapshot(snapshot);
  afterHistoryChange(`Move ${app.moves.length} - forward`);
}

function undoMove() {
  if (app.busy || app.thinking || app.mode !== "game") {
    return;
  }
  if (app.history.length <= 1) {
    setStatus("Nothing to undo");
    return;
  }

  const undoCount = app.humanSide !== null && humanCanMove() ? 2 : 1;
  for (let index = 0; index < undoCount && app.history.length > 1; index += 1) {
    const current = app.history.pop();
    app.redoStack.push(current);
  }
  applySnapshot(app.history[app.history.length - 1]);
  afterHistoryChange("Move undone");
}

async function triggerEngineMove() {
  if (!engineTurnAvailable()) {
    setStatus("Not the engine's turn");
    return;
  }
  app.engineAutoPaused = false;
  app.redoStack = [];
  await requestEngineMove(true);
}

async function copyFen() {
  try {
    await navigator.clipboard.writeText(app.fen);
    setStatus("FEN copied to clipboard");
  } catch {
    setStatus(`FEN: ${app.fen}`);
  }
}

function pgnResult() {
  return app.result || "*";
}

function pgnPlayerName(colour) {
  if (app.humanSide === null) {
    return `Sgurr ${title(colour)}`;
  }
  return app.humanSide === colour ? "Human" : "Sgurr";
}

function pgnDate() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}.${mm}.${dd}`;
}

function movesToPgn() {
  if (!app.moveRows.length) {
    return pgnResult();
  }

  const parts = [];
  for (const row of app.moveRows) {
    if (row.white) {
      parts.push(`${row.number}.`, row.white);
      if (row.black) {
        parts.push(row.black);
      }
    } else if (row.black) {
      parts.push(`${row.number}...`, row.black);
    }
  }
  parts.push(pgnResult());
  return parts.join(" ");
}

function exportPgn() {
  const headers = [
    ["Event", "Sgurr Web Demo Game"],
    ["Site", "Local browser"],
    ["Date", pgnDate()],
    ["White", pgnPlayerName("white")],
    ["Black", pgnPlayerName("black")],
    ["Result", pgnResult()],
  ];

  if (app.startFen !== START_FEN) {
    headers.push(["SetUp", "1"], ["FEN", app.startFen]);
  }

  const text = `${headers.map(([key, value]) => `[${key} "${value}"]`).join("\n")}\n\n${movesToPgn()}\n`;
  const blob = new Blob([text], { type: "application/x-chess-pgn" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const timestamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
  link.href = url;
  link.download = `Sgurr_web_game_${timestamp}.pgn`;
  link.click();
  URL.revokeObjectURL(url);
  setStatus("PGN exported");
}

function handleSquare(square) {
  if (app.mode === "editor") {
    handleEditorSquare(square);
    return;
  }

  if (!boardInteractionAvailable()) {
    return;
  }

  const pieces = projectPremovePieces(parseFenPieces(app.fen));
  const piece = pieces[square];
  const premoving = canQueuePremove();

  if (app.selected) {
    if (tryMove(app.selected, square)) {
      return;
    }
    if (app.selected !== square && !(piece && pieceColor(piece) === app.humanSide)) {
      app.selected = null;
      playSound("illegal");
      app.status = premoving ? "Premove not available" : "Illegal move";
      app.error = premoving ? "" : "Illegal move";
      render();
      return;
    }
  }

  if (app.selected === square) {
    app.selected = null;
    render();
    return;
  }

  if (piece && pieceColor(piece) === app.humanSide && legalFrom(square).length > 0) {
    app.selected = square;
  } else {
    app.selected = null;
  }
  render();
}

function tryMove(from, to, { animate = true } = {}) {
  const premoving = canQueuePremove();
  const availableMoves = premoving ? app.premoveMoves : app.legalMoves;
  const matches = availableMoves.filter(
    (move) => move.slice(0, 2) === from && move.slice(2, 4) === to,
  );

  if (!matches.length) {
    return false;
  }

  const promotions = matches.filter((move) => move.length === 5);
  const direct = matches.find((move) => move.length === 4);

  if (promotions.length && !direct) {
    showPromotion(from, to, promotions, { animate, premove: premoving });
    return true;
  }

  if (premoving) {
    queuePremove(direct || matches[0]);
  } else {
    makePlayerMove(direct || matches[0], { animate });
  }
  return true;
}

async function refreshPremoveProjection({ cancelOnFailure = false } = {}) {
  if (!hasPremoves() || app.humanSide === null || app.mode !== "game") {
    return true;
  }

  const token = (app.premoveRequestToken += 1);
  try {
    const data = await apiPost("/api/premove-sequence", {
      fen: app.fen,
      human_side: app.humanSide,
      premoves: app.premoves.map((premove) => premove.uci),
    });
    if (token !== app.premoveRequestToken || app.mode !== "game" || !hasPremoves()) {
      return false;
    }
    app.premoveMoves = data.premove_moves || [];
    render();
    return true;
  } catch (error) {
    if (token !== app.premoveRequestToken || app.mode !== "game") {
      return false;
    }
    if (cancelOnFailure) {
      clearPremoveQueueState();
      app.status = "Premove sequence cancelled: position changed";
      playSound("illegal");
      render();
      return false;
    }
    setError(error);
    return false;
  }
}

function queuePremove(uci) {
  if (!canQueuePremove()) {
    app.selected = null;
    app.status = "Premove window closed";
    render();
    return;
  }
  if (app.premoves.length >= 32) {
    app.status = "Premove queue is full";
    render();
    return;
  }
  const piece = projectPremovePieces(parseFenPieces(app.fen))[uci.slice(0, 2)] || null;
  app.premoves.push({
    uci,
    from: uci.slice(0, 2),
    to: uci.slice(2, 4),
    piece,
  });
  app.premoveMoves = [];
  app.selected = null;
  app.error = "";
  app.status = `${app.premoves.length} premove${app.premoves.length === 1 ? "" : "s"} queued`;
  playSound("move_self");
  render();
  refreshPremoveProjection();
}

function cancelPremoves() {
  if (!hasPremoves()) {
    return;
  }
  clearPremoveQueueState();
  app.selected = null;
  app.error = "";
  app.status = app.thinking
    ? "Premove sequence cancelled - Sgurr is thinking"
    : "Premove sequence cancelled";
  render();
}

function toggleFocusMode(force) {
  if (app.mode !== "game") {
    return;
  }
  app.focusMode = typeof force === "boolean" ? force : !app.focusMode;
  render();
}

export {
  cancelLiveGameWork,
  returnToMainMenu,
  resetLocalGame,
  startGame,
  startFromFen,
  rematchGame,
  openFenModal,
  loadFenFromModal,
  makePlayerMove,
  engineClockPayload,
  requestEngineMove,
  scheduleWatchMove,
  afterHistoryChange,
  undoPly,
  redoPly,
  undoMove,
  triggerEngineMove,
  copyFen,
  pgnResult,
  pgnPlayerName,
  pgnDate,
  movesToPgn,
  exportPgn,
  handleSquare,
  tryMove,
  refreshPremoveProjection,
  queuePremove,
  cancelPremoves,
  toggleFocusMode,
};
