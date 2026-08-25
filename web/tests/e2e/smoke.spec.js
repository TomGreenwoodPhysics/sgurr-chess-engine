import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { startStaticServer } from "../static-server.mjs";

const API_BASE = "http://127.0.0.1:8000";
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1";
const AFTER_E4_E5_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2";
const PROMOTION_FEN = "7k/P7/8/8/8/8/8/7K w - - 0 1";
const NNUE_SHA256 = "896eb832d74776a42375e7fa152b4e032fff1cf85ba2e529b420fe2d1b4b74bf";
const NNUE_BYTES = readFileSync(new URL("../../../nets/gen8.nnue", import.meta.url));

const WHITE_START_MOVES = [
  "a2a3", "a2a4", "b2b3", "b2b4", "c2c3", "c2c4", "d2d3", "d2d4",
  "e2e3", "e2e4", "f2f3", "f2f4", "g2g3", "g2g4", "h2h3", "h2h4",
  "b1a3", "b1c3", "g1f3", "g1h3",
];
const BLACK_START_MOVES = WHITE_START_MOVES.map((move) => (
  `${move[0]}${9 - Number(move[1])}${move[2]}${9 - Number(move[3])}`
));

const FULL_MATERIAL = {
  white: 39,
  black: 39,
  diff: 0,
  captured: { white: [], black: [] },
};

function gameState({
  fen = START_FEN,
  startFen = START_FEN,
  turn = "white",
  legalMoves = WHITE_START_MOVES,
  premoveMoves = BLACK_START_MOVES,
  moves = [],
  moveRows = [],
  lastMove = null,
  latestEval = null,
  gameOver = false,
  result = null,
  winner = null,
  reason = null,
} = {}) {
  return {
    fen,
    start_fen: startFen,
    turn,
    legal_moves: legalMoves,
    premove_moves: premoveMoves,
    moves,
    move_rows: moveRows,
    last_move: lastMove,
    latest_eval: latestEval,
    in_check: false,
    material: FULL_MATERIAL,
    can_mate: { white: true, black: true },
    game_over: gameOver,
    result,
    winner,
    reason,
  };
}

const INITIAL_STATE = gameState();
const AFTER_E4_STATE = gameState({
  fen: AFTER_E4_FEN,
  turn: "black",
  legalMoves: BLACK_START_MOVES,
  premoveMoves: WHITE_START_MOVES,
  moves: ["e2e4"],
  moveRows: [{ number: 1, white: "e4", black: "" }],
  lastMove: { uci: "e2e4", san: "e4", by: "engine" },
});
const AFTER_E4_E5_STATE = gameState({
  fen: AFTER_E4_E5_FEN,
  legalMoves: [
    "a2a3", "a2a4", "b2b3", "b2b4", "c2c3", "c2c4", "d2d3", "d2d4",
    "f2f3", "f2f4", "g2g3", "g2g4", "h2h3", "h2h4", "b1a3", "b1c3",
    "g1e2", "g1f3", "g1h3", "f1e2", "f1d3", "f1c4", "f1b5", "f1a6",
    "d1e2", "e1e2",
  ],
  moves: ["e2e4", "e7e5"],
  moveRows: [{ number: 1, white: "e4", black: "e5" }],
  lastMove: { uci: "e7e5", san: "e5", by: "engine" },
  latestEval: {
    kind: "cp",
    value: 18,
    display: "+0.2",
    depth: 8,
    nodes: 1200,
    time_ms: 12,
    pv: ["g1f3"],
    perspective: "white",
  },
});
// A game that turns: White stands slightly better after 1.e4 e5, then throws
// it away over 2.Nf3 Nc6. Two scored positions either side of a human move is
// the minimum a turning point needs, and the drop is signed white-relative
// exactly as the backend sends it.
const AFTER_NF3_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2";
const AFTER_NC6_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3";

const AFTER_NF3_STATE = gameState({
  fen: AFTER_NF3_FEN,
  turn: "black",
  legalMoves: ["b8c6", "b8a6", "g8f6", "d7d6", "d7d5", "f8e7"],
  premoveMoves: ["f1c4", "f1b5", "b1c3", "d2d4"],
  moves: ["e2e4", "e7e5", "g1f3"],
  moveRows: [
    { number: 1, white: "e4", black: "e5" },
    { number: 2, white: "Nf3", black: "" },
  ],
  lastMove: { uci: "g1f3", san: "Nf3", by: "player" },
});

const COLLAPSE_STATE = gameState({
  fen: AFTER_NC6_FEN,
  legalMoves: [],
  premoveMoves: [],
  moves: ["e2e4", "e7e5", "g1f3", "b8c6"],
  moveRows: [
    { number: 1, white: "e4", black: "e5" },
    { number: 2, white: "Nf3", black: "Nc6" },
  ],
  lastMove: { uci: "b8c6", san: "Nc6", by: "engine" },
  latestEval: {
    kind: "cp",
    value: -350,
    display: "-3.5",
    depth: 9,
    nodes: 4200,
    time_ms: 30,
    pv: ["f1c4"],
    perspective: "white",
  },
  gameOver: true,
  result: "1/2-1/2",
  reason: "threefold_repetition",
});

const WATCH_DRAW_STATE = gameState({
  fen: AFTER_E4_FEN,
  turn: "black",
  legalMoves: BLACK_START_MOVES,
  premoveMoves: WHITE_START_MOVES,
  moves: ["e2e4"],
  moveRows: [{ number: 1, white: "e4", black: "" }],
  lastMove: { uci: "e2e4", san: "e4", by: "engine" },
  gameOver: true,
  result: "1/2-1/2",
  reason: "threefold_repetition",
});

