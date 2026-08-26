const PIECE_TYPES = Object.freeze({ p: 0, n: 1, b: 2, r: 3, q: 4, k: 5 });
const PIECE_NAMES = Object.freeze(["pawn", "knight", "bishop", "rook", "queen", "king"]);

const EXPECTED_NETWORK = Object.freeze({
  magic: "RUKN",
  bytes: 592160,
  version: 1,
  input: 768,
  hidden: 384,
  qa: 255,
  qb: 64,
  scale: 400,
  sha256: "896eb832d74776a42375e7fa152b4e032fff1cf85ba2e529b420fe2d1b4b74bf",
});

function readInt16Array(view, offset, count) {
  const values = new Int16Array(count);
  for (let index = 0; index < count; index += 1) {
    values[index] = view.getInt16(offset + index * 2, true);
  }
  return values;
}

function parseNnue(buffer) {
  if (!(buffer instanceof ArrayBuffer)) {
    throw new Error("Network response is not binary");
  }
  if (buffer.byteLength !== EXPECTED_NETWORK.bytes) {
    throw new Error("Unexpected network size");
  }

  const view = new DataView(buffer);
  const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 4));
  const version = view.getUint32(4, true);
  const input = view.getUint32(8, true);
  const hidden = view.getUint32(12, true);
  const qa = view.getUint32(16, true);
  const qb = view.getUint32(20, true);
  const scale = view.getUint32(24, true);
  if (
    magic !== EXPECTED_NETWORK.magic
    || version !== EXPECTED_NETWORK.version
    || input !== EXPECTED_NETWORK.input
    || hidden !== EXPECTED_NETWORK.hidden
    || qa !== EXPECTED_NETWORK.qa
    || qb !== EXPECTED_NETWORK.qb
    || scale !== EXPECTED_NETWORK.scale
  ) {
    throw new Error("Network architecture does not match Sgurr Gen8");
  }

  let offset = 28;
  const featureWeights = readInt16Array(view, offset, input * hidden);
  offset += featureWeights.byteLength;
  const featureBias = readInt16Array(view, offset, hidden);
  offset += featureBias.byteLength;
  const outputWeights = readInt16Array(view, offset, hidden * 2);
  offset += outputWeights.byteLength;
  const outputBias = view.getInt32(offset, true);

  return {
    magic,
    version,
    input,
    hidden,
    qa,
    qb,
    scale,
    featureWeights,
    featureBias,
    outputWeights,
    outputBias,
  };
}

function squareName(square) {
  return `${"abcdefgh"[square % 8]}${Math.floor(square / 8) + 1}`;
}

function parseFen(fen) {
  const fields = String(fen || "").trim().split(/\s+/);
  if (fields.length < 2) {
    throw new Error("Incomplete FEN");
  }
  const rows = fields[0].split("/");
  if (rows.length !== 8) {
    throw new Error("FEN must contain eight ranks");
  }

  const pieces = [];
  rows.forEach((row, rowIndex) => {
    let file = 0;
    for (const token of row) {
      if (/^[1-8]$/.test(token)) {
        file += Number(token);
        continue;
      }
      const ptype = PIECE_TYPES[token.toLowerCase()];
      if (ptype === undefined || file >= 8) {
        throw new Error("Invalid FEN placement");
      }
      const colour = token === token.toUpperCase() ? 0 : 1;
      const square = (7 - rowIndex) * 8 + file;
      pieces.push({
        piece: token,
        colour,
        ptype,
        square,
        squareName: squareName(square),
        label: `${colour === 0 ? "White" : "Black"} ${PIECE_NAMES[ptype]}`,
      });
      file += 1;
    }
    if (file !== 8) {
      throw new Error("Invalid FEN rank width");
    }
  });

  return {
    fen: fields.join(" "),
    pieces,
    sideToMove: fields[1] === "b" ? 1 : 0,
  };
}

function featureIndex(perspective, piece) {
  const relativeSquare = perspective === 0 ? piece.square : piece.square ^ 56;
  const relativeColour = piece.colour === perspective ? 0 : 1;
  return relativeColour * 384 + piece.ptype * 64 + relativeSquare;
}

function clipped(value, qa) {
  return Math.max(0, Math.min(qa, value));
}

