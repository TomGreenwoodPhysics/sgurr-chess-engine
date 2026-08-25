import { apiUrl, START_FEN } from "../js/config.js";
import { initLabPreferences } from "../search-lab/preferences.js";
import { CortexVisual } from "./cortex.js";
import { EXPECTED_NETWORK, parseFen } from "./nnue-model.js";

const NETWORK_PATH = `/api/nnue/gen8/${EXPECTED_NETWORK.sha256}.nnue`;
const POSITION_PRESETS = Object.freeze({
  start: START_FEN,
  ruy: "r1bqk2r/pppp1ppp/2n2n2/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 5",
  kiwipete: "r3k2r/p1ppqpb1/bn2pnp1/2pP4/1p2P3/2N2N2/PPQBBPPP/R3K2R w KQkq - 0 1",
});
const PIECE_CODES = Object.freeze({ p: "P", n: "N", b: "B", r: "R", q: "Q", k: "K" });
const LANE_BANDS = Object.freeze([
  "Top quarter",
  "Upper-middle quarter",
  "Lower-middle quarter",
  "Bottom quarter",
]);

const refs = {
  shell: document.querySelector("#insideShell"),
  board: document.querySelector("#nnueBoard"),
  boardStatus: document.querySelector("#boardStatus"),
  turn: document.querySelector("#positionTurn"),
  preset: document.querySelector("#positionPreset"),
  fenForm: document.querySelector("#nnueFenForm"),
  fenInput: document.querySelector("#nnueFenInput"),
  fenStatus: document.querySelector("#fenStatus"),
  undo: document.querySelector("#undoPosition"),
  canvas: document.querySelector("#cortexCanvas"),
  cortexView: document.querySelector("#cortexViewButton"),
  circuitView: document.querySelector("#circuitViewButton"),
  laneAtlasDetail: document.querySelector("#laneAtlasDetail"),
  laneBandButtons: [...document.querySelectorAll("[data-lane-band]")],
  beforeState: document.querySelector("#beforeState"),
  deltaState: document.querySelector("#deltaState"),
  afterState: document.querySelector("#afterState"),
  replay: document.querySelector("#replayTransition"),
  modelSignal: document.querySelector("#modelSignal"),
  modelStatus: document.querySelector("#modelStatus"),
  loadingTitle: document.querySelector("#loadingTitle"),
  loadingDetail: document.querySelector("#loadingDetail"),
  retry: document.querySelector("#retryModel"),
  evaluation: document.querySelector("#nnueEval"),
  evaluationLabel: document.querySelector(".eval-readout > span"),
  evaluationDetail: document.querySelector("#nnueEvalDetail"),
  pieceCount: document.querySelector("#pieceCount"),
  activeFeatures: document.querySelector("#activeFeatures"),
  clippedLow: document.querySelector("#clippedLow"),
  clippedHigh: document.querySelector("#clippedHigh"),
  rawOutput: document.querySelector("#rawOutput"),
  updateTitle: document.querySelector("#updateTitle"),
  changedLanes: document.querySelector("#changedLanes"),
  pieceEdits: document.querySelector("#pieceEdits"),
  weightRows: document.querySelector("#weightRows"),
  laneOperations: document.querySelector("#laneOperations"),
  featureTrace: document.querySelector("#featureTrace"),
  laneTitle: document.querySelector("#laneTitle"),
  laneAddress: document.querySelector("#laneAddress"),
  laneMeter: document.querySelector("#laneMeter"),
  laneRaw: document.querySelector("#laneRaw"),
  laneClipped: document.querySelector("#laneClipped"),
  laneDelta: document.querySelector("#laneDelta"),
  laneContributionLabel: document.querySelector("#laneContributionLabel"),
  laneContribution: document.querySelector("#laneContribution"),
  laneNote: document.querySelector("#laneNote"),
  promotionDialog: document.querySelector("#promotionDialog"),
};

