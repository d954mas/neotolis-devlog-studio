# Workspace state — 2026-07-26

This is a preservation and handoff snapshot, not a backup.

## Final publish archive

The local Yandex Disk sync tree now contains seven SHA-verified final packages:

```text
C:\Users\ROG\YandexDisk\Devlogs\projects\
  not_a_trolley_problem\
    devlogs\<production>\publish\
    reels\<production>\publish\
```

The archive merges each delivered production's complete `data/publish/` with
its immutable delivery bundle (video, metadata, cover/thumbnail and manifest).
It is append-only and managed by `tools/publish_archive.py`: identical files
are skipped; different existing bytes block instead of being overwritten.
The initial archive copied 59 files / 595,469,400 bytes.

This protects final upload packages only. It is deliberately not a backup of
raw recordings, gameplay sources, caches, reviews, or working renders.

## Git

- Branch: `agent/automatic-speech-edit`
- HEAD: `88e2d46 fix(studio): close merge-readiness blockers`
- `not_a_trolley_problem/`: 4,287 files, 19,596,078,870 bytes
  (approximately 18.25 GiB).
- Only 8 files inside that product are currently tracked by git, all from
  `reels/2026_07_19_reel_01`.
- Large media under `**/data/**` is intentionally ignored by `.gitignore`.
- Delivery MP4s outside `data/` are untracked, not backed up by git.

No existing product file was deleted or moved during the Zerah benchmark or
long-form integration.

## Product tree

```text
not_a_trolley_problem/                 4,287 files / 18.25 GiB
  product.toml
  shared/                                 20 files / 81.3 MiB
  devlogs/                             2,347 files / 16.03 GiB
    2026_07_17_devlog_01                 448 files / 896.1 MiB
    2026_07_22_devlog_01               1,899 files / 15.16 GiB
  reels/                               1,850 files / 1.55 GiB
    2026_07_17_reel_01
    2026_07_18_reel_01..03
    2026_07_19_reel_01..04
    2026_07_22_reel_01..03
  delivery/                               35 files / 584.9 MiB
    devlogs/
      2026_07_17_devlog_01
      2026_07_22_devlog_01
    reels/
      2026_07_17_reel_01
      2026_07_18_reel_01
      2026_07_18_reel_01_pre_caption_fix
      2026_07_18_reel_02
      2026_07_18_reel_02_pre_caption_fix
      2026_07_19_reel_02
      2026_07_19_reel_03
  social/                                 33 files / 20.2 MiB
```

Largest file classes:

| Extension | Files | Approx size |
|---|---:|---:|
| `.mp4` | 701 | 16.16 GiB |
| `.wav` | 495 | 1.30 GiB |
| `.png` | 1,125 | 572.7 MiB |
| `.jpg` | 1,150 | 106.2 MiB |
| `.json` | 340 | 7.0 MiB |
| `.md` | 142 | 700 KiB |
| `.py` | 62 | 232 KiB |

## Existing long-form productions

### `2026_07_17_devlog_01`

- Script: `SCRIPT.md`.
- Production tree exists with edit, data, review and assets.
- No `data/plan/shot_manifest.json` was found at snapshot time.
- Upload/delivery bundle exists.
- Public upload: <https://www.youtube.com/watch?v=aBvBszNCmIE>.

### `2026_07_22_devlog_01`

- Planning sources:
  `data/plan/brief.md`, `draft_script.md`, `WORKING_VO.md`,
  `MASTER_PLAN.md`, `SHOT_LEDGER_DAYS_1_6.md`,
  `ASSEMBLY_SCRIPT_DAYS_1_6.md`.
- `data/plan/shot_manifest.json` exists.
- Final render and delivery bundle exist.
- Review evidence is extensive, including exact-hash beat regressions.
- Public upload: <https://www.youtube.com/watch?v=MrN40vBm64w>.

## Zerah benchmark additions

Tracked control files:

- `docs/ZERAH_DEVLOG_BENCHMARK.md`
- `docs/LONGFORM_DEVLOG_SPEC.md`
- `docs/LONG_DEVLOG_PLAYBOOK.md`
- `docs/CHECKLIST_LONG_DEVLOG.md`
- `common/quality/VQ-LONGFORM.md`
- `tools/devlog_reference_lab/`

Ignored research media and evidence:

```text
data/research/zerah_games/source/      3 exact 1080p60 videos + sidecars
data/research/zerah_games/analysis/    transcripts, metrics, contact sheets
data/research/our_long_devlogs/        matching analysis of both deliveries
```

## Executable long-form integration

New `kind=devlog` productions scaffold:

```text
data/plan/story_map.json
data/plan/shot_manifest.json
```

Commands:

```powershell
dl2 longform-check <product:production>
dl2 longform-check <product:production> --strict
```

The same gate is called from `dl2 preflight` and `dl2 autopilot-run`.
Review packs include story-map and montage-role facts.

## Preservation risk

Git and the Yandex publish archive cannot currently restore most of the
working product, especially the 16+ GiB of source/intermediate MP4 assets and
1.3 GiB of WAV assets. Creating a manifest or archiving publish files verifies
deliveries but does not preserve production media bytes.

Before any cleanup, dedupe, migration, or disk reclamation:

1. choose an external backup destination with at least 20 GiB free;
2. copy the full `not_a_trolley_problem/` tree;
3. verify file count, total bytes, and hashes of delivery/source masters;
4. commit the non-media production controls separately.