function evaluateFen(network, fen) {
  const position = parseFen(fen);
  const whiteAccumulator = Int32Array.from(network.featureBias);
  const blackAccumulator = Int32Array.from(network.featureBias);
  const activeFeatures = [];

  for (const piece of position.pieces) {
    const whiteIndex = featureIndex(0, piece);
    const blackIndex = featureIndex(1, piece);
    const whiteOffset = whiteIndex * network.hidden;
    const blackOffset = blackIndex * network.hidden;
    for (let lane = 0; lane < network.hidden; lane += 1) {
      whiteAccumulator[lane] += network.featureWeights[whiteOffset + lane];
      blackAccumulator[lane] += network.featureWeights[blackOffset + lane];
    }
    activeFeatures.push({ ...piece, whiteIndex, blackIndex });
  }

  const whiteActivation = new Uint16Array(network.hidden);
  const blackActivation = new Uint16Array(network.hidden);
  const whiteOutputOffset = position.sideToMove === 0 ? 0 : network.hidden;
  const blackOutputOffset = position.sideToMove === 1 ? 0 : network.hidden;
  const whiteOutputWeights = network.outputWeights.slice(
    whiteOutputOffset,
    whiteOutputOffset + network.hidden,
  );
  const blackOutputWeights = network.outputWeights.slice(
    blackOutputOffset,
    blackOutputOffset + network.hidden,
  );
  const whiteContribution = new Int32Array(network.hidden);
  const blackContribution = new Int32Array(network.hidden);
  let raw = network.outputBias;
  let clippedLow = 0;
  let clippedHigh = 0;

  for (let lane = 0; lane < network.hidden; lane += 1) {
    const whiteValue = clipped(whiteAccumulator[lane], network.qa);
    const blackValue = clipped(blackAccumulator[lane], network.qa);
    whiteActivation[lane] = whiteValue;
    blackActivation[lane] = blackValue;
    if (whiteAccumulator[lane] <= 0) clippedLow += 1;
    if (blackAccumulator[lane] <= 0) clippedLow += 1;
    if (whiteAccumulator[lane] >= network.qa) clippedHigh += 1;
    if (blackAccumulator[lane] >= network.qa) clippedHigh += 1;
    whiteContribution[lane] = whiteValue * whiteOutputWeights[lane];
    blackContribution[lane] = blackValue * blackOutputWeights[lane];
    raw += whiteContribution[lane] + blackContribution[lane];
  }

  const centipawns = Math.max(
    -29000,
    Math.min(29000, Math.trunc((raw * network.scale) / (network.qa * network.qb))),
  );

  return {
    fen: position.fen,
    sideToMove: position.sideToMove,
    pieces: position.pieces,
    activeFeatures,
    whiteAccumulator,
    blackAccumulator,
    whiteActivation,
    blackActivation,
    whiteOutputWeights,
    blackOutputWeights,
    whiteContribution,
    blackContribution,
    raw,
    centipawns,
    whiteRelative: position.sideToMove === 0 ? centipawns : -centipawns,
    clippedLow,
    clippedHigh,
    activeLaneCount: network.hidden * 2 - clippedLow,
  };
}

function positionEdits(before, after) {
  const beforeMap = new Map(before.activeFeatures.map((piece) => [piece.square, piece]));
  const afterMap = new Map(after.activeFeatures.map((piece) => [piece.square, piece]));
  const removed = [];
  const added = [];

  for (const [square, piece] of beforeMap) {
    if (afterMap.get(square)?.piece !== piece.piece) {
      removed.push(piece);
    }
  }
  for (const [square, piece] of afterMap) {
    if (beforeMap.get(square)?.piece !== piece.piece) {
      added.push(piece);
    }
  }
  return { removed, added };
}

function evaluateTransition(network, beforeFen, afterFen) {
  const before = beforeFen ? evaluateFen(network, beforeFen) : null;
  const after = evaluateFen(network, afterFen);
  const whiteDelta = new Int32Array(network.hidden);
  const blackDelta = new Int32Array(network.hidden);
  let changedLaneValues = 0;

  if (before) {
    for (let lane = 0; lane < network.hidden; lane += 1) {
      whiteDelta[lane] = after.whiteAccumulator[lane] - before.whiteAccumulator[lane];
      blackDelta[lane] = after.blackAccumulator[lane] - before.blackAccumulator[lane];
      if (whiteDelta[lane] !== 0) changedLaneValues += 1;
      if (blackDelta[lane] !== 0) changedLaneValues += 1;
    }
  }

  const edits = before ? positionEdits(before, after) : { removed: [], added: [] };
  const pieceSquareEdits = edits.removed.length + edits.added.length;
  return {
    before,
    after,
    whiteDelta,
    blackDelta,
    edits,
    pieceSquareEdits,
    weightRowUpdates: pieceSquareEdits * 2,
    laneOperations: pieceSquareEdits * network.hidden * 2,
    changedLaneValues,
  };
}

export {
  EXPECTED_NETWORK,
  evaluateFen,
  evaluateTransition,
  featureIndex,
  parseFen,
  parseNnue,
};
