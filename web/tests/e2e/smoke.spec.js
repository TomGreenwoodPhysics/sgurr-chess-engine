import { expect, test } from "@playwright/test";
import { startStaticServer } from "../static-server.mjs";

const API_BASE = "http://127.0.0.1:8000";
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1";
const AFTER_E4_E5_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2";

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
    start_fen: START_FEN,
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

async function installMockBackend(page, { finishWatch = false, engineExists = true } = {}) {
  const calls = [];
  await page.route(`${API_BASE}/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

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
      });
      return;
    }

    const body = request.method() === "POST" ? request.postDataJSON() : null;
    calls.push({ path, body });
    if (path === "/api/new") {
      await json(route, INITIAL_STATE);
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
        await json(route, AFTER_E4_STATE);
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

test("opens the board editor with a full editable board", async ({ page }) => {
  await installMockBackend(page);
  await openMainMenu(page);
  await page.locator("#boardEditorButton").click();

  await expect(page.locator("#appShell")).toHaveAttribute("data-mode", "editor");
  await expect(page.locator("#editorPanel")).toBeVisible();
  await expect(page.locator("#editorPanel h2")).toHaveText("Board editor");
  await expect(page.locator("#board .square")).toHaveCount(64);
  await expect(page.locator("#editorPlayButton")).toBeEnabled();
});

test("keeps game-start controls disabled when the engine is missing", async ({ page }) => {
  await installMockBackend(page, { engineExists: false });
  await page.goto("/");
  await page.locator("#wakeSgurrButton").click();
  await expect(page.locator("#introScreen")).toBeHidden();

  await expect(page.locator("#menuStatus")).toContainText("Build sgurr_cpp\\sgr_v6_0.exe");
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
  await expect(page.locator("#resultModal")).toBeVisible();
});
