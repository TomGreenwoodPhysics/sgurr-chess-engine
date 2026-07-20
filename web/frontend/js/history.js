import { clearPremoveQueueState, scheduleGameOverRevealEnd } from "./board.js";
import { updateOpeningState } from "./openings.js";
import { app } from "./state.js";

function makeSnapshot() {
  return {
    fen: app.fen,
    startFen: app.startFen,
    turn: app.turn,
    legalMoves: [...app.legalMoves],
    premoveMoves: [...app.premoveMoves],
    basePremoveMoves: [...app.basePremoveMoves],
    moves: [...app.moves],
    moveRows: app.moveRows.map((row) => ({ ...row })),
    lastMove: app.lastMove,
    lastMoveInfo: app.lastMoveInfo ? { ...app.lastMoveInfo } : null,
    latestEval: app.latestEval ? { ...app.latestEval } : null,
    evalHistory: app.evalHistory.map((point) => ({ ...point })),
    material: app.material ? JSON.parse(JSON.stringify(app.material)) : null,
    canMate: { ...app.canMate },
    gameOver: app.gameOver,
    result: app.result,
    winner: app.winner,
    reason: app.reason,
    inCheck: app.inCheck,
    gameOverRevealAt: app.gameOverRevealAt,
    clocks: { ...app.clocks },
    clockFlagged: app.clockFlagged,
  };
}

function applySnapshot(snapshot) {
  app.fen = snapshot.fen;
  app.startFen = snapshot.startFen;
  app.turn = snapshot.turn;
  app.legalMoves = [...snapshot.legalMoves];
  app.premoveMoves = snapshot.premoveMoves ? [...snapshot.premoveMoves] : [];
  app.basePremoveMoves = snapshot.basePremoveMoves
    ? [...snapshot.basePremoveMoves]
    : [...app.premoveMoves];
  clearPremoveQueueState();
  app.moves = [...snapshot.moves];
  app.moveRows = snapshot.moveRows.map((row) => ({ ...row }));
  app.lastMove = snapshot.lastMove;
  app.lastMoveInfo = snapshot.lastMoveInfo ? { ...snapshot.lastMoveInfo } : null;
  app.latestEval = snapshot.latestEval ? { ...snapshot.latestEval } : null;
  app.evalHistory = snapshot.evalHistory ? snapshot.evalHistory.map((point) => ({ ...point })) : [];
  app.material = snapshot.material ? JSON.parse(JSON.stringify(snapshot.material)) : null;
  app.canMate = snapshot.canMate ? { ...snapshot.canMate } : { white: true, black: true };
  app.gameOver = snapshot.gameOver;
  app.result = snapshot.result;
  app.winner = snapshot.winner;
  app.reason = snapshot.reason;
  app.inCheck = snapshot.inCheck;
  app.gameOverRevealAt = snapshot.gameOverRevealAt;
  app.clocks = { ...snapshot.clocks };
  app.clockFlagged = snapshot.clockFlagged;
  app.clockCueSecond = null;
  app.resultSoundPlayed = false;
  app.clockLastTick = app.mode === "game" && !app.gameOver ? performance.now() : null;
  app.pendingAnimation = null;
  app.activeAnimation = null;
  updateOpeningState();
  scheduleGameOverRevealEnd();
}

function recordSnapshot({ clearRedo = true } = {}) {
  app.history.push(makeSnapshot());
  if (clearRedo) {
    app.redoStack = [];
  }
}

export {
  makeSnapshot,
  applySnapshot,
  recordSnapshot,
};
