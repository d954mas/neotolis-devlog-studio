# Neotolis Diary Wishlist Graphs Reel - 2026-06-04

Source page:
https://neotolis-diary.dev/games/019df32e-4d8f-75c2-8517-e028c6f3819d

Fresh prod capture:
- `data/screens/prod_20260604_wishlist_graphs/theme_light_mobile_fullpage.png`
- `data/screens/prod_20260604_wishlist_graphs/theme_dark_mobile_fullpage.png`
- captured as mobile full-page screenshots via `tmp/capture_neotolis_current_tab_themes.mjs`
- real tab-click states captured via `tmp/capture_neotolis_chart_tabs_cdp.mjs`

Current package index:
- `CURRENT_PACKAGE.md` is the short handoff index for the recommended files, temp-music review copies, QA report, VO timing, and rejected-candidate warning.
- `ACCEPTANCE_CHECKLIST.md` maps the user requirements to current evidence and calls out the remaining subjective playback review.
- `delivery/` contains short-name copies of the current light/dark no-VO and temp-music MP4s plus cover frames, review sheets, `README.md`, `ACCEPTANCE_CHECKLIST.md`, `voiceover_timing_ru.md`, `posting_copy_ru.md`, and `qa_report.md`.

Current prod data shown in capture:
- `256 wishlists`
- `as of yesterday`
- `updated 13h ago`
- wishlist chart, daily wishlist growth, events

Rendered short/no-VO variants:
- `neotolis_diary_20260604_wishlist_graphs_light_no_vo_short.mp4`
- `neotolis_diary_20260604_wishlist_graphs_dark_no_vo_short.mp4`
- recommended after the latest feedback:
  - `neotolis_diary_20260604_wishlist_graphs_light_live_macro_bumper_snappy_focus_no_vo_short.mp4`
  - `neotolis_diary_20260604_wishlist_graphs_dark_live_macro_bumper_snappy_focus_no_vo_short.mp4`
- optional temp-music review copies, still without voiceover:
  - `neotolis_diary_20260604_wishlist_graphs_light_live_macro_bumper_snappy_focus_temp_music.mp4`
  - `neotolis_diary_20260604_wishlist_graphs_dark_live_macro_bumper_snappy_focus_temp_music.mp4`

Live capture experiment:
- raw browser screencasts captured under `data/reels/live_capture/20260604_wishlist_graphs/`
- `prod_light_live_actions.mp4`: 1080x1920, 30fps, 15.0s, motion peak_delta 50.54
- `prod_dark_live_actions.mp4`: 1080x1920, 30fps, 15.7s, motion peak_delta 57.83
- not used directly in the final cut because the raw browser capture is visibly riskier for jank than the controlled camera pass
- A/B live-opening candidates were created by trimming the stable first live section and joining it to the current smooth tail:
  - `neotolis_diary_20260604_wishlist_graphs_light_live_opening_ab.mp4`: PASS, 1080x1920, 30fps, 14.80s, peak_delta 41.46
  - `neotolis_diary_20260604_wishlist_graphs_dark_live_opening_ab.mp4`: PASS, 1080x1920, 30fps, 14.80s, peak_delta 34.32
- A/B candidates are kept as review alternatives, not replacing the main `*_no_vo_short.mp4`, because they feel more live but focus the wishlist count less clearly than the controlled annotated opening
- Hybrid candidates use the live browser opening, then the smooth controlled tail. They were useful review files because they add real page actions without the raw-capture jank.
- Fast hybrid candidates shorten the live opening from 5.6s to 3.35s, so the reel reaches the full wishlist chart around second 4 instead of lingering on the header.
- Fast focus candidates additionally reframe only the opening downward/closer so the first seconds spend less space on the hero banner and more on the wishlist row, tab controls, and chart.
- Snappy focus candidates shortened the live opening to 2.25s and became the base for the later clean-bumper version.
- Chart-hook overlay candidates were tested as a data-first cold open:
  - `neotolis_diary_20260604_wishlist_graphs_light_live_chart_hook_snappy_focus_no_vo_short.mp4`
  - `neotolis_diary_20260604_wishlist_graphs_dark_live_chart_hook_snappy_focus_no_vo_short.mp4`
  - motion review passed, but the visual review rejected them because crossfading a chart packshot into a different UI state created ghosted/dirty overlapping text and duplicate chart lines
