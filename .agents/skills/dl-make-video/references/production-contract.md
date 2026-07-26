# Production contract

## Required manifests

`product.toml`: `id`, `title`, `game_root`, optional `[sources]`.

`production.toml`: `id`, `kind`, `date`, `orientation`, `edit_path`, `data_root`,
`delivery_root`. Production ids are `YYYY_MM_DD_devlog_NN` or
`YYYY_MM_DD_reel_NN`.

## Required scoped artifacts

- `data/plan/script_approval.json`
- `data/plan/shot_manifest.json`
- `data/plan/story_map.json` (required for `kind=devlog`)
- `data/assets/catalog.json`
- `data/review/preflight.json`
- `data/review/contact_sheet.jpg`
- `data/review/keyframes/`
- `data/review/feedback.json`
- `data/finalize/video.mp4`
- `data/publish/metadata.md`
- `data/publish/thumbnail.png` or `cover.png`
- `data/publish/video.mp4` (exact reviewed final; same-volume hardlink when possible)
- `data/review/reflections/<timestamp>.md`

## Shot fields

Each shot records `id`, `vo_range`, `purpose`, `src`, `source_role`, `t0`, `t1`,
`min_readable_duration`, `reuse`, `motion`, `intent`, `presentation`, and
`approved`. Use `presentation=inset|framed|contain|split` for an intentional
opposite-orientation source; otherwise it is treated as full-bleed.

For `kind=devlog`, each shot also records `arc_id`, `story_role`, and
`visual_mode`. A shot longer than 8 seconds records
`internal_changes_seconds`; no semantic gap may exceed 6 seconds. The story
map is `devlog.longform_story_map/v1` and binds every arc to before, payoff,
and failure/process evidence. Run `dl2 longform-check --strict` before final
VO.

## Delivery metadata headings

Use `# Title`, `# Description`, `# Tags`, `# Hashtags`, and optional `# Chapters`.
Tags may contain spaces. Every hashtag is one Unicode letters/numbers/underscore
token beginning with `#`; spaces and punctuation inside a hashtag are invalid.

## Telemetry event fields

Record `product_id`, `production_id`, `stage`, `agent_role`, `wall_ms`,
`human_wait_ms`, `input_tokens`, `cached_input_tokens`, `output_tokens`, and
`artifact_paths`. Report direct production, tooling fixes, review, packaging, and
reflection separately.
