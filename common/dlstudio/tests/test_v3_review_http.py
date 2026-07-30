from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from itertools import count
from pathlib import Path
from threading import Barrier, Lock
from time import sleep

import pytest
from fastapi.testclient import TestClient

from dlstudio.application.api import start_workflow
from dlstudio.foundation.api import BlobRef, canonical_bytes
from dlstudio.persistence.api import open_local_repositories
from dlstudio.review.api import ReviewRound, ReviewVerdict
from dlstudio.timeline.api import CheckReport, TimelineIR, VisualInstruction
from dlstudio.workflow.api import NamedRef, WorkflowStore


def _save_stage(
    workflows: WorkflowStore,
    stage: str,
    outputs: tuple[NamedRef, ...],
    *,
    inputs: tuple[NamedRef, ...] = (),
    contract: str | None = None,
) -> None:
    current = workflows.read_current()
    assert current is not None
    running = current.start(  # type: ignore[arg-type]
        stage,
        inputs,
        contract=contract or f"fixture.{stage}.v1",
    )
    workflows.save(
        running,
        expected_workflow_revision=current.revision,
        expected_head_revision=workflows.head_revision(),
    )
    completed = running.succeed(running.attempts[-1].operation_id, outputs)
    workflows.save(
        completed,
        expected_workflow_revision=running.revision,
        expected_head_revision=workflows.head_revision(),
    )


