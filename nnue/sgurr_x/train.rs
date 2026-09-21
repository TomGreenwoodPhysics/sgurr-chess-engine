/*
Sgurr-X stage X0: 768 -> 1024 -> 1, trained on public Stockfish/Lc0 data.

Matches Sgurr's inference exactly, so no C++ changes are needed:
  - crelu, NOT screlu. sgurr_cpp/nnue.cpp clamps to [0, QA] and feeds the
    result straight to madd. Training screlu here would produce a net that
    trains well and plays terribly.
  - QA/QB/SCALE below are copied from sgurr_cpp/nnue.hpp. Do not drift.
  - 768 inputs, dual perspective, concat(stm, ntm) -- the same order the
    engine reads as out_weight[k] and out_weight[HL + k].

HL is a compile-time constant in the engine, so this trains against a build
made with -DSGR_HL=1024. The loader rejects a mismatch, so a wrong pairing
fails loudly rather than silently.

Run:  cargo r -r --example sgurr_x
Then: python nnue/sgurr_x/export.py checkpoints/<name>/quantised.bin nets/sgurr_x.nnue
*/
use bullet_lib::{
    game::inputs::Chess768,
    nn::optimiser::AdamW,
    trainer::{
        save::SavedFormat,
        schedule::{TrainingSchedule, TrainingSteps, lr, wdl},
        settings::LocalSettings,
    },
    value::{ValueTrainerBuilder, loader},
};

const HIDDEN_SIZE: usize = 1024;
const SCALE: i32 = 400;
const QA: i16 = 255;
const QB: i16 = 64;

fn main() {
    let mut trainer = ValueTrainerBuilder::default()
        .dual_perspective()
        .optimiser(AdamW)
        .inputs(Chess768)
        .save_format(&[
            SavedFormat::id("l0w").round().quantise::<i16>(QA),
            SavedFormat::id("l0b").round().quantise::<i16>(QA),
            SavedFormat::id("l1w").round().quantise::<i16>(QB),
            SavedFormat::id("l1b").round().quantise::<i16>(QA * QB),
        ])
        .loss_fn(|output, target| output.sigmoid().squared_error(target))
        .build(|builder, stm_inputs, ntm_inputs| {
            let l0 = builder.new_affine("l0", 768, HIDDEN_SIZE);
            let l1 = builder.new_affine("l1", 2 * HIDDEN_SIZE, 1);

            let stm_hidden = l0.forward(stm_inputs).crelu();
            let ntm_hidden = l0.forward(ntm_inputs).crelu();
            l1.forward(stm_hidden.concat(ntm_hidden))
        });

    let schedule = TrainingSchedule {
        net_id: "sgurr_x_hl1024".to_string(),
        eval_scale: SCALE as f32,
        steps: TrainingSteps {
            batch_size: 16_384,
            batches_per_superbatch: 6104,
            start_superbatch: 1,
            // 40 superbatches ~= 4B positions ~= 3.4 epochs of S1's 1.18B.
            end_superbatch: 40,
        },
        // NOTE: bullet's wdl is the weight on the GAME RESULT. Sgurr's lambda
        // is the weight on the SEARCH SCORE, so they are inverses: Sgurr's
        // lambda 0.8 corresponds to wdl 0.2. Do not carry that number across
        // anyway -- 0.8 was fitted to Sgurr's own labels, and these are
        // Stockfish's. 0.3 is a starting guess and wants a sweep.
        wdl_scheduler: wdl::ConstantWDL { value: 0.3 },
        lr_scheduler: lr::StepLR { start: 0.001, gamma: 0.3, step: 15 },
        save_rate: 10,
    };

    let settings = LocalSettings {
        threads: 4,
        test_set: None,
        output_directory: "checkpoints",
        batch_queue_size: 64,
    };

    // Decompressed bulletformat. S1 is Stockfish-generated, S2 is Lc0-derived;
    // Stockfish's own advice is S1 first, then retrain on S2.
    let data_loader = loader::DirectSequentialDataLoader::new(&[
        "../../data/sgurr_x/UHO.pdist.iter-1.bullet.bin",
    ]);

    trainer.run(&schedule, &settings, &data_loader);
}
