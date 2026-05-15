"""Trolley YouTube edit — beats as typed dataclasses.

Single source of truth for: rendering (compose.py), teleprompter (recorder.html),
and review (preview.html). Everything those tools need about a beat lives here.

Edit's CONCAT_ORDER below defines what gets concatenated into the final video.
To deprecate a beat: remove its id from CONCAT_ORDER (keep the Beat object for
reference). To revive: add the id back.
"""
from devlog.types import Beat, Chunk, Scene
from trolley.shared.palette import TROLLEY_PALETTE as _PAL


# ─── Local aliases (only used inside this file for readability) ───
_GOLD = _PAL.gold
_GOLD_DIM = _PAL.gold_dim
_BG = _PAL.bg
_RED = _PAL.red


BEATS: dict[str, Beat] = {

    # ════════════════════════════════════════════════════════════════
    # ACT 0 — HOOK
    # ════════════════════════════════════════════════════════════════
    "a0-1": Beat(
        title="Шок-claim",
        face="full",
        vo="Ни одной строчки кода в этой игре я не написал сам.",
        stage='Энергично, без вибрато. Произнести разборчиво — это ключевая фраза видео. Микро-пауза перед "сам".',
        audio="data/finalize/a0-1_audio_final.wav",
        words="data/finalize/a0-1_words.json",
        scene=Scene(kind="video", src="data/trailer/trailer_final_30fps.mp4", offset=12.0),
        chunks=[
            Chunk(words=(0, 10), kind="overlay",
                  text="НИ ОДНОЙ СТРОЧКИ",
                  subtitle="ЗА 13 ДНЕЙ · БЕЗ ЕДИНОЙ СТРОКИ ВРУЧНУЮ",
                  position="bottom"),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # ACT 1 — JAM CONTEXT + DAY 1
    # ════════════════════════════════════════════════════════════════
    "a1-1": Beat(
        title="Тема + идея",
        face="none",
        vo=("Gamedev.js Jam две тысячи двадцать шестой год. Тема — Machines. Тринадцать дней. "
            "Трамвай — это машина. А проблема вагонетки — это интересная задачка, про которую "
            "можно сделать игру. А что если нет никакой проблемы? Что если трамвай ездит по "
            "кругу, и нужно просто добавлять больше людей."),
        stage=('Конверсационно, с лёгкой улыбкой к финалу. На "А что если нет никакой проблемы?" — '
               'поднять интонацию, intrigue. На "добавлять больше людей" — спокойно, почти буднично.'),
        audio="data/finalize/a1-1_audio_final.wav",
        words="data/finalize/a1-1_words.json",
        scene=Scene(kind="video", src="data/trailer/clean_gameplay.mp4", offset=3.5),
        chunks=[
            Chunk(words=(0, 8), kind="image",
                  src="data/jam/gamedevjs_jam2026_banner.png", fit="cover"),
            Chunk(words=(9, 12), kind="overlay",
                  text="ТРАМВАЙ = МАШИНА", subtitle="ВПИСЫВАЕТСЯ В ТЕМУ", position="bottom"),
            Chunk(words=(13, 23), kind="overlay",
                  text="ПРОБЛЕМА ВАГОНЕТКИ", subtitle="МОРАЛЬНО-ЭТИЧЕСКИЙ ВЫБОР", position="bottom"),
            Chunk(words=(24, 29), kind="plate",
                  text="А ЧТО ЕСЛИ\nНЕТ ПРОБЛЕМЫ?",
                  size=220, subtitle="ДРУГОЙ УГОЛ", subtitle_color=_GOLD_DIM,
                  line_gap_ratio=0.10, ken_burns=True,
                  bg_image="data/itch/snap_village_artshot.png", bg_opacity=0.30),
            Chunk(words=(30, 41), kind="overlay",
                  text="ТРАМВАЙ ЕЗДИТ ПО КРУГУ", subtitle="ПРОСТО ДОБАВЛЯЙ ЛЮДЕЙ", position="bottom"),
        ],
    ),

    "a1-2": Beat(
        title="Day 1 — кружочки",
        face="none",
        vo=("День первый. Рельсы, кружочки. Любая игра начинается с примитивов — нужно проверить, "
            "интересна ли механика. Тащишь, бросаешь, трамвай ездит, монетки летят."),
        stage='Деловой тон. На "Любая игра начинается с примитивов" — спокойная уверенность, teaching moment.',
        audio="data/finalize/a1-2_audio_final.wav",
        words="data/finalize/a1-2_words.json",
        chunks=[
            Chunk(words=(0, 4), kind="overlay", text="", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/day1_progression_anim.mp4")),
            Chunk(words=(5, 9), kind="overlay",
                  text="РЕЛЬСЫ · КРУЖОЧКИ", subtitle="ПРИМИТИВЫ ДЛЯ ТЕСТА", position="top",
                  scene=Scene(kind="video", src="data/infographics/day1_progression_anim.mp4")),
            Chunk(words=(10, 14), kind="overlay",
                  text="ТЕСТ МЕХАНИКИ", subtitle="ИНТЕРЕСНО ЛИ ИГРАТЬ?", position="bottom",
                  scene=Scene(kind="video", src="data/recordings/day1_gameplay.mp4")),
            Chunk(words=(15, 20), kind="overlay",
                  text="ТАЩИШЬ → БРОСАЕШЬ", subtitle="CORE LOOP РАБОТАЕТ", position="bottom",
                  scene=Scene(kind="video", src="data/recordings/day1_gameplay.mp4")),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # ACT B — SHOWCASE
    # ════════════════════════════════════════════════════════════════
    "b3": Beat(
        title="Day 13 — большой список фич",
        face="pip",
        vo=("За тринадцать дней — вот что получилось. Липкий палец — ядро механики. Пять миров, "
            "в каждом свой босс. Прокачиваешь ранг — можешь сделать трамвайный выбор. Например: "
            "кот Шредингера или учёный. Мимы или клоуны. Десять таких карточек. Апгрейд-дерево — "
            "пятьдесят девять нод. Полное прохождение — пятнадцать-двадцать минут."),
        stage="Обзор фич игры списком. Темп — деловой, перечисляю по очереди. Лёгкая улыбка на названиях карт.",
        audio="data/finalize/b3_audio_final.wav",
        words="data/finalize/b3_words.json",
        # SINGLE trailer scene throughout — no mid-beat scene switching (iter_60: looked like glitches).
        # Extended trailer (32s) covers full b3 duration without loop.
        scene=Scene(kind="video", src="data/trailer/clean_gameplay_extended.mp4", offset=18.0),
        chunks=[
            Chunk(words=(0, 5), kind="overlay",
                  text="13 ДНЕЙ СПУСТЯ", subtitle="ВОТ ЧТО ПОЛУЧИЛОСЬ", position="bottom"),
            Chunk(words=(6, 10), kind="overlay",
                  text="ЛИПКИЙ ПАЛЕЦ", subtitle="ЯДРО МЕХАНИКИ", position="bottom",
                  scene=Scene(kind="video", src="data/itch/sticky_finger_gameplay.mp4")),
            Chunk(words=(11, 17), kind="overlay",
                  text="5 МИРОВ", subtitle="В КАЖДОМ — СВОЙ БОСС", position="bottom",
                  scene=Scene(kind="image", src="data/infographics/worlds_collage.png")),
            Chunk(words=(18, 24), kind="overlay",
                  text="ВЫБОР-КАРТОЧКИ", subtitle="НА КАЖДОМ РАНГЕ", position="bottom",
                  scene=Scene(kind="image", src="data/itch/choice_card_01.png")),
            Chunk(words=(25, 29), kind="overlay",
                  text="КОТ ШРЁДИНГЕРА ИЛИ УЧЁНЫЙ?", subtitle="АБСУРД В КАЖДОЙ ДИЛЕММЕ", position="bottom",
                  scene=Scene(kind="video", src="data/itch/choice_schrodinger.mp4", offset=7.0)),
            Chunk(words=(30, 32), kind="overlay",
                  text="МИМЫ ИЛИ КЛОУНЫ?", subtitle="АБСУРД В КАЖДОЙ ДИЛЕММЕ", position="bottom",
                  scene=Scene(kind="video", src="data/itch/choice_mimes.mp4", offset=3.5)),
            Chunk(words=(33, 37), kind="overlay",
                  text="10 КАРТ", subtitle="ВЫБОР НА КАЖДОМ РАНГЕ", position="bottom",
                  scene=Scene(kind="video", src="data/itch/choice_journal.mp4", offset=2.0)),
            Chunk(words=(38, 42), kind="overlay",
                  text="59 НОД", subtitle="АПГРЕЙД-ДЕРЕВО", position="bottom",
                  scene=Scene(kind="video", src="data/itch/tree_upgrade.mp4", offset=2.0)),
            Chunk(words=(43, 46), kind="overlay",
                  text="15-20 МИНУТ", subtitle="ПОЛНОЕ ПРОХОЖДЕНИЕ", position="bottom",
                  scene=Scene(kind="video", src="data/trailer/trailer_final_30fps.mp4", offset=15.0)),
        ],
    ),

    "b4": Beat(
        title="30k строк + инфографика",
        face="pip",
        vo=("Тридцать тысяч строк кода. Двести семьдесят три коммита. Сто два файла. И всё это "
            "написал ИИ. Я говорил что делать, Клод делал."),
        stage='Инфографика: 30k LOC + 273 commits + treemap. На "всё это написал ИИ" — снижение тона, констатация.',
        audio="data/finalize/b4_audio_final.wav",
        words="data/finalize/b4_words.json",
        chunks=[
            Chunk(words=(0, 3), kind="overlay",
                  text="30 000 СТРОК", subtitle="ВЕСЬ ПРОЕКТ — ИИ", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/commits_chart_anim.mp4")),
            Chunk(words=(4, 5), kind="overlay",
                  text="273 КОММИТА", subtitle="ЗА 13 ДНЕЙ", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/commits_chart_anim.mp4")),
            Chunk(words=(6, 7), kind="overlay",
                  text="102 ФАЙЛА", subtitle="ТОП-10 ПО СТРОКАМ", position="bottom",
                  scene=Scene(kind="image", src="data/infographics/biggest_files.png")),
            Chunk(words=(8, 13), kind="overlay",
                  text="ВСЁ ЭТО — ИИ", subtitle="НИ ОДНОЙ СТРОКИ ВРУЧНУЮ", position="bottom",
                  scene=Scene(kind="image", src="data/itch/code_claude.png")),
            Chunk(words=(14, 18), kind="overlay",
                  text="Я ГОВОРИЛ — ОН ДЕЛАЛ", subtitle="CLAUDE CODE · WORKFLOW", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/workflow_diagram_anim.mp4")),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # ACT 2 — METHOD
    # ════════════════════════════════════════════════════════════════
    "a2-1": Beat(
        title="Эти примитивы — ИИ. Мой workflow",
        face="pip",
        vo=("Полгода я не пишу код руками. Claude Code пишет, я проверяю. Проверяю как код, так и "
            "тестирую результат. В этом проекте я вообще не смотрел на код. Это джем, времени было мало."),
        stage='На "Я проверяю" — снижение тона. На "вообще не смотрел на код" — честное признание, без оправданий.',
        audio="data/finalize/a2-1_audio_final.wav",
        words="data/finalize/a2-1_words.json",
        chunks=[
            Chunk(words=(0, 5), kind="overlay",
                  text="6 МЕСЯЦЕВ", subtitle="БЕЗ КОДА РУКАМИ", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/workflow_diagram_anim.mp4")),
            Chunk(words=(6, 10), kind="overlay",
                  text="CLAUDE CODE ПИШЕТ", subtitle="Я ПРОВЕРЯЮ", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/workflow_diagram_anim.mp4", offset=1.6)),
            Chunk(words=(11, 17), kind="overlay",
                  text="ПРОВЕРЯЮ КОД + РЕЗУЛЬТАТ", subtitle="ДВОЙНОЙ КОНТРОЛЬ", position="bottom",
                  scene=Scene(kind="image", src="data/itch/code_claude.png")),
            Chunk(words=(17, 26), kind="plate",
                  text="NO CODE REVIEW", size=200,
                  subtitle="ТОЛЬКО В ЭТОМ ДЖЕМЕ", subtitle_color=_GOLD_DIM,
                  red_underline=True, ken_burns=True,
                  bg_image="data/itch/snap_hell.png", bg_opacity=0.45),
            Chunk(words=(27, 31), kind="overlay",
                  text="13 ДНЕЙ", subtitle="ВРЕМЕНИ МАЛО", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/timeline_13days_anim.mp4")),
        ],
    ),

    "a2-2": Beat(
        title="Это инструмент — главный тезис",
        face="full",
        vo=("Вокруг ИИ много хайпа. С одной стороны — игра за один промпт. И да, что-то простое за "
            "один промпт сделать можно. Но не большую игру. С другой стороны — ИИ не умеет делать "
            "игры. И тут тоже есть правда — у многих не получается. Реальность проще: ИИ — это "
            "инструмент. Нужно уметь им пользоваться. И если умеешь — можно делать игры на полном "
            "ИИ-слопе. Даже большие. Даже долгие."),
        stage='Размеренно, без crusader-тона. Финал "Даже большие. Даже долгие." — отрубленно, как точки.',
        audio="data/finalize/a2-2_audio_final.wav",
        words="data/finalize/a2-2_words.json",
        chunks=[
            Chunk(words=(0, 14), kind="overlay",
                  text="ВОКРУГ ИИ — ХАЙП", subtitle="ЛОШАДЬ БЕЗ ТОРМОЗОВ", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/hype_curve_anim.mp4")),
            Chunk(words=(15, 25), kind="overlay",
                  text="ЗА ОДИН ПРОМПТ", subtitle="ДА — НО ТОЛЬКО МАЛЕНЬКОЕ", position="bottom",
                  scene=Scene(kind="image", src="data/ai_hype/ai_logos_grid.png")),
            Chunk(words=(26, 33), kind="overlay",
                  text="ИИ НЕ УМЕЕТ", subtitle="Théâtre D'Opéra Spatial · Midjourney, 2022", position="bottom",
                  scene=Scene(kind="image", src="data/ai_hype/ai_art_opera.jpg")),
            Chunk(words=(34, 42), kind="overlay",
                  text="НО ЭТО ТОЖЕ ПРАВДА", subtitle="Codex Mortis · один из удачных примеров", position="bottom",
                  scene=Scene(kind="image", src="data/ai_hype/codex_mortis.jpg")),
            Chunk(words=(43, 51), kind="plate",
                  text="РЕАЛЬНОСТЬ\nПРОЩЕ", size=320,
                  subtitle="ИИ — ЭТО ИНСТРУМЕНТ", subtitle_color=_GOLD_DIM,
                  red_underline=True, line_gap_ratio=0.04, ken_burns=True,
                  bg_image="data/itch/snap_suburbs.png", bg_opacity=0.32),
            Chunk(words=(52, 61), kind="overlay",
                  text="НУЖНО УМЕТЬ · МОЖНО ДЕЛАТЬ", subtitle="ИНСТРУМЕНТ В УМЕЛЫХ РУКАХ", position="bottom",
                  scene=Scene(kind="image", src="data/infographics/art_grid_cover.png")),
            Chunk(words=(62, 65), kind="plate",
                  text="ДАЖЕ БОЛЬШИЕ", size=380,
                  subtitle="ДАЖЕ ДОЛГИЕ ПРОЕКТЫ", subtitle_color=_GOLD_DIM,
                  red_underline=True,
                  bg_image="data/infographics/art_grid_cover.png", bg_opacity=0.25),
        ],
    ),

    "a2-3": Beat(
        title="Лошадь + 3 практики",
        face="pip",
        vo=("ИИ — это лошадь без тормозов. Тянет быстро, не устаёт. Но без кучера улетит в канаву. "
            "И вот что делает кучер. Первое — рамки. Заранее решить какая игра. Второе — "
            "декомпозиция. Маленькие задачи, понятные интерфейсы. Третье — все цифры баланса в "
            "отдельный файл. Этих трёх вещей хватает чтобы делать игры целиком на ИИ. Даже большие."),
        stage='⚠ FACE-PIP — читай НЕПРЕРЫВНО, точки только интонационные. Самый важный beat видео.',
        audio="data/finalize/a2-3_audio_final.wav",
        words="data/finalize/a2-3_words.json",
        scene=Scene(kind="image", src="data/itch/05_trolley_progression.png"),
        chunks=[
            Chunk(words=(0, 15), kind="overlay",
                  text="ЛОШАДЬ БЕЗ ТОРМОЗОВ", subtitle="БЫСТРО · БЕЗ КУЧЕРА — В КАНАВУ", position="bottom",
                  scene=Scene(kind="video", src="data/trailer/clean_gameplay.mp4", offset=2.0)),
            Chunk(words=(16, 32), kind="overlay",
                  text="1.  РАМКИ", subtitle="ЧТО В ИГРЕ ЕСТЬ", position="bottom",
                  scene=Scene(kind="image", src="data/itch/snap_village.png", ken_burns=True)),
            Chunk(words=(33, 50), kind="overlay",
                  text="2.  ДЕКОМПОЗИЦИЯ", subtitle="МАЛЕНЬКИЕ ЗАДАЧИ · ЧЁТКИЕ ИНТЕРФЕЙСЫ", position="bottom",
                  scene=Scene(kind="image", src="data/itch/snap_suburbs.png", ken_burns=True)),
            Chunk(words=(51, 75), kind="overlay",
                  text="3.  КОНФИГИ В ФАЙЛ", subtitle="БАЛАНС РУКАМИ — КОГДА НЕ НРАВИТСЯ", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/balance_scroll_anim.mp4")),
            Chunk(words=(75, 86), kind="plate",
                  text="1. РАМКИ\n2. ДЕКОМПОЗИЦИЯ\n3. БАЛАНС В ФАЙЛ", size=150,
                  subtitle="ТРЁХ ВЕЩЕЙ ХВАТАЕТ", subtitle_color=_GOLD_DIM,
                  red_underline=True, line_gap_ratio=0.04,
                  bg_image="data/itch/05_trolley_progression.png", bg_opacity=0.30),
        ],
    ),

    "a2-4": Beat(
        title="С графикой та же история",
        face="none",
        vo=("С графикой та же история. ИИ генерирует — я отбираю. Пятьдесят итераций обложки. "
            "Стиль не пришёл из одного промпта. Он вырос из выкидывания того, что не зашло."),
        stage='"ИИ генерирует — я отбираю" — парная контрастная фраза (не разбивать).',
        audio="data/finalize/a2-4_audio_final.wav",
        words="data/finalize/a2-4_words.json",
        scene=Scene(kind="image", src="data/itch/asset_sheet_promo.png"),
        chunks=[
            Chunk(words=(0, 7), kind="overlay",
                  text="С АРТОМ ТО ЖЕ", subtitle="ИИ ГЕНЕРИРУЕТ — Я ОТБИРАЮ", position="bottom"),
            Chunk(words=(8, 27), kind="plate",
                  text="50 ИТЕРАЦИЙ", size=320,
                  subtitle="ОДНОЙ ОБЛОЖКИ · ОТБОР, НЕ ПРОМПТ", subtitle_color=_GOLD_DIM,
                  sub_ratio=0.20, red_underline=True, ken_burns=True,
                  bg_image="data/itch/asset_sheet_promo.png", bg_opacity=0.50),
        ],
    ),

    "a2-5": Beat(
        title="Критика игроков — моя позиция",
        face="full",
        vo=("На itch были комментарии про ИИ. ИИ-арт видно. Игроки правы. Особенно на задних фонах. "
            "Но это прототип за тринадцать дней — ИИ-арт на фоне лучше, чем белый экран. "
            "В Steam-версии будет нормальный визуал."),
        stage='"ИИ-арт видно" — staccato, как цитата. "Игроки правы" — без иронии, серьёзно, прямой взгляд.',
        audio="data/finalize/a2-5_audio_final.wav",
        words="data/finalize/a2-5_words.json",
        chunks=[
            Chunk(words=(0, 10), kind="overlay",
                  text="«ИИ-АРТ ВИДНО»", subtitle="КОММЕНТАРИИ С itch", position="bottom",
                  scene=Scene(kind="video", src="data/itch/itch_comments_anim.mp4")),
            Chunk(words=(11, 16), kind="overlay",
                  text="ИГРОКИ ПРАВЫ", subtitle="ОСОБЕННО НА ФОНАХ", position="bottom",
                  scene=Scene(kind="image", src="data/itch/04_forest_world.png", ken_burns=True)),
            Chunk(words=(17, 31), kind="overlay",
                  text="ИИ-АРТ > БЕЛЫЙ ЭКРАН", subtitle="ПРОТОТИП ЗА 13 ДНЕЙ", position="bottom",
                  scene=Scene(kind="image", src="data/itch/snap_village_artshot.png")),
            Chunk(words=(32, 37), kind="overlay",
                  text="В STEAM ВЕРСИИ", subtitle="ВИЗУАЛ БУДЕТ НОРМАЛЬНЫМ", position="top",
                  scene=Scene(kind="image", src="data/itch/steam_page.png")),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # FINALE — merged a3-6 (submit teaser) + b10 (results reveal)
    # ════════════════════════════════════════════════════════════════
    "finale": Beat(
        title="Финал — 26 апреля + результаты",
        face="none",
        vo=("Двадцать шестое апреля. Последний день Gamedev.js. Загружено. А дальше — что я не "
            "ждал. Игроки пришли. Что игроки будут играть. И что им понравится. Тридцать тысяч "
            "просмотров. Топ-2 incremental на itch. На джеме — восемнадцатое место из четырёхсот "
            "восьмидесяти девяти игр. И как бонус — Wavedash Deploy Challenge. Первое место. "
            "Тысяча долларов. Спасибо всем кто играл и поддержал."),
        stage='Эмоциональное ядро — "что игроки будут играть и им понравится". Wavedash — бонус, без overhype.',
        audio="data/finalize/finale_audio_final.wav",
        words="data/finalize/finale_words.json",
        chunks=[
            # a3-6 portion: submit
            Chunk(words=(0, 6), kind="plate",
                  text="26 АПРЕЛЯ", size=280,
                  subtitle="ПОСЛЕДНИЙ ДЕНЬ GAMEDEV.JS · ЗАГРУЖЕНО", subtitle_color=_GOLD_DIM,
                  red_underline=True, ken_burns=True,
                  bg_image="data/itch/06_submission_wavedash.png", bg_opacity=0.35),
            # Daily-views chart spans words 7-24 (3 overlays, same scene src merges)
            Chunk(words=(7, 16), kind="overlay",
                  text="А ДАЛЬШЕ — ЧТО Я НЕ ЖДАЛ", subtitle="ИГРОКИ ПРИШЛИ", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/daily_views_anim.mp4")),
            Chunk(words=(17, 20), kind="overlay",
                  text="ЧТО ИГРОКИ БУДУТ ИГРАТЬ", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/daily_views_anim.mp4", offset=3.48)),
            Chunk(words=(21, 24), kind="overlay",
                  text="И ЧТО ИМ ПОНРАВИТСЯ", subtitle="ЭТО УДИВИЛО БОЛЬШЕ ВСЕГО", position="bottom",
                  scene=Scene(kind="video", src="data/infographics/daily_views_anim.mp4", offset=6.14)),
            # Results
            Chunk(words=(25, 27), kind="plate",
                  text="30 000", size=560,
                  subtitle="ПРОСМОТРОВ · ITCH", subtitle_color=_GOLD_DIM,
                  red_underline=True, ken_burns=True,
                  bg_image="data/itch/snap_city.png", bg_opacity=0.45),
            Chunk(words=(28, 32), kind="image",
                  src="data/itch/itch_top2_mobile_crop.jpg", fit="contain",
                  label="ТОП-2 INCREMENTAL · ITCH", ken_burns=True),
            Chunk(words=(33, 39), kind="image",
                  src="data/itch/jam_results_pc.png", fit="contain",
                  label="GAMEDEV.JS JAM · #18 / 489", ken_burns=True),
            Chunk(words=(40, 46), kind="image",
                  src="data/itch/wavedash_winners_pc.png", fit="contain",
                  label="БОНУС · WAVEDASH", label_style="branded", ken_burns=True),
            Chunk(words=(47, 50), kind="plate",
                  text="1-Е МЕСТО\n$1 000", size=360,
                  subtitle="WAVEDASH CHALLENGE", subtitle_color=_GOLD_DIM,
                  red_underline=True, line_gap_ratio=0.04,
                  bg_image="data/itch/snap_city.png", bg_opacity=0.28),
            Chunk(words=(51, 56), kind="plate",
                  text="СПАСИБО", size=380,
                  subtitle="ВСЕМ, КТО ПОДДЕРЖАЛ", subtitle_color=_GOLD_DIM,
                  red_underline=True,
                  bg_image="data/itch/snap_city.png", bg_opacity=0.35),
        ],
    ),

    # ════════════════════════════════════════════════════════════════
    # OUTRO — CTA + продолжение следует
    # ════════════════════════════════════════════════════════════════
    "outro": Beat(
        title="Аутро — Steam + TG + вишлист",
        face="full",
        vo=("Продолжаю делать игру, двигаюсь на Steam. Если интересно — подписывайтесь, ставьте "
            "лайки, пишите в комментариях. Читаю и отвечаю. Ещё есть Telegram, стараюсь писать "
            "там каждый день. И добавляйте игру в вишлист — ссылка в описании. "
            "История только начинается. Продолжение следует."),
        stage='Спокойно, прямо, в камеру. Финал — с лёгким подъёмом, финальная точка. 👀 ЛИЦО full-frame.',
        audio="data/finalize/outro_audio_final.wav",
        words="data/finalize/outro_words.json",
        chunks=[
            # Face video plays continuously — same-src merging keeps it seamless
            Chunk(words=(0, 5), kind="overlay",
                  text="NOT A TROLLEY PROBLEM", position="bottom",
                  scene=Scene(kind="video", src="data/finalize/outro_face_synced.mp4")),
            Chunk(words=(6, 16), kind="overlay",
                  text="ПОДПИСКА · ЛАЙК · КОММЕНТАРИИ", subtitle="ЧИТАЮ И ОТВЕЧАЮ", position="bottom",
                  scene=Scene(kind="video", src="data/finalize/outro_face_synced.mp4")),
            Chunk(words=(17, 25), kind="overlay",
                  text="@d954mas_make_games", subtitle="TELEGRAM · КАЖДЫЙ ДЕНЬ", position="bottom",
                  scene=Scene(kind="video", src="data/finalize/outro_face_synced.mp4")),
            Chunk(words=(26, 33), kind="image",
                  src="data/itch/steam_page.png", fit="contain",
                  label="ДОБАВИТЬ В ВИШЛИСТ · STEAM"),
            Chunk(words=(34, 38), kind="plate",
                  text="ПРОДОЛЖЕНИЕ\nСЛЕДУЕТ", size=300,
                  subtitle="ИСТОРИЯ ТОЛЬКО НАЧИНАЕТСЯ", subtitle_color=_GOLD_DIM,
                  red_underline=True, line_gap_ratio=0.04, ken_burns=True,
                  bg_image="data/itch/snap_metropolis.png", bg_opacity=0.35),
        ],
    ),
}


# ─── Concat order — defines what gets rendered into the final video ───
CONCAT_ORDER: list[str] = [
    "a0-1",
    "a1-1", "a1-2",
    "b3", "b4",
    "a2-1", "a2-2", "a2-3", "a2-4", "a2-5",
    "finale",
    "outro",
]


# ─── Output filename (relative to project root) ──────────────────
OUTPUT = "data/finalize/iter91.mp4"
