# Studio v3 Phase 2 status

The v3 asset trust owner is `dlstudio.assets.AssetRevision`. It binds exact
blob bytes, probed media facts, provenance, approval evidence, license data,
and the previous logical revision into one canonical hash. Persistence writes
immutable blob/revision/index objects before one CAS head transition.

The clone rehearsal covers dry-run, apply, idempotent re-run, stale/interrupted
apply, projection rebuild, explicit reachability GC, same-volume clone
hardlink preflight, and cross-volume verified-copy policy. Mutable exports use
an isolated verified copy and can never alias the immutable object store.
Source fixtures remain byte- and mtime-identical.

The offline translator inspected all currently selected representative
productions:

- vertical: 18 legacy records, all explicitly blocked;
- long-form/capture: 141 legacy records, all explicitly blocked;
- legacy voice production: no legacy registry/catalog records.

The records are blocked rather than upgraded because their v2 schemas do not
carry a complete v3 license/provenance chain. In particular, historical
frame-stepped capture is not reclassified as ordinary gameplay, and zero
head/tail handles are not accepted. Exact per-record reasons and disk bytes are
in the adjacent JSON reports.

No runtime compatibility reader exists. The translator is offline under
`tools/studio_v3_migrate`; explicit v3 authoring ports must select trusted
source revisions or retain these records read-only.

The real destructive migration remains gated by the Phase 0 full-manifest and
verified-backup blocker. No user media was changed or deleted.