- Clean-bumper candidates replaced the opening with a same-frame chart push, then cut into the live/smooth sequence without a dirty crossfade:
  - `neotolis_diary_20260604_wishlist_graphs_light_live_clean_bumper_snappy_focus_no_vo_short.mp4`
  - `neotolis_diary_20260604_wishlist_graphs_dark_live_clean_bumper_snappy_focus_no_vo_short.mp4`
  - visually accepted as a calmer backup because `256 wishlists` stays real UI text and attention is directed with brackets/underline, not a large duplicate overlay
- Macro-bumper candidates keep the clean-bumper same-frame cut but start slightly closer to the graph/wishlist area:
  - `neotolis_diary_20260604_wishlist_graphs_light_live_macro_bumper_snappy_focus_no_vo_short.mp4`
  - `neotolis_diary_20260604_wishlist_graphs_dark_live_macro_bumper_snappy_focus_no_vo_short.mp4`
  - visually accepted as the current recommendation because the opening has more reel energy while preserving the real UI, full graph, and non-duplicated `256 wishlists`
- Latest macro-bumper pass adds subtle editorial punch-zooms around graph/growth/events/CTA transitions. These are camera-only pulses on real footage, not fake chart/data overlays.
- Latest Events pass tested extra event-card brackets/ticks and rejected them after visual review: they added presentation-like clutter over an already bright real thumbnail. The final version keeps Events clean and uses only camera-only punch motion.
- Latest finishing pass adds a restrained theme-aware color grade: slightly more contrast/saturation/sharpness on light, gentler lift on dark. No grain or decorative overlays were added.
- Latest opening pass adds a small early `NEOTOLIS DIARY` brand lockup in the empty gap above `Wishlists`; it fades by ~1.85s and does not cover the `256 wishlists` row, chart, or controls.
- Latest CTA pass rejected the subtle text-only ending after playback review showed it was not noticeable enough for a reel.
- Latest CTA cleanup keeps the URL out of the final frame after review showed it visually colliding with the real `+ Add event` control. The URL remains in posting copy instead of sitting over product UI.
- Latest CTA polish now uses a stronger theme-aware lower-third: larger `NEOTOLIS DIARY`, a clean high-contrast backing panel, an accent progress rail, and the short line `графики вишлистов уже на сайте`.
- Latest CTA safe-zone pass lifts the lower-third above the caption/control risk zone and narrows its right edge so Reels/TikTok side controls do not visually compete with the final lockup.
- Latest smoothness pass removes green growth pulse/spark markers and later non-interactive tap ripples after review showed they looked like buttons but did not change the UI. Orange tap rings remain only in the live opening where tab captures actually change state.
- Latest smoothness pass also softens the macro-bumper: smaller opening zoom and wider/weaker camera-only pulses to reduce the jerky feeling.
- Latest safe-zone pass adds `delivery/safezone_review.jpg` plus clean CTA stills to verify the opening and final frame against conservative vertical-platform overlays.
- Latest focus pass keeps the short-reel final camera around `Daily wishlist growth` + Events instead of letting the old event thumbnail dominate the ending. The temporary deeper endings at y=3500 and y=3300 were rejected after still review.
- Latest motion-energy pass widens and slightly strengthens the camera-only editorial pulses. It keeps the smooth-scroll fix but adds more reel cadence around graph/growth/events moments without adding text or fake data.
- Latest mid-roll action pass adds a short ring/tap cue on the real `+ Add event` button around the graph-to-events transition, so the middle reads as product action instead of a static screenshot.
- Latest transition cleanup removes the post-opening crossfade that briefly ghosted two UI states over each other. A tested push-wipe alternative was rejected because it produced a split-screen duplicate-controls frame; the current cut uses a clean montage cut into the scroll pass.
- Latest opening-motion cleanup fixes the macro bumper so it uses real captured opening frames under the camera push instead of animating one frozen frame. The small opening brand lockup was moved below `Open in Steam`, made softer, and faded earlier so it acts as a brand signal without competing with product UI text.
- Latest growth-rhythm pass adds a focal macro punch on the real `Daily wishlist growth` bars around the middle of the reel, reducing repeated same-looking scroll frames without adding text or fake chart data.
- Latest audio pass adds optional temp-music copies for review only. The recommended `*_no_vo_short.mp4` files remain visual-only; `*_temp_music.mp4` adds an AAC rhythm bed with no voiceover.
- Latest QA pass writes `qa_report.md` and checks all four current macro-bumper artifacts for 1080x1920/30fps/14.8s format, expected audio state, motion gate, sampled frame health, `CURRENT_PACKAGE.md`, and supporting review files.
- Latest delivery pass creates short-name copies under `delivery/` and includes them in the QA gate.
- Latest cover pass extracts `cover_light.jpg` and `cover_dark.jpg` from the opening hook around 0.70s; both show the real wishlist row, chart, and brand lockup without duplicating the `256` as a large overlay.
- Latest acceptance pass adds `ACCEPTANCE_CHECKLIST.md`, mapping requirements to artifacts and documenting that the only unproven item is subjective "10/10" playback quality.
- Latest delivery review pass adds `delivery/review_light.jpg` and `delivery/review_dark.jpg` as short-name contact sheets for quick visual scanning.

