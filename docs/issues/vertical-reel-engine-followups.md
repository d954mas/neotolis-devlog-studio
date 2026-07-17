# Engine follow-ups из рефлексии trolley3d r01 (2026-07-17)

Источник: разбор devlog-reflector после первого рилса серии trolley3d.
Правила/чек-листы уже зафиксированы (docs/CHECKLIST_VERTICAL_REEL.md,
common/quality/VQ-SAFE.md, VQ-RES.md, AGENTS.md, skill dl-make-video).
Ниже — движковые изменения, которые убирают корень проблем из дефолтов.
Маршрут: deep-reasoner/fast-worker + `dl2 verify --changed`.

## 1. Orientation-aware дефолт позиции band-оверлея (средний)

`common/dlstudio/src/dlstudio/render/raster/_content.py:209-210` —
`position=="bottom"` кладёт плашку в `H - box_h - design.px(78)` (~44px от
низа на 1080-ширине) — внутри unsafe-зоны Instagram. Для portrait-резолюций
дефолт должен целиться в `y_ratio≈0.74` (зона субтитров 0.66–0.78), а не в
фикс-отступ от края. Плюс regression-тест.

## 2. Шаблон нового vertical-проекта стартует безопасно (малый)

`common/dlstudio/src/dlstudio/cli/newvideo.py` (`--format vertical`) меняет
только `RESOLUTION`; шаблонные `template/{design,beats}.py` не задают
`position`/`y_ratio` вовсе. Добавить в шаблон orientation-aware пример
(band с `y_ratio=0.73` + комментарий о платформенных зонах).

## 3. Дефолт CaptionStyle.y_ratio (малый)

`common/dlstudio/src/dlstudio/model/design.py:59` — дефолт `0.78` на самой
верхней границе безопасного диапазона. Сдвинуть к `0.74`.

## 4. `dl2 publish --platform reel` (средний)

`common/dlstudio/src/dlstudio/cli/__init__.py:813` — publish умеет только
YouTube-пакет. Добавить путь для Reels/TikTok/Shorts: caption + hashtags +
attribution (CC-BY музыка) в `data/publish/reel_caption.md`, чтобы
атрибуция персистилась автоматически (в r01 делали вручную).

## 5. (другой репозиторий) devapi_client побайтовое чтение сокета

`game-67-idle/ai_studio/runtime_automation/devapi_client.py` — уже
тикетнуто как T0440 в таскборде game-67-idle; здесь для полноты.
