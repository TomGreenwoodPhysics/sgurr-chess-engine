import { app } from "./state.js";

// Handles post-game positions, evaluations, and turning points.
// Review stores every ply because app.evalHistory only keeps the live graph window.
// Import only state to avoid a cycle with ui.js and engine.js.

// Clamp mate scores for graphs and swing calculations. Display the server's original label.
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

// Replace records by ply and truncate after takebacks or restarts.
// Record a score only when freshEval is true because human moves may retain the previous score.
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

// Keep only engine-scored plies. Each gap covers a human move and its reply.
function reviewEvalSeries() {
  return reviewEntries()
    .filter((entry) => entry.cp !== null && entry.cp !== undefined)
    .map((entry) => ({ ply: entry.ply, cp: clampCp(entry.cp), display: entry.display }));
}

// Return the largest swing against the human, or null when it cannot be calculated.
function reviewSwing() {
  if (app.humanSide === null) {
    return null;
  }
  const series = reviewEvalSeries();
  if (series.length < 2) {
    return null;
  }

  // Scores are White-relative, so invert deltas for a human playing Black.
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

  // Prefer the human move within the swing. Fall back to the ending ply.
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

// Use the latest scored evaluation at or before the displayed position.
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
  // Open on the turning point when available.
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
