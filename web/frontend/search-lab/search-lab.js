import { apiUrl } from "../js/config.js";
import { initDemoTooltips, setDemoReason } from "../js/demo-tooltip.js";
import { initSearchNetwork } from "./network.js";
import { initLabPreferences } from "./preferences.js";

const RUY_FEN = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3";

function position(name, fen, line, last = []) {
  return { name, fen, line, last, aria: `${name} chess position` };
}

const POSITIONS = {
  ruy: {
    name: "Ruy Lopez",
    fen: RUY_FEN,
    line: "1. e4 e5 2. Nf3 Nc6 3. Bb5",
    aria: "Ruy Lopez position after 3.Bb5",
    last: ["f1", "b5"],
  },
  italian: {
    name: "Italian Game",
    fen: "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    line: "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5",
    aria: "Italian Game position with White to move",
    last: ["f8", "c5"],
  },
  najdorf: {
    name: "Sicilian Najdorf",
    fen: "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6",
    line: "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6",
    aria: "Sicilian Najdorf position with White to move",
    last: ["a7", "a6"],
  },
  qgd: position("Queen's Gambit Declined", "rnbqkb1r/ppp2ppp/4pn2/3p4/2PP4/2N5/PP2PPPP/R1BQKBNR w KQkq - 2 4", "Classical central tension", ["g8", "f6"]),
  slav: position("Slav Defence", "rnbqkb1r/pp2pppp/2p2n2/8/2pP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 5", "A captured gambit pawn and rapid development", ["d5", "c4"]),
  winawer: position("French Winawer", "rnbqk1nr/pp3ppp/4p3/2ppP3/3P4/P1P5/2P2PPP/R1BQKBNR b KQkq - 0 6", "Locked centre · damaged structure · opposite-wing play", ["b2", "c3"]),
  caro: position("Caro-Kann Classical", "rn1qkbnr/pp2pppp/2p5/5b2/3PN3/8/PPP2PPP/R1BQKBNR w KQkq - 1 5", "Solid structure with a developed light bishop", ["c8", "f5"]),
  kingsindianopening: position("King's Indian Defence", "rnbq1rk1/ppp2pbp/3p1np1/4p3/2PPP3/2N2N2/PP2BPPP/R1BQ1RK1 b - - 1 7", "Space against a compact kingside", ["e1", "g1"]),
  grunfeld: position("Grünfeld Defence", "rnbqk2r/ppp1ppbp/6p1/8/3PP3/2P5/P4PPP/R1BQKBNR w KQkq - 1 7", "A huge pawn centre under immediate pressure", ["f8", "g7"]),
  nimzo: position("Nimzo-Indian", "rnbq1rk1/pp3ppp/4pn2/2pp4/1bPP4/2NBPN2/PP3PPP/R1BQ1RK1 b - - 1 7", "Pin pressure and flexible pawn breaks", ["e1", "g1"]),
  catalan: position("Catalan Opening", "rnbq1rk1/ppp1bppp/4pn2/3p4/2PP4/5NP1/PP2PPBP/RNBQ1RK1 b - - 5 6", "Long-diagonal pressure over a quiet centre", ["e1", "g1"]),
  english: position("English Opening", "rnbqkb1r/ppp2ppp/1n6/4p3/8/2N3P1/PP1PPPBP/R1BQK1NR w KQkq - 2 6", "Flank pressure and transpositional choices", ["d5", "b6"]),
  pirc: position("Pirc Austrian Attack", "rnbq1rk1/ppp1ppbp/3p1np1/8/3PPP2/2N2N2/PPP3PP/R1BQKB1R w KQ - 3 6", "An ambitious pawn centre facing a kingside fianchetto", ["e8", "g8"]),
  dragon: position("Sicilian Dragon", "rnbq1rk1/pp2ppbp/3p1np1/8/3NP3/2N1BP2/PPPQ2PP/R3KB1R b KQ - 2 8", "Opposite-side attacking plans begin to form", ["d1", "d2"]),
  vienna: position("Vienna Gambit", "rnbqkb1r/ppp2ppp/8/3pP3/4n3/2N2Q2/PPPP2PP/R1B1KBNR b KQkq - 1 5", "Immediate tactics around an exposed central knight", ["d1", "f3"]),
  smithmorra: position("Smith-Morra Gambit", "rnbqkbnr/pp1ppppp/8/8/4P3/2N5/PP3PPP/R1BQKBNR b KQkq - 0 4", "A pawn traded for open files and fast development", ["b1", "c3"]),
  carlsbad: {
    name: "Carlsbad structure",
    fen: "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PPQ1BPPP/R1BR2K1 w - - 4 11",
    line: "Queen's Gambit structure · minority attack against central counterplay",
    aria: "Carlsbad pawn structure middlegame with White to move",
    last: [],
  },
  kingindian: {
    name: "King's Indian",
    fen: "r1bq1rk1/ppp1npbp/3p1np1/3Pp3/2P1P3/2N2N2/PP2BPPP/R1BQ1RK1 w - - 1 9",
    line: "Classical King's Indian · queenside space against a kingside attack",
    aria: "Classical King's Indian middlegame with White to move",
    last: ["c6", "e7"],
  },
  hanging: {
    name: "Hanging pawns",
    fen: "2rq1rk1/pb1nbppp/1p2pn2/8/2BP4/2N1PN2/PPQ2PPP/R1B2RK1 w - - 0 12",
    line: "An isolated central pawn pair creates both space and tactical targets",
    aria: "Complex hanging pawns middlegame with White to move",
    last: [],
  },
  closedruy: position("Closed Ruy Lopez", "r1bq1rk1/2pnbppp/p2p1n2/1p2p3/3PP3/1BP2N1P/PP3PP1/RNBQR1K1 w - - 1 11", "A dense manoeuvring battle behind locked pawns", ["b8", "d7"]),
  iqp: position("Isolated queen's pawn", "r1bqrnk1/pp2bppp/2p2n2/3p2B1/3P4/2NBP3/PPQ1NPPP/R4RK1 w - - 0 11", "Activity and outposts versus a long-term weakness", ["c7", "c6"]),
  hedgehog: position("Hedgehog structure", "r3k2r/1bqnbppp/pp1ppn2/8/2PQP3/1PN2NP1/P4PBP/R1BR2K1 w kq - 1 12", "A compressed position full of latent pawn breaks", ["b8", "d7"]),
  maroczy: position("Maróczy Bind", "r1bq1rk1/pp2ppbp/2np1np1/8/2PNP3/2N1B3/PP2BPPP/R2Q1RK1 b - - 1 9", "Space restriction against a flexible Sicilian setup", ["e1", "g1"]),
  stonewall: position("Stonewall structure", "rnbqk2r/pp4pp/2pbpn2/3p1p2/2PP4/5NP1/PP2PPBP/RNBQ1RK1 w kq - 0 7", "A locked centre and fixed kingside squares", ["c7", "c6"]),
  botvinnik: position("Botvinnik English", "r1bq1rk1/ppp3bp/2np1np1/4pp2/2P1P3/2NP2P1/PP2NPBP/R1BQ1RK1 w - - 4 9", "A closed centre with attacks growing on both wings", ["e8", "g8"]),
  benoni: position("Modern Benoni", "rnbqk2r/pp3pbp/3p1np1/2pP4/4PP2/2N5/PP4PP/R1BQKBNR w KQkq - 1 8", "A queenside majority races kingside counterplay", ["f8", "g7"]),
  frenchlocked: position("Closed French", "r3kbnr/pp1b1ppp/1qn1p3/3pP3/3P4/3B1N2/PP3PPP/RNBQK2R w KQkq - 1 8", "Pawn chains make every break consequential", ["c8", "d7"]),
  symenglish: position("Symmetrical English", "r1bq1rk1/pp1pppbp/2n2np1/8/2PN4/2N3P1/PP2PPBP/R1BQ1RK1 b - - 0 8", "Near symmetry hiding several sharp imbalances", ["f3", "d4"]),
  kiwipete: position("Kiwipete stress test", "r3k2r/p1ppqpb1/bn2pnp1/2pP4/1p2P3/2N2N2/PPQBBPPP/R3K2R w KQkq - 0 1", "Maximum move density · pins, castling and captures collide"),
  promotionattack: position("Promotion-rank attack", "rnbq1k1r/pp1Pbppp/2p2n2/8/2B5/8/PPP1NPPP/RNBQK2R w KQ - 1 8", "A pawn on the seventh rank distorts the whole search"),
  pinnedmaze: position("Pinned-piece maze", "r4rk1/1pp1qppp/p1np1n2/8/4P1b1/1BN1B3/PPP1QPPP/R4RK1 w - - 0 10", "Forty-five legal moves around a web of pins"),
  greekgift: position("Greek Gift sacrifice", "r1bqkb1r/pp1n1ppB/2n1p3/3pP3/3p4/2N2N2/PPP2PPP/R1BQ1RK1 b kq - 0 8", "A bishop lands on h7 and the king must calculate", ["d3", "h7"]),
  yugoslav: position("Yugoslav Attack", "2rq1rk1/pp1bppbp/3p1np1/4n3/3NP2P/1BN1BP2/PPPQ2P1/2KR3R b - - 0 12", "Opposite-side castling with both attacks already moving", ["h2", "h4"]),
  kidstorm: position("King's Indian pawn storm", "r1bq1rk1/pppnn1bp/3p4/3Pp1p1/2P1Pp2/2N2P2/PP2BBPP/R2QNRK1 w - - 0 13", "Locked centre · both wings poised to erupt", ["g6", "g5"]),
  legaltrap: position("Légal Trap crossroads", "r2qkbnr/ppp2ppp/2np4/4N2b/2B1P3/2N4P/PPPP1PP1/R1BQK2R b KQkq - 0 6", "A loose queen and a mating net compete", ["f3", "e5"]),
  scotch: position("Scotch tactical centre", "r1b1kb1r/ppp2ppp/2n5/3q4/3pn3/2N2N2/PPP2PPP/R1BQR1K1 b kq - 1 8", "An exposed centre with forty-seven legal replies", ["b1", "c3"]),
  evans: position("Evans Gambit", "r1bqk1nr/pppp1ppp/2n5/b7/2B1P3/1QPp1N2/P4PPP/RNB2RK1 b kq - 1 8", "Material is secondary to time and open lines", ["d1", "b3"]),
  poisonedpawn: position("Najdorf Poisoned Pawn", "rnb1kb1r/1p3ppp/p2ppn2/6B1/3NPP2/q1N5/P1PQ2PP/1R2KB1R w Kkq - 2 10", "The queen raids b2 while development catches fire", ["b2", "a3"]),
  kingsgambit: position("King's Gambit melee", "rnbqkb1r/ppp2p1p/3p4/8/3PPnpP/2N5/PPP3P1/R1BQKB1R b KQkq - 0 9", "An open king, advanced pawns and unstable material", ["d2", "d4"]),
  traxler: position("Traxler counterattack", "r1bqk2r/pppp1Npp/2n5/4p3/2B1n3/4K3/PPPP2PP/RNBQ3R b kq - 1 7", "Both kings are exposed and quiet moves barely exist", ["f2", "e3"]),
  marshall: position("Marshall Attack", "r1bq1rk1/4bppp/p1p5/1p1nR3/8/1BP5/PP1P1PPP/RNBQ2K1 w - - 0 12", "Material traded for a sustained initiative", ["c7", "c6"]),
  semislav: position("Botvinnik Semi-Slav", "r1bqkb1r/3n1ppp/4pP2/1p6/3p4/3B1N2/PP3PPP/R1BQK2R b KQkq - 0 12", "Passed pawns and exposed diagonals make a calculation maze", ["e5", "f6"]),
  panov: position("Panov Attack", "rnbqk2r/pp3ppp/4p3/3n4/1b1P4/2N2N2/PP1B1PPP/R2QKB1R b KQkq - 1 8", "An isolated centre with forty-four candidate moves", ["c1", "d2"]),
  opposition: {
    name: "King and pawn ending",
    fen: "8/5pk1/6p1/3p4/3P4/5KP1/5P2/8 w - - 0 1",
    line: "A classical opposition battle where a single tempo can decide the result",
    aria: "King and pawn ending with White to move",
    last: [],
  },
  lucena: {
    name: "Lucena rook ending",
    fen: "1K6/1P3k2/8/8/8/8/r7/3R4 w - - 0 1",
    line: "The classic winning rook ending · build a bridge for the passed pawn",
    aria: "Lucena rook ending with White to move",
    last: [],
  },
  bishops: {
    name: "Opposite-coloured bishops",
    fen: "8/5pk1/4b1p1/3pP3/3P1P2/6P1/5BK1/8 w - - 0 1",
    line: "Opposite-coloured bishops turn pawn breaks and diagonals into the whole game",
    aria: "Opposite-coloured bishop ending with White to move",
    last: [],
  },
  rookrace: position("Rook and pawn race", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", "Passed pawns pull both rooks across the board"),
  philidor: position("Philidor rook defence", "8/8/8/4k3/4P3/8/6K1/3R1r2 w - - 0 1", "Checks, king shelter and one critical rank"),
  vancura: position("Vancura rook defence", "8/8/R7/P4k2/8/4r3/7K/8 b - - 0 1", "Side checks fight a rook pawn on the sixth"),
  rookpawns: position("Four-pawn rook ending", "8/5pk1/3p2p1/4p2p/4P3/3P1PP1/5K1P/2R3r1 w - - 0 1", "Active rooks versus a dense pawn structure"),
  queenend: position("Queen endgame", "6k1/5pp1/7p/3q4/3P4/4Q1P1/5P1P/6K1 w - - 0 1", "Checks branch everywhere across an open board"),
  queenpawn: position("Queen versus advanced pawn", "8/1P6/8/8/8/4k3/8/3Q2K1 w - - 0 1", "Promotion threats force exact queen geometry"),
  pawnrace: position("Opposite-wing pawn race", "8/5pk1/4p2p/8/8/1P4P1/5P1P/6K1 w - - 0 1", "Both kings choose between pursuit and promotion"),
  triangulation: position("King triangulation", "8/8/4k3/3p1p2/3P1P2/4K3/8/8 w - - 0 1", "A tiny tree where move order changes everything"),
  bishopknight: position("Bishop versus knight", "8/5pk1/3bp2p/4P3/2P2P2/2N3P1/5K1P/8 w - - 0 1", "Long diagonals against short-range blockades"),
  knights: position("Knight endgame", "8/5pk1/4p2p/3nP3/3N1P2/6P1/5K1P/8 w - - 0 1", "Outposts and zugzwang create looping routes"),
  samebishops: position("Same-coloured bishops", "8/5pk1/3bp2p/4P3/2P2P2/3B2P1/5K1P/8 w - - 0 1", "Competing diagonals and pawn targets"),
  rookknight: position("Rook and knight versus pawns", "6k1/5ppp/8/8/8/3N4/5PPP/4R1K1 w - - 0 1", "A material imbalance with a wide first ring"),
  bishoppair: position("Bishop pair versus knight", "8/5pk1/4p2p/8/2B2P2/2B2nP1/5K1P/8 b - - 0 1", "The side in check must find a path through two diagonals"),
  rookbishoprook: position("Rook and bishop versus rook", "8/8/8/4k3/8/3BK3/5R2/6r1 w - - 0 1", "A notoriously deep conversion on an almost empty board"),
  connectedpassers: position("Connected passed pawns", "8/2k5/8/3PP3/8/8/4K3/8 w - - 0 1", "Two pawns create a clean, deep promotion race"),
};

const POSITION_GROUPS = [
  { label: "Openings · broad trees", keys: ["ruy", "italian", "najdorf", "qgd", "slav", "winawer", "caro", "kingsindianopening", "grunfeld", "nimzo", "catalan", "english", "pirc", "dragon", "vienna", "smithmorra"] },
  { label: "Strategic middlegames", keys: ["carlsbad", "kingindian", "hanging", "closedruy", "iqp", "hedgehog", "maroczy", "stonewall", "botvinnik", "benoni", "frenchlocked", "symenglish"] },
  { label: "Tactical · high branching", keys: ["kiwipete", "promotionattack", "pinnedmaze", "greekgift", "yugoslav", "kidstorm", "legaltrap", "scotch", "evans", "poisonedpawn", "kingsgambit", "traxler", "marshall", "semislav", "panov"] },
  { label: "Endgames · deep geometry", keys: ["opposition", "lucena", "bishops", "rookrace", "philidor", "vancura", "rookpawns", "queenend", "queenpawn", "pawnrace", "triangulation", "bishopknight", "knights", "samebishops", "rookknight", "bishoppair", "rookbishoprook", "connectedpassers"] },
];

// Captured from the shipped v8.2 binary on the Ruy Lopez benchmark position.
// Scores below are converted from UCI side-to-move values to the website's
// usual White-relative convention.
const ITERATIONS = [
  { depth: 1, nodes: 60, nps: 60000, score: -26, uci: "a7a6" },
  { depth: 2, nodes: 226, nps: 226000, score: -17, uci: "g8e7" },
  { depth: 3, nodes: 510, nps: 510000, score: -11, uci: "d7d6" },
  { depth: 4, nodes: 1675, nps: 1675000, score: -4, uci: "h7h5" },
  { depth: 5, nodes: 5074, nps: 5074000, score: 19, uci: "g8e7" },
  { depth: 6, nodes: 8917, nps: 4458500, score: 6, uci: "g8e7" },
  { depth: 7, nodes: 17755, nps: 4438750, score: 0, uci: "g8e7" },
  { depth: 8, nodes: 37113, nps: 4123666, score: 0, uci: "g8e7" },
  { depth: 9, nodes: 148072, nps: 3796717, score: 28, uci: "g7g6" },
  { depth: 10, nodes: 501826, nps: 3717229, score: 40, uci: "g8e7" },
  { depth: 11, nodes: 747976, nps: 3702851, score: 35, uci: "g8e7" },
  { depth: 12, nodes: 1271020, nps: 3652356, score: 40, uci: "a7a6" },
];

const WALKTHROUGH = [
  {
    depth: 1,
    phase: "deepen",
    tag: "FIRST PASS",
    text: "Depth 1 is only a first draft. A full-window search puts 1…a6 in front after 60 nodes.",
  },
  {
    depth: 2,
    phase: "window",
    tag: "NARROW THE WINDOW",
    text: "The previous score seeds a narrow aspiration window and the old leader is searched first. One ply deeper, 1…Ne7 takes over.",
  },
  {
    depth: 4,
    phase: "pvs",
    tag: "CHEAP CHALLENGES",
    text: "The presumed best move gets a full search. Later candidates begin with narrow PVS probes; 1…h5 survives its challenge and becomes the new leader.",
  },
  {
    depth: 5,
    phase: "quiet",
    tag: "SETTLE THE LEAVES",
    text: "At nominal depth zero, quiescence continues forcing captures and checks. With those noisy leaves settled, 1…Ne7 returns and the score crosses to White's side.",
  },
  {
    depth: 8,
    phase: "window",
    tag: "REUSE OLD WORK",
    text: "Earlier iterations have filled the transposition table and trained move ordering. 1…Ne7 now holds for four completed depths while the tree grows to 37,113 nodes.",
  },
  {
    depth: 9,
    phase: "pvs",
    tag: "A DEEP REPLY",
    text: "Another ply exposes a reply that changes the root verdict. 1…g6 becomes best; branches that cannot beat the current bound are cut without full expansion.",
  },
  {
    depth: 10,
    phase: "quiet",
    tag: "RE-SEARCH",
    text: "A candidate that beats its narrow probe earns more work. The deeper pass restores 1…Ne7 after the search passes half a million nodes.",
  },
  {
    depth: 12,
    phase: "deepen",
    tag: "COMMIT",
    text: "Depth 12 completes at 1,271,020 nodes. 1…a6 returns as the leader, and Sgurr commits to it rather than using any unfinished next iteration.",
  },
];

const MOVE_NAMES = {
  a7a6: "a6",
  g8e7: "Ne7",
  d7d6: "d6",
  h7h5: "h5",
  g7g6: "g6",
};

const PIECE_NAMES = {
  p: "pawn",
  n: "knight",
  b: "bishop",
  r: "rook",
  q: "queen",
  k: "king",
};

const refs = {
  walkthroughTab: document.querySelector("#walkthroughTab"),
  liveTab: document.querySelector("#liveTab"),
  networkTab: document.querySelector("#networkTab"),
  modeNote: document.querySelector("#modeNote"),
  positionName: document.querySelector("#positionName"),
  sideBadge: document.querySelector("#sideBadge"),
  chessboard: document.querySelector("#chessboard"),
  positionLine: document.querySelector("#positionLine"),
  livePositionControls: document.querySelector("#livePositionControls"),
  positionSelect: document.querySelector("#positionSelect"),
  customFenPanel: document.querySelector("#customFenPanel"),
  customFenForm: document.querySelector("#customFenForm"),
  customFenInput: document.querySelector("#customFenInput"),
  customFenApply: document.querySelector("#customFenApply"),
  customFenStatus: document.querySelector("#customFenStatus"),
  networkDepthField: document.querySelector("#networkDepthField"),
  networkRunMode: document.querySelector("#networkRunMode"),
  networkDepth: document.querySelector("#networkDepth"),
  networkDepthHint: document.querySelector("#networkDepthHint"),
  runSearchButton: document.querySelector("#runSearchButton"),
  depthValue: document.querySelector("#depthValue"),
  nodesValue: document.querySelector("#nodesValue"),
  npsValue: document.querySelector("#npsValue"),
  scoreValue: document.querySelector("#scoreValue"),
  scoreKind: document.querySelector("#scoreKind"),
  leaderValue: document.querySelector("#leaderValue"),
  leaderUci: document.querySelector("#leaderUci"),
  rootLabel: document.querySelector("#rootLabel"),
  candidateGrid: document.querySelector("#candidateGrid"),
  eventTag: document.querySelector("#eventTag"),
  explanationText: document.querySelector("#explanationText"),
  walkthroughControls: document.querySelector("#walkthroughControls"),
  previousStep: document.querySelector("#previousStep"),
  playWalkthrough: document.querySelector("#playWalkthrough"),
  nextStep: document.querySelector("#nextStep"),
  stepScrubber: document.querySelector("#stepScrubber"),
  stepCount: document.querySelector("#stepCount"),
  livePanel: document.querySelector("#livePanel"),
  searchPanel: document.querySelector(".search-panel"),
  networkPanel: document.querySelector("#networkPanel"),
  iterationStrip: document.querySelector(".iteration-strip"),
  searchSignal: document.querySelector("#searchSignal"),
  liveDetail: document.querySelector("#liveDetail"),
  iterationChart: document.querySelector("#iterationChart"),
  iterationTitle: document.querySelector("#iterationTitle"),
  iterationCopy: document.querySelector("#iterationCopy"),
};

function populatePositionSelect() {
  const fragment = document.createDocumentFragment();
  for (const group of POSITION_GROUPS) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = group.label;
    for (const key of group.keys) {
      const entry = POSITIONS[key];
      const option = document.createElement("option");
      option.value = key;
      option.textContent = entry.name;
      option.title = entry.line;
      option.selected = key === "ruy";
      optgroup.appendChild(option);
    }
    fragment.appendChild(optgroup);
  }
  refs.positionSelect.replaceChildren(fragment);
}

