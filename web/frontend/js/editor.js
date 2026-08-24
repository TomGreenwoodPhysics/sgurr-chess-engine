import { syncClock } from "./clocks.js";
import { CHECKMATE_DRILLS, EDIT_RETURN_SIDES, ODDS_PRESETS, ODDS_RECIPIENTS, START_FEN } from "./config.js";
import { startFromFen } from "./game.js";
import { app } from "./state.js";
import { render, setStatus } from "./ui.js";
import { clonePieces, fenTurn, parseFenPieces, pieceForColour, pieceLabel, piecesToBoardFen, startingPieces, title } from "./utils.js";

function composeEditorFen() {
  const pieces = app.editor.pieces;
  let rights = "";

  if (pieces.e1 === "K") {
    if (pieces.h1 === "R") {
      rights += "K";
    }
    if (pieces.a1 === "R") {
      rights += "Q";
    }
  }
  if (pieces.e8 === "k") {
    if (pieces.h8 === "r") {
      rights += "k";
    }
    if (pieces.a8 === "r") {
      rights += "q";
    }
  }

  return `${piecesToBoardFen(pieces)} ${app.editor.turn === "white" ? "w" : "b"} ${rights || "-"} - 0 1`;
}

function editorReturnLabel() {
  if (app.editor.returnSide === "white") {
    return "You play: White";
  }
  if (app.editor.returnSide === "black") {
    return "You play: Black";
  }
  return "Mode: Watch";
}

function editorOddsLabel() {
  return `Odds for: ${app.editor.oddsRecipient === "you" ? "You" : "Engine"}`;
}

function editorPositionError() {
  const pieces = app.editor.pieces;
  let whiteKings = 0;
  let blackKings = 0;

  for (const [square, piece] of Object.entries(pieces)) {
    if (piece === "K") {
      whiteKings += 1;
    } else if (piece === "k") {
      blackKings += 1;
    }

    if (piece.toLowerCase() === "p" && (square[1] === "1" || square[1] === "8")) {
      return "Pawn on a back rank";
    }
  }

  if (whiteKings === 0) {
    return "White king missing";
  }
  if (blackKings === 0) {
    return "Black king missing";
  }
  if (whiteKings > 1 || blackKings > 1) {
    return "Too many kings";
  }
  return null;
}

function setEditorStatus(message, isError = false) {
  app.editor.status = message;
  app.editor.error = isError ? message : "";
  render();
}

function enterBoardEditor() {
  if (app.busy || app.thinking) {
    setStatus("Wait for Sgurr to finish thinking");
    return;
  }

  syncClock();
  clearTimeout(app.watchTimer);
  const previousMode = app.mode === "editor" ? app.editor.previousMode : app.mode;
  const sourceFen = app.mode === "game" ? app.fen : START_FEN;

  app.editor.previousMode = previousMode;
  app.editor.pieces = parseFenPieces(sourceFen);
  app.editor.turn = fenTurn(sourceFen);
  app.editor.returnSide = app.mode === "game" ? app.humanSide : "white";
  app.editor.oddsRecipient = "you";
    app.editor.brush = null;
    app.editor.heldPiece = null;
    app.editor.heldFrom = null;
    app.editor.status = "Board editor";
    app.editor.error = "";
    app.activeAnimation = null;
    app.pendingAnimation = null;
    app.mode = "editor";
  app.focusMode = false;
  app.selected = null;
  app.clockLastTick = null;
  render();
}

function exitBoardEditor(message = "Editor cancelled") {
  app.editor.brush = null;
  app.editor.heldPiece = null;
  app.editor.heldFrom = null;
  app.editor.status = message;
  app.editor.error = "";
  app.mode = app.editor.previousMode || "menu";
  if (app.mode === "game") {
    app.clockLastTick = performance.now();
  }
  render();
}

async function finishBoardEditor() {
  const localError = editorPositionError();
  if (localError) {
    setEditorStatus(`Fix position: ${localError}`, true);
    return;
  }

  const fen = composeEditorFen();
  const side = app.editor.returnSide;
  app.busy = true;
  render();

  try {
    app.editor.error = "";
    await startFromFen(fen, side, "Loaded editor position");
  } catch (error) {
    app.busy = false;
    setEditorStatus(error.message || String(error), true);
  }
}

async function copyEditorFen() {
  const fen = composeEditorFen();
  try {
    await navigator.clipboard.writeText(fen);
    setEditorStatus("FEN copied to clipboard");
  } catch {
    setEditorStatus(`FEN: ${fen}`);
  }
}

function cycleEditorPlayer() {
  const choices = app.publicDemo ? ["white", "black"] : EDIT_RETURN_SIDES;
  const index = choices.indexOf(app.editor.returnSide);
  const next = index < 0 ? 0 : (index + 1) % choices.length;
  app.editor.returnSide = choices[next];
  setEditorStatus(editorReturnLabel());
}

function cycleEditorTurn() {
  app.editor.turn = app.editor.turn === "white" ? "black" : "white";
  setEditorStatus(`First move: ${title(app.editor.turn)}`);
}

function cycleEditorOddsRecipient() {
  const index = ODDS_RECIPIENTS.indexOf(app.editor.oddsRecipient);
  app.editor.oddsRecipient = ODDS_RECIPIENTS[(index + 1) % ODDS_RECIPIENTS.length];
  setEditorStatus(editorOddsLabel());
}

