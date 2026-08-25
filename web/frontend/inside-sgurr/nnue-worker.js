import { EXPECTED_NETWORK, evaluateTransition, parseNnue } from "./nnue-model.js";

let network = null;

function hex(buffer) {
  return [...new Uint8Array(buffer)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

self.addEventListener("message", async (event) => {
  const message = event.data || {};
  try {
    if (message.type === "load") {
      const response = await fetch(message.url, { cache: "force-cache" });
      if (!response.ok) {
        throw new Error(`Evaluator download failed (${response.status})`);
      }
      const buffer = await response.arrayBuffer();
      const digest = await crypto.subtle.digest("SHA-256", buffer);
      if (hex(digest) !== EXPECTED_NETWORK.sha256) {
        throw new Error("Evaluator checksum does not match Gen8");
      }
      network = parseNnue(buffer);
      self.postMessage({
        type: "loaded",
        requestId: message.requestId,
        architecture: {
          version: network.version,
          input: network.input,
          hidden: network.hidden,
          qa: network.qa,
          qb: network.qb,
          scale: network.scale,
          bytes: buffer.byteLength,
          sha256: EXPECTED_NETWORK.sha256,
        },
      });
      return;
    }

    if (message.type === "evaluate") {
      if (!network) {
        throw new Error("Evaluator is not loaded");
      }
      const transition = evaluateTransition(network, message.beforeFen, message.afterFen);
      self.postMessage({ type: "evaluation", requestId: message.requestId, transition });
    }
  } catch (error) {
    self.postMessage({
      type: "error",
      requestId: message.requestId,
      detail: error instanceof Error ? error.message : String(error),
    });
  }
});
