import { app } from "./state.js";

// Post-game review: step back through a finished game with the evaluation
// beside it, and find the moment it turned.
//
// This keeps its own per-ply record rather than reusing app.evalHistory,
// which is deliberately capped at the last 36 points for the live sparkline
// and so cannot describe a whole game. Recording is cheap -- one small object
// per ply -- and the record doubles as the position source, so review can
// re-render the real board instead of needing a second board renderer.
//
// Imports are limited to state on purpose: ui.js and engine.js depend on this
// module, so depending on them back would close an import cycle.

// Mate is stored as +/-100000 so it sorts correctly, but that number would
// swamp both the graph and the swing arithmetic. Everything numeric here
// works on the clamped value; the human-readable string from the server
// ("+0.8", "M3") is what actually gets displayed.
const SWING_CLAMP_CP = 2000;

function clampCp(cp) {
  return Math.max(-SWING_CLAMP_CP, Math.min(SWING_CLAMP_CP, cp));
}

function centipawns(evalInfo) {
  if (!evalInfo) {
    return null;
  }
  if (evalInfo.kind === "mate") {
    return evalInfo.value > 0 ? 100000 : -100000;
  }
  return Number(evalInfo.value) || 0;
}

function defaultReview() {
  return { active: false, index: 0, plies: [] };
}

// "1." for White's first move, "1..." for Black's reply.
function plyLabel(ply) {
  if (ply <= 0) {
    return "Start";
  }
  const moveNumber = Math.ceil(ply / 2);
  return ply % 2 === 1 ? `${moveNumber}.` : `${moveNumber}...`;
}

function plyMoveText(entry) {
  if (!entry || entry.ply <= 0) {
    return "Start position";
  }
  return `${plyLabel(entry.ply)} ${entry.san || entry.uci || "?"}`;
}

// Called on every server state. Keyed by ply so a repeated update for the
// same ply overwrites rather than duplicating, and the truncation keeps the
// record honest when plies are taken back or a new game starts.
//
// `freshEval` matters more than it looks. The player-move path applies its
// response with keepEval: true, so after a human move app.latestEval still
// holds the score from the engine's *previous* search. Recording that would
// be a lie twice over: it draws a flat segment on the graph where no
// evaluation happened, and -- because the stale point sits between the two
// real ones -- it shrinks the swing span onto the engine's reply and blames
// the wrong move. Only genuinely scored positions get a cp.
function recordReviewPly({ freshEval = true } = {}) {
  if (app.mode !== "game") {
    return;
  }
  const ply = app.moves.length;
  const cp = freshEval ? centipawns(app.latestEval) : null;
  app.review.plies[ply] = {
    ply,
    fen: app.fen,
    uci: app.lastMoveInfo?.uci || null,
    san: app.lastMoveInfo?.san || null,
    by: app.lastMoveInfo?.by || null,
    cp,
    kind: cp === null ? null : app.latestEval?.kind || "cp",
    display: cp === null ? null : app.latestEval?.display || null,
  };
  if (app.review.plies.length > ply + 1) {
    app.review.plies.length = ply + 1;
  }
}

function resetReview() {
  app.review = defaultReview();
}

function reviewEntries() {
  return app.review.plies.filter(Boolean);
}

function reviewCurrent() {
  const entries = reviewEntries();
  if (!entries.length) {
    return null;
  }
  const index = Math.max(0, Math.min(app.review.index, entries.length - 1));
  return entries[index];
}

// Only plies the engine actually scored. The engine searches on its own turn,
// so evals land roughly every other ply; the gap between two of them brackets
// one human move and its reply, which is exactly the span a swing describes.
function reviewEvalSeries() {
  return reviewEntries()
    .filter((entry) => entry.cp !== null && entry.cp !== undefined)
    .map((entry) => ({ ply: entry.ply, cp: clampCp(entry.cp), display: entry.display }));
}

// The sharpest turn against the human, in centipawns, together with the move
// that spans it. Returns null when there is nothing to say -- a game too short
// to have two scored positions, or a self-play game with no human side.
function reviewSwing() {
  if (app.humanSide === null) {
    return null;
  }
  const series = reviewEvalSeries();
  if (series.length < 2) {
    return null;
  }

  // Evals are white-relative (the backend sets perspective: "white"), so a
  // Black-playing human reads every delta the other way round.
  const humanSign = app.humanSide === "white" ? 1 : -1;
  let worst = null;
  for (let i = 1; i < series.length; i += 1) {
    const delta = (series[i].cp - series[i - 1].cp) * humanSign;
    if (worst === null || delta < worst.delta) {
      worst = {
        delta,
        fromPly: series[i - 1].ply,
        toPly: series[i].ply,
        fromDisplay: series[i - 1].display,
        toDisplay: series[i].display,
      };
    }
  }

  // A game the human never lost ground in has no turning point worth naming.
  if (!worst || worst.delta >= 0) {
    return null;
  }

  // Name the human's own move inside the span where possible; fall back to
  // the ply the swing landed on.
  const entries = reviewEntries();
  const spanned = entries.filter(
    (entry) => entry.ply > worst.fromPly && entry.ply <= worst.toPly,
  );
  const humanMove = spanned.find((entry) => entry.by === "player") || spanned[spanned.length - 1];

  return {
    ...worst,
    ply: humanMove?.ply ?? worst.toPly,
    moveText: plyMoveText(humanMove),
    pawns: Math.abs(worst.delta) / 100,
  };
}

// The engine's most recent assessment at or before the position on screen.
// Not every ply is scored, so the eval column would otherwise sit on the
// game's *final* score while you scrub through positions where it was not
// remotely true. Walking backwards to the last real evaluation keeps the
// column, the graph and the board describing the same moment.
function reviewEvalAt(index) {
  const entries = reviewEntries();
  for (let i = Math.min(index, entries.length - 1); i >= 0; i -= 1) {
    const entry = entries[i];
    if (entry.cp !== null && entry.cp !== undefined) {
      return { kind: entry.kind || "cp", value: entry.cp, display: entry.display };
    }
  }
  return null;
}

function reviewIndexForPly(ply) {
  const entries = reviewEntries();
  const found = entries.findIndex((entry) => entry.ply === ply);
  return found === -1 ? entries.length - 1 : found;
}

function enterReview() {
  const entries = reviewEntries();
  if (!entries.length) {
    return false;
  }
  app.review.active = true;
  // Open on the turning point when there is one: the answer to "where did
  // that go wrong" is the reason to open a review at all.
  const swing = reviewSwing();
  app.review.index = swing ? reviewIndexForPly(swing.ply) : entries.length - 1;
  return true;
}

function exitReview() {
  app.review.active = false;
}

function reviewGoto(index) {
  const entries = reviewEntries();
  if (!entries.length) {
    return;
  }
  app.review.index = Math.max(0, Math.min(index, entries.length - 1));
}

function reviewStep(direction) {
  reviewGoto(app.review.index + direction);
}

export {
  defaultReview,
  resetReview,
  recordReviewPly,
  reviewEntries,
  reviewCurrent,
  reviewEvalSeries,
  reviewEvalAt,
  reviewSwing,
  reviewIndexForPly,
  enterReview,
  exitReview,
  reviewGoto,
  reviewStep,
  plyLabel,
  plyMoveText,
};