let mode = "walkthrough";
let walkthroughIndex = 0;
let playTimer = null;
let liveController = null;
let liveIterations = [];
let liveCandidates = [];
let customPosition = null;
const searchNetwork = initSearchNetwork();
let networkDepthLimit = 20;
let publicDemo = false;
let capabilitiesReady = false;
let searchRunning = false;

function syncRunSearchButton() {
  refs.runSearchButton.disabled = !capabilitiesReady || searchRunning;
}

function demoDepthReason() {
  return `Depths above ${networkDepthLimit} are available locally and disabled on the free demo.`;
}

function selectedPosition() {
  if (refs.positionSelect.value === "custom" && customPosition) return customPosition;
  return POSITIONS[refs.positionSelect.value] || POSITIONS.ruy;
}

function selectedNetworkDepth() {
  return Number(refs.networkDepth.value) || 14;
}

function updateNetworkDepthControl() {
  const depth = selectedNetworkDepth();
  const live = refs.networkRunMode.value === "live";
  refs.runSearchButton.textContent = live
    ? `Watch depth-${depth} live`
    : `Record depth-${depth} search`;
  const hint = depth >= 18
    ? live
      ? "Extreme depth: watch every iteration live as the horizon expands from 1 to the target."
      : "Extreme depth: this can take a while, especially in tactical positions."
    : depth >= 14
      ? live
        ? "Every completed iteration stays in the web while the next depth unfolds."
        : "The full iterative search is recorded; real-time replay preserves its timing."
      : "The web streams continuously from depth 1 to the selected horizon.";
  refs.networkDepthHint.textContent = publicDemo ? `${hint} ${demoDepthReason()}` : hint;
  if (mode === "network") refs.modeNote.textContent = live
    ? `Live engine trace · depths 1–${depth} · no prerecorded motion`
    : `Recorded node trace · depths 1–${depth} · replayable`;
}

