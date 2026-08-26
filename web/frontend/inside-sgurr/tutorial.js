import { initLabTour } from "../js/lab-tour.js";

const STEPS = Object.freeze([
  {
    key: "model",
    selector: ".model-line",
    placement: "bottom",
    kicker: "Start here",
    title: "What NNUE does",
    text: "NNUE is the small neural network Sgurr uses to score a position. Search calls it again and again; this page shows one call on its own.",
  },
  {
    key: "board",
    selector: "#nnueBoard",
    placement: "right",
    kicker: "01 / Input",
    title: "The board becomes numbers",
    text: "The network does not see a picture. Every piece and square selects a stored row of numbers that was adjusted during training.",
  },
  {
    key: "trace",
    selector: "#pieceInspector",
    placement: "right",
    kicker: "Follow one piece",
    title: "One piece feeds both views",
    text: "Click a piece to trace it. Its row is added once from White's view and once from Black's mirrored view.",
  },
  {
    key: "accumulators",
    selector: ".cortex-stage",
    placement: "left",
    kicker: "02 / Accumulators",
    title: "The rows are added together",
    text: "The two panels each hold 384 totals. Every piece contributes to them. Larger, brighter lanes are carrying stronger values.",
  },
  {
    key: "modes",
    selector: ".display-mode-buttons",
    placement: "bottom",
    kicker: "Change the reading",
    title: "Four ways to read the lanes",
    text: "Contribution shows effect on the score. Move change isolates one move. Activation shows values after clipping. Clipped shows values held at 0 or 255.",
  },
  {
    key: "timeline",
    selector: ".state-rail",
    placement: "top",
    kicker: "After a move",
    title: "See what changed",
    text: "Make a legal move, then use Before, Change and After to separate the old position from the update. Replay runs those stages in order.",
  },
  {
    key: "autopsy",
    selector: "#moveAutopsy",
    placement: "top",
    kicker: "Move autopsy",
    title: "Find the lanes that mattered",
    text: "After a move, this list ranks the biggest changes for each side. Select a lane to see its exact arithmetic in the readout.",
  },
  {
    key: "output",
    selector: ".eval-readout",
    placement: "left",
    kicker: "03 / Output",
    title: "One score comes out",
    text: "The last layer combines the 768 lane values into one number. Positive favours White; negative favours Black. It is a static score, not a search result.",
  },
]);

export function initNnueTutorial() {
  return initLabTour({
    name: "nnue",
    storageKey: "sgurrNnueTutorialSeen",
    steps: STEPS,
  });
}
