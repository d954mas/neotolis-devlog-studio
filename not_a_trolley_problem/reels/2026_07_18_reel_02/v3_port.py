"""Generated static Studio v3 port; no legacy runtime imports."""

from dlstudio.assets.api import Approval, AssetRevision, BlobRef, License, MediaFacts, Provenance
from dlstudio.authoring.api import Animation, AudioClip, Edit, MediaGeometry, MediaLayer, VideoFade

ASSETS = (
    AssetRevision(
        asset_id='asset.05b5602520821fd995b2',
        blob=BlobRef('05b5602520821fd995b2d147dd4258c31cc1128d39ab570b3f9035ef46b37f62', 1681998),
        media=MediaFacts.from_payload({'kind': 'audio', 'format_name': 'wav', 'duration_ns': 17520000000, 'sample_rate': 48000, 'channels': 1, 'codec': 'pcm_s16le'}),
        provenance=Provenance.from_payload({'origin': 'recorded', 'capture_method': 'voice_take', 'logical_source': 'data/audio/voice.wav', 'script_sha256': '11a46c01ab482979c909fe04698be6ee9cd93b3d990491ba9f3e4992578ce4a4'}),
        approval=Approval.from_payload({'status': 'pending', 'evidence_sha256': (), 'reason': 'no exact v3 migration evidence'}),
        license=License.from_payload({'license_id': 'creator-owned-voice', 'attribution_required': False}),
    ),
    AssetRevision(
        asset_id='asset.52213fb23c3211ca8271',
        blob=BlobRef('52213fb23c3211ca82711fc7b6b194a65aec478cc87f8089e0ae6f4018e0f5d7', 13435417),
        media=MediaFacts.from_payload({'kind': 'video', 'format_name': 'mov', 'duration_ns': 17533333000, 'width': 1080, 'height': 1920, 'fps_num': 30, 'fps_den': 1, 'codec': 'h264'}),
        provenance=Provenance.from_payload({'origin': 'generated', 'capture_method': 'legacy_generated_port', 'logical_source': 'data/infographics/master.mp4'}),
        approval=Approval.from_payload({'status': 'pending', 'evidence_sha256': (), 'reason': 'no exact v3 migration evidence'}),
        license=License.from_payload({'license_id': 'legacy-generated-license-unverified', 'attribution_required': False, 'redistribution_allowed': False}),
    ),
    AssetRevision(
        asset_id='asset.2b037f207c57dfa73382',
        blob=BlobRef('2b037f207c57dfa73382f9a39bce52e258605c63b029b07cb1e9b8b29d48d070', 4263118),
        media=MediaFacts.from_payload({'kind': 'audio', 'format_name': 'ogg', 'duration_ns': 240000000000, 'sample_rate': 44100, 'channels': 2, 'codec': 'vorbis'}),
        provenance=Provenance.from_payload({'origin': 'provided', 'capture_method': 'purchased_library', 'logical_source': 'data/music/first_day_in_a_loop.ogg', 'provider_receipt_sha256': '9385a3563edee41e51a1cb61e2be7f4bbe489277749ddcb907329d54be9d40a7'}),
        approval=Approval.from_payload({'status': 'approved', 'evidence_sha256': ('4532e5b77e91d90c8e2235d24a71eb8c06ae389c87523c25c7914abb5073aaec', '9385a3563edee41e51a1cb61e2be7f4bbe489277749ddcb907329d54be9d40a7')}),
        license=License.from_payload({'license_id': 'purchased-premium-royalty-free', 'attribution_required': False}),
    ),
    AssetRevision(
        asset_id='asset.1e5afeca942f7b73cdcd',
        blob=BlobRef('1e5afeca942f7b73cdcd0b681522da02f4c2a928be801bb1e900f405a859dae5', 45690),
        media=MediaFacts.from_payload({'kind': 'image', 'format_name': 'png', 'width': 1080, 'height': 1920}),
        provenance=Provenance.from_payload({'origin': 'derived', 'capture_method': 'v3_static_raster_port', 'logical_source': 'data/v3_port/raster/caption-100a3c4bbc3af8728f677fa99b4ab0e28e9283bcb1ff82ed6c959a25dd079bb8.png', 'provider_receipt_sha256': '100a3c4bbc3af8728f677fa99b4ab0e28e9283bcb1ff82ed6c959a25dd079bb8'}),
        approval=Approval.from_payload({'status': 'validated', 'evidence_sha256': ('100a3c4bbc3af8728f677fa99b4ab0e28e9283bcb1ff82ed6c959a25dd079bb8',)}),
        license=License.from_payload({'license_id': 'derived-from-legacy-source-license-unverified', 'attribution_required': False, 'redistribution_allowed': False}),
    ),
    AssetRevision(
        asset_id='asset.873fe2fc340f4a438c8b',
        blob=BlobRef('873fe2fc340f4a438c8b746334ad99294c177d0f3f87b9db4364aa5f1c50a05e', 17569),
        media=MediaFacts.from_payload({'kind': 'image', 'format_name': 'png', 'width': 1080, 'height': 1920}),
        provenance=Provenance.from_payload({'origin': 'derived', 'capture_method': 'v3_static_raster_port', 'logical_source': 'data/v3_port/raster/caption-7ab53c39ee2376e393180708edfd158861ac0cec080d56293f93d7827a129787.png', 'provider_receipt_sha256': '7ab53c39ee2376e393180708edfd158861ac0cec080d56293f93d7827a129787'}),
        approval=Approval.from_payload({'status': 'validated', 'evidence_sha256': ('7ab53c39ee2376e393180708edfd158861ac0cec080d56293f93d7827a129787',)}),
        license=License.from_payload({'license_id': 'derived-from-legacy-source-license-unverified', 'attribution_required': False, 'redistribution_allowed': False}),
    ),
    AssetRevision(
        asset_id='asset.ef15f3e17484eba04fc3',
        blob=BlobRef('ef15f3e17484eba04fc3d316cadde9ad61cf871579997e91258f7ba767b977a0', 31541),
        media=MediaFacts.from_payload({'kind': 'image', 'format_name': 'png', 'width': 1080, 'height': 1920}),
        provenance=Provenance.from_payload({'origin': 'derived', 'capture_method': 'v3_static_raster_port', 'logical_source': 'data/v3_port/raster/caption-ec887ef8c7c7fd499ba04fcf9e3d883380205413f04dcdececae2bdc198b5d01.png', 'provider_receipt_sha256': 'ec887ef8c7c7fd499ba04fcf9e3d883380205413f04dcdececae2bdc198b5d01'}),
        approval=Approval.from_payload({'status': 'validated', 'evidence_sha256': ('ec887ef8c7c7fd499ba04fcf9e3d883380205413f04dcdececae2bdc198b5d01',)}),
        license=License.from_payload({'license_id': 'derived-from-legacy-source-license-unverified', 'attribution_required': False, 'redistribution_allowed': False}),
    ),
    AssetRevision(
        asset_id='asset.356ae0ffe389637a63c1',
        blob=BlobRef('356ae0ffe389637a63c14e68b0849da47ae02e0497abb338a21ac117452d0802', 21052),
        media=MediaFacts.from_payload({'kind': 'image', 'format_name': 'png', 'width': 1080, 'height': 1920}),
        provenance=Provenance.from_payload({'origin': 'derived', 'capture_method': 'v3_static_raster_port', 'logical_source': 'data/v3_port/raster/caption-fea6a0f78699222d7735f87bb82ef1668a248281ea0d28124d16768b5f28e70a.png', 'provider_receipt_sha256': 'fea6a0f78699222d7735f87bb82ef1668a248281ea0d28124d16768b5f28e70a'}),
        approval=Approval.from_payload({'status': 'validated', 'evidence_sha256': ('fea6a0f78699222d7735f87bb82ef1668a248281ea0d28124d16768b5f28e70a',)}),
        license=License.from_payload({'license_id': 'derived-from-legacy-source-license-unverified', 'attribution_required': False, 'redistribution_allowed': False}),
    ),
    AssetRevision(
        asset_id='asset.6ae0b3ad5ae49e931bd8',
        blob=BlobRef('6ae0b3ad5ae49e931bd8760641a03ccbd74f7313695eb715979584cbb58a040d', 24925),
        media=MediaFacts.from_payload({'kind': 'image', 'format_name': 'png', 'width': 1080, 'height': 1920}),
        provenance=Provenance.from_payload({'origin': 'derived', 'capture_method': 'v3_static_raster_port', 'logical_source': 'data/v3_port/raster/caption-ffe1f32f719dea5fe47f0538cec8c01a4f10d8c229cc8cd8ff1d70080d68e2ab.png', 'provider_receipt_sha256': 'ffe1f32f719dea5fe47f0538cec8c01a4f10d8c229cc8cd8ff1d70080d68e2ab'}),
        approval=Approval.from_payload({'status': 'validated', 'evidence_sha256': ('ffe1f32f719dea5fe47f0538cec8c01a4f10d8c229cc8cd8ff1d70080d68e2ab',)}),
        license=License.from_payload({'license_id': 'derived-from-legacy-source-license-unverified', 'attribution_required': False, 'redistribution_allowed': False}),
    ),
)