function clearEditorBoard() {
  app.editor.pieces = {};
  app.editor.brush = null;
  app.editor.heldPiece = null;
  app.editor.heldFrom = null;
  setEditorStatus("Board cleared");
}

function loadEditorStartPosition() {
  app.editor.pieces = startingPieces();
  app.editor.turn = "white";
  app.editor.brush = null;
  app.editor.heldPiece = null;
  app.editor.heldFrom = null;
  setEditorStatus("Start position");
}

function toggleEditorBrush(piece) {
  app.editor.brush = app.editor.brush === piece ? null : piece;
  app.editor.heldPiece = null;
  app.editor.heldFrom = null;
  setEditorStatus(app.editor.brush ? `${pieceLabel(piece)} brush` : "Brush cleared");
}

function drillAttackerColour() {
  return app.editor.returnSide || app.editor.turn;
}

function loadCheckmateDrill(key) {
  const drill = CHECKMATE_DRILLS.find((entry) => entry.key === key);
  if (!drill) {
    setEditorStatus("Unknown drill", true);
    return;
  }

  const attacker = drillAttackerColour();
  const defender = attacker === "white" ? "black" : "white";
  const pieces = {};
  const attackerKing = attacker === "white" ? "e4" : "e5";
  const defenderKing = attacker === "white" ? "e8" : "e1";
  const fallbackSquares =
    drill.pieces.length === 1
      ? [attacker === "white" ? "d4" : "d5"]
      : drill.key === "two_rooks"
        ? attacker === "white"
          ? ["d4", "h4"]
          : ["d5", "h5"]
        : attacker === "white"
          ? ["c4", "f4"]
          : ["c5", "f5"];

  pieces[attackerKing] = pieceForColour("K", attacker);
  pieces[defenderKing] = pieceForColour("K", defender);
  drill.pieces.forEach((piece, index) => {
    pieces[fallbackSquares[index]] = pieceForColour(piece, attacker);
  });

  app.editor.pieces = pieces;
  app.editor.brush = null;
  app.editor.heldPiece = null;
  app.editor.heldFrom = null;
  setEditorStatus(`${title(attacker)} ${drill.label} drill`);
}

function squareForColour(square, colour) {
  if (colour === "white") {
    return square;
  }
  return `${square[0]}${9 - Number(square[1])}`;
}

function oddsRemovedColour() {
  if (!app.editor.returnSide) {
    return null;
  }
  const recipient =
    app.editor.oddsRecipient === "you"
      ? app.editor.returnSide
      : app.editor.returnSide === "white"
        ? "black"
        : "white";
  return recipient === "white" ? "black" : "white";
}

function loadOddsPreset(key) {
  const preset = ODDS_PRESETS.find((entry) => entry.key === key);
  if (!preset) {
    setEditorStatus("Unknown odds preset", true);
    return;
  }

  const removedColour = oddsRemovedColour();
  if (!removedColour) {
    setEditorStatus("Choose White or Black before odds", true);
    return;
  }

  const pieces = startingPieces();
  for (const square of preset.squares) {
    delete pieces[squareForColour(square, removedColour)];
  }

  app.editor.pieces = pieces;
  app.editor.turn = "white";
  app.editor.brush = null;
  app.editor.heldPiece = null;
  app.editor.heldFrom = null;
  const target = app.editor.oddsRecipient === "you" ? "You" : "Engine";
  const verb = app.editor.oddsRecipient === "you" ? "get" : "gets";
  setEditorStatus(`${target} ${verb} ${preset.label.toLowerCase()}`);
}

function handleEditorSquare(square) {
  if (app.editor.brush) {
    app.editor.pieces = clonePieces(app.editor.pieces);
    app.editor.pieces[square] = app.editor.brush;
    app.editor.heldPiece = null;
    app.editor.heldFrom = null;
    setEditorStatus(`${pieceLabel(app.editor.brush)} placed on ${square}`);
    return;
  }

  if (app.editor.heldPiece) {
    app.editor.pieces = clonePieces(app.editor.pieces);
    app.editor.pieces[square] = app.editor.heldPiece;
    setEditorStatus(`${pieceLabel(app.editor.heldPiece)} moved to ${square}`);
    app.editor.heldPiece = null;
    app.editor.heldFrom = null;
    return;
  }

  const piece = app.editor.pieces[square];
  if (piece) {
    app.editor.pieces = clonePieces(app.editor.pieces);
    delete app.editor.pieces[square];
    app.editor.heldPiece = piece;
    app.editor.heldFrom = square;
    setEditorStatus(`${pieceLabel(piece)} picked up`);
  }
}

function handleEditorDelete(square) {
  if (app.editor.brush) {
    app.editor.brush = null;
    setEditorStatus("Brush cleared");
    return;
  }

  if (app.editor.pieces[square]) {
    app.editor.pieces = clonePieces(app.editor.pieces);
    delete app.editor.pieces[square];
    setEditorStatus(`${square} cleared`);
  }
}

export {
  composeEditorFen,
  editorReturnLabel,
  editorOddsLabel,
  editorPositionError,
  setEditorStatus,
  enterBoardEditor,
  exitBoardEditor,
  finishBoardEditor,
  copyEditorFen,
  cycleEditorPlayer,
  cycleEditorTurn,
  cycleEditorOddsRecipient,
  clearEditorBoard,
  loadEditorStartPosition,
  toggleEditorBrush,
  drillAttackerColour,
  loadCheckmateDrill,
  squareForColour,
  oddsRemovedColour,
  loadOddsPreset,
  handleEditorSquare,
  handleEditorDelete,
};
