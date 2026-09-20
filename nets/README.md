# Networks

Trained NNUE files are build artefacts, so only shipped networks are committed.
`gen9.nnue` is the current network. `gen8.nnue` remains for older releases.

```bash
SGR_EVALFILE=nets/gen9.nnue sgurr_cpp/sgr.exe bench
#   -> nodes 3337275
```

The engine reads `$SGR_EVALFILE`, defaulting to `sgurr.nnue` in the working
directory. With no network it uses the hand-crafted evaluation and says so on
stdout, so a missing net is visible rather than silent.

---

## Model release record: gen9.nnue

| | |
|---|---|
| file | `gen9.nnue` |
| SHA-256 | `92c925ce1036035119e5921248a8b48a34304d1834be07cfa27924e787632ce1` |
| size | 592,160 bytes |
| architecture | `768 -> 384 -> 1`, integer-quantised, output scale 400 |
| shipped in | v9.0 "Dearg" |
| dataset | [../data/gen9_102m/manifest.json](../data/gen9_102m/manifest.json), 102,011,689 self-play positions, SHA-256 `fb42bb334652ed60b702a53553a976ea5e5fdd6af1930bbd43dfe700ce339f60` |
| labeller | `nets/gen8.nnue` at 150,000 nodes per move |
| training | [../data/gen9_102m/training_log.json](../data/gen9_102m/training_log.json), seed 0, lambda 0.8, 8 epochs, batch 16,384, Adam, cosine learning rate, no validation split |
| source commit | `dc6d05f` |

Lambda 0.8 was selected by games. It beat lambda 0.9 by 18.1 ±16.9 Elo and
lambda 0.7 by 23.3 ±18.5 Elo in 1,000-game seed-0 matches. Final pool
calibration measured **3081.2 ±6.7** over 6,508 valid games.

```bash
sha256sum nets/gen9.nnue
# 92c925ce1036035119e5921248a8b48a34304d1834be07cfa27924e787632ce1

cd sgurr_cpp && ./nnue_selfcheck.exe ../nets/gen9.nnue
# checks=4516 fails=0 evalsum=-10123 -> PASS
```

---

## Model release record: gen8.nnue

Recorded per the checklist in
[../docs/PROJECT_PROVENANCE.md](../docs/PROJECT_PROVENANCE.md).

| | |
|---|---|
| file | `gen8.nnue` |
| SHA-256 | `896eb832d74776a42375e7fa152b4e032fff1cf85ba2e529b420fe2d1b4b74bf` |
| size | 592,160 bytes |
| architecture | `768 → 384 → 1` perspective, integer-quantised (QA 255, QB 64, output scale 400) |
| shipped in | v8.0 "Thearlaich", v8.1, v8.2 |
| dataset | [../data/v8.0/manifest.json](../data/v8.0/manifest.json), 55,931,801 self-play positions over 60 shards, archive SHA-256 `ec315af911878c51a40149b2610b779bf208f46ad6e28223182cbe30b3c3e220` |
| labeller | `nets/gen7.nnue` at `nodes:150000` per move |
| training config | [../configs/pipeline_gen8.json](../configs/pipeline_gen8.json), 8 epochs, cosine schedule, `val_frac` 0 |
| λ | 0.9, selected by games in the pipeline's `select` stage (0.9 and 1.0 were both trained) |
| loss curve | [../data/v8.0/training_log.json](../data/v8.0/training_log.json) |
| source commit | `4a2fe06`: the gen8 cycle that froze the dataset and shipped the net |

**Provenance.** Positions are Sgurr self-play throughout, labelled by the
previous generation's own network. No external game database, opening
database beyond the repository's generated `testing/book.epd`, or third-party
model weights entered the training pipeline. The net is original Sgurr
material under [../LICENSE](../LICENSE).

**Selected by games, not by loss.** The λ=1.0 variant trained to a lower loss
(0.00558 vs 0.00682 final epoch) and lost the playoff. That is the project's
standing rule, and [../docs/METHODOLOGY.md](../docs/METHODOLOGY.md) records why.

**Verify what you have:**

```bash
sha256sum nets/gen8.nnue
# 896eb832d74776a42375e7fa152b4e032fff1cf85ba2e529b420fe2d1b4b74bf

# Bit-exactness of engine inference against the trainer's forward pass:
cd sgurr_cpp && ./nnue_selfcheck.exe ../nets/gen8.nnue
#   -> checks=4516 fails=0 evalsum=-142859 -> PASS
```