async function loadCapabilities() {
  capabilitiesReady = false;
  syncRunSearchButton();
  try {
    const response = await fetch(apiUrl("/api/capabilities"));
    if (!response.ok) return;
    const data = await response.json();
    publicDemo = Boolean(data.public_demo);
    networkDepthLimit = Number(data.limits?.search_network_depth) || 20;

    for (const option of refs.networkDepth.options) {
      option.dataset.label ||= option.textContent;
      const unavailable = publicDemo && Number(option.value) > networkDepthLimit;
      option.disabled = unavailable;
      option.textContent = unavailable
        ? `${option.dataset.label} · local only`
        : option.dataset.label;
      option.title = unavailable ? demoDepthReason() : "";
    }

    refs.networkDepth.title = publicDemo ? demoDepthReason() : "";
    setDemoReason(refs.networkDepth, publicDemo ? demoDepthReason() : "");
    if (selectedNetworkDepth() > networkDepthLimit) {
      const enabled = [...refs.networkDepth.options]
        .filter((option) => !option.disabled)
        .map((option) => Number(option.value));
      if (enabled.length) refs.networkDepth.value = String(Math.max(...enabled));
    }
    updateNetworkDepthControl();
  } catch {
    // Local static previews can run without a backend.
  } finally {
    capabilitiesReady = true;
    syncRunSearchButton();
  }
}

