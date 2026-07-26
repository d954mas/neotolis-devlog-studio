# Phase 0 disposition matrix

Canonical machine rules:
`tools/studio_v3_migrate/disposition_rules.json`.

## Project roots

| Root class | Disposition | Basis |
|---|---|---|
| Product root (`product.toml`) | `MIGRATE_ACTIVE` | Current product/production layout |
| v2 edit root (`edits/`) | `MIGRATE_ACTIVE` | Explicit Python edit port required |
| `neotolis_diary`, `not_a_trolley_problem`, `trolley_devlog` | `MIGRATE_ACTIVE` | Current active work |
| `trolley`, `trolley3d` | `ARCHIVE_READ_ONLY` | Source/reference roots, not Studio runtime roots |
| Any unknown top-level project root | `ARCHIVE_READ_ONLY` | Fail-safe preservation; never inferred deletable |

`DELETE_CONFIRMED` has no project rule. It can be introduced only after a
separate proof that a root is generated and unnecessary.

## Artifact classes

| Old path/schema | Action | Target owner |
|---|---|---|
| `product.toml`, `production.toml`, `devlog.toml`, preferences | migrate | constraints/application |
| `edits/**/*.py` | explicit port | authoring |
| asset registry/catalog/capture request/result | migrate | assets/capture |
| story map, shot/script/production manifests | migrate | constraints/workflow |
| recordings, audio, word timings, speech-edit evidence | migrate | speech/assets |
| source footage/images/music/SFX/fonts/infographics | migrate | assets |
| review packs and mutable feedback | archive; recompute trusted verdict | review/archive |
| publish/license/delivery files | archive as bytes; rebuild v3 release trust | release/archive |
| finalize/cache | recompute | rendering/cache |
| HyperFrames sources/manifests | migrate | adapters/hyperframes |
| local scripts/docs | archive as migration context | archive/local_context |
| unknown JSON/TOML/Python | parse, then archive untranslated | archive |
| any other unknown artifact | archive unchanged | archive/unknown_preserved |

Rules use priority only to resolve intentional semantic nesting (for example a
recording is more specific than generic media). Two top-priority matches are
an ambiguity and block. Fallback is an explicit single preservation rule, so
unknown does not become deletion.

All known JSON/TOML/Python records are parsed during inventory. UTF-8 BOM is
accepted as legacy encoding evidence; malformed content still blocks.

