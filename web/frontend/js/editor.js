import { syncClock } from "./clocks.js";
import { startPositionAnalysis } from "./analysis.js";
import { CHECKMATE_DRILLS, EDIT_RETURN_SIDES, ODDS_PRESETS, ODDS_RECIPIENTS, START_FEN, apiUrl } from "./config.js";
import { startFromFen } from "./game.js";
import { app, refs } from "./state.js";
import { render, setStatus } from "./ui.js";
import { clonePieces, parseFenPieces, pieceForColour, pieceLabel, piecesToBoardFen, startingPieces, title } from "./utils.js";

const EDITOR_DRAFT_KEY = "sgurrEditorDraft";
const EDITOR_PIECES = new Set("PNBRQKpnbrqk");

function fenParts(fen) {
  const parts = String(fen || "").trim().split(/\s+/);
  return {
    turn: parts[1] === "b" ? "black" : "white",
    castlingRights: /^[KQkq]+$/.test(parts[2] || "") ? parts[2] : "-",
    epSquare: /^([a-h][36]|-)$/.test(parts[3] || "") ? parts[3] : "-",
    halfmoveClock: Math.max(0, Number.parseInt(parts[4], 10) || 0),
    fullmoveNumber: Math.max(1, Number.parseInt(parts[5], 10) || 1),
  };
}

function loadEditorPosition(fen) {
  const meta = fenParts(fen);
  app.editor.pieces = parseFenPieces(fen);
  app.editor.turn = meta.turn;
  app.editor.castlingRights = meta.castlingRights;
  app.editor.epSquare = meta.epSquare;
  app.editor.halfmoveClock = meta.halfmoveClock;
  app.editor.fullmoveNumber = meta.fullmoveNumber;
  app.editor.brush = null;
  app.editor.heldPiece = null;
  app.editor.heldFrom = null;
}

function resetEditorPositionMetadata({ start = false } = {}) {
  app.editor.castlingRights = start ? "KQkq" : "-";
  app.editor.epSquare = "-";
  app.editor.halfmoveClock = 0;
  app.editor.fullmoveNumber = 1;
}

function castlingRightsForPieces(pieces) {
  let rights = "";
  if (pieces.e1 === "K") {
    rights += pieces.h1 === "R" ? "K" : "";
    rights += pieces.a1 === "R" ? "Q" : "";
  }
  if (pieces.e8 === "k") {
    rights += pieces.h8 === "r" ? "k" : "";
    rights += pieces.a8 === "r" ? "q" : "";
  }
  return rights || "-";
}

function markEditorBoardChanged() {
  app.editor.epSquare = "-";
  app.editor.halfmoveClock = 0;
}

function readEditorDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(EDITOR_DRAFT_KEY) || "null");
    if (!draft || typeof draft.pieces !== "object" || Array.isArray(draft.pieces)) {
      return null;
    }
    const entries = Object.entries(draft?.pieces || {});
    if (!entries.every(([square, piece]) => /^[a-h][1-8]$/.test(square) && EDITOR_PIECES.has(piece))) {
      return null;
    }
    return {
      pieces: Object.fromEntries(entries),
      turn: draft.turn === "black" ? "black" : "white",
      returnSide: ["white", "black", null].includes(draft.returnSide) ? draft.returnSide : "white",
      oddsRecipient: draft.oddsRecipient === "engine" ? "engine" : "you",
      castlingRights: /^[KQkq]+$/.test(draft.castlingRights || "")
        ? draft.castlingRights
        : castlingRightsForPieces(draft.pieces),
      epSquare: /^([a-h][36]|-)$/.test(draft.epSquare || "") ? draft.epSquare : "-",
      halfmoveClock: Math.max(0, Number.parseInt(draft.halfmoveClock, 10) || 0),
      fullmoveNumber: Math.max(1, Number.parseInt(draft.fullmoveNumber, 10) || 1),
    };
  } catch {
    return null;
  }
}

function saveEditorDraft() {
  localStorage.setItem(EDITOR_DRAFT_KEY, JSON.stringify({
    pieces: app.editor.pieces,
    turn: app.editor.turn,
    returnSide: app.editor.returnSide,
    oddsRecipient: app.editor.oddsRecipient,
    castlingRights: app.editor.castlingRights,
    epSquare: app.editor.epSquare,
    halfmoveClock: app.editor.halfmoveClock,
    fullmoveNumber: app.editor.fullmoveNumber,
  }));
}

function composeEditorFen() {
  const pieces = app.editor.pieces;
  const availableRights = castlingRightsForPieces(pieces).replace("-", "");

  const requestedRights = app.editor.castlingRights === "-" ? "" : app.editor.castlingRights;
  const rights = [..."KQkq"].filter(
    (right) => requestedRights.includes(right) && availableRights.includes(right),
  ).join("");
  return `${piecesToBoardFen(pieces)} ${app.editor.turn === "white" ? "w" : "b"} ${rights || "-"} ${app.editor.epSquare || "-"} ${app.editor.halfmoveClock} ${app.editor.fullmoveNumber}`;
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
  saveEditorDraft();
  render();
}

