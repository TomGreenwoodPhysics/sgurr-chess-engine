// Carry an explicitly supplied position between the overview and labs.
const requestedFen = new URLSearchParams(location.search).get("fen");
const labFen = requestedFen && requestedFen.length <= 128 ? requestedFen.trim() : null;

function preserveLabPosition() {
  if (!labFen) return;
  document.querySelectorAll(".lab-switch a, .lab-choice-card").forEach((link) => {
    const url = new URL(link.href);
    url.searchParams.set("fen", labFen);
    link.href = url.href;
  });
}

export { labFen, preserveLabPosition };
