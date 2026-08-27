# Project provenance

Original Sgurr source code, documentation, model files and project assets are
copyright Tom Greenwood under the terms in [`../LICENSE`](../LICENSE).

## Repository records

| Area | Record |
| --- | --- |
| C++ engine | Sources are in `sgurr_cpp/`; the UCI identity is defined in `sgurr_cpp/main.cpp`. |
| Web application | The FastAPI backend and browser frontend are in `web/`. |
| Training pipeline | Training, export and verification code is in `nnue/` and `pipeline.py`. |
| Self-play data | Versioned manifests and training logs are in `data/`. |
| Opening positions | `testing/book_gen.py` generates balanced legal openings. |
| Intro artwork | The source image is `docs/assets/sgurr-cave-chamber-source.png`; web derivatives are in `web/frontend/assets/intro/`. |

## Shipped network

[`../nets/README.md`](../nets/README.md) records the SHA-256, dataset manifest,
training configuration, labeller and source commit for `gen8.nnue`. The model
was trained from Sgurr self-play data. No external game database or model
weights entered the training pipeline.

## Third-party material

Third-party software and media retain their own terms. They are listed in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and
[`THIRD_PARTY_ASSETS.md`](THIRD_PARTY_ASSETS.md), with dependency licence texts
under `web/licenses/`.

