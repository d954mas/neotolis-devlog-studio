# Studio v3 offline migration harness

This package is deliberately outside `common/dlstudio`. Runtime code must not
import it. It has no `apply` or delete command: Phase 0 produces evidence and
rehearses recovery only.

```powershell
py -3.12 -m tools.studio_v3_migrate roots `
  --workspace C:\projects\devlogs `
  --report docs\studio_v3\phase0\project_roots.json

py -3.12 -m tools.studio_v3_migrate dry-run `
  --workspace C:\projects\devlogs `
  --manifest C:\safe\before_manifest.json `
  --budget C:\safe\disk_budget.json `
  --backup-destination D:\studio-v3-backup `
  --clone-destination C:\safe\migration-clone

py -3.12 -m tools.studio_v3_migrate backup `
  --workspace C:\projects\devlogs `
  --manifest C:\safe\before_manifest.json `
  --destination D:\studio-v3-backup `
  --report C:\safe\backup_report.json

py -3.12 -m tools.studio_v3_migrate restore-rehearsal `
  --manifest C:\safe\before_manifest.json `
  --backup D:\studio-v3-backup `
  --destination C:\safe\restored-clone `
  --report C:\safe\restore_report.json
```

Safety invariants:

- unknown project roots and unknown artifacts are preserved read-only;
- equal-priority matches, malformed known records, unreadable files, missing
  files, and source mutation after inventory all block;
- source media cannot map to `DROP`/`DELETE`;
- backup is a byte copy, never a hardlink;
- backup and rehearsal destinations must be empty and outside their source;
- every copied/restored path, size, and SHA-256 must match the manifest;
- existing destinations are never overwritten;
- `dry-run` has no mutation path into a project.