EDIT = Edit(
    production_id='2026_07_18_reel_02',
    width=1080,
    height=1920,
    fps_num=30,
    fps_den=1,
    duration_ns=17520000000,
    background='#0d0e0e',
    assets=ASSETS,
    visuals=(
        MediaLayer('asset.52213fb23c3211ca8271', 0, 17520000000, 0, 0, 0, 1080, 1920, fit='cover', source_start_ns=0, loop=False, freeze_at_end=False, ken_burns=False, transition='cut', transition_ns=0, transition_intent=None, geometry=MediaGeometry(1080, 1920, 1080, 1920, crop_x=0, crop_y=0, pad_x=None, pad_y=None)),
        MediaLayer('asset.873fe2fc340f4a438c8b', 0, 1920000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
        MediaLayer('asset.1e5afeca942f7b73cdcd', 1920000000, 6100000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
        MediaLayer('asset.ef15f3e17484eba04fc3', 8020000000, 3300000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
        MediaLayer('asset.6ae0b3ad5ae49e931bd8', 11320000000, 2760000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
        MediaLayer('asset.356ae0ffe389637a63c1', 14080000000, 2240000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
    ),
    audio=(
        AudioClip('asset.05b5602520821fd995b2', 0, 17520000000, role='voice'),
        AudioClip('asset.2b037f207c57dfa73382', 0, 17520000000, source_start_ns=22000000000, gain_db_milli=-23000, fade_in_ns=500000000, fade_out_ns=2200000000, role='music', duck=True, loop=True),
    ),
    video_fades=(

    ),
    target_lufs_milli=-14000,
    true_peak_db_milli=-1000,
    duck_amount_db_milli=-12000,
    duck_threshold_db_milli=-30000,
    duck_attack_ms=120,
    duck_release_ms=400,
    standalone_story='The reel asks why 2D was not extended, explains the sprite cost, contrasts 3D freedom, and resolves that this is a new game.',
    kind='reel',
)
