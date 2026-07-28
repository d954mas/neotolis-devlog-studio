# Phase 2 — asset identity and migration status

Status: **PASS**

`dlstudio.assets.AssetRevision` is the only owner of asset bytes, probed media
facts, provenance, approval and license. Revisions and indexes are immutable;
one CAS head publishes a completed repository update.

The one-shot migrator was exercised on a separate restored clone, applied to
the workspace, rerun idempotently, then physically removed. Runtime code never
imports migration tooling.

Three historical productions were ported without promoting trust:

| Production | Assets | Approval facts preserved |
|---|---:|---|
| Vertical reel | 8 | 1 approved, 5 validated, 2 pending |
| Long-form | 37 | 1 approved, 18 validated, 18 pending |
| Capture/VO | 47 | 23 validated, 24 pending |

All 92 exact sources and reachable evidence objects are present in immutable
storage. The second apply ingested zero assets and kept the same repository
heads and timeline hashes. Missing historical approvals and redistribution
proof remain explicit release blockers; no legacy note was converted into
proof.

Execution-bound evidence is
`docs/studio_v3/phase6/active_ports_run.json`.
