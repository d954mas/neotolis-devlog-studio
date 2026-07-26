"""Pure authoring DSL to TimelineIR compiler."""

from __future__ import annotations

from dlstudio.timeline.api import (
    AnimationInstruction,
    AssetSnapshot,
    AudioInstruction,
    MediaGeometry as TimelineMediaGeometry,
    TimelineIR,
    VideoFadeInstruction,
    VisualInstruction,
)

from .api import AudioClip, Edit, MediaLayer, SolidLayer, TextLayer


def compile_edit(edit: Edit) -> TimelineIR:
    revisions = {revision.asset_id: revision for revision in edit.assets}
    if len(revisions) != len(edit.assets):
        raise ValueError("edit contains duplicate asset ids")
    visuals: list[VisualInstruction] = []
    used_asset_ids: set[str] = set()
    for layer in edit.visuals:
        common = {
            "start_ns": layer.start_ns,
            "duration_ns": layer.duration_ns,
            "z": layer.z,
            "x": layer.x,
            "y": layer.y,
            "width": layer.width,
            "height": layer.height,
            "opacity_milli": layer.opacity_milli,
        }
        if isinstance(layer, SolidLayer):
            visuals.append(
                VisualInstruction(kind="solid", color=layer.color, **common)
            )
        elif isinstance(layer, MediaLayer):
            revision = revisions.get(layer.asset_id)
            if revision is None:
                raise ValueError(f"unknown media asset: {layer.asset_id}")
            used_asset_ids.add(layer.asset_id)
            visuals.append(
                VisualInstruction(
                    kind="media",
                    asset=revision.ref,
                    fit=layer.fit,
                    source_start_ns=layer.source_start_ns,
                    loop=layer.loop,
                    freeze_at_end=layer.freeze_at_end,
                    ken_burns=layer.ken_burns,
                    transition=layer.transition,
                    transition_ns=layer.transition_ns,
                    fade_out_ns=layer.fade_out_ns,
                    geometry=(
                        None
                        if layer.geometry is None
                        else TimelineMediaGeometry(
                            source_width=layer.geometry.source_width,
                            source_height=layer.geometry.source_height,
                            scaled_width=layer.geometry.scaled_width,
                            scaled_height=layer.geometry.scaled_height,
                            crop_x=layer.geometry.crop_x,
                            crop_y=layer.geometry.crop_y,
                            pad_x=layer.geometry.pad_x,
                            pad_y=layer.geometry.pad_y,
                        )
                    ),
                    animations=tuple(
                        AnimationInstruction(
                            prop=animation.prop,
                            start_milli=animation.start_milli,
                            end_milli=animation.end_milli,
                            ease=animation.ease,
                            start_ns=animation.start_ns,
                            end_ns=animation.end_ns,
                        )
                        for animation in layer.animations
                    ),
                    transition_intent=layer.transition_intent,
                    **common,
                )
            )
        elif isinstance(layer, TextLayer):
            revision = revisions.get(layer.font_asset_id)
            if revision is None or revision.media.kind != "font":
                raise ValueError(f"unknown font asset: {layer.font_asset_id}")
            used_asset_ids.add(layer.font_asset_id)
            visuals.append(
                VisualInstruction(
                    kind="text",
                    text=layer.text,
                    font_asset=revision.ref,
                    font_size=layer.font_size,
                    color=layer.color,
                    role=layer.role,
                    transition=layer.transition,
                    transition_ns=layer.transition_ns,
                    **common,
                )
            )
        else:  # pragma: no cover - closed union.
            raise TypeError(type(layer).__name__)
    audio: list[AudioInstruction] = []
    for clip in edit.audio:
        assert isinstance(clip, AudioClip)
        revision = revisions.get(clip.asset_id)
        if revision is None or revision.media.kind not in {"audio", "video"}:
            raise ValueError(f"unknown audio asset: {clip.asset_id}")
        used_asset_ids.add(clip.asset_id)
        audio.append(
            AudioInstruction(
                revision.ref,
                clip.start_ns,
                clip.duration_ns,
                clip.source_start_ns,
                clip.gain_db_milli,
                clip.fade_in_ns,
                clip.fade_out_ns,
                clip.role,
                clip.duck,
                clip.loop,
            )
        )
    return TimelineIR(
        production_id=edit.production_id,
        width=edit.width,
        height=edit.height,
        fps_num=edit.fps_num,
        fps_den=edit.fps_den,
        duration_ns=edit.duration_ns,
        background=edit.background,
        assets=tuple(
            AssetSnapshot.from_revision(revisions[asset_id])
            for asset_id in sorted(used_asset_ids)
        ),
        visuals=tuple(visuals),
        audio=tuple(audio),
        video_fades=tuple(
            VideoFadeInstruction(
                direction=fade.direction,
                start_ns=fade.start_ns,
                duration_ns=fade.duration_ns,
                color=fade.color,
            )
            for fade in edit.video_fades
        ),
        target_lufs_milli=edit.target_lufs_milli,
        true_peak_db_milli=edit.true_peak_db_milli,
        duck_amount_db_milli=edit.duck_amount_db_milli,
        duck_threshold_db_milli=edit.duck_threshold_db_milli,
        duck_attack_ms=edit.duck_attack_ms,
        duck_release_ms=edit.duck_release_ms,
        metadata={
            "kind": edit.kind,
            "standalone_story": edit.standalone_story,
        },
    )