let worker = null;
let workerRequestId = 0;
let workerRequests = new Map();
let position = null;
let transition = null;
let history = [];
let selectedSquare = null;
let selectedLane = null;
let busy = true;
let modelReady = false;
let currentPhase = "after";
let replayTimers = [];
let bootSequence = 0;
let boardFocusPending = false;
let boardFocusSquare = null;
let currentLaneBand = 0;
let laneBandTimer = null;

const visual = new CortexVisual(refs.canvas, (details) => {
  if (details) selectedLane = { perspective: details.perspective, index: details.index };
  renderLane(details);
});

function scheduleLaneBand() {
  if (laneBandTimer !== null) window.clearTimeout(laneBandTimer);
  laneBandTimer = null;
  if (visual.reducedMotion || document.hidden) return;
  laneBandTimer = window.setTimeout(() => {
    setLaneBand((currentLaneBand + 1) % LANE_BANDS.length);
  }, 7200);
}

function setLaneBand(band) {
  currentLaneBand = Math.max(0, Math.min(LANE_BANDS.length - 1, Number(band) || 0));
  visual.setAtlasBand(currentLaneBand);
  for (const button of refs.laneBandButtons) {
    const active = Number(button.dataset.laneBand) === currentLaneBand;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  renderLaneBand();
  scheduleLaneBand();
}

function renderLaneBand() {
  const first = currentLaneBand * 96;
  const last = first + 96;
  const prefix = `${LANE_BANDS[currentLaneBand]} · ${String(first).padStart(3, "0")}–${String(last - 1).padStart(3, "0")}`;
  if (!transition) {
    refs.laneAtlasDetail.textContent = `${prefix} in both accumulators.`;
    return;
  }
  if (currentPhase === "delta" && transition.before) {
    let changed = 0;
    for (const values of [transition.whiteDelta, transition.blackDelta]) {
      for (let index = first; index < last; index += 1) changed += values[index] !== 0 ? 1 : 0;
    }
    refs.laneAtlasDetail.textContent = `${prefix} · ${changed} of 192 changed.`;
    return;
  }
  const snapshot = snapshotForPhase();
  let active = 0;
  let saturated = 0;
  for (const values of [snapshot.whiteActivation, snapshot.blackActivation]) {
    for (let index = first; index < last; index += 1) {
      active += values[index] > 0 ? 1 : 0;
      saturated += values[index] >= 255 ? 1 : 0;
    }
  }
  refs.laneAtlasDetail.textContent = `${prefix} · ${active} of 192 active · ${saturated} clipped.`;
}

function makeWorker() {
  if (worker) worker.terminate();
  for (const request of workerRequests.values()) {
    window.clearTimeout(request.timeout);
    request.reject(new Error("Evaluator restarted"));
  }
  workerRequests = new Map();
  worker = new Worker(new URL("./nnue-worker.js", import.meta.url), { type: "module" });
  worker.addEventListener("message", (event) => {
    const message = event.data || {};
    const request = workerRequests.get(message.requestId);
    if (!request) return;
    window.clearTimeout(request.timeout);
    workerRequests.delete(message.requestId);
    if (message.type === "error") {
      request.reject(new Error(message.detail || "Evaluator error"));
    } else {
      request.resolve(message);
    }
  });
  worker.addEventListener("error", () => {
    for (const request of workerRequests.values()) {
      window.clearTimeout(request.timeout);
      request.reject(new Error("Evaluator worker could not start"));
    }
    workerRequests.clear();
  });
}

function requestWorker(type, payload = {}) {
  const requestId = ++workerRequestId;
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      workerRequests.delete(requestId);
      reject(new Error("Evaluator took too long to respond"));
    }, 90_000);
    workerRequests.set(requestId, { resolve, reject, timeout });
    worker.postMessage({ type, requestId, ...payload });
  });
}

