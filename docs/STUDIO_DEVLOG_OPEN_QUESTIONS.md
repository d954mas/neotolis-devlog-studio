# Studio devlog production — вопросы и решения на потом

**Дата начала:** 2026-07-24
**Правило:** вопросы из этого файла не блокируют безопасную работу над текущим
milestone. Вопрос поднимается пользователю только перед решением, которое
существенно меняет продукт или итоговый workflow.

## Не блокируют Milestone A

1. Нужен ли в Milestone B отдельный transcript UI, или достаточно
   agent/CLI-операций, которые компилируются обратно в `beats.py`?
2. Нужен ли после Milestone C optional round-trip в Premiere/Resolve, или
   Studio должна всегда выдавать только готовый render?
3. Какие post-publish источники считать основными для Milestone D:
   YouTube retention/CTR, Steam wishlist clicks или ручной журнал?
4. Должен ли visual brand preset быть общим для всех devlogs или отдельным для
   каждого проекта?
5. Какой game-owned endpoint должен выдавать semantic gameplay state proof:
   отдельный `game.capture.proof` или canonical hash выбранных
   `game.state.get`/UI/time-mode фактов?
6. Может ли игра отдавать нормализованный `focus_rect`/subject center для
   canonical capture states, или anchor всегда остаётся ручным?
7. Где должен жить day/story identity для правила source-density:
   в Beat metadata, shot manifest или отдельном story plan?

## Принятые безопасные допущения

1. `beats.py` и IR остаются source of truth.
2. Gameplay capture остаётся внешним процессом, но Studio владеет request,
   validation, ingest и approval.
3. Deterministic DevAPI capture разрешён для debug proof/presentation, но не
   как editorial gameplay.
4. Неправильный state, speed, method, resolution или недостаточные handles
   требуют recapture, а не маскировки в монтаже.
5. Milestone A сначала доказывается на одном реальном дне/beat, затем
   расширяется на полный devlog.
6. Build identity берётся из SHA реально запущенного executable, а не из
   branch/filename или аргумента capture-агента.
