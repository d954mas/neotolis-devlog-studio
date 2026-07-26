# Phase 0 inventory/recovery status

## Completed

- Machine-readable project and artifact disposition rules.
- Safe default for unknown roots/artifacts (`ARCHIVE_READ_ONLY` / `ARCHIVE`).
- Root-only classification report: 5 roots, 3 active, 2 read-only archive,
  zero unmatched and zero ambiguous.
- Full before-manifest generator with SHA-256, size, parser validation,
  exact disposition, target owner, and source-media marker.
- Explicit dry-run command with no apply/delete path.
- Disk/copy/hardlink budget report.
- Copy-only verified backup and restore-to-empty-clone rehearsal.
- Tests for unknown preservation, ambiguity, malformed records, BOM legacy
  records, media preservation, source mutation, non-empty destination refusal,
  exact restore, and hardlink budget semantics.

Synthetic rehearsal result: 2 entries, 109 bytes, zero unmatched/ambiguous/
parse failures; backup and restored clone both have zero missing, extra, and
mismatched entries.

## Fail-closed real-workspace blocker

Project-root classification is complete. The full real-workspace manifest,
real disk budget, and full recovery copy are not claimed complete because the
Codex Python process cannot read 14 current `trolley_devlog` WAV files.
`inventory_blockers.json` names every path.

The sandbox can stat those files but content reads and ACL inspection are
denied even for an escalated command. Existing migrated copies and a prior
hash manifest are evidence that the bytes existed, but they are not treated as
proof that the unreadable source has not changed. The safe next action is to
run the documented identical `dry-run` under the owning Windows user.
Omitting those WAVs, trusting size without SHA-256, or inventing hashes is
prohibited.

## Verification

```text
py -3.12 -m pytest tools\studio_v3_migrate\tests -q
12 passed in 0.14s

py -3.12 -m compileall -q tools\studio_v3_migrate
PASS

git diff --check -- tools/studio_v3_migrate docs/studio_v3/phase0
PASS
```
