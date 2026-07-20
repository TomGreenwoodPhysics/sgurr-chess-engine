import { OPENING_BOOK, START_FEN } from "./config.js";
import { app } from "./state.js";
import { fenPositionKey } from "./utils.js";

function recogniseOpening(moves = app.moves, startFen = app.startFen) {
  if (fenPositionKey(startFen) !== fenPositionKey(START_FEN) || !moves.length) {
    return null;
  }

  let bestMatch = null;
  for (const opening of OPENING_BOOK) {
    const matches = opening.moves.every((move, index) => moves[index] === move);
    if (matches && (!bestMatch || opening.moves.length > bestMatch.moves.length)) {
      bestMatch = opening;
    }
  }
  return bestMatch;
}

function updateOpeningState() {
  app.currentOpening = recogniseOpening();
}

function maybeOpeningReaction() {
  const opening = app.currentOpening;
  if (!opening || app.gameOver || app.moves.length < 2) {
    return null;
  }

  const depth = opening.moves.length;
  const isNewBranch = opening.key !== app.openingAnnouncedKey;
  const isMeaningfullyDeeper = depth >= app.openingAnnouncedDepth + 2;
  if (app.openingAnnouncedKey && (!isNewBranch || !isMeaningfullyDeeper)) {
    return null;
  }

  app.openingAnnouncedKey = opening.key;
  app.openingAnnouncedDepth = depth;
  return opening.line;
}

export {
  recogniseOpening,
  updateOpeningState,
  maybeOpeningReaction,
};