function enterBoardEditor(intent = "play", sourceFen = null) {
  if (app.busy || app.thinking) {
    setStatus("Wait for Sgurr to finish thinking");
    return;
  }

  syncClock();
  clearTimeout(app.watchTimer);
  const previousMode = app.mode === "editor" ? app.editor.previousMode : app.mode;

  app.editor.previousMode = previousMode;
  app.editor.intent = intent === "analysis" ? "analysis" : "play";
  if (sourceFen) {
    loadEditorPosition(sourceFen);
    app.editor.initialised = true;
  } else if (!app.editor.initialised) {
    const draft = readEditorDraft();
    const sourceFen = app.mode === "game" ? app.fen : START_FEN;
    if (draft) {
      app.editor.pieces = draft.pieces;
      app.editor.turn = draft.turn;
      app.editor.castlingRights = draft.castlingRights;
      app.editor.epSquare = draft.epSquare;
      app.editor.halfmoveClock = draft.halfmoveClock;
      app.editor.fullmoveNumber = draft.fullmoveNumber;
    } else {
      loadEditorPosition(sourceFen);
    }
    app.editor.returnSide = draft
      ? draft.returnSide
      : app.mode === "game" ? app.humanSide : "white";
    app.editor.oddsRecipient = draft?.oddsRecipient || "you";
    app.editor.initialised = true;
  }
  if (app.publicDemo && app.editor.returnSide === null) {
    app.editor.returnSide = "white";
  }
  app.editor.brush = null;
  app.editor.heldPiece = null;
  app.editor.heldFrom = null;
  app.editor.status = app.editor.intent === "analysis"
    ? "Build or paste a position for Sgurr to analyse"
    : "Build or paste a position, then play from it";
  app.editor.error = "";
  app.activeAnimation = null;
  app.pendingAnimation = null;
  app.mode = "editor";
  app.focusMode = false;
  app.selected = null;
  app.clockLastTick = null;
  saveEditorDraft();
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
    await startFromFen(fen, side, "Loaded editor position", "editor");
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

async function requestFenState(fen, signal = undefined) {
  const response = await fetch(apiUrl("/api/load-fen"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fen }),
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Position could not be loaded (${response.status})`);
  }
  return data;
}

async function loadFenIntoEditor() {
  const fen = refs.editorFenInput.value.trim();
  if (!fen) {
    setEditorStatus("Enter a FEN first", true);
    return;
  }

  app.busy = true;
  app.editor.status = "Checking FEN";
  app.editor.error = "";
  render();
  try {
    const data = await requestFenState(fen);
    loadEditorPosition(data.fen);
    app.busy = false;
    setEditorStatus("FEN loaded into the editor");
  } catch (error) {
    app.busy = false;
    setEditorStatus(error.message || String(error), true);
    refs.editorFenInput.value = fen;
    refs.editorFenInput.focus();
  }
}

async function analyseEditorPosition() {
  const localError = editorPositionError();
  if (localError) {
    setEditorStatus(`Fix position: ${localError}`, true);
    return;
  }

  const fen = composeEditorFen();
  app.busy = true;
  app.editor.status = "Checking position";
  app.editor.error = "";
  render();
  try {
    const data = await requestFenState(fen);
    app.busy = false;
    await startPositionAnalysis(data.fen, {
      orientation: app.editor.returnSide || app.editor.turn,
      validated: data,
    });
  } catch (error) {
    app.busy = false;
    setEditorStatus(error.message || String(error), true);
  }
}

function finishEditorPrimaryAction() {
  return app.editor.intent === "analysis"
    ? analyseEditorPosition()
    : finishBoardEditor();
}

function cycleEditorTurn() {
  app.editor.turn = app.editor.turn === "white" ? "black" : "white";
  app.editor.epSquare = "-";
  setEditorStatus(`First move: ${title(app.editor.turn)}`);
}

function cycleEditorOddsRecipient() {
  const index = ODDS_RECIPIENTS.indexOf(app.editor.oddsRecipient);
  app.editor.oddsRecipient = ODDS_RECIPIENTS[(index + 1) % ODDS_RECIPIENTS.length];
  setEditorStatus(editorOddsLabel());
}

function clearEditorBoard() {
  app.editor.pieces = {};
  resetEditorPositionMetadata();
  app.editor.brush = null;
  app.editor.heldPiece = null;
  app.editor.heldFrom = null;
  setEditorStatus("Board cleared");
}

function loadEditorStartPosition() {
  app.editor.pieces = startingPieces();
  app.editor.turn = "white";
  resetEditorPositionMetadata({ start: true });
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
  resetEditorPositionMetadata();
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
  resetEditorPositionMetadata({ start: true });
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
    markEditorBoardChanged();
    app.editor.heldPiece = null;
    app.editor.heldFrom = null;
    setEditorStatus(`${pieceLabel(app.editor.brush)} placed on ${square}`);
    return;
  }

  if (app.editor.heldPiece) {
    app.editor.pieces = clonePieces(app.editor.pieces);
    app.editor.pieces[square] = app.editor.heldPiece;
    markEditorBoardChanged();
    setEditorStatus(`${pieceLabel(app.editor.heldPiece)} moved to ${square}`);
    app.editor.heldPiece = null;
    app.editor.heldFrom = null;
    return;
  }

  const piece = app.editor.pieces[square];
  if (piece) {
    app.editor.pieces = clonePieces(app.editor.pieces);
    delete app.editor.pieces[square];
    markEditorBoardChanged();
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
    markEditorBoardChanged();
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
  analyseEditorPosition,
  finishEditorPrimaryAction,
  loadFenIntoEditor,
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
  saveEditorDraft,
};