function positionSide(fen) {
  return fen.split(/\s+/)[1] === "b" ? "Black" : "White";
}

function validateFen(value) {
  const fields = value.trim().split(/\s+/);
  if (fields.length !== 6) return { error: "Use a complete FEN with all six fields." };
  const [placement, side, castling, enPassant, halfmove, fullmove] = fields;
  const rows = placement.split("/");
  if (rows.length !== 8) return { error: "The piece placement must contain eight ranks." };

  let whiteKings = 0;
  let blackKings = 0;
  for (const row of rows) {
    let squares = 0;
    for (const token of row) {
      if (/^[1-8]$/.test(token)) squares += Number(token);
      else if (/^[prnbqkPRNBQK]$/.test(token)) {
        squares += 1;
        if (token === "K") whiteKings += 1;
        if (token === "k") blackKings += 1;
      } else return { error: "The piece placement contains an unknown symbol." };
    }
    if (squares !== 8) return { error: "Every FEN rank must describe exactly eight squares." };
  }
  if (whiteKings !== 1 || blackKings !== 1) return { error: "The position needs exactly one king of each colour." };
  if (!/^[wb]$/.test(side)) return { error: "The side-to-move field must be w or b." };
  if (!(castling === "-" || (/^[KQkq]+$/.test(castling) && new Set(castling).size === castling.length))) {
    return { error: "The castling field is not valid." };
  }
  if (!/^(-|[a-h][36])$/.test(enPassant)) return { error: "The en-passant square is not valid." };
  if (!/^\d+$/.test(halfmove)) return { error: "The halfmove clock must be zero or greater." };
  if (!/^\d+$/.test(fullmove) || Number(fullmove) < 1) return { error: "The move number must be one or greater." };
  return { fen: fields.join(" ") };
}