function json(route, body, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function installMockBackend(page, {
  finishWatch = false,
  engineExists = true,
  publicDemo = false,
  mateOpening = false,
  nnueAvailable = true,
} = {}) {
  const calls = [];
  await page.route(`${API_BASE}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (path === `/api/nnue/gen8/${NNUE_SHA256}.nnue`) {
      if (!nnueAvailable) {
        await json(route, { detail: "NNUE Lab unavailable" }, 503);
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/octet-stream",
        headers: { "Cache-Control": "public, max-age=31536000, immutable" },
        body: NNUE_BYTES,
      });
      return;
    }
    if (path.startsWith("/assets/")) {
      await route.fulfill({ status: 204, contentType: "application/octet-stream", body: "" });
      return;
    }
    if (path === "/health") {
      await json(route, {
        ok: true,
        engine_exists: engineExists,
        engine_running: false,
        python_chess: "test",
        public_demo: publicDemo,
      });
      return;
    }
    if (path === "/api/engines") {
      await json(route, {
        default: "v8.2",
        public_demo: publicDemo,
        engines: [
          {
            id: "v8.2",
            label: 'Sgurr v8.2 "Thearlaich"',
            subtitle: "GEN8 NNUE + PACKED TT · ~3012",
            tech: "GEN8 NNUE + PACKED TT",
            rating: 3012,
            available: engineExists,
          },
          {
            id: "v8.1",
            label: 'Sgurr v8.1 "Thearlaich"',
            subtitle: "GEN8 NNUE + PGO SPEED · ~2981",
            tech: "GEN8 NNUE + PGO SPEED",
            rating: 2981,
            available: !publicDemo && engineExists,
            unavailable_reason: "Available locally; the free demo includes Sgurr v8.2 only.",
            unavailable_badge: "LOCAL ONLY",
          },
        ],
      });
      return;
    }
    if (path === "/api/capabilities") {
      await json(route, {
        public_demo: publicDemo,
        self_play: !publicDemo,
        limits: {
          search_network_depth: publicDemo ? 12 : 20,
          search_trace_movetime_ms: publicDemo ? 5000 : 5000,
        },
      });
      return;
    }

    const body = request.method() === "POST" ? request.postDataJSON() : null;
    calls.push({ path, body });
    if (path === "/api/new") {
      await json(route, INITIAL_STATE);
      return;
    }
    if (path === "/api/load-fen") {
      if (body.fen === "bad fen") {
        await json(route, { detail: "Invalid FEN" }, 400);
        return;
      }
      if (body.fen === START_FEN) {
        await json(route, INITIAL_STATE);
        return;
      }
      const kingsOnly = body.fen.startsWith("4k3/8/8/8/8/8/8/4K3");
      const promotion = body.fen === PROMOTION_FEN;
      await json(route, gameState({
        fen: body.fen,
        startFen: body.fen,
        turn: body.fen.split(" ")[1] === "b" ? "black" : "white",
        legalMoves: kingsOnly
          ? []
          : promotion
            ? ["a7a8q", "a7a8r", "a7a8b", "a7a8n"]
            : ["e1d1", "e1f1"],
        premoveMoves: [],
        gameOver: kingsOnly,
        result: kingsOnly ? "1/2-1/2" : null,
        reason: kingsOnly ? "insufficient_material" : null,
      }));
      return;
    }
    if (path === "/api/search-trace") {
      const events = [
        { type: "started", engine: "v8.2", label: 'Sgurr v8.2 "Thearlaich"', perspective: "white", movetime_ms: 5000 },
        {
          type: "iteration", kind: "cp", value: 8, display: "+0.1", depth: 3,
          nodes: 720, nps: 240000, time_ms: 3, pv: ["d2d4"],
          pv_san: ["d4"], pv_fens: [START_FEN],
        },
        {
          type: "iteration", kind: "cp", value: 18, display: "+0.2", depth: 6,
          nodes: 8200, nps: 820000, time_ms: 10, pv: ["e2e4", "e7e5"],
          pv_san: ["e4", "e5"], pv_fens: [START_FEN, AFTER_E4_FEN, AFTER_E4_E5_FEN],
        },
        {
          type: "iteration", kind: "cp", value: 31, display: "+0.3", depth: 12,
          nodes: 1271020, nps: 3652356, time_ms: 348, pv: ["e2e4", "e7e5", "g1f3"],
          pv_san: ["e4", "e5", "Nf3"], pv_fens: [START_FEN, AFTER_E4_FEN, AFTER_E4_E5_FEN, AFTER_NF3_FEN],
        },
        {
          type: "complete", bestmove: "e2e4", bestmove_san: "e4",
          final: {
            kind: "cp", value: 31, display: "+0.3", depth: 12,
            nodes: 1271020, nps: 3652356, time_ms: 348, pv: ["e2e4", "e7e5", "g1f3"],
            pv_san: ["e4", "e5", "Nf3"], pv_fens: [START_FEN, AFTER_E4_FEN, AFTER_E4_E5_FEN, AFTER_NF3_FEN],
          },
        },
      ];
      await route.fulfill({
        status: 200,
        contentType: "application/x-ndjson",
        body: `${events.map((event) => JSON.stringify(event)).join("\n")}\n`,
      });
      return;
    }
    if (path === "/api/player-move" && body?.move === "e2e4") {
      await json(route, { ...AFTER_E4_STATE, last_move: { ...AFTER_E4_STATE.last_move, by: "player" } });
      return;
    }
    if (path === "/api/player-move" && body?.move === "g1f3") {
      await json(route, AFTER_NF3_STATE);
      return;
    }
    if (path === "/api/engine-move") {
      if (finishWatch) {
        await json(route, WATCH_DRAW_STATE);
      } else if (body?.fen === START_FEN) {
        await json(route, mateOpening ? {
          ...AFTER_E4_STATE,
          latest_eval: {
            kind: "mate",
            value: -4,
            display: "-M4",
            depth: 12,
            nodes: 5800,
            time_ms: 42,
            pv: ["e2e4"],
            perspective: "white",
          },
        } : AFTER_E4_STATE);
      } else if (body?.fen === AFTER_E4_FEN) {
        await json(route, AFTER_E4_E5_STATE);
      } else if (body?.fen === AFTER_NF3_FEN) {
        await json(route, COLLAPSE_STATE);
      } else {
        await json(route, { detail: `Unexpected engine FEN: ${body?.fen}` }, 400);
      }
      return;
    }
    await json(route, { detail: `No test route for ${path}` }, 404);
  });
  return calls;
}

async function openMainMenu(page) {
  await page.goto("/");
  await page.locator("#wakeSgurrButton").click();
  await expect(page.locator("#introScreen")).toBeHidden();
  await expect(page.locator("#menuStatus")).toHaveText("Ready");
}

let pageErrors;
let staticServer;

test.beforeAll(async () => {
  staticServer = await startStaticServer();
});

test.afterAll(async () => {
  staticServer.closeAllConnections?.();
  await new Promise((resolve, reject) => {
    staticServer.close((error) => error ? reject(error) : resolve());
  });
});

test.beforeEach(async ({ page }) => {
  pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem("sgurrAnimationMode", "Off");
    localStorage.setItem("sgurrSoundEnabled", "false");
    localStorage.setItem("sgurrMusicEnabled", "false");
    localStorage.setItem("sgurrGameMusicEnabled", "false");
  });
});

test.afterEach(() => {
  expect(pageErrors).toEqual([]);
});

test("wakes into the default Classic Wood menu with playable controls", async ({ page }) => {
  await installMockBackend(page);
  await openMainMenu(page);

  await expect(page.locator("html")).toHaveAttribute("data-theme", "wood");
  await expect(page.locator("#menuScreen")).toBeVisible();
  await expect(page.locator("#playWhiteButton")).toBeEnabled();
  await expect(page.locator("#playBlackButton")).toBeEnabled();
  await expect(page.locator("#watchButton")).toBeEnabled();
  await expect(page.locator(".menu-action-card")).toHaveCount(6);
  await expect(page.locator(".menu-action-card small")).toHaveCount(0);
  await expect(page.locator(".search-lab-link strong")).toHaveText("Search Lab");
  await expect(page.locator(".search-lab-link")).toHaveAttribute("href", "search-lab/?mode=network");
  await expect(page.locator(".inside-sgurr-link strong")).toHaveText("Inside Sgurr");
  await expect(page.locator(".inside-sgurr-link")).toHaveAttribute("href", "inside-sgurr/");
});

test("opens Sgurr's exact NNUE evaluator and reveals a move update", async ({ page }) => {
  test.setTimeout(30_000);
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");

  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");
  await expect(page.locator("#nnueBoard .board-square")).toHaveCount(64);
  await expect(page.locator("#modelStatus")).toContainText("Gen8 v1 loaded");
  await expect(page.locator("#nnueEval")).toHaveText("+0.32");
  await expect(page.locator(".signal-path li")).toHaveCount(4);
  await expect(page.locator(".visual-key > div")).toHaveCount(6);
  const boardGeometry = await page.evaluate(() => {
    const board = document.querySelector("#nnueBoard").getBoundingClientRect();
    const occupied = document.querySelector('[data-square="a8"]').getBoundingClientRect();
    const empty = document.querySelector('[data-square="a4"]').getBoundingClientRect();
    return {
      width: board.width,
      ratioError: Math.abs(board.width - board.height),
      rowError: Math.abs(occupied.height - empty.height),
    };
  });
  expect(boardGeometry.width).toBeGreaterThan(380);
  expect(boardGeometry.ratioError).toBeLessThanOrEqual(1);
  expect(boardGeometry.rowError).toBeLessThanOrEqual(1);
  await expect(page.locator("#cortexViewButton")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-view", "cortex");
  await page.locator('[data-lane-band="2"]').click();
  await expect(page.locator('[data-lane-band="2"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-atlas-band", "2");
  await expect(page.locator("#laneAtlasDetail")).toContainText("192–287");
  await page.locator("#cortexCanvas").focus();
  for (let step = 0; step < 16; step += 1) await page.keyboard.press("ArrowRight");
  await expect(page.locator("#laneAddress")).toHaveText("B:000");

  await page.locator("#circuitViewButton").click();
  await expect(page.locator("#circuitViewButton")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-view", "circuit");

  await page.locator('[data-square="e2"]').click();
  await expect(page.locator('[data-square="e2"]')).toBeFocused();
  await expect(page.locator('[data-square="e2"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('[data-square="e4"]')).toHaveClass(/legal/);
  await page.locator('[data-square="e4"]').click();
  await expect(page.locator("#nnueEval")).toHaveText("+0.53");
  await expect(page.locator("#pieceEdits")).toHaveText("2");
  await expect(page.locator("#weightRows")).toHaveText("4");
  await expect(page.locator("#laneOperations")).toHaveText("1,536");
  await expect(page.locator("#featureTrace")).toContainText("inputs W 12→28 · B 436→420");
  await expect(page.locator("#beforeState")).toBeEnabled();
  await expect(page.locator("#deltaState")).toBeEnabled();

  await page.locator("#beforeState").click();
  await expect(page.locator("#nnueEval")).toHaveText("+0.32");
  await page.locator("#deltaState").click();
  await expect(page.locator("#nnueEval")).toHaveText("+0.21");
  await expect(page.locator(".eval-readout > span")).toHaveText("White evaluation change");

  await page.locator("#undoPosition").click();
  await expect(page.locator("#nnueEval")).toHaveText("+0.32");
  await expect(page.locator("#positionTurn")).toHaveText("White to move");
  await expect(page.locator('[data-square="e2"] .piece-image')).toBeVisible();
  await expect(page.locator("#undoPosition")).toBeDisabled();
});

test("reads a piece's two feature rows out of the shipped network", async ({ page }) => {
  test.setTimeout(30_000);
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");

  await expect(page.locator("#pieceInspector")).toHaveAttribute("data-state", "idle");
  await page.locator('[data-square="e2"]').click();
  await expect(page.locator("#pieceInspector")).toHaveAttribute("data-state", "ready");
  await expect(page.locator("#pieceInspectorTitle")).toHaveText("White pawn on e2");
  await expect(page.locator("#whiteFeatureIndex")).toHaveText("W:012");
  await expect(page.locator("#blackFeatureIndex")).toHaveText("B:436");
  await expect(page.locator("#whiteFeatureSummary")).toContainText("peak");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-feature", "active");
  await expect(page.locator('[data-square="e2"]')).toHaveClass(/inspected/);

  // A piece with no legal move of its own is still readable.
  await page.locator('[data-square="d8"]').click();
  await expect(page.locator("#pieceInspectorTitle")).toHaveText("Black queen on d8");

  await page.locator("#clearPieceInspector").click();
  await expect(page.locator("#pieceInspector")).toHaveAttribute("data-state", "idle");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-feature", "idle");
  await expect(page.locator('[data-square="d8"]')).not.toHaveClass(/inspected/);
});

test("switches the accumulator display between the four readings", async ({ page }) => {
  test.setTimeout(30_000);
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");

  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-display-mode", "contribution");
  await expect(page.locator("#goldKeyText")).toHaveText("Raises White's score");

  await page.locator('.display-mode-buttons [data-display-mode="clipped"]').click();
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-display-mode", "clipped");
  await expect(page.locator('.display-mode-buttons [data-display-mode="clipped"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('.display-mode-buttons [data-display-mode="contribution"]')).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("#goldKeyText")).toHaveText("Held at 255");
  await expect(page.locator("#cyanKeyText")).toHaveText("Held at 0");

  await page.locator('.display-mode-buttons [data-display-mode="activation"]').click();
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-display-mode", "activation");
  await expect(page.locator("#displayModeNote")).toContainText("0 to 255");
});

test("fades the accumulator display between states instead of cutting", async ({ page }) => {
  test.setTimeout(30_000);
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-motion", "settled");

  await page.locator('.display-mode-buttons [data-display-mode="clipped"]').click();
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-motion", "settling");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-motion", "settled");

  // The halos fade in and back out rather than appearing and vanishing.
  await page.locator('[data-square="e2"]').click();
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-feature", "active");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-motion", "settling");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-motion", "settled");
  await page.locator("#clearPieceInspector").click();
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-motion", "settling");
  await expect(page.locator("#cortexCanvas")).toHaveAttribute("data-motion", "settled");
});

test("walks a move along the evaluation path and back to the current state", async ({ page }) => {
  test.setTimeout(30_000);
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");

  await expect(page.locator("#stateTimeline")).toBeDisabled();
  await page.locator('[data-square="e2"]').click();
  await page.locator('[data-square="e4"]').click();
  await expect(page.locator("#nnueEval")).toHaveText("+0.53");
  await expect(page.locator("#stateTimeline")).toBeEnabled();
  await expect(page.locator(".signal-path")).toHaveAttribute("data-active", "false");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-anatomy", "idle");

  await page.locator("#replayTransition").click();
  await expect(page.locator(".signal-path")).toHaveAttribute("data-active", "true");
  await expect(page.locator(".signal-path li.active")).toHaveCount(1);
  await expect(page.locator(".signal-path")).toHaveAttribute("data-active", "false", { timeout: 8000 });
  await expect(page.locator("#afterState")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#nnueEval")).toHaveText("+0.53");
});

test("scrubs the state timeline through before, change and after", async ({ page }) => {
  test.setTimeout(30_000);
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");

  await page.locator('[data-square="e2"]').click();
  await page.locator('[data-square="e4"]').click();
  await expect(page.locator("#nnueEval")).toHaveText("+0.53");
  await expect(page.locator("#stateTimeline")).toHaveValue("2");

  await page.locator("#stateTimeline").fill("0");
  await expect(page.locator("#nnueEval")).toHaveText("+0.32");
  await expect(page.locator("#beforeState")).toHaveAttribute("aria-pressed", "true");

  await page.locator("#stateTimeline").fill("1");
  await expect(page.locator("#nnueEval")).toHaveText("+0.21");
  await expect(page.locator(".eval-readout > span")).toHaveText("White evaluation change");

  await page.locator("#afterState").click();
  await expect(page.locator("#stateTimeline")).toHaveValue("2");
});

test("shows the quick guide once and remembers it was dismissed", async ({ page }) => {
  test.setTimeout(30_000);
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");

  await expect(page.locator("#insideGuide")).toBeVisible();
  await page.locator("#dismissInsideGuide").click();
  await expect(page.locator("#insideGuide")).toBeHidden();
  expect(await page.evaluate(() => localStorage.getItem("sgurrInsideGuide"))).toBe("dismissed");

  // A returning visitor never sees it again. The shared setup wipes storage on
  // every navigation, so seed the dismissal the way a real second visit would.
  await page.addInitScript(() => localStorage.setItem("sgurrInsideGuide", "dismissed"));
  await page.reload();
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");
  await expect(page.locator("#insideGuide")).toBeHidden();
});

test("keeps the NNUE chamber usable on a narrow screen", async ({ page }) => {
  test.setTimeout(30_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");

  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");
  await expect(page.locator("#cortexViewButton")).toBeVisible();
  await expect(page.locator("#beforeState")).toBeVisible();
  await expect(page.locator("#afterState")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("does not fabricate NNUE activity when the model is unavailable", async ({ page }) => {
  await installMockBackend(page, { nnueAvailable: false });
  await page.goto("/inside-sgurr/");

  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "error");
  await expect(page.locator("#modelStatus")).toHaveText("Evaluator unavailable");
  await expect(page.locator("#loadingTitle")).toHaveText("The evaluator did not open");
  await expect(page.locator("#retryModel")).toBeVisible();
  await expect(page.locator("#nnueEval")).toHaveText("—");
});

test("offers a promotion choice in the NNUE position board", async ({ page }) => {
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");

  await page.locator("#nnueFenInput").fill(PROMOTION_FEN);
  await page.locator("#nnueFenForm .primary-button").click();
  await expect(page.locator('[data-square="a7"]')).toBeEnabled();
  await page.locator('[data-square="a7"]').click();
  await page.locator('[data-square="a8"]').click();
  await expect(page.locator("#promotionDialog")).toBeVisible();
  await expect(page.locator("#promotionDialog .promotion-options button")).toHaveCount(4);
  await page.locator("#promotionDialog .promotion-cancel").click();
  await expect(page.locator("#promotionDialog")).toBeHidden();
  await expect(page.locator('[data-square="a7"] .piece-image')).toBeVisible();
});

test("keeps rejected FEN text available for correction", async ({ page }) => {
  await installMockBackend(page);
  await page.goto("/inside-sgurr/");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");

  await page.locator("#nnueFenInput").fill("bad fen");
  await page.locator("#nnueFenForm .primary-button").click();
  await expect(page.locator("#fenStatus")).toHaveText("Invalid FEN");
  await expect(page.locator("#nnueFenInput")).toHaveValue("bad fen");
  await expect(page.locator("#insideShell")).toHaveAttribute("data-state", "ready");
});

test("uses volume sliders without duplicate audio toggles", async ({ page }) => {
  await installMockBackend(page);
  await openMainMenu(page);
  await page.locator("#menuSettingsButton").click();

  await expect(page.locator("#settingsModal")).toBeVisible();
  await expect(page.locator("#soundEnabledInput, #musicEnabledInput, #gameMusicEnabledInput")).toHaveCount(0);
  await page.locator("#masterVolumeInput").fill("0.55");
  await expect(page.locator("#masterVolumeValue")).toHaveText("55%");
  await page.locator("#musicVolumeInput").fill("0.25");
  await expect(page.locator("#musicVolumeValue")).toHaveText("25%");

  const stored = await page.evaluate(() => ({
    master: localStorage.getItem("sgurrMasterVolume"),
    menu: localStorage.getItem("sgurrMusicVolume"),
    oldMenuToggle: localStorage.getItem("sgurrMusicEnabled"),
  }));
  expect(stored).toEqual({ master: "0.55", menu: "0.25", oldMenuToggle: null });
});

test("shows the remaining mate distance", async ({ page }) => {
  await installMockBackend(page, { mateOpening: true });
  await openMainMenu(page);
  await page.locator("#playBlackButton").click();

  await expect(page.locator("#evalChip")).toHaveText("-M4");
  await expect(page.locator("#evalValue")).toHaveText("-M4");
  await expect(page.locator("#trendValue")).toHaveText("-M4");
});

test("keeps local-only controls visible in the free demo", async ({ page }) => {
  await installMockBackend(page, { publicDemo: true });
  await openMainMenu(page);

  await expect(page.locator("#watchButton")).toHaveAttribute("aria-disabled", "true");
  await expect(page.locator("#watchButton")).toHaveAttribute("title", /available.*locally/i);
  await expect(page.locator("#engineDownButton")).toBeDisabled();
  await expect(page.locator("#engineUpButton")).toBeDisabled();
  await expect(page.locator("#engineDownButton")).toHaveAttribute("data-demo-reason", /v8\.2 only/i);
  await page.locator("#engineDownButton").hover({ force: true });
  await expect(page.locator("#demoTooltip")).toBeVisible();
  await expect(page.locator("#demoTooltip")).toContainText("v8.2 only");

  await page.locator("#menuEngineButton").click();
  const localOnly = page.locator('.engine-card[aria-disabled="true"]');
  await expect(localOnly).toContainText("LOCAL ONLY");
  await expect(localOnly).toHaveAttribute("title", /free demo includes Sgurr v8\.2/i);
  await expect(localOnly).toBeDisabled();
  await localOnly.evaluate((button) => button.click());
  await expect(page.locator("#engineModal")).toBeVisible();
  await expect(page.locator("#menuEngineButton")).toContainText("v8.2");

  await page.locator("#engineModal [data-close-modal]").click();
  await page.locator("#positionLabButton").click();
  await expect(page.locator("#editorPlayerButton")).toHaveAttribute("data-demo-reason", /self-play/i);
  await page.locator("#editorMainMenuButton").click();
  await expect(page.locator("#positionLabButton")).toBeEnabled();
});

test("starts at v8.2 and cycles left through weaker engines", async ({ page }) => {
  await installMockBackend(page);
  await openMainMenu(page);

  await expect(page.locator("#engineDownButton")).toBeEnabled();
  await expect(page.locator("#menuEngineButton")).toContainText("v8.2");
  await page.locator("#engineDownButton").click();
  await expect(page.locator("#menuEngineButton")).toContainText("v8.1");
  await page.locator("#engineDownButton").click();
  await expect(page.locator("#menuEngineButton")).toContainText("v8.2");
});

test("limits Search Network depth on the free demo", async ({ page }) => {
  let releaseCapabilities;
  const capabilitiesResponse = new Promise((resolve) => {
    releaseCapabilities = resolve;
  });
  await page.route(`${API_BASE}/api/capabilities`, async (route) => {
    await capabilitiesResponse;
    await json(route, {
      public_demo: true,
      limits: { search_network_depth: 12 },
    });
  });
  await page.goto("/search-lab/?mode=network");

  await expect(page.locator("#runSearchButton")).toBeDisabled();
  releaseCapabilities();
  await expect(page.locator("#networkDepth")).toHaveValue("12");
  await expect(page.locator("#runSearchButton")).toBeEnabled();
  await expect(page.locator('#networkDepth option[value="12"]')).toBeEnabled();
  await expect(page.locator('#networkDepth option[value="14"]')).toBeDisabled();
  await expect(page.locator('#networkDepth option[value="20"]')).toBeDisabled();
  await expect(page.locator("#networkDepthHint")).toContainText("disabled on the free demo");
  await expect(page.locator("#networkDepth")).toHaveAttribute("data-demo-reason", /available locally/i);
  await page.locator("#networkDepth").hover();
  await expect(page.locator("#demoTooltip")).toContainText("above 12");
});

test("finishes a Search Network replay cleanly at the demo node limit", async ({ page }) => {
  await page.route(`${API_BASE}/api/capabilities`, async (route) => {
    await json(route, {
      public_demo: true,
      limits: { search_network_depth: 12 },
    });
  });
  await page.route(`${API_BASE}/api/search-network`, async (route) => {
    const events = [
      { type: "started", depth: 12 },
      { type: "trace", event: { e: "start", pass: 8, depth: 8, limit: 1200, t_us: 100 } },
      { type: "trace", event: { e: "node", id: 0, parent: -1, ply: 0, depth: 8, move: "", kind: "root", hash: "root", t_us: 200 } },
      { type: "trace", event: { e: "node", id: 1, parent: 0, ply: 1, depth: 7, move: "a7a6", kind: "search", hash: "child", t_us: 300 } },
      { type: "trace", event: { e: "best", id: 0, child: 1, move: "a7a6", score: -26, t_us: 400 } },
      { type: "trace", event: { e: "pv", pass: 8, depth: 8, score: -26, moves: ["a7a6"], t_us: 500 } },
      { type: "trace", event: { e: "finish", pass: 8, depth: 8, score: -26, best: "a7a6", t_us: 600 } },
      { type: "progress", depth: 8, nodes: 1_200_000, time_ms: 900 },
      {
        type: "complete",
        bestmove: "a7a6",
        target_depth: 12,
        depth: 8,
        nodes: 1_500_000,
        limited: true,
      },
    ];
    await route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: `${events.map((event) => JSON.stringify(event)).join("\n")}\n`,
    });
  });

  await page.goto("/search-lab/?mode=network");
  await expect(page.locator("#networkDepth")).toHaveValue("12");
  await page.locator("#networkRunMode").selectOption("replay");
  await page.locator("#runSearchButton").click();

  await expect(page.locator("#networkCanvas")).toHaveAttribute("data-search-limited", "true");
  await expect(page.locator("#networkCanvas")).toHaveAttribute("data-state", "complete");
  await expect(page.locator("#networkStreamState")).toContainText("Capped · depth 8/12");
  await expect(page.locator("#networkEventTag")).toHaveText("NODE LIMIT REACHED");
  await expect(page.locator("#networkPlay")).toHaveText("Replay");
});

test("steps through the search microscope and accepts a live trace", async ({ page }) => {
  test.setTimeout(40_000);
  const principalVariation = [
    "a7a6", "b1c3", "g8f6", "d2d4", "e7e5", "c1g5",
    "f8e7", "d1d2", "e8g8", "e1c1", "c8e6", "f2f4",
    "a8c8", "g2g3", "h7h6", "g5h4", "b7b5", "f1h3",
  ];
  await page.route(`${API_BASE}/api/search-trace`, async (route) => {
    const events = [
      { type: "started", engine: "v8.2", label: 'Sgurr v8.2 "Thearlaich"', perspective: "white" },
      { type: "iteration", kind: "cp", value: -26, display: "-0.3", depth: 1, nodes: 60, nps: 60000, time_ms: 1, pv: ["a7a6"] },
      { type: "iteration", kind: "cp", value: 40, display: "+0.4", depth: 12, nodes: 1271020, nps: 3652356, time_ms: 348, pv: ["a7a6"] },
      { type: "complete", bestmove: "a7a6" },
    ];
    await route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: `${events.map((event) => JSON.stringify(event)).join("\n")}\n`,
    });
  });
  await page.route(`${API_BASE}/api/search-network`, async (route) => {
    const request = route.request().postDataJSON();
    const depth = request.depth;
    const events = [{ type: "started", depth }];
    let elapsed = 0;
    for (let iteration = 1; iteration <= depth; iteration += 1) {
      elapsed += 10_000;
      events.push(
        { type: "trace", event: { e: "start", pass: iteration, depth: iteration, limit: 1200, t_us: elapsed } },
        { type: "trace", event: { e: "node", id: 0, parent: -1, ply: 0, depth: iteration, move: "", kind: "root", hash: "root", t_us: elapsed + 100 } },
        { type: "trace", event: { e: "node", id: 1, parent: 0, ply: 1, depth: iteration - 1, move: "a7a6", kind: "search", hash: `child-${iteration}`, t_us: elapsed + 500 } },
        { type: "trace", event: { e: "node", id: 2, parent: 1, ply: 2, depth: Math.max(0, iteration - 2), move: "b1c3", kind: "search", hash: `leaf-${iteration}`, t_us: elapsed + 900 } },
        { type: "trace", event: { e: "end", id: 2, reason: "quiescence", score: 26, t_us: elapsed + 1400 } },
        { type: "trace", event: { e: "best", id: 1, child: 2, move: "b1c3", score: 26, t_us: elapsed + 1800 } },
        ...(iteration === depth
          ? [{ type: "trace", event: { e: "best", id: 0, child: 2, move: "b1c3", score: -30, t_us: elapsed + 2000 } }]
          : []),
        { type: "trace", event: { e: "best", id: 0, child: 1, move: "a7a6", score: -26, t_us: elapsed + 2200 } },
      );
      for (let nodeId = 3; nodeId <= 160; nodeId += 1) {
        const ply = 1 + Math.floor(Math.log2(nodeId));
        events.push({
          type: "trace",
          event: {
            e: "node",
            id: nodeId,
            parent: Math.floor(nodeId / 2),
            ply,
            depth: Math.max(0, iteration - ply),
            move: "b1c3",
            kind: "search",
            hash: nodeId === 4 ? `branch-${iteration}-3` : `branch-${iteration}-${nodeId}`,
            t_us: elapsed + 2300 + nodeId * 10,
          },
        });
        if (nodeId === 4) {
          events.push({
            type: "trace",
            event: { e: "end", id: 4, reason: "tt-hit", score: 18, t_us: elapsed + 2345 },
          });
        }
      }
      if (iteration === depth) {
        events.push(
          { type: "trace", event: { e: "cutoff", id: 0, child: 1, move: "a7a6", score: -26, t_us: elapsed + 2600 } },
          { type: "trace", event: { e: "activity", ply: iteration, depth: 0, hash: "later", t_us: elapsed + 3000 } },
        );
      }
      events.push(
        { type: "trace", event: { e: "pv", pass: iteration, depth: iteration, score: -26, moves: principalVariation.slice(0, iteration), t_us: elapsed + 3400 } },
        { type: "trace", event: { e: "finish", pass: iteration, depth: iteration, score: -26, best: "a7a6", t_us: elapsed + 4000 } },
        { type: "progress", depth: iteration, nodes: iteration * 1000 },
      );
    }
    events.push({ type: "complete", bestmove: "a7a6", events: "bounded" });
    await route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: `${events.map((event) => JSON.stringify(event)).join("\n")}\n`,
    });
  });

  await page.goto("/search-lab/");
  await expect(page.locator("h1")).toContainText("A move is not found");
  expect(await page.locator(".mode-tab").evaluateAll((tabs) => tabs.map((tab) => tab.id))).toEqual([
    "networkTab",
    "liveTab",
    "walkthroughTab",
  ]);
  await expect(page.locator("#labThemeSelect option")).toHaveCount(7);
  await page.locator("#labThemeSelect").selectOption("galaxy");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "galaxy");
  expect(await page.evaluate(() => localStorage.getItem("sgurrTheme"))).toBe("galaxy");
  await expect(page.locator("#labMusicToggle")).toHaveCount(0);
  await expect(page.locator("#labMusicVolume")).toHaveCount(0);
  await expect(page.locator("#networkSpeed option")).toHaveCount(6);
  await expect(page.locator('#networkSpeed option[value="ultra"]')).toHaveText("Ultra slow · inspect each step");
  await expect(page.locator('#networkSpeed option[value="fast"]')).toHaveText("Fast · rapid scan");
  await expect(page.locator('#networkSpeed option[value="very-fast"]')).toHaveText("Very fast · whole search");
  await expect(page.locator("#chessboard .board-square")).toHaveCount(64);
  await expect(page.locator("#positionSelect optgroup")).toHaveCount(4);
  await expect(page.locator("#positionSelect option")).toHaveCount(61);
  await expect(page.locator("#leaderValue")).toHaveText("a6");

  await page.locator("#nextStep").click();
  await expect(page.locator("#depthValue")).toHaveText("2");
  await expect(page.locator("#leaderValue")).toHaveText("Ne7");

  await page.locator("#liveTab").click();
  await page.locator("#runSearchButton").click();
  await expect(page.locator("#searchSignal")).toHaveClass(/complete/);
  await expect(page.locator("#depthValue")).toHaveText("12");
  await expect(page.locator("#searchSignal")).toContainText("Committed to a6");

  await page.locator("#networkTab").click();
  await expect(page.locator("#networkPanel")).toBeVisible();
  await expect(page.locator("#networkEngineTime")).toHaveText("0 µs");
  await expect(page.locator("#networkSearchedNodeCount")).toHaveText("0");
  await page.locator("#customFenPanel summary").click();
  await page.locator("#customFenInput").fill("not a fen");
  await page.locator("#customFenApply").click();
  await expect(page.locator("#customFenStatus")).toHaveAttribute("data-state", "error");
  const customFen = "4k3/8/8/8/8/8/8/4K2R b K - 0 1";
  await page.locator("#customFenInput").fill(customFen);
  await page.locator("#customFenInput").press("Enter");
  await expect(page.locator("#customFenStatus")).toHaveAttribute("data-state", "ready");
  await expect(page.locator("#positionName")).toHaveText("Custom position");
  await expect(page.locator("#sideBadge")).toHaveText("Black to move");
  await expect(page.locator("#chessboard .board-piece")).toHaveCount(3);
  await expect(page.locator("#positionSelect")).toHaveValue("custom");
  await expect(page.locator("#positionSelect option")).toHaveCount(62);
  await page.locator("#positionSelect").selectOption("lucena");
  const rookBoardGeometry = await page.locator("#chessboard .board-square").evaluateAll((squares) => squares.map((square) => {
    const bounds = square.getBoundingClientRect();
    return { width: bounds.width, height: bounds.height };
  }));
  const rookWidths = rookBoardGeometry.map(({ width }) => width);
  const rookHeights = rookBoardGeometry.map(({ height }) => height);
  expect(Math.max(...rookWidths) - Math.min(...rookWidths)).toBeLessThan(0.5);
  expect(Math.max(...rookHeights) - Math.min(...rookHeights)).toBeLessThan(0.5);
  expect(Math.abs(rookWidths[0] - rookHeights[0])).toBeLessThan(0.5);
  await page.locator("#positionSelect").selectOption("najdorf");
  await expect(page.locator("#networkRunMode")).toHaveValue("live");
  await page.locator("#networkDepth").selectOption("18");
  await expect(page.locator("#runSearchButton")).toContainText("depth-18");
  await page.locator("#networkSpeed").selectOption("realtime");
  await page.locator("#runSearchButton").click();
  await expect(page.locator("#networkNodeCount")).toHaveText("2143");
  await expect(page.locator("#networkSearchedNodeCount")).toHaveText("18,000");
  await expect(page.locator("#networkEventTag")).toHaveText("SEARCH COMPLETE");
  await expect(page.locator("#networkCanvas")).toHaveAttribute("data-state", "complete");
  await expect(page.locator("#networkCanvas")).toHaveAttribute("data-completion-emanation", "active");
  await expect(page.locator("#networkCanvas")).toHaveAttribute("data-completion-emanation-duration-ms", "3850");
  await expect(page.locator("#networkStreamState")).toHaveAttribute("data-state", "complete");
  await expect(page.locator("#networkBestMove")).toHaveText("a7 → a6");
  await expect(page.locator("#networkPly")).toHaveText("18");
  const canvas = page.locator("#networkCanvas");
  await expect(page.locator("#networkEngineTime")).toHaveText("184 ms");
  await expect(page.locator("#networkEngineTimeMode")).toHaveText("final engine time");
  await expect(canvas).toHaveAttribute("data-engine-time-us", "184000");
  await expect(canvas).toHaveAttribute("data-engine-time-unit", "milliseconds");
  await expect(canvas).toHaveAttribute("data-engine-time-mode", "complete");
  await expect(canvas).toHaveAttribute("data-engine-nodes", "18000");
  await expect(canvas).toHaveAttribute("data-engine-nodes-mode", "complete");
  await expect(canvas).toHaveAttribute("data-render-strategy", "world-with-detail");
  await expect(canvas).toHaveAttribute("data-node-design", "synapse-shells");
  await expect(canvas).toHaveAttribute("data-network-luminosity", "1.08");
  await expect(canvas).toHaveAttribute("data-completion-dimming", "disabled");
  await expect(canvas).toHaveAttribute("data-cutoff-effect", "implosion");
  await expect(canvas).toHaveAttribute("data-cutoff-implosions", /^[1-9]\d*$/);
  await expect(canvas).toHaveAttribute("data-transposition-effect", "wormhole-flash");
  await expect(canvas).toHaveAttribute("data-wormhole-flashes", /^[1-9]\d*$/);
  await expect(canvas).toHaveAttribute("data-depth-echo-design", "orbital-memory");
  await expect(canvas).toHaveAttribute("data-depth-echoes", "18");
  await expect(canvas).toHaveAttribute("data-leader-effect", "instability-ghosts");
  await expect(canvas).toHaveAttribute("data-leader-changes", /^[1-9]\d*$/);
  await expect(canvas).toHaveAttribute("data-leader-stability", "locked");
  await expect(canvas).toHaveAttribute("data-cached-nodes", "2143");
  expect(Number(await canvas.getAttribute("data-evaluated-nodes"))).toBeGreaterThan(0);
  await expect(canvas).toHaveAttribute("data-selection-strategy", "consequential");
  await expect(canvas).toHaveAttribute("data-curated-nodes", "120");
  await expect(canvas).toHaveAttribute("data-curated-promoted", /^[1-9]\d*$/);
  await expect(canvas).toHaveAttribute("data-pv-depth", "18");
  await expect(canvas).toHaveAttribute("data-pv-plies", "18");
  await expect(canvas).toHaveAttribute("data-pv-moves", principalVariation.join(" "));
  await expect(canvas).toHaveAttribute("data-pv-reveal", "1.000");
  await expect(canvas).toHaveAttribute("data-survivor-glow", "persistent");
  await expect(canvas).toHaveAttribute("data-principal-hit-radius", "26");
  await expect(canvas).toHaveAttribute("data-standard-hit-radius", "10");
  await expect(canvas).toHaveAttribute("data-principal-hit-targets", "18");
  await expect(canvas).toHaveAttribute("data-pan-constraint", "bounded-overscroll");
  await expect(canvas).toHaveAttribute("data-bloom-layer", "half-resolution");
  await expect(canvas).toHaveAttribute("data-bloom-alignment", "world-space");
  expect(Number(await canvas.getAttribute("data-bloom-builds"))).toBeGreaterThan(0);
  await expect(canvas).toHaveAttribute("data-background-design", "deep-neural-space");
  await expect(canvas).toHaveAttribute("data-background-mood", "galactic-ominous");
  expect(Number(await canvas.getAttribute("data-background-builds"))).toBeGreaterThan(0);
  await expect(canvas).toHaveAttribute("data-depth-atmosphere", "volumetric-shells");
  await expect(canvas).toHaveAttribute("data-depth-atmosphere-shells", /^[4-9]$/);
  expect(Number(await canvas.getAttribute("data-depth-atmosphere-builds"))).toBeGreaterThan(0);
  await expect(canvas).toHaveAttribute("data-center-exposure", "filmic-radial-compression");
  await expect(canvas).toHaveAttribute("data-center-exposure-floor", "0.48");
  await expect(canvas).toHaveAttribute("data-event-ingestion", "frame-sliced-queue");
  await expect(canvas).toHaveAttribute("data-live-event-slice-ms", "3");
  await expect(canvas).toHaveAttribute("data-live-event-queue", "0");
  await expect(canvas).toHaveAttribute("data-live-event-queue-peak", /^[1-9]\d*$/);
  await expect(canvas).toHaveAttribute("data-live-cache", "incremental-depth-layer");
  expect(Number(await canvas.getAttribute("data-live-structure-builds"))).toBeGreaterThan(0);
  await expect(canvas).toHaveAttribute("data-static-cache", "completed-depths");
  await expect(canvas).toHaveAttribute("data-live-bloom", "cached-sprites");
  await expect(canvas).toHaveAttribute("data-glow-renderer", "cached-sprites");
  await expect(canvas).toHaveAttribute("data-evaluation-profile", "linear-cached");
  await expect(canvas).toHaveAttribute("data-effect-budget", /^(full|balanced|protected)$/);
  await expect(canvas).toHaveAttribute("data-effect-budget-policy", "adaptive-transients-only");
  await expect(canvas).toHaveAttribute("data-live-animation-policy", "continuous-60fps-overlay");
  await expect(canvas).toHaveAttribute("data-structural-rate", /^(10fps|15fps)$/);
  await expect(canvas).toHaveAttribute("data-survivor-design", "celestial-filament");
  await expect(canvas).toHaveAttribute("data-survivor-envelope", "amber-white-core");
  await expect(canvas).toHaveAttribute("data-survivor-particles", "2");
  await expect(canvas).toHaveAttribute("data-terminal-star", "stable");
  await expect(canvas).toHaveAttribute("data-depth-waves", "18");
  await expect(page.locator(".network-legend")).toContainText("brighter = stronger move");
  await expect(page.locator(".network-legend")).toContainText("completed-depth PV");
  await expect(canvas).toHaveAttribute("data-structure-state", "settled");
  await expect(canvas).toHaveAttribute("data-completion-transition", "settled", { timeout: 4000 });
  await expect(canvas).toHaveAttribute("data-completion-choreography", "settled", { timeout: 5000 });
  await expect(canvas).toHaveAttribute("data-completion-emanation", "settled", { timeout: 6000 });
  await expect(canvas).toHaveAttribute("data-frozen-depths", "18", { timeout: 4000 });
  await expect(canvas).toHaveAttribute("data-animation-rate", "24fps-ambient", { timeout: 4000 });
  const settledBuilds = Number(await canvas.getAttribute("data-static-builds"));
  const settledBloomBuilds = Number(await canvas.getAttribute("data-bloom-builds"));
  const settledBackgroundBuilds = Number(await canvas.getAttribute("data-background-builds"));
  const settledAtmosphereBuilds = Number(await canvas.getAttribute("data-depth-atmosphere-builds"));
  const settledLiveStructureBuilds = Number(await canvas.getAttribute("data-live-structure-builds"));
  // A ceiling against runaway rebuilding, not a tuned constant: the count
  // depends on how many frames the machine fits into the settling animation,
  // and a slow CI runner legitimately lands higher than a fast desktop. The
  // invariant that matters is the next assertion, that it stops growing once
  // the scene has settled. Runaway rebuilding would be in the hundreds.
  expect(settledBuilds).toBeLessThan(80);
  await page.waitForTimeout(120);
  expect(Number(await canvas.getAttribute("data-static-builds"))).toBe(settledBuilds);
  expect(Number(await canvas.getAttribute("data-bloom-builds"))).toBe(settledBloomBuilds);
  expect(Number(await canvas.getAttribute("data-background-builds"))).toBe(settledBackgroundBuilds);
  expect(Number(await canvas.getAttribute("data-depth-atmosphere-builds"))).toBe(settledAtmosphereBuilds);
  expect(Number(await canvas.getAttribute("data-live-structure-builds"))).toBe(settledLiveStructureBuilds);
  await page.locator("#networkZoomIn").click();
  await expect(page.locator("#networkZoomLevel")).toHaveText("128%");
  const navigationBuilds = Number(await canvas.getAttribute("data-static-builds"));
  await page.waitForTimeout(8);
  expect(Number(await canvas.getAttribute("data-static-builds"))).toBe(navigationBuilds);
  await expect(canvas).toHaveAttribute("data-quality", "full");
  await expect(canvas).toHaveAttribute("data-render-layer", "native-detail");
  const firstDetailBuilds = Number(await canvas.getAttribute("data-detail-builds"));
  expect(firstDetailBuilds).toBeGreaterThan(0);
  expect(Number(await canvas.getAttribute("data-static-builds"))).toBe(navigationBuilds);
  await expect(canvas).toHaveAttribute("data-detail-tier", "high");
  const canvasBounds = await canvas.boundingBox();
  expect(canvasBounds).not.toBeNull();
  await page.mouse.move(canvasBounds.x + canvasBounds.width / 2, canvasBounds.y + canvasBounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(canvasBounds.x + canvasBounds.width / 2 + 180, canvasBounds.y + canvasBounds.height / 2 + 90, { steps: 8 });
  await expect(canvas).toHaveAttribute("data-quality", "navigation");
  // Navigation reuses the detail image already on screen rather than swapping
  // in a coarser stand-in, so the picture must not change character mid-drag
  // and no new detail may be rendered while the pointer is down.
  const detailBuildsDuringNavigation = Number(await canvas.getAttribute("data-detail-builds"));
  await expect(canvas).toHaveAttribute("data-render-layer", "stable-detail");
  await expect(canvas).toHaveAttribute("data-structure-state", "stable-detail");
  await expect(canvas).toHaveAttribute("data-detail-during-navigation", "preserved");
  await expect(canvas).toHaveAttribute("data-bloom-state", "cached-navigation");
  await expect(canvas).toHaveAttribute("data-bloom-alignment", "world-space");
  await expect(canvas).toHaveAttribute("data-background-effects", "preserved-navigation");
  expect(Number(await canvas.getAttribute("data-depth-atmosphere-builds"))).toBe(settledAtmosphereBuilds);
  expect(Number(await canvas.getAttribute("data-static-builds"))).toBe(navigationBuilds);
  await page.waitForTimeout(80);
  expect(Number(await canvas.getAttribute("data-detail-builds"))).toBe(detailBuildsDuringNavigation);
  await page.mouse.up();
  await expect(canvas).toHaveAttribute("data-quality", "full");
  await expect(canvas).toHaveAttribute("data-render-layer", "native-detail");
  await expect(canvas).toHaveAttribute("data-navigation-release", "native-ready");
  await expect(canvas).toHaveAttribute("data-navigation-release-strategy", "staged-pass-slices");
  await expect(canvas).toHaveAttribute("data-navigation-release-fallback", "previous-detail-until-ready");
  await expect(canvas).toHaveAttribute("data-navigation-release-swap", "atomic");
  await expect(canvas).toHaveAttribute("data-navigation-release-slice-ms", "4");
  await expect(canvas).toHaveAttribute("data-navigation-release-progress", "1.000");
  await expect(canvas).toHaveAttribute("data-navigation-release-passes", "18");
  expect(Number(await canvas.getAttribute("data-navigation-release-builds"))).toBeGreaterThan(0);
  expect(Number(await canvas.getAttribute("data-navigation-release-max-slice-ms"))).toBeGreaterThan(0);
  expect(Number(await canvas.getAttribute("data-navigation-release-passes-per-slice"))).toBeLessThanOrEqual(2);
  expect(Number(await canvas.getAttribute("data-detail-builds"))).toBeGreaterThan(firstDetailBuilds);
  await expect(canvas).toHaveAttribute("data-cached-nodes", "2143");
  expect(Number(await canvas.getAttribute("data-static-builds"))).toBe(navigationBuilds);
  for (let zoomStep = 0; zoomStep < 6; zoomStep += 1) {
    await page.locator("#networkZoomIn").click();
  }
  await expect(page.locator("#networkZoomLevel")).toHaveText("450%");
  await expect(canvas).toHaveAttribute("data-quality", "full");
  await expect(canvas).toHaveAttribute("data-render-layer", "native-detail");
  const maximumZoomDetailBuilds = Number(await canvas.getAttribute("data-detail-builds"));
  await page.locator("#networkZoomIn").click();
  await page.mouse.wheel(0, -120);
  await page.waitForTimeout(30);
  await expect(page.locator("#networkZoomLevel")).toHaveText("450%");
  await expect(canvas).toHaveAttribute("data-quality", "full");
  await expect(canvas).toHaveAttribute("data-render-layer", "native-detail");
  expect(Number(await canvas.getAttribute("data-detail-builds"))).toBe(maximumZoomDetailBuilds);
  await page.locator("#networkFitView").click();
  await expect(page.locator("#networkZoomLevel")).toHaveText("100%");
  await page.waitForTimeout(250);
  await expect(page.locator("#networkNodeCount")).toHaveText("2143");
  await canvas.focus();
  for (let panStep = 0; panStep < 40; panStep += 1) await page.keyboard.press("ArrowRight");
  const boundedPanX = Math.abs(Number(await canvas.getAttribute("data-pan-x")));
  expect(boundedPanX).toBeGreaterThan(0);
  expect(boundedPanX).toBeLessThan(600);
  await page.keyboard.press("Home");
  expect(Number(await canvas.getAttribute("data-pan-x"))).toBe(0);

  await page.locator("#networkRunMode").selectOption("replay");
  await expect(page.locator("#runSearchButton")).toContainText("Record depth-18");
  await page.locator("#runSearchButton").click();
  await expect(page.locator("#networkEventTag")).toHaveText("SEARCH COMPLETE");
  await expect(page.locator("#networkNodeCount")).toHaveText("2143");
  await page.locator("#networkScrubber").evaluate((scrubber) => {
    const target = Math.floor(Number(scrubber.max) * 0.62);
    scrubber.value = String(target);
    scrubber.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(canvas).toHaveAttribute("data-state", "paused");
  await expect(canvas).toHaveAttribute("data-replay-scrub-state", "settled");
  await expect(canvas).toHaveAttribute("data-seek-hot-nodes", "0");
  const scrubbedEngineNodes = Number((await page.locator("#networkSearchedNodeCount").textContent()).replaceAll(",", ""));
  expect(scrubbedEngineNodes).toBeGreaterThan(0);
  expect(scrubbedEngineNodes).toBeLessThan(18000);
  await page.locator("#networkSpeed").selectOption("very-fast");
  await page.locator("#networkRestart").click();
  await expect(canvas).toHaveAttribute("data-replay-scrub-state", "playing");
  await expect(page.locator("#networkEventTag")).toHaveText("SEARCH COMPLETE", { timeout: 10_000 });
  await expect(page.locator("#networkNodeCount")).toHaveText("2143");
  await expect(page.locator("#networkEngineTime")).toHaveText("184 ms");
  await expect(page.locator("#networkEngineTimeMode")).toHaveText("recorded engine clock");
  await expect(page.locator("#networkSearchedNodeCount")).toHaveText("18,000");
  await expect(canvas).toHaveAttribute("data-engine-time-us", "184000");
  await expect(canvas).toHaveAttribute("data-engine-time-mode", "replay");
  await expect(canvas).toHaveAttribute("data-engine-nodes", "18000");
  await expect(canvas).toHaveAttribute("data-engine-nodes-mode", "replay");
});

test("returns from the microscope directly to the main menu", async ({ page }) => {
  await installMockBackend(page);
  await openMainMenu(page);
  await page.locator(".search-lab-link").click();
  await expect(page).toHaveURL(/\/search-lab\/\?mode=network$/);
  await expect(page.locator("#networkTab")).toHaveClass(/active/);
  await expect(page.locator("#networkPanel")).toBeVisible();
  await page.locator(".brand").click();
  await expect(page).toHaveURL(/\?view=menu$/);
  await expect(page.locator("#introScreen")).toBeHidden();
  await expect(page.locator("#menuScreen")).toBeVisible();
  await expect(page.locator("#menuStatus")).toHaveText("Ready");
});

test("plays e4 as White and renders Sgurr's e5 reply", async ({ page }) => {
  const calls = await installMockBackend(page);
  await openMainMenu(page);
  await page.locator("#playWhiteButton").click();

  await expect(page.locator("#appShell")).toHaveAttribute("data-mode", "game");
  await expect(page.locator("#board .square")).toHaveCount(64);
  await expect(page.locator("#board .piece-image").first()).toHaveAttribute(
    "src",
    /assets\/pieces\/chessnut\/[wb][KQRBNP]\.svg$/,
  );
  await page.locator('[data-square="e2"]').click();
  await expect(page.locator('[data-square="e4"]')).toHaveClass(/legal/);
  await page.locator('[data-square="e4"]').click();

  await expect(page.locator("#moveRows")).toContainText("e4");
  await expect(page.locator("#moveRows")).toContainText("e5");
  await expect(page.locator("#turnValue")).toHaveText("White to move");
  expect(calls.filter((call) => call.path === "/api/player-move")).toHaveLength(1);
  expect(calls.filter((call) => call.path === "/api/engine-move")).toHaveLength(1);
});

test("plays as Black with a flipped board after Sgurr opens", async ({ page }) => {
  const calls = await installMockBackend(page);
  await openMainMenu(page);
  await page.locator("#playBlackButton").click();

  await expect.poll(() => calls.filter((call) => call.path === "/api/engine-move").length).toBe(1);
  await expect(page.locator("#board .square").first()).toHaveAttribute("data-square", "h1");
  await expect(page.locator("#moveRows")).toContainText("e4");
  await expect(page.locator("#turnValue")).toHaveText("Black to move");
});

test("enters the two-core arena in Watch mode", async ({ page }) => {
  const calls = await installMockBackend(page, { finishWatch: true });
  await openMainMenu(page);
  await page.locator("#watchButton").click();

  await expect(page.locator(".core-header")).toHaveClass(/watch-mode/);
  await expect(page.locator("#watchWhiteInstance")).toBeVisible();
  await expect(page.locator("#watchBlackInstance")).toBeVisible();
  await expect.poll(() => calls.filter((call) => call.path === "/api/engine-move").length).toBe(1);
  await expect(page.locator("#resultModal")).toBeVisible();
  await expect(page.locator("#resultModal")).toHaveAttribute("data-outcome", "watch-draw");
});

test("opens Position Lab with a full editable board", async ({ page }) => {
  await installMockBackend(page);
  await openMainMenu(page);
  await page.locator("#positionLabButton").click();

  await expect(page.locator("#appShell")).toHaveAttribute("data-mode", "editor");
  await expect(page.locator("#editorPanel")).toBeVisible();
  await expect(page.locator("#editorPanel h2")).toHaveText("Position Lab");
  await expect(page.locator("#board .square")).toHaveCount(64);
  await expect(page.locator("#editorPlayButton")).toBeEnabled();
});

test("keeps Position Lab footer controls accessible on a short desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 620 });
  await installMockBackend(page);
  await openMainMenu(page);
  await page.locator("#positionLabButton").click();

  const geometry = await page.evaluate(() => {
    const panel = document.querySelector("#editorPanel").getBoundingClientRect();
    const actions = document.querySelector(".editor-actions").getBoundingClientRect();
    return {
      panelBottom: panel.bottom,
      actionsBottom: actions.bottom,
      overflow: getComputedStyle(document.querySelector("#editorPanel")).overflow,
    };
  });
  expect(geometry.actionsBottom).toBeLessThanOrEqual(geometry.panelBottom + 1);
  expect(geometry.overflow).toBe("visible");

  await page.locator("#editorHelpButton").scrollIntoViewIfNeeded();
  await page.locator("#editorHelpButton").click();
  await expect(page.locator("#helpModal")).toBeVisible();
});

test("loads a full FEN into the editor and starts play from it", async ({ page }) => {
  const calls = await installMockBackend(page);
  const fen = "r3k2r/8/8/8/8/8/8/R3K2R b Kq - 17 42";
  await openMainMenu(page);
  await page.locator("#positionLabButton").click();
  await page.locator("#editorFenInput").fill(fen);
  await page.locator("#editorLoadFenButton").click();

  await expect(page.locator("#editorStatus")).toHaveText("FEN loaded into the editor");
  await expect(page.locator("#editorTurnButton")).toHaveText("First move: Black");
  await expect(page.locator("#editorFenInput")).toHaveValue(fen);
  await expect(page.locator("#board .piece-image")).toHaveCount(6);

  await page.locator("#editorPlayerButton").click();
  await expect(page.locator("#editorPlayerButton")).toHaveText("You play: Black");
  await page.locator("#editorPlayButton").click();
  await expect(page.locator("#appShell")).toHaveAttribute("data-mode", "game");
  expect(calls.filter((call) => call.path === "/api/load-fen")).toHaveLength(2);
  expect(calls.filter((call) => call.path === "/api/load-fen").at(-1).body.fen).toBe(fen);
});

test("streams deep position analysis and steps through Sgurr's line", async ({ page }) => {
  const calls = await installMockBackend(page, { publicDemo: true });
  await openMainMenu(page);
  await page.locator("#positionLabButton").click();

  await expect(page.locator("#editorHeading")).toHaveText("Position Lab");
  await expect(page.locator("#editorAnalyseButton")).toHaveClass(/preferred/);
  await page.locator("#editorAnalyseButton").click();

  await expect(page.locator("#analysisPanel")).toBeVisible();
  await expect(page.locator("#appShell")).toHaveAttribute("data-mode", "analysis");
  await expect(page.locator("#analysisStatus")).toContainText("prefers e4");
  await expect(page.locator("#analysisScore")).toHaveText("+0.3");
  await expect(page.locator("#analysisDepth")).toHaveText("12");
  await expect(page.locator("#analysisBestMove")).toHaveText("e4");
  await expect(page.locator("#analysisDepths button")).toHaveCount(2);
  await expect(page.locator("#analysisDecisionSummary")).toContainText("e4 took the lead at depth 6");
  await expect(page.locator("#analysisChangeCount")).toHaveText("2 leaders");
  await expect(page.locator(".analysis-leader-card").first()).toContainText("D6-D12");
  await expect(page.locator(".analysis-leader-card").first()).toContainText("FINAL");
  await expect(page.locator(".analysis-leader-card").last()).toContainText("d4");
  await expect(page.locator("#analysisPvMoves button")).toHaveCount(3);

  await page.locator('#analysisPvMoves button[data-ply="3"]').click();
  await expect(page.locator("#analysisPlyCounter")).toContainText("3 plies");
  await expect(page.locator('[data-square="g1"]')).toHaveClass(/last/);
  await expect(page.locator('[data-square="f3"]')).toHaveClass(/last/);
  await page.locator("#analysisRootButton").click();
  await expect(page.locator("#analysisPlyCounter")).toHaveText("Root position");

  const searchCall = calls.find((call) => call.path === "/api/search-trace");
  expect(searchCall.body.movetime_ms).toBe(5000);
  await page.locator("#analysisEditButton").click();
  await expect(page.locator("#editorPanel")).toBeVisible();
  await expect(page.locator("#editorFenInput")).toHaveValue(START_FEN);
});

test("keeps position analysis usable on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installMockBackend(page, { publicDemo: true });
  await openMainMenu(page);
  await page.locator("#positionLabButton").click();
  await page.locator("#editorAnalyseButton").click();

  await expect(page.locator("#analysisPanel")).toBeVisible();
  await expect(page.locator("#analysisAgainButton")).toBeVisible();
  await expect(page.locator("#analysisPvMoves button")).toHaveCount(3);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("keeps an edited position and offers to replay it", async ({ page }) => {
  const calls = await installMockBackend(page);
  await openMainMenu(page);
  await page.locator("#positionLabButton").click();
  await page.locator("#editorClearButton").click();
  await page.locator('.palette-button[title="White king"]').click();
  await page.locator('[data-square="e1"]').click();
  await page.locator('.palette-button[title="Black king"]').click();
  await page.locator('[data-square="e8"]').click();
  await expect(page.locator("#board .piece-image")).toHaveCount(2);

  await page.locator("#editorCancelButton").click();
  await page.locator("#positionLabButton").click();
  await expect(page.locator("#board .piece-image")).toHaveCount(2);
  await page.locator("#editorPlayButton").click();

  await expect(page.locator("#resultModal")).toBeVisible();
  await expect(page.locator("#rematchButton")).toHaveText("Replay position");
  await page.locator("#rematchButton").click();
  await expect.poll(() => calls.filter((call) => call.path === "/api/load-fen").length).toBe(2);
  await expect(page.locator("#rematchButton")).toHaveText("Replay position");
});

test("keeps game-start controls disabled when the engine is missing", async ({ page }) => {
  await installMockBackend(page, { engineExists: false });
  await page.goto("/");
  await page.locator("#wakeSgurrButton").click();
  await expect(page.locator("#introScreen")).toBeHidden();

  await expect(page.locator("#menuStatus")).toContainText("Build the current Sgurr engine");
  await expect(page.locator("#playWhiteButton")).toBeDisabled();
  await expect(page.locator("#playBlackButton")).toBeDisabled();
  await expect(page.locator("#watchButton")).toBeDisabled();
});

test("reviews a finished game and names the move it turned on", async ({ page }) => {
  await installMockBackend(page);
  await openMainMenu(page);
  await page.locator("#playWhiteButton").click();

  // 1.e4 e5, then 2.Nf3 Nc6 which ends the game with the eval collapsed.
  await page.locator('[data-square="e2"]').click();
  await page.locator('[data-square="e4"]').click();
  await expect(page.locator("#moveRows")).toContainText("e5");
  await page.locator('[data-square="g1"]').click();
  await page.locator('[data-square="f3"]').click();

  await expect(page.locator("#resultModal")).toBeVisible();
  await page.locator("#reviewGameButton").click();

  // Review takes over from the result modal and opens on the turning point.
  await expect(page.locator("#resultModal")).toBeHidden();
  await expect(page.locator("#reviewBlock")).toBeVisible();
  await expect(page.locator("#board .square")).toHaveCount(64);

  // +0.2 -> -3.5 white-relative, spanning White's own 2.Nf3.
  const swing = page.locator("#reviewSwingButton");
  await expect(swing).toBeVisible();
  await expect(swing).toContainText("2. Nf3");
  await expect(swing).toContainText("+0.2");
  await expect(swing).toContainText("-3.5");
  await expect(swing).toContainText("3.7 pawns");
  await expect(page.locator("#reviewMove")).toHaveText("2. Nf3");

  const reviewGeometry = await page.evaluate(() => {
    const panel = document.querySelector(".side-panel").getBoundingClientRect();
    const trend = document.querySelector(".trend-block").getBoundingClientRect();
    return {
      panelBottom: panel.bottom,
      trendBottom: trend.bottom,
      overflow: getComputedStyle(document.querySelector(".side-panel")).overflow,
    };
  });
  expect(reviewGeometry.trendBottom).toBeLessThanOrEqual(reviewGeometry.panelBottom + 1);
  expect(reviewGeometry.overflow).toBe("visible");

  // Stepping back reaches the start position, and the controls bound there.
  await page.locator("#reviewStartButton").click();
  await expect(page.locator("#reviewMove")).toHaveText("Start position");
  await expect(page.locator("#reviewPrevButton")).toBeDisabled();
  await expect(page.locator("#reviewStartButton")).toBeDisabled();

  await page.locator("#reviewNextButton").click();
  await expect(page.locator("#reviewMove")).toHaveText("1. e4");

  // Ending review hands the result modal back.
  await page.locator("#reviewExitButton").click();
  await expect(page.locator("#reviewBlock")).toBeHidden();
  await expect(page.locator(".side-panel")).not.toHaveClass(/review-mode/);
  await expect(page.locator("#resultModal")).toBeVisible();
});
