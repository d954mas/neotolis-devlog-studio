# Phase 0 — inventory and recovery status

Status: **PASS**

- Five project roots classified: three migrated/ported, two read-only archive.
- Final manifest covers 11,008 entries and 33,367,407,382 bytes.
- Unmatched, ambiguous, parse-failure and unreadable counts are zero.
- The manifest records SHA-256, size, disposition, owner and source-media
  classification for every entry.
- Copy-based backup exists outside the workspace and verifies against manifest
  digest
  `ff92b7bde893945d769d717508e5ea44b16503dfcbcc90e876f3813fde34f44e`.
- A fresh restore rehearsal is separate from the migration clone and verifies
  all 11,008 paths byte-for-byte.

The earlier unreadable-WAV blocker is resolved. It remains in git history as
the reason cutover originally stopped; it is not a current exception or
waiver.

Current evidence is under `docs/studio_v3/phase6/`:

- `before_manifest.json`
- `disk_budget.json`
- `backup_report.json`
- `restore_report.json`
- `active_ports_run.json`