function ensureCustomPositionOption() {
  let option = refs.positionSelect.querySelector('option[value="custom"]');
  if (option) return option;
  const group = document.createElement("optgroup");
  group.label = "Your position";
  group.dataset.customFenGroup = "true";
  option = document.createElement("option");
  option.value = "custom";
  option.textContent = "Custom FEN";
  group.appendChild(option);
  refs.positionSelect.appendChild(group);
  return option;
}

function applyCustomFen() {
  const result = validateFen(refs.customFenInput.value);
  if (result.error) {
    refs.customFenInput.setAttribute("aria-invalid", "true");
    refs.customFenStatus.dataset.state = "error";
    refs.customFenStatus.textContent = result.error;
    return false;
  }

  customPosition = position(
    "Custom position",
    result.fen,
    "Your FEN position - ready for Sgurr to search.",
  );
  ensureCustomPositionOption();
  refs.positionSelect.value = "custom";
  refs.customFenInput.setAttribute("aria-invalid", "false");
  refs.customFenStatus.dataset.state = "ready";
  refs.customFenStatus.textContent = `${positionSide(result.fen)} to move - position ready.`;
  if (liveController) liveController.abort();
  liveController = null;
  setPosition(customPosition);
  if (mode === "network") {
    searchNetwork.reset("Custom FEN loaded. Choose a depth and begin the search.");
    updateNetworkDepthControl();
  } else if (mode === "live") {
    resetLive();
  }
  return true;
}

function renderBoard(position) {
  refs.chessboard.innerHTML = "";
  refs.chessboard.setAttribute("aria-label", position.aria);
  const rows = position.fen.split(" ")[0].split("/");
  const lastSquares = new Set(position.last);

  rows.forEach((row, rowIndex) => {
    let fileIndex = 0;
    for (const token of row) {
      const empty = Number(token);
      if (Number.isInteger(empty) && empty > 0) {
        for (let count = 0; count < empty; count += 1) {
          addSquare(null, rowIndex, fileIndex, lastSquares);
          fileIndex += 1;
        }
      } else {
        addSquare(token, rowIndex, fileIndex, lastSquares);
        fileIndex += 1;
      }
    }
  });
}

