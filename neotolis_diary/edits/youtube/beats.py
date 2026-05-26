"""Neotolis Diary short devlog.

Starter edit for a 1-2 minute progress update about the promotion diary:
old production UI, new v2 visual direction, Reddit/YouTube sources, and the
open-source project history.
"""
from devlog.types import Beat, Chunk, Scene
from neotolis_diary.shared.palette import NEOTOLIS_DIARY_PALETTE as _PAL


_GOLD_DIM = _PAL.gold_dim
_MOTION_PACK = "data/infographics/neotolis_motion_pack.mp4"


BEATS: dict[str, Beat] = {
    "b01": Beat(
        title="Hook: зачем дневник продвижения",
        vo=(
            "Когда продвигаешь игру, легко обмануться: вроде я что-то делал. "
            "А через неделю уже не помнишь: что именно, сколько раз, и был ли от этого эффект. "
            "Мне не хотелось держать это в голове или в таблице, поэтому я сделал маленький дневник продвижения для игры."
        ),
        stage="Разговорно, как вступление в ролик. Не продавать, а объяснить личную боль.",
        audio="data/finalize/b01_audio_tight_pause.wav",
        words="data/finalize/b01_words_tight_pause.json",
        chunks=[
            Chunk(words=(0, 9), kind="overlay",
                  text="Я ЖЕ ЧТО-ТО ДЕЛАЛ", size=230,
                  subtitle="НО ЧТО ИМЕННО? СКОЛЬКО? И ЧТО СРАБОТАЛО?",
                  style="hero",
                  scene=Scene(kind="image", src="data/screens/real_prod/feed_01_top.png", ken_burns=True)),
            Chunk(words=(10, 25), kind="overlay",
                  text="ЧТО ИМЕННО?",
                  subtitle="СКОЛЬКО РАЗ? И БЫЛ ЛИ ЭФФЕКТ?",
                  position="bottom",
                  scene=Scene(kind="image", src="data/screens/real_prod/feed_02_scroll.png")),
            Chunk(words=(26, 43), kind="image",
                  src="data/screens/real_prod_new/feed_01_top.png",
                  ken_burns=True),
        ],
        face="none",
    ),

    "b02": Beat(
        title="Что это за сайт",
        vo=(
            "Это Neotolis Diary. Сюда я складываю все действия по продвижению игры: посты, ролики, комментарии, эксперименты. "
            "Туда же можно добавить внешние события: обзор, прессу, чужой Reddit-пост, любую ссылку. "
            "В итоге получается лента по датам: открываешь игру и видишь, что с ней происходило."
        ),
        stage="Как показываешь свой инструмент зрителю, без рекламного тона.",
        audio="data/finalize/b02_audio_tight_pause.wav",
        words="data/finalize/b02_words_tight_pause.json",
        chunks=[
            Chunk(words=(0, 15), kind="overlay",
                  text="NEOTOLIS DIARY", size=220,
                  subtitle="ЛЕНТА ДЛЯ СЕЛФ-МАРКЕТИНГА ИГРЫ",
                  position="bottom", style="hero",
                  scene=Scene(kind="image", src="data/screens/real_prod_new/feed_01_top.png", ken_burns=True)),
            Chunk(words=(16, 28), kind="overlay",
                  text="МОЖНО ДОБАВИТЬ ВНЕШНИЕ СОБЫТИЯ",
                  subtitle="ОБЗОР · ПРЕССА · REDDIT · ЛЮБАЯ ССЫЛКА",
                  position="bottom",
                  scene=Scene(kind="image", src="data/screens/real_prod_new/add_event.png")),
            Chunk(words=(29, 42), kind="overlay",
                  text="ЛЕНТА ПО ДАТАМ",
                  subtitle="ОТКРЫВАЕШЬ И ВИДИШЬ, ЧТО ПРОИСХОДИЛО",
                  position="bottom",
                  scene=Scene(kind="image", src="data/screens/real_prod_new/feed_02_scroll.png")),
        ],
        face="none",
    ),

    "b03": Beat(
        title="Старый визуал и новый прод",
        vo=(
            "Раньше на проде был старый вид: работало, но ощущалось как внутренняя штука для себя. "
            "Сейчас я залил новый дизайн. Он все еще простой, но уже выглядит как инструмент, "
            "который не стыдно открывать каждый день."
        ),
        stage="Контраст было-стало. Сначала спокойно признать старый вид, потом показать обновление как прогресс.",
        audio="data/finalize/b03_audio_tight_pause.wav",
        words="data/finalize/b03_words_tight_pause.json",
        chunks=[
            Chunk(words=(0, 13), kind="overlay",
                  text="ДО ОБНОВЛЕНИЯ",
                  subtitle="РАБОЧИЙ, НО ЕЩЕ СЫРОЙ UI",
                  position="bottom",
                  scene=Scene(kind="image", src="data/screens/real_prod/feed_01_top.png")),
            Chunk(words=(14, 33), kind="video",
                  src=_MOTION_PACK, offset=16.0),
        ],
        face="none",
    ),

    "b04": Beat(
        title="Reddit и YouTube",
        vo=(
            "События можно добавлять руками: например, если вышел обзор или кто-то упомянул игру. "
            "А можно подключить источники. Я уже подключил YouTube и Reddit, и новые ролики или посты сами попадают в ленту. "
            "Плюс к ним подтягиваются просмотры, лайки, комментарии и ответы. Уже видно не просто ссылку, а реакцию."
        ),
        stage="Живее, как демо конкретных фич. Не перечислять слишком сухо.",
        audio="data/finalize/b04_audio_tight_pause.wav",
        words="data/finalize/b04_words_tight_pause.json",
        chunks=[
            Chunk(words=(0, 12), kind="overlay",
                  text="МОЖНО ДОБАВЛЯТЬ РУКАМИ",
                  subtitle="ОБЗОР · УПОМИНАНИЕ · ЛЮБАЯ ССЫЛКА",
                  position="bottom",
                  scene=Scene(kind="image", src="data/screens/real_prod_new/add_event.png")),
            Chunk(words=(13, 16), kind="overlay",
                  text="ПОДКЛЮЧАЕШЬ ИСТОЧНИКИ",
                  subtitle="НЕ ТОЛЬКО РУЧНОЙ ВВОД",
                  position="bottom",
                  scene=Scene(kind="image", src="data/screens/real_prod_new/sources.png")),
            Chunk(words=(17, 31), kind="video",
                  src=_MOTION_PACK, offset=32.0),
            Chunk(words=(32, 40), kind="video",
                  src=_MOTION_PACK, offset=48.0),
            Chunk(words=(41, 47), kind="overlay",
                  text="УЖЕ ВИДНО РЕАКЦИЮ",
                  subtitle="НЕ ПРОСТО ССЫЛКА",
                  position="bottom",
                  scene=Scene(kind="image", src="data/screens/real_prod_new/feed_02_scroll.png")),
        ],
        face="none",
    ),

    "b05": Beat(
        title="История и исходники",
        vo=(
            "И это не закрытый сервис только для меня. Проект открытый, исходники публичные, лицензия MIT. "
            "Можно пользоваться моей версией на neotolis-diary.dev, а можно поднять свою, если хочется хранить данные у себя."
        ),
        stage="Сухая инженерная конкретика. Не превращать в техдоклад.",
        audio="data/finalize/b05_audio_tight_pause.wav",
        words="data/finalize/b05_words_tight_pause.json",
        chunks=[
            Chunk(words=(0, 13), kind="overlay",
                  text="OPEN SOURCE · MIT", size=250,
                  subtitle="ПУБЛИЧНЫЕ ИСХОДНИКИ",
                  position="top",
                  scene=Scene(kind="image", src="data/screens/github_repo.png", ken_burns=True)),
            Chunk(words=(14, 18), kind="overlay",
                  text="МОЖНО ПОЛЬЗОВАТЬСЯ\nМОЕЙ ВЕРСИЕЙ", size=155,
                  subtitle="NEOTOLIS-DIARY.DEV",
                  position="middle", style="hero",
                  scene=Scene(kind="image", src="data/screens/real_prod_new/feed_01_top.png", ken_burns=True)),
            Chunk(words=(19, 28), kind="overlay",
                  text="МОЖНО ПОДНЯТЬ СВОЮ КОПИЮ",
                  subtitle="ЕСЛИ ХОЧЕТСЯ ДЕРЖАТЬ ДАННЫЕ У СЕБЯ",
                  position="bottom",
                  scene=Scene(kind="image", src="data/screens/github_repo.png")),
        ],
        face="none",
    ),

    "b06": Beat(
        title="Зачем это дальше",
        vo=(
            "Дальше хочу свести это с результатами: посты, ролики и обсуждения — рядом с просмотрами, реакциями и вишлистами. "
            "Чтобы видеть не просто: я что-то делал. А после каких действий реально что-то менялось."
        ),
        stage="Финал как личный вывод, без пафоса.",
        audio="data/finalize/b06_audio_tight_pause.wav",
        words="data/finalize/b06_words_tight_pause.json",
        chunks=[
            Chunk(words=(0, 16), kind="video",
                  src=_MOTION_PACK, offset=64.0),
            Chunk(words=(17, 23), kind="overlay",
                  text="ЧТО СДЕЛАЛ → ЧТО ИЗМЕНИЛОСЬ",
                  subtitle="ДЕЙСТВИЯ И РЕЗУЛЬТАТЫ РЯДОМ",
                  position="bottom",
                  scene=Scene(kind="image", src="data/screens/real_prod_new/feed_02_scroll.png")),
            Chunk(words=(24, 29), kind="overlay",
                  text="НЕ ОЩУЩЕНИЯ В ГОЛОВЕ", size=190,
                  subtitle="А ПОНИМАНИЕ, ЧТО СРАБОТАЛО",
                  position="middle", style="hero",
                  scene=Scene(kind="image", src="data/screens/real_prod_new/feed_02_scroll.png", ken_burns=True)),
        ],
        face="none",
    ),
}

CONCAT_ORDER: list[str] = ["b01", "b02", "b03", "b04", "b05", "b06"]
OUTPUT = "data/finalize/neotolis_diary_iter01.mp4"
