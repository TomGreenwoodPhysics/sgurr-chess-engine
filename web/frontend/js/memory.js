import { app } from "./state.js";

function defaultBlobMemory() {
  return {
    version: 1,
    games: 0,
    wins: 0,
    losses: 0,
    draws: 0,
    longestPly: 0,
    totalPly: 0,
    openings: {},
  };
}

function loadBlobMemory() {
  const fallback = defaultBlobMemory();
  try {
    const stored = JSON.parse(localStorage.getItem("sgurrBlobMemory") || "null");
    if (!stored || typeof stored !== "object") {
      return fallback;
    }

    const nonNegative = (value) => Math.max(0, Math.floor(Number(value) || 0));
    const openings = {};
    if (stored.openings && typeof stored.openings === "object") {
      for (const [key, record] of Object.entries(stored.openings)) {
        if (!record || typeof record !== "object") {
          continue;
        }
        const count = nonNegative(record.count);
        const name = String(record.name || "").trim();
        if (count && name) {
          openings[key] = { name, count };
        }
      }
    }

    return {
      version: 1,
      games: nonNegative(stored.games),
      wins: nonNegative(stored.wins),
      losses: nonNegative(stored.losses),
      draws: nonNegative(stored.draws),
      longestPly: nonNegative(stored.longestPly),
      totalPly: nonNegative(stored.totalPly),
      openings,
    };
  } catch {
    return fallback;
  }
}

function saveBlobMemory() {
  localStorage.setItem("sgurrBlobMemory", JSON.stringify(app.memory));
}

function favoriteMemoryOpening() {
  return Object.values(app.memory.openings).sort((left, right) => right.count - left.count)[0] || null;
}

function blobMemoryGreeting(side) {
  if (side === null || !app.memory.games) {
    return side === null ? "Self-play ready" : "Engine ready";
  }

  const favorite = favoriteMemoryOpening();
  if (favorite?.count >= 2) {
    return `${favorite.name} has appeared in ${favorite.count} previous games.`;
  }
  return `Starting game ${app.memory.games + 1} in this browser.`;
}

function recordCompletedEncounter() {
  if (app.memoryRecorded || !app.gameOver || app.humanSide === null || !app.result) {
    return;
  }

  const winner = app.winner || (app.result === "1-0" ? "white" : app.result === "0-1" ? "black" : null);
  app.memory.games += 1;
  app.memory.totalPly += app.moves.length;
  app.memory.longestPly = Math.max(app.memory.longestPly, app.moves.length);
  if (!winner) {
    app.memory.draws += 1;
  } else if (winner === app.humanSide) {
    app.memory.wins += 1;
  } else {
    app.memory.losses += 1;
  }

  if (app.currentOpening) {
    const previous = app.memory.openings[app.currentOpening.key] || {
      name: app.currentOpening.name,
      count: 0,
    };
    app.memory.openings[app.currentOpening.key] = {
      name: app.currentOpening.name,
      count: previous.count + 1,
    };
  }

  app.memoryRecorded = true;
  saveBlobMemory();
}

export {
  defaultBlobMemory,
  loadBlobMemory,
  saveBlobMemory,
  favoriteMemoryOpening,
  blobMemoryGreeting,
  recordCompletedEncounter,
};
