# Asset Provenance And Distribution Review

This manifest covers visual and audio assets used by the Sgurr web application
as of 27 August 2026. Keep it with release records and update it whenever an
asset is added, replaced, or modified.

The linked source pages and their displayed licence labels were rechecked on
13 July 2026. Hashes for the exact local files are in
`web/ASSET_CHECKSUMS.sha256`.

## Commercial Readiness

**Web asset status: cleared for commercial redistribution under the recorded
terms.** The former non-commercial Cardinal pieces have been removed from the
web application, and ordinary UI/game cues are now generated procedurally.

This is an asset inventory, not legal advice or a certification of the full
repository.

Status meanings:

| Status | Meaning |
| --- | --- |
| `CLEAR` | Licence is recorded and permits commercial redistribution. |
| `UNVERIFIED` | Source or licence is missing; exclude from releases. |
| `PROJECT-ASSET` | Produced for Sgurr; source and release hash retained. |

## Chess Pieces

| Sgurr files | Source / author | Licence | Status |
| --- | --- | --- | --- |
| `web/frontend/assets/pieces/chessnut/{w,b}{K,Q,R,B,N,P}.svg` | [Chessnut](https://github.com/LexLuengas/chessnut-pieces), Alexis Luengas | Apache License 2.0 | `CLEAR` |

The pieces are stored unmodified. The original `LICENSE.txt`, `COPYRIGHT.txt`,
and a local provenance README are stored in the same directory and must remain
with distributions containing the SVGs.

## Intro Artwork

| Sgurr file | Provenance | Status |
| --- | --- | --- |
| `docs/assets/sgurr-cave-chamber-source.png` | Sgurr intro source artwork. | `PROJECT-ASSET` |
| `web/frontend/assets/intro/sgurr-cave-chamber.webp` | Browser-ready background derived from the source artwork. | `PROJECT-ASSET` |
| `web/frontend/assets/intro/sgurr-social-card.jpg` | Social preview derived from the intro artwork. | `PROJECT-ASSET` |

The PNG is retained as the high-resolution source; browsers receive the WebP
background and JPEG social card. No bundled font is used by the frontend; its
CSS uses system font stacks.

## Project-Created Audio

The following ordinary cues are synthesized at runtime in
`web/frontend/js/audio.js` with oscillators and generated noise. They do not load a
sampled media asset:

- button, move, capture, castle, promotion, check, illegal-move, game-start,
  and game-end cues.

## Cleared File-Backed Audio

All assets in this section are recorded as Creative Commons Zero (`CC0 1.0`).
Attribution is not required, but source details are retained.

| Sgurr file | Source | Original file | Status |
| --- | --- | --- | --- |
| `assets/sounds/result-human-explosion.ogg` | [Kenney Sci-Fi Sounds](https://kenney.nl/assets/sci-fi-sounds) | `explosionCrunch_003.ogg` | `CLEAR` |
| `assets/sounds/result-sgurr-energy.ogg` | [Kenney Sci-Fi Sounds](https://kenney.nl/assets/sci-fi-sounds) | `forceField_002.ogg` | `CLEAR` |
| `assets/sounds/clock-warning.ogg` | [Kenney Interface Sounds](https://kenney.nl/assets/interface-sounds) | `tick_004.ogg` | `CLEAR` |
| `assets/sounds/clock-flag.ogg` | [Kenney Interface Sounds](https://kenney.nl/assets/interface-sounds) | `error_008.ogg` | `CLEAR` |
| `assets/sounds/result-draw.ogg` | [Kenney Interface Sounds](https://kenney.nl/assets/interface-sounds) | `glass_004.ogg` | `CLEAR` |
| `assets/sounds/result-human-victory.ogg` | [OpenGameArt: Win Jingle](https://opengameart.org/content/win-jingle), Fupi | `winfretless_0.ogg` | `CLEAR` |
| `assets/sounds/result-sgurr-alien.ogg` | [OpenGameArt: 80 CC0 Creature SFX](https://opengameart.org/content/80-cc0-creature-sfx), rubberduck | `alien_03.ogg` | `CLEAR` |
| `assets/sounds/result-sgurr-burble.ogg` | Same source as above | `burble_01.ogg` | `CLEAR` |
| `assets/sounds/result-human-splat.ogg` | [OpenGameArt: 40 CC0 Water / Splash / Slime SFX](https://opengameart.org/content/40-cc0-water-splash-slime-sfx), rubberduck | `slime_09.ogg` | `CLEAR` |
| `assets/sounds/result-draw-neutral.ogg` | [OpenGameArt: UI Sound Effects](https://opengameart.org/content/ui-sound-effects-button-clicks-user-feedback-notifications), Robin Lamb | `ding_deep.ogg` | `CLEAR` |
| `assets/music/menu-theme.ogg` | [OpenGameArt: Lost in a Bad Place](https://opengameart.org/content/lost-in-a-bad-place-horror-ambience-loop), congusbongus | `lost.ogg` | `CLEAR` |
| `assets/music/game-pulse.mp3` | [OpenGameArt: Dark Sci-Fi Audio Pack](https://opengameart.org/content/dark-sci-fi-audio-pack), SRG774 | `pulse.mp3` | `CLEAR` |
| `assets/music/game-urgent.mp3` | Same source as above | `urgent.mp3` | `CLEAR` |

The production server uses a filename allowlist for these files. It does not
mount the repository-level asset directory as a public static tree.

## Release Checklist

- Include this manifest, `THIRD_PARTY_NOTICES.md`, and every adjacent asset
  licence/copyright file.
- Archive source downloads and the intro source artwork.
- Verify release files against `web/ASSET_CHECKSUMS.sha256`.
- Build the release from an explicit allowlist; do not publish the repository
  root.
- Verify that the browser requests Chessnut SVGs and only allowlisted audio.
- Re-run backend and browser tests after any asset replacement.