def _review_ready_production(root: Path) -> tuple[Path, BlobRef]:
    root.mkdir()
    (root / "edit.py").write_text("EDIT = None\n", encoding="utf-8")
    manifest = root / "production.toml"
    manifest.write_text(
        "\n".join(
            (
                'schema = "dlstudio.production"',
                "version = 3",
                'id = "fixture.reel"',
                'authoring = "edit.py"',
                'delivery_root = "delivery"',
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, _, workflows = open_local_repositories(
        root,
        "fixture.reel",
    )
    store = repository.objects
    timeline = TimelineIR(
        production_id="fixture.reel",
        width=64,
        height=96,
        fps_num=30,
        fps_den=1,
        duration_ns=200_000_000,
        background="black",
        visuals=(
            VisualInstruction(
                "solid",
                0,
                200_000_000,
                0,
                0,
                0,
                64,
                96,
                color="black",
            ),
        ),
    )
    timeline_ref = store.put_bytes(timeline.canonical_bytes())
    policy_ref = store.put_bytes(b"policy")
    report = CheckReport(timeline_ref, policy_ref, ())
    report_ref = store.put_bytes(report.canonical_bytes())
    constraints_ref = store.put_bytes(b"constraints")
    artifact_ref = store.put_bytes(bytes(range(128)))

    start_workflow(workflows, run_id="run.main", kind="reel")
    _save_stage(
        workflows,
        "prepare",
        (
            NamedRef("timeline", timeline_ref),
            NamedRef("check_policy", policy_ref),
            NamedRef("check_report", report_ref),
            NamedRef("constraints", constraints_ref),
        ),
    )
    _save_stage(
        workflows,
        "draft",
        (NamedRef("artifact", store.put_bytes(b"draft")),),
    )
    _save_stage(
        workflows,
        "final",
        (
            NamedRef("artifact", artifact_ref),
            NamedRef("execution", store.put_bytes(b"execution")),
            NamedRef("render_options", store.put_bytes(b"options")),
        ),
    )
    return manifest, artifact_ref


def _changes_payload(
    *,
    context: dict[str, object],
    end_frame_exclusive: int,
    target_ids: list[str],
    outcome: str = "changes_requested",
    finding_id: str = "studio.ui.001",
) -> dict[str, object]:
    return {
        "expected_artifact": context["artifact"],
        "expected_timeline": context["timeline"],
        "expected_check_report": context["check_report"],
        "expected_constraints": context["constraints"],
        "outcome": outcome,
        "scope": ["visual", "audio", "constraints"],
        "reviewer": "author",
        "reviewed_at": "2026-07-30T00:00:00Z",
        "findings": [
            {
                "finding_id": finding_id,
                "text": "Move this element.",
                "requires_change": True,
                "locator": {
                    "start_frame": 5,
                    "end_frame_exclusive": end_frame_exclusive,
                    "region": {
                        "x_milli": 100,
                        "y_milli": 200,
                        "width_milli": 300,
                        "height_milli": 150,
                    },
                    "target_ids": target_ids,
                },
            }
        ],
    }


def _first_round_ref(
    *,
    verdict_payload: dict[str, object],
) -> BlobRef:
    verdict = ReviewVerdict.from_canonical_bytes(
        canonical_bytes(
            verdict_payload,
            domain=ReviewVerdict.DOMAIN,
            version=ReviewVerdict.VERSION,
        )
    )
    return ReviewRound(verdict.ref).ref


def _invalidate_prepare(
    production_root: Path,
) -> tuple[WorkflowStore, BlobRef]:
    repository, _, workflows = open_local_repositories(
        production_root,
        "fixture.reel",
    )
    current = workflows.read_current()
    assert current is not None
    prepared = next(
        attempt
        for attempt in current.attempts
        if attempt.stage == "prepare" and attempt.state == "succeeded"
    )
    authoring_ref = repository.objects.put_bytes(b"authoring revision 2")
    _save_stage(
        workflows,
        "prepare",
        prepared.outputs,
        inputs=(NamedRef("authoring", authoring_ref),),
        contract="fixture.prepare.v2",
    )
    new_artifact = repository.objects.put_bytes(
        bytes(reversed(range(128)))
    )
    return workflows, new_artifact


def test_review_http_validates_exact_frames_targets_and_survives_submission(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.http import create_app

    manifest, _ = _review_ready_production(tmp_path / "production")
    client = TestClient(create_app(manifest))

    context = client.get("/api/v3/review/context")
    assert context.status_code == 200
    context_payload = context.json()
    assert context_payload["items"][0]["item_id"] == "visual.000"

    beyond_end = client.post(
        "/api/v3/review",
        json=_changes_payload(
            context=context_payload,
            end_frame_exclusive=7,
            target_ids=["visual.000"],
        ),
    )
    assert beyond_end.status_code == 409

    unknown_target = client.post(
        "/api/v3/review",
        json=_changes_payload(
            context=context_payload,
            end_frame_exclusive=6,
            target_ids=["visual.999"],
        ),
    )
    assert unknown_target.status_code == 409

    stale_payload = _changes_payload(
        context=context_payload,
        end_frame_exclusive=6,
        target_ids=["visual.000"],
    )
    stale_payload["expected_artifact"] = {
        "sha256": "f" * 64,
        "size": context_payload["artifact"]["size"],
    }
    stale = client.post("/api/v3/review", json=stale_payload)
    assert stale.status_code == 409
    assert "review context changed" in stale.json()["detail"]

    accepted = client.post(
        "/api/v3/review",
        json=_changes_payload(
            context=context_payload,
            end_frame_exclusive=6,
            target_ids=["visual.000"],
        ),
    )
    assert accepted.status_code == 200

    current = client.get("/api/v3/review/current")
    assert current.status_code == 200
    assert current.json()["outcome"] == "changes_requested"
    locator = current.json()["findings"][0]["locator"]
    assert locator["start_frame"] == 5
    assert locator["end_frame_exclusive"] == 6
    assert accepted.json()["current_stage"] == "review"
    assert accepted.json()["action"] == "review"
    assert client.get("/api/v3/review/context").status_code == 200


def test_block_review_remains_the_current_review_action(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.http import create_app

    manifest, _ = _review_ready_production(tmp_path / "block")
    client = TestClient(create_app(manifest))
    context = client.get("/api/v3/review/context").json()

    accepted = client.post(
        "/api/v3/review",
        json=_changes_payload(
            context=context,
            end_frame_exclusive=6,
            target_ids=["visual.000"],
            outcome="block",
        ),
    )

    assert accepted.status_code == 200
    current = client.get("/api/v3/review/current")
    assert current.status_code == 200
    assert current.json()["outcome"] == "block"
    assert accepted.json()["current_stage"] == "review"
    assert accepted.json()["action"] == "review"


@pytest.mark.parametrize(
    ("method", "headers", "expected_status"),
    (
        ("GET", {}, 200),
        ("HEAD", {}, 200),
        ("GET", {"Range": "bytes=2-5"}, 206),
    ),
)
def test_lineage_artifact_remains_available_while_final_is_invalidated(
    tmp_path: Path,
    method: str,
    headers: dict[str, str],
    expected_status: int,
) -> None:
    from dlstudio.adapters.http import create_app

    production_root = tmp_path / "production"
    manifest, first_artifact = _review_ready_production(production_root)
    client = TestClient(create_app(manifest))
    context = client.get("/api/v3/review/context").json()
    payload = _changes_payload(
        context=context,
        end_frame_exclusive=6,
        target_ids=["visual.000"],
    )
    payload["expected_latest_round"] = None
    payload["resolutions"] = []
    accepted = client.post("/api/v3/review", json=payload)
    assert accepted.status_code == 200

    _invalidate_prepare(production_root)
    url = (
        f"/api/v3/review/artifacts/{first_artifact.sha256}"
        f"?size={first_artifact.size}"
    )

    response = client.request(method, url, headers=headers)

    assert response.status_code == expected_status
    if method == "HEAD":
        assert response.content == b""
        assert response.headers["content-length"] == str(first_artifact.size)
    elif headers:
        assert response.headers["content-range"] == "bytes 2-5/128"
        assert response.content == bytes(range(128))[2:6]
    else:
        assert response.content == bytes(range(128))


def test_concurrent_artifact_requests_serialize_cache_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dlstudio.adapters import http as http_adapter
    from dlstudio.persistence.workflow import WorkflowRepository

    class MutationDetectingOrderedDict(OrderedDict):
        instances: list["MutationDetectingOrderedDict"] = []

        def __init__(self) -> None:
            super().__init__()
            self.active_mutations = 0
            self.concurrent_mutation = False
            self.counter_lock = Lock()
            self.instances.append(self)

        def _observe(self, operation, *args):
            with self.counter_lock:
                self.active_mutations += 1
                if self.active_mutations > 1:
                    self.concurrent_mutation = True
            try:
                sleep(0.02)
                return operation(self, *args)
            finally:
                with self.counter_lock:
                    self.active_mutations -= 1

        def __setitem__(self, key, value) -> None:
            self._observe(OrderedDict.__setitem__, key, value)

        def move_to_end(self, key, last: bool = True) -> None:
            self._observe(OrderedDict.move_to_end, key, last)

        def popitem(self, last: bool = True):
            return self._observe(OrderedDict.popitem, last)

    monkeypatch.setattr(
        http_adapter,
        "OrderedDict",
        MutationDetectingOrderedDict,
    )
    manifest, artifact = _review_ready_production(tmp_path / "production")
    client = TestClient(
        http_adapter.create_app(manifest),
        raise_server_exceptions=False,
    )
    context = client.get("/api/v3/review/context").json()
    payload = _changes_payload(
        context=context,
        end_frame_exclusive=6,
        target_ids=["visual.000"],
    )
    payload["expected_latest_round"] = None
    payload["resolutions"] = []
    assert client.post("/api/v3/review", json=payload).status_code == 200

    cache_identity = count(10_000)
    monkeypatch.setattr(
        WorkflowRepository,
        "head_revision",
        lambda _self: next(cache_identity),
    )
    workers = 12
    start = Barrier(workers)
    url = (
        f"/api/v3/review/artifacts/{artifact.sha256}"
        f"?size={artifact.size}"
    )

    def request_artifact(_position: int) -> int:
        start.wait()
        return client.get(url).status_code

    with ThreadPoolExecutor(max_workers=workers) as pool:
        statuses = tuple(pool.map(request_artifact, range(workers)))

    assert statuses == (200,) * workers
    assert not any(
        cache.concurrent_mutation
        for cache in MutationDetectingOrderedDict.instances
    )


def test_review_round_fields_survive_invalidation_and_authorize_lineage_media(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.http import create_app

    production_root = tmp_path / "production"
    manifest, first_artifact = _review_ready_production(production_root)
    client = TestClient(create_app(manifest))
    first_context = client.get("/api/v3/review/context").json()
    first_payload = _changes_payload(
        context=first_context,
        end_frame_exclusive=6,
        target_ids=["visual.000"],
    )
    first_payload["expected_latest_round"] = None
    first_payload["resolutions"] = []

    first = client.post("/api/v3/review", json=first_payload)
    assert first.status_code == 200
    first_current = client.get("/api/v3/review/current")
    assert first_current.status_code == 200
    first_round = _first_round_ref(
        verdict_payload=first_current.json(),
    )
    assert first_current.json()["outcome"] == (
        "changes_requested"
    )

    workflows, second_artifact = _invalidate_prepare(production_root)

    # The latest exact review is history, not a completed workflow attempt,
    # so upstream authoring invalidation must not make it disappear.
    after_invalidation = client.get("/api/v3/review/current")
    assert after_invalidation.status_code == 200
    assert after_invalidation.json()["artifact"] == first_artifact.as_payload()

    _save_stage(
        workflows,
        "draft",
        (NamedRef("artifact", workflows.put_blob(b"draft revision 2")),),
    )
    _save_stage(
        workflows,
        "final",
        (
            NamedRef("artifact", second_artifact),
            NamedRef("execution", workflows.put_blob(b"execution revision 2")),
            NamedRef(
                "render_options",
                workflows.put_blob(b"options revision 2"),
            ),
        ),
    )

    second_context = client.get("/api/v3/review/context").json()
    assert second_context["latest_round"] == first_round.as_payload()
    assert second_context["latest_verdict"] == first_current.json()
    second_payload = _changes_payload(
        context=second_context,
        end_frame_exclusive=6,
        target_ids=["visual.000"],
        outcome="block",
        finding_id="studio.ui.002",
    )
    second_payload["expected_latest_round"] = first_round.as_payload()
    second_payload["resolutions"] = [
        {
            "previous_finding_id": "studio.ui.001",
            "status": "still_wrong",
            "current_finding_id": "studio.ui.002",
        }
    ]
    second = client.post("/api/v3/review", json=second_payload)
    assert second.status_code == 200
    assert second.json()["current_stage"] == "review"
    assert client.get("/api/v3/review/current").json()["artifact"] == (
        second_artifact.as_payload()
    )

    first_bytes = bytes(range(128))
    second_bytes = bytes(reversed(range(128)))
    for artifact, expected in (
        (first_artifact, first_bytes),
        (second_artifact, second_bytes),
    ):
        url = (
            f"/api/v3/review/artifacts/{artifact.sha256}"
            f"?size={artifact.size}"
        )
        full = client.get(url)
        assert full.status_code == 200
        assert full.content == expected

        head = client.head(url)
        assert head.status_code == 200
        assert head.content == b""
        assert head.headers["content-length"] == str(len(expected))

        partial = client.get(url, headers={"Range": "bytes=2-5"})
        assert partial.status_code == 206
        assert partial.headers["content-range"] == "bytes 2-5/128"
        assert partial.content == expected[2:6]

    unrelated = workflows.put_blob(b"stored but unrelated")
    unrelated_url = (
        f"/api/v3/review/artifacts/{unrelated.sha256}"
        f"?size={unrelated.size}"
    )
    assert client.get(unrelated_url).status_code == 409
    assert client.head(unrelated_url).status_code == 409
    assert client.get(
        unrelated_url,
        headers={"Range": "bytes=0-2"},
    ).status_code == 409


def test_review_artifact_supports_range_and_rejects_stale_identity(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.http import create_app

    manifest, artifact = _review_ready_production(tmp_path / "production")
    client = TestClient(create_app(manifest))
    url = (
        f"/api/v3/review/artifacts/{artifact.sha256}"
        f"?size={artifact.size}"
    )

    partial = client.get(url, headers={"Range": "bytes=2-5"})
    assert partial.status_code == 206
    assert partial.headers["content-range"] == "bytes 2-5/128"
    assert partial.headers["content-type"].startswith("video/mp4")
    assert partial.content == bytes(range(2, 6))

    stale = client.get(
        f"/api/v3/review/artifacts/{'f' * 64}?size={artifact.size}"
    )
    assert stale.status_code == 409