Recording guide:
- `voiceover_timing_ru.md` contains the current 14.8s Russian VO timing draft for the macro-bumper cut
- it now includes a primary take, punchier take, optional shorter take, and recording notes for using the `*_temp_music.mp4` files as a rhythm reference
- file is UTF-8; PowerShell may display Cyrillic as mojibake if read without `-Encoding UTF8`

Posting guide:
- `posting_copy_ru.md` contains a Russian caption, short caption, first-line hooks, pinned comment, and hashtags for publishing the reel.

Review:
- light: PASS, 1080x1920, 30fps, 14.8s, motion peak/median 4.06, peak_delta 41.46
- dark: PASS, 1080x1920, 30fps, 14.8s, motion peak/median 2.74, peak_delta 34.30
- hybrid light: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 4.26, peak_delta 41.53
- hybrid dark: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 3.07, peak_delta 34.32
- fast hybrid light: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 3.93, peak_delta 41.54
- fast hybrid dark: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 2.77, peak_delta 34.32
- fast focus light: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 4.49, peak_delta 40.57
- fast focus dark: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 2.97, peak_delta 33.70
- snappy focus light: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 4.50, peak_delta 40.56
- snappy focus dark: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 2.92, peak_delta 33.68
- clean bumper light: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 4.40, peak_delta 40.64
- clean bumper dark: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 2.94, peak_delta 33.61
- macro bumper light: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 3.91, peak_delta 18.60
- macro bumper dark: PASS, 1080x1920, 30fps, 14.80s, motion peak/median 3.63, peak_delta 22.23
- temp-music light: PASS, 1080x1920, 30fps, 14.80s, AAC audio 14.80s, motion peak/median 3.91, peak_delta 18.60, mean_volume -19.1 dB, max_volume -5.4 dB
- temp-music dark: PASS, 1080x1920, 30fps, 14.80s, AAC audio 14.80s, motion peak/median 3.63, peak_delta 22.23, mean_volume -19.1 dB, max_volume -5.4 dB
- package QA: PASS for root and delivery copies of light/dark no-VO and light/dark temp-music artifacts; see `qa_report.md`
- rejected chart-hook light: PASS by motion only, 1080x1920, 30fps, 14.80s, motion peak/median 4.40, peak_delta 40.63; rejected visually due dirty crossfade
- rejected chart-hook dark: PASS by motion only, 1080x1920, 30fps, 14.80s, motion peak/median 2.93, peak_delta 33.61; rejected visually due dirty crossfade

