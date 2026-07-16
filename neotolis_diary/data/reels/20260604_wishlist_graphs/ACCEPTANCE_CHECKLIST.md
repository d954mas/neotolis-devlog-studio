# Acceptance Checklist - Neotolis Diary Wishlist Graphs Reel

This checklist maps the user requirements to current evidence. It is intentionally stricter than `qa_report.md`: automated QA proves technical gates, while final "10/10" reel quality still requires human playback review.

## Requirements And Evidence

| Requirement | Status | Evidence |
|---|---|---|
| New reel about promotion diary changes | Pass | Current package contains the 14.8s wishlist graphs reel in `delivery/light_no_vo.mp4` and `delivery/dark_no_vo.mp4`. |
| Use real production visuals and data | Pass | Manifest records prod capture from `https://neotolis-diary.dev/games/019df32e-4d8f-75c2-8517-e028c6f3819d`; visuals show real `256 wishlists`, wishlist chart, daily wishlist growth, and events. |
| Light and dark theme versions | Pass | `delivery/light_no_vo.mp4`, `delivery/dark_no_vo.mp4`, plus temp-music copies. |
| Visual-first, no final voiceover | Pass | Visual-only files have no audio; temp-music copies are explicitly review-only and contain no voiceover. |
| Avoid huge `256` text over the UI | Pass | `256 wishlists` remains real UI text; attention uses brackets/underline/focus marks only. |
| Use arrows/outline/focus instead of duplicate stat overlays | Pass | Opening uses bracket/underline/focus marks on the real row and chart. Rejected full event brackets are documented in `review_manifest.md`. |
| Add motion, not static screenshots | Pass | Real tab-click opening is preserved, then the reel uses a continuous camera pass, bracket/focus accents, softened camera-only zooms, and a deliberate final CTA hold. Non-interactive green pulses and later fake tap ripples were removed. Motion gate passes in `qa_report.md`. |
| Smooth, non-janky motion | Pass | QA motion gate passes: light peak 16.72 ratio 4.72; dark peak 22.16 ratio 4.79. Raw browser captures and heavier macro punches were rejected for jank risk. |
| Fill vertical screen | Pass | QA confirms 1080x1920 vertical format for root and delivery files. |
| Modern, clean visual style, not school presentation | Partial, requires human review | Dirty chart-hook, fake line tracer, event brackets, full overlays, subtle text-only CTA, and weak final frame variants were rejected. Current ending uses a stronger lower-third CTA with a clean backing panel. Final subjective quality still needs playback review. |
| Tell the story clearly | Pass for prep | `voiceover_timing_ru.md` provides primary, punchier, and shorter Russian VO drafts synced to the 14.8s cut. |
| Ready for posting | Pass | `posting_copy_ru.md`, cover frames, delivery copies, and QA report are present. |

## Current Delivery Files

- `delivery/light_no_vo.mp4`
- `delivery/dark_no_vo.mp4`
- `delivery/light_temp_music.mp4`
- `delivery/dark_temp_music.mp4`
- `delivery/cover_light.jpg`
- `delivery/cover_dark.jpg`
- `delivery/review_light.jpg`
- `delivery/review_dark.jpg`
- `delivery/safezone_review.jpg`
- `delivery/cta_light_review.jpg`
- `delivery/cta_dark_review.jpg`
- `delivery/voiceover_timing_ru.md`
- `delivery/posting_copy_ru.md`
- `delivery/qa_report.md`

## Remaining Human Review

The only unproven requirement is the subjective "10/10" quality target. Automated checks cannot prove that. Review the temp-music versions in motion:

- `delivery/light_temp_music.mp4`
- `delivery/dark_temp_music.mp4`

If either still feels weak, the next iteration should be based on a concrete playback note: exact timestamp, what feels wrong, and whether it is a pacing, composition, text, color, or story issue.
