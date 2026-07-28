"""Studio v3 authoring; asset trust lives in the repository."""

from dlstudio.authoring.api import Animation, AudioClip, Edit, MediaGeometry, MediaLayer, VideoFade
EDIT = Edit(
    production_id='2026_07_18_reel_02',
    width=1080,
    height=1920,
    fps_num=30,
    fps_den=1,
    duration_ns=17520000000,
    background='#0d0e0e',
    visuals=(
        MediaLayer('asset.data.infographics.master.mp4.b72a837e', 0, 17520000000, 0, 0, 0, 1080, 1920, fit='cover', source_start_ns=0, loop=False, freeze_at_end=False, ken_burns=False, transition='cut', transition_ns=0, transition_intent=None, geometry=MediaGeometry(1080, 1920, 1080, 1920, crop_x=0, crop_y=0, pad_x=None, pad_y=None)),
        MediaLayer('asset.data.v3.port.raster.caption.7ab53c39ee2376e393180708edfd158861ac0cec080d56293f93d7827a129787.png.ff519412', 0, 1920000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
        MediaLayer('asset.data.v3.port.raster.caption.100a3c4bbc3af8728f677fa99b4ab0e28e9283bcb1ff82ed6c959a25dd079bb8.png.1a837a03', 1920000000, 6100000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
        MediaLayer('asset.data.v3.port.raster.caption.ec887ef8c7c7fd499ba04fcf9e3d883380205413f04dcdececae2bdc198b5d01.png.e5f18060', 8020000000, 3300000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
        MediaLayer('asset.data.v3.port.raster.caption.ffe1f32f719dea5fe47f0538cec8c01a4f10d8c229cc8cd8ff1d70080d68e2ab.png.68a12a87', 11320000000, 2760000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
        MediaLayer('asset.data.v3.port.raster.caption.fea6a0f78699222d7735f87bb82ef1668a248281ea0d28124d16768b5f28e70a.png.49fdf7cc', 14080000000, 2240000000, 100, 0, 0, 1080, 1920, fit='stretch', transition='fade', transition_ns=80000000, fade_out_ns=80000000),
    ),
    audio=(
        AudioClip('asset.data.audio.voice.wav.a528157a', 0, 17520000000, role='voice'),
        AudioClip('asset.data.music.first.day.in.a.loop.ogg.8081d22a', 0, 17520000000, source_start_ns=22000000000, gain_db_milli=-23000, fade_in_ns=500000000, fade_out_ns=2200000000, role='music', duck=True, loop=True),
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
