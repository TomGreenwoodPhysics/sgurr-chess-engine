# Sgurr Project Provenance

This record documents the evidence currently present in the repository. It is
intended to make a future commercial release review reproducible. The owner
attestation at the end must be completed before a public commercial release.

## Original Project Work

| Area | Repository evidence | Recorded status |
| --- | --- | --- |
| Sgurr engine | `sgurr_cpp/main.cpp` emits `id author Tom`; engine sources live under `sgurr_cpp/`. | Project-created; owner confirmation required. |
| Web application | Backend and browser implementation live under `web/` and were developed specifically for Sgurr. | Project-created; owner confirmation required. |
| Desktop GUI | The pygame desktop client was the design and behaviour reference for the web application. Superseded by `web/` and archived at the `archive/desktop-gui-final` tag. | Project-created; owner confirmation required. |
| Sgurr v4 NNUE/data | `data/v4.0/manifest.json` records 6,000,204 self-play positions, generation settings, shard hashes, and archive hash. | Self-play provenance recorded; owner confirmation required. |
| Opening positions | `testing/book_gen.py` generates balanced random legal openings; `testing/README.md` documents the process. | Repository-generated; owner confirmation required. |
| Intro artwork | Source artwork and web derivatives live under `web/frontend/assets/intro/` with recorded release hashes. | Bundled project asset; release hash recorded. |

The asset and dependency records are maintained separately in
`THIRD_PARTY_ASSETS.md` and `THIRD_PARTY_NOTICES.md`.

## Model Release Record

The record for the currently shipped network is
[`../nets/README.md`](../nets/README.md), `gen8.nnue`, with its SHA-256,
dataset manifest, training configuration, labeller and source commit.

For every shipped NNUE file:

1. Record the exact filename and SHA-256 hash.
2. Link it to the dataset manifest, training configuration, and source commit.
3. Retain the self-play shard/archive hashes and the generating engine build.
4. Confirm that no externally sourced game database or model weights entered
   the training pipeline unless their licence and provenance are documented.
5. Keep the signed release record outside the repository as well as in the
   release archive.

## Owner Attestation

Before commercial release, the owner should sign and date a copy of this
checklist:

- I confirm that I own, or have written permission to commercialise, the
  original Sgurr engine, frontend, backend, desktop GUI, and model artefacts.
- I have reviewed contributor history and obtained any required assignments or
  permissions.
- I have verified the shipped model against its recorded hash and provenance.
- I have included all required third-party notices and licence texts.
- I have excluded legacy or experimental assets whose provenance is not clear.
- I have reviewed the product name, logo, domain, privacy disclosures, terms of
  use, and any consumer-law obligations for the intended markets.
- I understand that a hosted website and a downloadable backend/desktop bundle
  have different third-party software distribution obligations.

Owner: ______________________________

Signature: ___________________________  Date: __________________