Latest visual iteration:
- macro bumper is now the recommended cut: first 2.25s start directly on the real wishlist/chart area with a stronger-but-safe push, then cut from the same frame into the live/smooth sequence
- this avoids the rejected chart-hook ghosting and avoids a giant `256` overlay; `256 wishlists` remains the product UI, with bracket/underline focus marks only
- first macro-bumper attempt was rejected because the crop cut the left UI and chart bracket; the accepted version uses a softer 1.075x start crop so the graph stays complete
- middle scroll now has five small editorial punch-zooms at ~4.05s, 6.35s, 9.55s, 10.78s, and 12.10s to break the flat-scroll feeling without adding extra text
- the daily-growth section has an additional focal macro punch around ~7.38s so the green bar data briefly fills more of the phone frame
- Events section now has an additional subtle camera-only punch around ~10.78s; no event-card overlays remain after rejecting a cluttered bracket attempt
- final post grade makes the light version less pale and the dark version more contrasty while keeping product UI text readable
- first-second clarity improved with a small, softened `NEOTOLIS DIARY` lockup placed below the status card and clear of the real `Open in Steam` text; it fades early before the chart becomes the dominant visual
- real browser tab-click opening: captured `All time -> Month -> Week -> All time` states from prod, then transitions into the smooth page pass
- macro bumper now preserves those real opening frames under the camera push; the frozen-frame macro opening was rejected because it weakened the live-action feel
- earlier recommended cut used a faster `3.35s` live opening; previous `5.6s` opening was technically valid but held the page header too long for a reel
- snappy cut uses a `2.25s` live opening; this moves the reel into the full chart sooner and makes the hook less header-heavy
- snappy/focus base also uses `--opening-focus`, which applies a small opening-only crop/push after annotation so the real product callouts stay attached to the UI
- hybrid overlay now accepts `--opening-seconds`; without this, the 2.25s snappy cut could accidentally keep opening annotations alive over tail frames
- opening focus was retuned to avoid a chopped hero-banner strip, preserve the left edge of `Wishlists`, and keep the chart brackets inside the phone frame
- opening crop moved from `TAB_CROP_Y=430` to `320` so the first seconds include `Not a Trolley Problem!` page context plus the wishlist row and chart
- removed the opening text chip; the first screen now uses only focus marks on the real UI, not text over the page
- removed the spotlight layer because it looked like presentation cards on the light theme
- opening crop is shifted down to prioritize the `256 wishlists` row, chart controls, and wishlist plot instead of the game hero artwork
- opening tab-click segment now has a subtle deterministic camera push so it reads as filmed product action instead of a static screenshot
- smooth camera pass over the real prod full-page capture after the opening
- no oversized `256` overlay; the number remains real product UI, not a duplicated hero stat
- early `256 wishlists` attention is now a short side arrow plus a small bracket/underline on the real row, then it fades before the graph becomes the main focus
- late opening frames do not keep highlighting `256`; the chart and tabs become the dominant visual instead
- removed the long diagonal `256 wishlists` arrow from both the opening overlay and the tab-action tail; it looked too much like a presentation annotation
- opening top cleanup is theme-specific: stronger on light to hide the clipped hero strip, lighter on dark to preserve the product title
- tap/ripple cues on the actual chart tabs; no fake filter switch or invented data animation
- clean corner-brackets on the real wishlist chart plot area instead of a heavy full rectangle
- removed an attempted line-tracer because it looked like a fake drawn graph rather than real product data
- no green growth pulse markers; growth and events use calmer bracket/focus treatment instead of fake taps
- short spark accents were added on real growth peaks; a stronger diagonal scan/glint pass was tested and rejected because it read like a fake line drawn over the chart
- Events section no longer adds any extra vertical rail overlay; the remaining rail is the real product UI
- late Events camera now eases slightly right to center the event cards and reduce dominance of the real left-side rail
- final CTA uses a strong lower-third backing panel after the prior text-only CTA was too easy to miss
- final CTA stays above the bottom control risk zone and leaves a right-side margin for platform controls while being large enough to read in a phone feed
- final CTA no longer includes the URL; this avoids dirty overlap with the real `Events` / `+ Add event` text behind it
- final CTA now uses theme-aware text, a larger brand lockup, a short wishlist-graphs line, and a brighter accent rail
- final CTA no longer blends back to a chart packshot in short reels; it stays on the continuous real scroll to avoid a restart/loop feeling
- the short-reel scroll now stops around `Daily wishlist growth` + Events instead of diving into lower blank feed cards or old thumbnails
- middle Events transition now has one ring/tap cue on the real `+ Add event` button; this was added after review showed the daily-growth section could read too much like a static screenshot
- the opening-to-scroll transition now avoids transparent frame blending; rejected push-wipe debug frames were replaced by a clean cut to avoid ghosted UI and split-screen artifacts
- final camera eases into a deliberate hold under the CTA instead of continuing to scroll through the last second
- tighter 12.6/13.4/14.2 second variants were tested and rejected because the light-theme motion review exceeded the `peak_delta < 42` gate around the high-contrast event thumbnail
- a first attempt at Events horizontal reframing failed because the easing value was not clamped and produced black fields; this was rejected and fixed with clamped `camera_x`