async function postJson(path, payload) {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

function squareName(square) {
  return `${"abcdefgh"[square % 8]}${Math.floor(square / 8) + 1}`;
}

function pieceAsset(piece) {
  const colour = piece === piece.toUpperCase() ? "w" : "b";
  return `../assets/pieces/chessnut/${colour}${PIECE_CODES[piece.toLowerCase()]}.svg`;
}

function legalTargets() {
  if (!selectedSquare || !position) return new Set();
  return new Set(
    position.legal_moves
      .filter((move) => move.startsWith(selectedSquare))
      .map((move) => move.slice(2, 4)),
  );
}

function renderBoard() {
  const activeSquare = refs.board.contains(document.activeElement)
    ? document.activeElement?.dataset.square
    : null;
  if (activeSquare) {
    boardFocusPending = true;
    boardFocusSquare = activeSquare;
  }
  const parsed = parseFen(position?.fen || START_FEN);
  const pieceBySquare = new Map(parsed.pieces.map((piece) => [piece.square, piece]));
  const targets = legalTargets();
  const legalSources = new Set((position?.legal_moves || []).map((move) => move.slice(0, 2)));
  const lastMove = position?.last_move?.uci || "";
  const fragment = document.createDocumentFragment();

  for (let rank = 7; rank >= 0; rank -= 1) {
    for (let file = 0; file < 8; file += 1) {
      const square = rank * 8 + file;
      const name = squareName(square);
      const piece = pieceBySquare.get(square);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `board-square${(rank + file) % 2 === 0 ? " dark" : ""}`;
      button.dataset.square = name;
      button.disabled = busy || (!legalSources.has(name) && !targets.has(name));
      button.setAttribute("aria-label", `${piece ? piece.label : "Empty"}, ${name}`);
      button.setAttribute("aria-pressed", String(name === selectedSquare));
      if (name === selectedSquare) button.classList.add("selected");
      if (targets.has(name)) button.classList.add("legal");
      if (lastMove && (name === lastMove.slice(0, 2) || name === lastMove.slice(2, 4))) {
        button.classList.add("last-move");
      }
      if (piece) {
        const image = document.createElement("img");
        image.className = "piece-image";
        image.src = pieceAsset(piece.piece);
        image.alt = "";
        image.draggable = false;
        button.appendChild(image);
      }
      if (file === 0) {
        const label = document.createElement("span");
        label.className = "square-rank";
        label.textContent = String(rank + 1);
        button.appendChild(label);
      }
      if (rank === 0) {
        const label = document.createElement("span");
        label.className = "square-file";
        label.textContent = "abcdefgh"[file];
        button.appendChild(label);
      }
      fragment.appendChild(button);
    }
  }

  refs.board.replaceChildren(fragment);
  if (!busy && boardFocusPending) {
    const preferred = refs.board.querySelector(`[data-square="${selectedSquare || boardFocusSquare}"]:not(:disabled)`)
      || refs.board.querySelector(".board-square:not(:disabled)");
    boardFocusPending = false;
    if (preferred) requestAnimationFrame(() => preferred.focus({ preventScroll: true }));
  }
  refs.fenInput.value = position?.fen || START_FEN;
  refs.preset.value = Object.entries(POSITION_PRESETS)
    .find(([, fen]) => fen === (position?.fen || START_FEN))?.[0] || "custom";
  refs.turn.textContent = `${position?.turn === "black" ? "Black" : "White"} to move`;
  refs.undo.disabled = busy || history.length === 0;
  if (position?.game_over) {
    const reason = String(position.reason || "game over").replaceAll("_", " ");
    refs.boardStatus.textContent = `${position.result || "Game over"} · ${reason}`;
  } else if (position) {
    const count = position.legal_moves.length;
    refs.boardStatus.textContent = `${count} legal move${count === 1 ? "" : "s"} · select a piece to update the network`;
  }
}

function setBusy(nextBusy, { preserveFen = false } = {}) {
  const pendingFen = refs.fenInput.value;
  busy = nextBusy;
  renderBoard();
  if (preserveFen) refs.fenInput.value = pendingFen;
  refs.preset.disabled = nextBusy;
  refs.fenInput.disabled = nextBusy;
  refs.fenForm.querySelector('button[type="submit"]').disabled = nextBusy;
  refs.undo.disabled = nextBusy || history.length === 0;
}

function formatSigned(value, decimals = 2) {
  if (!Number.isFinite(value)) return "—";
  const rounded = Math.abs(value) < 0.5 * 10 ** -decimals ? 0 : value;
  return `${rounded >= 0 ? "+" : "−"}${Math.abs(rounded).toFixed(decimals)}`;
}

function formatInteger(value) {
  if (!Number.isFinite(value)) return "—";
  return Math.trunc(value).toLocaleString("en-GB");
}

function snapshotForPhase() {
  if (!transition) return null;
  if (currentPhase === "before" && transition.before) return transition.before;
  return transition.after;
}

function renderEvaluation() {
  const snapshot = snapshotForPhase();
  if (!snapshot) return;
  if (currentPhase === "delta" && transition.before) {
    const scoreDelta = transition.after.whiteRelative - transition.before.whiteRelative;
    refs.evaluationLabel.textContent = "White evaluation change";
    refs.evaluation.textContent = formatSigned(scoreDelta / 100);
    refs.evaluationDetail.textContent = `${formatSigned(transition.before.whiteRelative / 100)} → ${formatSigned(transition.after.whiteRelative / 100)}`;
  } else {
    refs.evaluationLabel.textContent = "White evaluation";
    refs.evaluation.textContent = formatSigned(snapshot.whiteRelative / 100);
    refs.evaluationDetail.textContent = `${snapshot.sideToMove === 0 ? "White" : "Black"} to move · raw ${formatInteger(snapshot.raw)}`;
  }
  refs.pieceCount.textContent = snapshot.pieces.length;
  refs.activeFeatures.textContent = `${snapshot.activeFeatures.length} × 2`;
  refs.clippedLow.textContent = `${snapshot.clippedLow} / 768`;
  refs.clippedHigh.textContent = `${snapshot.clippedHigh} / 768`;
  refs.rawOutput.textContent = formatInteger(snapshot.raw);
}

function renderUpdate() {
  if (!transition) return;
  if (!transition.before) {
    const rows = transition.after.pieces.length * 2;
    refs.updateTitle.textContent = "Full refresh";
    refs.changedLanes.textContent = "768 lanes";
    refs.pieceEdits.textContent = transition.after.pieces.length;
    refs.weightRows.textContent = rows;
    refs.laneOperations.textContent = formatInteger(rows * 384);
    refs.featureTrace.textContent = `${transition.after.pieces.length} occupied squares · ${rows} perspective features loaded`;
    return;
  }
  refs.updateTitle.textContent = transition.pieceSquareEdits === 2 ? "Incremental move" : "Position change";
  refs.changedLanes.textContent = `${transition.changedLaneValues} changed`;
  refs.pieceEdits.textContent = transition.pieceSquareEdits;
  refs.weightRows.textContent = transition.weightRowUpdates;
  refs.laneOperations.textContent = formatInteger(transition.laneOperations);
  const { removed, added } = transition.edits;
  if (removed.length === 1 && added.length === 1 && removed[0].piece === added[0].piece) {
    const piece = removed[0];
    refs.featureTrace.textContent = `${piece.label} ${piece.squareName} → ${added[0].squareName} · inputs W ${piece.whiteIndex}→${added[0].whiteIndex} · B ${piece.blackIndex}→${added[0].blackIndex}`;
  } else {
    refs.featureTrace.textContent = `${removed.length} removed · ${added.length} added · mapped through the exact accumulator delta`;
  }
}

function renderLane(details) {
  if (!details) {
    refs.laneTitle.textContent = "Select a lane";
    refs.laneAddress.textContent = "—";
    refs.laneMeter.style.width = "0%";
    refs.laneRaw.textContent = "—";
    refs.laneClipped.textContent = "—";
    refs.laneDelta.textContent = "—";
    refs.laneContributionLabel.textContent = "Output contribution";
    refs.laneContribution.textContent = "—";
    refs.laneNote.textContent = "Hover, tap or use the arrow keys on the display.";
    return;
  }
  const perspective = details.perspective === "white" ? "White" : "Black";
  refs.laneTitle.textContent = `${perspective}-view lane`;
  refs.laneAddress.textContent = `${perspective[0]}:${String(details.index).padStart(3, "0")}`;
  refs.laneMeter.style.width = `${Math.max(1, Math.min(100, details.clipped / 2.55))}%`;
  refs.laneRaw.textContent = formatInteger(details.raw);
  refs.laneClipped.textContent = `${details.clipped} / 255`;
  refs.laneDelta.textContent = `${details.delta >= 0 ? "+" : "−"}${formatInteger(Math.abs(details.delta))}`;
  refs.laneContributionLabel.textContent = details.phase === "delta" ? "White output change" : "White contribution";
  refs.laneContribution.textContent = `${formatSigned(details.centipawns)} cp`;
  const firstLane = Math.floor(details.index / 96) * 96;
  const band = `${String(firstLane).padStart(3, "0")}–${String(firstLane + 95).padStart(3, "0")}`;
  refs.laneNote.textContent = details.phase === "delta"
    ? `Lane band ${band}. The value includes the side-to-move output swap.`
    : `Lane band ${band}. This lane uses the ${details.outputHalf} output weights.`;
}

function strongestLane(snapshot) {
  let target = { perspective: "white", index: 0 };
  let strength = -1;
  for (const perspective of ["white", "black"]) {
    const values = perspective === "white" ? snapshot.whiteContribution : snapshot.blackContribution;
    for (let index = 0; index < values.length; index += 1) {
      const candidate = Math.abs(values[index]);
      if (candidate > strength) {
        strength = candidate;
        target = { perspective, index };
      }
    }
  }
  return target;
}

function refreshSelectedLane() {
  const snapshot = snapshotForPhase();
  if (!snapshot) return;
  selectedLane ||= strongestLane(snapshot);
  renderLane(visual.laneDetails(selectedLane));
}

function cancelReplay() {
  for (const timer of replayTimers) window.clearTimeout(timer);
  replayTimers = [];
}

function setPhase(phase, { keepReplay = false } = {}) {
  if (!transition || ((phase === "before" || phase === "delta") && !transition.before)) return;
  if (!keepReplay) cancelReplay();
  currentPhase = phase;
  visual.setPhase(phase);
  for (const [name, button] of [
    ["before", refs.beforeState],
    ["delta", refs.deltaState],
    ["after", refs.afterState],
  ]) {
    const active = name === phase;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  renderLaneBand();
  renderEvaluation();
  refreshSelectedLane();
}

function replayTransition() {
  cancelReplay();
  if (!transition?.before || visual.reducedMotion) {
    setPhase("after", { keepReplay: true });
    return;
  }
  setPhase("before", { keepReplay: true });
  replayTimers.push(
    window.setTimeout(() => setPhase("delta", { keepReplay: true }), 520),
    window.setTimeout(() => {
      setPhase("after", { keepReplay: true });
      replayTimers = [];
    }, 1300),
  );
}

function setView(view) {
  visual.setView(view);
  const cortex = view === "cortex";
  refs.cortexView.classList.toggle("active", cortex);
  refs.circuitView.classList.toggle("active", !cortex);
  refs.cortexView.setAttribute("aria-pressed", String(cortex));
  refs.circuitView.setAttribute("aria-pressed", String(!cortex));
}

async function evaluate(beforeFen, afterFen, { replay = false } = {}) {
  const message = await requestWorker("evaluate", { beforeFen, afterFen });
  transition = message.transition;
  currentPhase = "after";
  selectedLane = null;
  visual.setTransition(transition);
  refs.beforeState.disabled = !transition.before;
  refs.deltaState.disabled = !transition.before;
  refs.replay.disabled = !transition.before;
  renderUpdate();
  setPhase("after");
  if (replay && transition.before) replayTransition();
}

async function applyPosition(nextPosition, { beforeFen = null, record = false, replay = false } = {}) {
  const previous = position;
  await evaluate(beforeFen, nextPosition.fen, { replay });
  if (record && previous) history.push(previous);
  position = nextPosition;
  selectedSquare = null;
  renderBoard();
  refs.undo.disabled = busy || history.length === 0;
}

async function loadFen(fen, { record = true, replay = true } = {}) {
  const requestedFen = String(fen).trim();
  setBusy(true, { preserveFen: true });
  refs.fenStatus.dataset.state = "loading";
  refs.fenStatus.textContent = "Checking position";
  const beforeFen = position?.fen || null;
  let positionAccepted = false;
  try {
    const nextPosition = await postJson("/api/load-fen", { fen: requestedFen });
    positionAccepted = true;
    await applyPosition(nextPosition, { beforeFen, record, replay });
    refs.fenStatus.dataset.state = "ready";
    refs.fenStatus.textContent = "Position loaded. Choose a move or select a lane.";
  } catch (error) {
    if (positionAccepted) {
      showBootError(error);
      return;
    }
    refs.fenStatus.dataset.state = "error";
    refs.fenStatus.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    if (refs.shell.dataset.state !== "error") {
      setBusy(false, { preserveFen: !positionAccepted });
    }
  }
}

async function playMove(move) {
  if (!position || busy) return;
  const previous = position;
  setBusy(true);
  refs.boardStatus.dataset.state = "loading";
  refs.boardStatus.textContent = `Applying ${move.slice(0, 2)} → ${move.slice(2, 4)}`;
  let moveAccepted = false;
  try {
    const nextPosition = await postJson("/api/player-move", {
      fen: previous.fen,
      start_fen: previous.start_fen,
      moves: previous.moves,
      move,
    });
    moveAccepted = true;
    await applyPosition(nextPosition, { beforeFen: previous.fen, record: true, replay: true });
    refs.boardStatus.dataset.state = "ready";
  } catch (error) {
    if (moveAccepted) {
      showBootError(error);
      return;
    }
    refs.boardStatus.dataset.state = "error";
    refs.boardStatus.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    if (refs.shell.dataset.state !== "error") setBusy(false);
  }
}

function choosePromotion(candidates) {
  const glyphs = position?.turn === "black"
    ? { q: "♛", r: "♜", b: "♝", n: "♞" }
    : { q: "♕", r: "♖", b: "♗", n: "♘" };
  for (const piece of refs.promotionDialog.querySelectorAll(".promotion-piece")) {
    piece.textContent = glyphs[piece.dataset.piece];
  }
  refs.promotionDialog.returnValue = "";
  refs.promotionDialog.showModal();
  return new Promise((resolve) => {
    refs.promotionDialog.addEventListener("close", () => {
      const choice = refs.promotionDialog.returnValue;
      resolve(["q", "r", "b", "n"].includes(choice)
        ? candidates.find((move) => move.endsWith(choice)) || null
        : null);
    }, { once: true });
  });
}

async function handleBoardClick(event) {
  const square = event.target.closest(".board-square")?.dataset.square;
  if (!square || busy || !position) return;
  if (selectedSquare) {
    const candidates = position.legal_moves.filter((move) => move.startsWith(selectedSquare + square));
    if (candidates.length) {
      const move = candidates.length > 1 ? await choosePromotion(candidates) : candidates[0];
      if (!move) {
        renderBoard();
        return;
      }
      selectedSquare = null;
      playMove(move);
      return;
    }
  }
  const isLegalSource = position.legal_moves.some((move) => move.startsWith(square));
  selectedSquare = isLegalSource && selectedSquare !== square ? square : null;
  renderBoard();
}

async function undoPosition() {
  if (!history.length || busy) return;
  const previous = history.at(-1);
  const beforeFen = position.fen;
  setBusy(true);
  try {
    await applyPosition(previous, { beforeFen, replay: true });
    history.pop();
  } catch (error) {
    showBootError(error);
  } finally {
    if (refs.shell.dataset.state !== "error") setBusy(false);
  }
}

async function loadModel(sequence) {
  makeWorker();
  refs.modelSignal.dataset.state = "loading";
  refs.modelStatus.textContent = "Loading Gen8 evaluator";
  const result = await requestWorker("load", { url: apiUrl(NETWORK_PATH) });
  if (sequence !== bootSequence || refs.shell.dataset.state !== "loading") {
    throw new Error("Evaluator load was superseded");
  }
  modelReady = true;
  refs.modelSignal.dataset.state = "ready";
  refs.modelStatus.textContent = `Gen8 v${result.architecture.version} loaded · exact integer inference`;
  return result;
}

function showBootError(error) {
  modelReady = false;
  busy = true;
  refs.shell.dataset.state = "error";
  refs.modelSignal.dataset.state = "error";
  refs.modelStatus.textContent = "Evaluator unavailable";
  refs.loadingTitle.textContent = "The evaluator did not open";
  refs.loadingDetail.textContent = error instanceof Error ? error.message : String(error);
  refs.retry.hidden = false;
  renderBoard();
}

async function boot() {
  const sequence = ++bootSequence;
  refs.shell.dataset.state = "loading";
  refs.retry.hidden = true;
  refs.loadingTitle.textContent = "Opening the evaluator";
  refs.loadingDetail.textContent = "Verifying the shipped Gen8 network";
  busy = true;
  try {
    const [model, nextPosition] = await Promise.all([
      loadModel(sequence),
      postJson("/api/load-fen", { fen: position?.fen || START_FEN }),
    ]);
    if (sequence !== bootSequence) return;
    if (!model.architecture || !nextPosition.fen) throw new Error("Evaluator response was incomplete");
    history = [];
    await applyPosition(nextPosition);
    refs.shell.dataset.state = "ready";
    refs.boardStatus.dataset.state = "ready";
    refs.fenStatus.dataset.state = "ready";
    refs.fenStatus.textContent = "Position loaded. Choose a move or select a lane.";
    busy = false;
    renderBoard();
  } catch (error) {
    if (sequence !== bootSequence) return;
    showBootError(error);
  }
}

refs.board.addEventListener("click", handleBoardClick);
refs.fenForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (modelReady) loadFen(refs.fenInput.value);
});
refs.preset.addEventListener("change", () => {
  const fen = POSITION_PRESETS[refs.preset.value];
  if (modelReady && fen) loadFen(fen);
});
refs.undo.addEventListener("click", undoPosition);
refs.cortexView.addEventListener("click", () => setView("cortex"));
refs.circuitView.addEventListener("click", () => setView("circuit"));
for (const button of refs.laneBandButtons) {
  button.addEventListener("click", () => setLaneBand(button.dataset.laneBand));
}
refs.beforeState.addEventListener("click", () => setPhase("before"));
refs.deltaState.addEventListener("click", () => setPhase("delta"));
refs.afterState.addEventListener("click", () => setPhase("after"));
refs.replay.addEventListener("click", replayTransition);
refs.retry.addEventListener("click", boot);
document.addEventListener("sgurrthemechange", () => visual.draw(performance.now()));
document.addEventListener("visibilitychange", () => {
  if (document.hidden && laneBandTimer !== null) {
    window.clearTimeout(laneBandTimer);
    laneBandTimer = null;
  } else if (!document.hidden) {
    scheduleLaneBand();
  }
});

initLabPreferences();
setLaneBand(0);
renderBoard();
boot();
