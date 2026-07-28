# Phase 0 recovery contract

Cutover is not authorized by this tooling. A later cutover may proceed only
from a complete manifest whose unmatched, ambiguous, parse-failure, and
unreadable counts are all zero.

## Protocol

1. Stop Studio/render writers.
2. Generate the final before-manifest and disk budget.
3. Prove destination free space is at least the reported peak.
4. Create a copy-based backup outside the workspace.
5. Re-hash every backup entry against the before-manifest.
6. Restore that backup into a new empty clone.
7. Re-hash the clone and prove no missing, extra, size-mismatched, or
   hash-mismatched entries.
8. Rehearse migration on a separate clone; never on the recovery backup.
9. Only after rehearsal may the cutover transaction switch the production
   head.

Hardlinks may reduce disposable same-volume clone cost, but never qualify as
backup: a source mutation can mutate a hardlinked “backup”. Cross-volume clone
and every recovery backup use verified copies.

The tool refuses destinations that exist and are non-empty, destinations
inside the source, source bytes changed after the manifest, and incomplete
backup trees. It performs no cleanup after failure so partial evidence remains
inspectable and user data is never silently removed.

## Rehearsal evidence

The checked-in synthetic rehearsal exercises a product TOML plus a recording
through inventory, backup, verification, restore, and second verification.
Reports are in this directory:

- `rehearsal_before_manifest.json`
- `rehearsal_disk_budget.json`
- `rehearsal_backup_report.json`
- `rehearsal_restore_report.json`

The real-workspace blocker was later resolved under the owning Windows user.
The final manifest, disk budget, verified external backup and independent
restore evidence are in `docs/studio_v3/phase6/`. The disposable migration
clone is a different directory from both backup and restore rehearsal.