function addSquare(piece, row, file, lastSquares) {
  const squareName = `${"abcdefgh"[file]}${8 - row}`;
  const square = document.createElement("span");
  square.className = `board-square ${(row + file) % 2 ? "dark" : "light"}`;
  if (lastSquares.has(squareName)) square.classList.add("last");

  if (piece) {
    const white = piece === piece.toUpperCase();
    const type = piece.toLowerCase();
    const image = document.createElement("img");
    image.className = "board-piece";
    image.src = `../assets/pieces/chessnut/${white ? "w" : "b"}${type.toUpperCase()}.svg`;
    image.alt = `${white ? "White" : "Black"} ${PIECE_NAMES[type]}`;
    image.draggable = false;
    square.appendChild(image);
  }

  if (file === 0) {
    const rank = document.createElement("span");
    rank.className = "coordinate rank";
    rank.textContent = String(8 - row);
    square.appendChild(rank);
  }
  if (row === 7) {
    const fileLabel = document.createElement("span");
    fileLabel.className = "coordinate file";
    fileLabel.textContent = "abcdefgh"[file];
    square.appendChild(fileLabel);
  }
  refs.chessboard.appendChild(square);
}

function setPosition(position) {
  refs.positionName.textContent = position.name;
  refs.positionLine.textContent = position.line;
  const side = positionSide(position.fen);
  refs.sideBadge.textContent = `${side} to move`;
  refs.rootLabel.textContent = `${side} chooses`;
  renderBoard(position);
}

function formatCount(value) {
  const number = Number(value) || 0;
  return new Intl.NumberFormat("en-GB").format(number);
}

function formatRate(value) {
  const number = Number(value) || 0;
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}m nps`;
  if (number >= 1_000) return `${Math.round(number / 1_000)}k nps`;
  return `${number} nps`;
}

function formatScore(score) {
  const value = Number(score) || 0;
  if (value === 0) return "0.00";
  return `${value > 0 ? "+" : "−"}${(Math.abs(value) / 100).toFixed(2)}`;
}

function moveLabel(uci) {
  if (!uci) return "—";
  if (MOVE_NAMES[uci]) return MOVE_NAMES[uci];
  if (uci.length >= 4) return `${uci.slice(0, 2)}→${uci.slice(2, 4)}${uci.slice(4)}`;
  return uci;
}

function setPhase(name) {
  document.querySelectorAll(".search-phases span").forEach((phase) => {
    phase.classList.toggle("active", phase.dataset.phase === name);
  });
}

function createCandidate(uci, state, leader) {
  const node = document.createElement("div");
  node.className = `candidate-node seen${leader ? " leader" : ""}`;
  node.dataset.uci = uci;
  const title = document.createElement("strong");
  title.textContent = moveLabel(uci);
  const code = document.createElement("code");
  code.textContent = uci;
  const status = document.createElement("span");
  status.className = "candidate-state";
  status.textContent = state;
  const replies = document.createElement("span");
  replies.className = "reply-lines";
  replies.setAttribute("aria-hidden", "true");
  replies.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
  node.append(title, code, status, replies);
  return node;
}

function renderWalkthroughCandidates(depth, leader) {
  refs.candidateGrid.innerHTML = "";
  refs.candidateGrid.classList.remove("live-grid");
  const firstDepth = new Map();
  ITERATIONS.forEach((iteration) => {
    if (!firstDepth.has(iteration.uci)) firstDepth.set(iteration.uci, iteration.depth);
  });
  firstDepth.forEach((seenDepth, uci) => {
    const seen = seenDepth <= depth;
    const node = createCandidate(
      uci,
      uci === leader ? `leader at depth ${depth}` : seen ? `first led at depth ${seenDepth}` : "not reached yet",
      uci === leader,
    );
    node.classList.toggle("seen", seen);
    if (!seen) node.classList.remove("seen");
    refs.candidateGrid.appendChild(node);
  });
}

function renderLiveCandidates(leader, depth) {
  refs.candidateGrid.innerHTML = "";
  refs.candidateGrid.classList.add("live-grid");
  if (!liveCandidates.length) {
    const empty = createCandidate("waiting", "completed depths will appear here", false);
    empty.classList.remove("seen");
    empty.querySelector("strong").textContent = "No leader yet";
    empty.querySelector("code").textContent = "—";
    refs.candidateGrid.appendChild(empty);
    return;
  }
  liveCandidates.forEach((candidate) => {
    refs.candidateGrid.appendChild(createCandidate(
      candidate.uci,
      candidate.uci === leader ? `leader at depth ${depth}` : `first led at depth ${candidate.depth}`,
      candidate.uci === leader,
    ));
  });
}

function renderIterationChart(iterations, currentDepth, interactive) {
  refs.iterationChart.innerHTML = "";
  refs.iterationChart.style.gridTemplateColumns = `repeat(${Math.min(12, Math.max(4, iterations.length))}, minmax(36px, 1fr))`;
  iterations.forEach((iteration) => {
    const item = document.createElement(interactive ? "button" : "div");
    if (interactive) item.type = "button";
    item.className = `iteration${iteration.depth === currentDepth ? " current" : ""}`;
    const depth = document.createElement("strong");
    depth.textContent = `d${iteration.depth}`;
    const score = document.createElement("span");
    score.textContent = iteration.kind === "mate" ? iteration.display : formatScore(iteration.score ?? iteration.value);
    const move = document.createElement("small");
    move.textContent = moveLabel(iteration.uci ?? iteration.pv?.[0]);
    item.append(depth, score, move);
    if (interactive) {
      item.setAttribute("aria-label", `Show depth ${iteration.depth}`);
      item.addEventListener("click", () => {
        const target = WALKTHROUGH.findIndex((step) => step.depth >= iteration.depth);
        walkthroughIndex = target < 0 ? WALKTHROUGH.length - 1 : target;
        stopWalkthrough();
        renderWalkthrough();
      });
    }
    refs.iterationChart.appendChild(item);
  });
}

function renderWalkthrough() {
  const step = WALKTHROUGH[walkthroughIndex];
  const iteration = ITERATIONS.find((item) => item.depth === step.depth);
  refs.depthValue.textContent = String(iteration.depth);
  refs.nodesValue.textContent = formatCount(iteration.nodes);
  refs.npsValue.textContent = formatRate(iteration.nps);
  refs.scoreValue.textContent = formatScore(iteration.score);
  refs.scoreKind.textContent = "pawns · White relative";
  refs.leaderValue.textContent = moveLabel(iteration.uci);
  refs.leaderUci.textContent = iteration.uci;
  refs.eventTag.textContent = step.tag;
  refs.explanationText.textContent = step.text;
  refs.stepScrubber.value = String(walkthroughIndex);
  refs.stepCount.textContent = `${walkthroughIndex + 1} / ${WALKTHROUGH.length}`;
  refs.previousStep.disabled = walkthroughIndex === 0;
  refs.nextStep.disabled = walkthroughIndex === WALKTHROUGH.length - 1;
  setPhase(step.phase);
  renderWalkthroughCandidates(iteration.depth, iteration.uci);
  renderIterationChart(ITERATIONS, iteration.depth, true);
}

function stopWalkthrough() {
  if (playTimer !== null) window.clearInterval(playTimer);
  playTimer = null;
  refs.playWalkthrough.textContent = "Play";
}

function toggleWalkthrough() {
  if (playTimer !== null) {
    stopWalkthrough();
    return;
  }
  if (walkthroughIndex === WALKTHROUGH.length - 1) walkthroughIndex = 0;
  renderWalkthrough();
  refs.playWalkthrough.textContent = "Pause";
  playTimer = window.setInterval(() => {
    if (walkthroughIndex >= WALKTHROUGH.length - 1) {
      stopWalkthrough();
      return;
    }
    walkthroughIndex += 1;
    renderWalkthrough();
  }, 1900);
}

function resetLive() {
  const position = selectedPosition();
  setPosition(position);
  liveIterations = [];
  liveCandidates = [];
  refs.depthValue.textContent = "—";
  refs.nodesValue.textContent = "0";
  refs.npsValue.textContent = "waiting";
  refs.scoreValue.textContent = "—";
  refs.scoreKind.textContent = "White relative";
  refs.leaderValue.textContent = "—";
  refs.leaderUci.textContent = "waiting";
  refs.eventTag.textContent = "LIVE TRACE";
  refs.explanationText.textContent = "Run the engine to watch each completed iterative-deepening pass arrive from Sgurr in real time.";
  refs.searchSignal.className = "search-signal";
  refs.searchSignal.querySelector("strong").textContent = "Ready for a live search";
  refs.liveDetail.textContent = "This starts a separate Sgurr process, so it cannot interrupt anyone playing a game.";
  setPhase("deepen");
  renderLiveCandidates(null, 0);
  renderIterationChart([], 0, false);
}

function setMode(nextMode) {
  mode = nextMode;
  const live = mode === "live";
  const network = mode === "network";
  const walkthrough = mode === "walkthrough";
  stopWalkthrough();
  refs.walkthroughTab.classList.toggle("active", walkthrough);
  refs.walkthroughTab.setAttribute("aria-pressed", String(walkthrough));
  refs.liveTab.classList.toggle("active", live);
  refs.liveTab.setAttribute("aria-pressed", String(live));
  refs.networkTab.classList.toggle("active", network);
  refs.networkTab.setAttribute("aria-pressed", String(network));
  refs.livePositionControls.hidden = walkthrough;
  refs.networkDepthField.hidden = !network;
  refs.walkthroughControls.hidden = !walkthrough;
  refs.livePanel.hidden = !live;
  refs.searchPanel.hidden = network;
  refs.networkPanel.hidden = !network;
  refs.iterationStrip.hidden = network;
  refs.modeNote.textContent = network
    ? refs.networkRunMode.value === "live"
      ? `Live engine trace · depths 1–${selectedNetworkDepth()} · no prerecorded motion`
      : `Recorded node trace · depths 1–${selectedNetworkDepth()} · replayable`
    : live
      ? "A separate engine process · completed depths only"
      : "Recorded from Sgurr v8.2 · exact completed-depth output";
  refs.iterationTitle.textContent = live ? "The live verdict" : "The verdict keeps moving";
  refs.iterationCopy.textContent = live
    ? "Every mark arrives directly from the engine. The final mark is the deepest pass completed before its time limit."
    : "Each dot is a fully completed depth. Unfinished work is discarded when the clock expires.";

  if (network) {
    if (liveController) liveController.abort();
    liveController = null;
    setPosition(selectedPosition());
    updateNetworkDepthControl();
    syncRunSearchButton();
    searchNetwork.reset();
  } else if (live) {
    searchNetwork.reset();
    refs.runSearchButton.textContent = "Run a 1.5 second search";
    syncRunSearchButton();
    resetLive();
  } else {
    searchNetwork.reset();
    if (liveController) liveController.abort();
    liveController = null;
    setPosition(POSITIONS.ruy);
    renderWalkthrough();
  }
}

async function runNetworkSearch() {
  if (!capabilitiesReady || searchRunning) return;
  const position = selectedPosition();
  const depth = selectedNetworkDepth();
  if (depth > networkDepthLimit) {
    refs.networkDepthHint.textContent = demoDepthReason();
    return;
  }
  const runMode = refs.networkRunMode.value;
  searchRunning = true;
  syncRunSearchButton();
  refs.networkRunMode.disabled = true;
  refs.networkDepth.disabled = true;
  refs.runSearchButton.textContent = runMode === "live"
    ? `Watching depth ${depth}…`
    : `Searching to depth ${depth}…`;
  try {
    await searchNetwork.load(position.fen, depth, runMode);
  } finally {
    searchRunning = false;
    refs.networkRunMode.disabled = false;
    refs.networkDepth.disabled = false;
    syncRunSearchButton();
  }
  if (mode !== "network") {
    refs.runSearchButton.textContent = mode === "live" ? "Run a 1.5 second search" : "Run search";
    return;
  }
  refs.runSearchButton.textContent = runMode === "live"
    ? `Watch depth ${depth} again`
    : `Record depth ${depth} again`;
}

function handleLiveEvent(event) {
  if (event.type === "started") {
    refs.searchSignal.querySelector("strong").textContent = `${event.label} is searching`;
    return;
  }
  if (event.type === "error") throw new Error(event.detail || "The engine trace stopped");
  if (event.type === "complete") {
    refs.searchSignal.className = "search-signal complete";
    refs.searchSignal.querySelector("strong").textContent = `Committed to ${moveLabel(event.bestmove)}`;
    refs.liveDetail.textContent = `${liveIterations.length} completed depths streamed. Any unfinished next pass was discarded.`;
    syncRunSearchButton();
    refs.runSearchButton.textContent = "Run again";
    return;
  }
  if (event.type !== "iteration") return;

  const uci = event.pv?.[0] || "—";
  const iteration = { ...event, uci, score: event.value };
  liveIterations.push(iteration);
  if (uci !== "—" && !liveCandidates.some((candidate) => candidate.uci === uci)) {
    liveCandidates.push({ uci, depth: event.depth });
  }
  refs.depthValue.textContent = String(event.depth ?? "—");
  refs.nodesValue.textContent = formatCount(event.nodes);
  refs.npsValue.textContent = formatRate(event.nps || ((event.nodes || 0) / Math.max(event.time_ms || 1, 1)) * 1000);
  refs.scoreValue.textContent = event.kind === "mate" ? event.display : formatScore(event.value);
  refs.scoreKind.textContent = event.kind === "mate" ? "forced mate · White relative" : "pawns · White relative";
  refs.leaderValue.textContent = moveLabel(uci);
  refs.leaderUci.textContent = uci;
  refs.eventTag.textContent = `DEPTH ${event.depth} COMPLETE`;
  refs.explanationText.textContent = `${moveLabel(uci)} leads after ${formatCount(event.nodes)} searched nodes. Sgurr now starts a deeper pass using this result to order the next search.`;
  // UCI reports a completed depth, not the engine's current interior-node
  // mechanism. Keep the live highlight on the one fact the stream proves.
  setPhase("deepen");
  renderLiveCandidates(uci, event.depth);
  renderIterationChart(liveIterations, event.depth, false);
  refs.liveDetail.textContent = `Depth ${event.depth} arrived after ${formatCount(event.time_ms)} ms. The stream carries completed iterations, not individual nodes.`;
}

async function readNdjson(response) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("This browser cannot read the live search stream");
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.trim()) handleLiveEvent(JSON.parse(line));
    }
    if (done) break;
  }
  if (buffer.trim()) handleLiveEvent(JSON.parse(buffer));
}

async function runLiveSearch() {
  if (!capabilitiesReady || searchRunning) return;
  if (liveController) liveController.abort();
  liveController = new AbortController();
  const position = selectedPosition();
  resetLive();
  searchRunning = true;
  syncRunSearchButton();
  refs.runSearchButton.textContent = "Searching…";
  refs.searchSignal.className = "search-signal searching";
  refs.searchSignal.querySelector("strong").textContent = "Starting Sgurr";
  refs.liveDetail.textContent = "The first completed depth will appear almost immediately.";

  try {
    const response = await fetch(apiUrl("/api/search-trace"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fen: position.fen, engine: "v8.2", movetime_ms: 1500 }),
      signal: liveController.signal,
    });
    if (!response.ok) {
      let detail = `Search request failed (${response.status})`;
      try { detail = (await response.json()).detail || detail; } catch { /* keep status */ }
      throw new Error(detail);
    }
    await readNdjson(response);
  } catch (error) {
    if (error.name === "AbortError") return;
    refs.searchSignal.className = "search-signal error";
    refs.searchSignal.querySelector("strong").textContent = "Live search unavailable";
    refs.liveDetail.textContent = error.message || String(error);
    refs.eventTag.textContent = "CONNECTION LOST";
    refs.explanationText.textContent = "The guided walkthrough remains available even when the engine backend is offline.";
    syncRunSearchButton();
    refs.runSearchButton.textContent = "Try again";
  } finally {
    liveController = null;
    searchRunning = false;
    syncRunSearchButton();
  }
}

refs.walkthroughTab.addEventListener("click", () => setMode("walkthrough"));
refs.liveTab.addEventListener("click", () => setMode("live"));
refs.networkTab.addEventListener("click", () => setMode("network"));
refs.previousStep.addEventListener("click", () => {
  stopWalkthrough();
  walkthroughIndex = Math.max(0, walkthroughIndex - 1);
  renderWalkthrough();
});
refs.nextStep.addEventListener("click", () => {
  stopWalkthrough();
  walkthroughIndex = Math.min(WALKTHROUGH.length - 1, walkthroughIndex + 1);
  renderWalkthrough();
});
refs.playWalkthrough.addEventListener("click", toggleWalkthrough);
refs.stepScrubber.addEventListener("input", () => {
  stopWalkthrough();
  walkthroughIndex = Number(refs.stepScrubber.value);
  renderWalkthrough();
});
refs.customFenForm.addEventListener("submit", (event) => {
  event.preventDefault();
  applyCustomFen();
});
refs.customFenInput.addEventListener("input", () => {
  if (refs.customFenInput.getAttribute("aria-invalid") !== "true") return;
  refs.customFenInput.removeAttribute("aria-invalid");
  refs.customFenStatus.dataset.state = "";
  refs.customFenStatus.textContent = "The board and side to move will update before you search.";
});
refs.positionSelect.addEventListener("change", () => {
  if (mode === "network") {
    setPosition(selectedPosition());
    searchNetwork.reset();
    updateNetworkDepthControl();
  } else {
    resetLive();
  }
});
refs.networkDepth.addEventListener("change", () => {
  searchNetwork.reset();
  updateNetworkDepthControl();
});
refs.networkRunMode.addEventListener("change", () => {
  searchNetwork.reset();
  updateNetworkDepthControl();
});
refs.runSearchButton.addEventListener("click", () => {
  if (mode === "network") runNetworkSearch();
  else runLiveSearch();
});

populatePositionSelect();
initDemoTooltips();
initLabPreferences();
setPosition(POSITIONS.ruy);
if (new URLSearchParams(window.location.search).get("mode") === "network") {
  setMode("network");
} else {
  renderWalkthrough();
}
loadCapabilities();
