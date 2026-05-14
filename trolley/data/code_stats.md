# Кодовая база: что и где

Полный инвентарь `src/` для визуализации в девлоге.

## Тоталы
- **30 778 строк JS**
- **102 JS-файла** в `src/features/`
- **+ 8 ассет-файлов и тестовые сцены отдельно**

## По областям (где живёт код)

| Область | Файлов | Строк | % | Назначение |
|---|---:|---:|---:|---|
| `ui/` | 18 | **8 630** | 28% | HUD, панели, модалки, choice-cards, settings — самая большая зона |
| `core/` | 47 | **6 719** | 22% | Engine, ECS, audio, input, layout, platform — переиспользуемый шаблон |
| `data/` | 13 | 2 674 | 9% | Balance, choices, locations, upgrade tree, NPC tiers |
| `render/` | 19 | 2 632 | 9% | Pixi-рендеры, текстур-кеши, decor, paths |
| `systems/` | 16 | 1 806 | 6% | ECS-системы (boss, collision, finger, hand-grab, motion) |
| `entities/` | 6 | 392 | 1% | NPC + boss spawn helpers |
| `audio/` (game) | 0 | 0 | — | Аудио всё в `core/audio/` |
| **Прочее** (scenes, effects.js, game.js, save.js) | — | ~8 000 | 26% | Корневые файлы game.js, effects.js, save.js + testbeds |

## Top-10 самых жирных файлов

| # | Файл | Строк | Что это |
|---:|---|---:|---|
| 1 | `scenes/GameScene.js` | **2 872** | Главная игровая сцена — оркестратор всех систем |
| 2 | `ui/TrolleyChoiceModal.js` | **2 347** | Выбор-карточки (Шрёдингер / Truck-kun / etc) — 10 сценариев |
| 3 | `ui/UpgradesPanel.js` | 1 217 | Апгрейд-дерево с 9 ветками, 196 уровнями |
| 4 | `ui/TrolleyJournal.js` | 1 040 | Журнал выборов с возможностью пересмотреть |
| 5 | `ui/Onboarding.js` | 775 | Туториал с подсказками |
| 6 | `scenes/character_world_test/CharacterWorldTestScene.js` | 735 | Тестовая сцена (не в проде) |
| 7 | `scenes/character_world_test/Character3D.js` | 731 | 3D-эксперимент с персонажами |
| 8 | `trailer/TrailerOverlay.js` | 546 | Оверлей для 20-сек трейлера |
| 9 | `effects.js` | 525 | Recalc effects: applies upgrade tree to gameplay state |
| 10 | `game.js` | 524 | Точка входа: boot Engine + assets + audio + scene |

## Что в `core/` (шаблон для будущих игр)

| Подпапка | Файлов | Строк | Назначение |
|---|---:|---:|---|
| `graphics/` | 9 | 1 036 | Графические утилиты, baked sprites helpers |
| `ui/` | 4 | 1 031 | Базовые UI-компоненты (panels, buttons) |
| `platform/` | 5 | 987 | Adapters для itch / poki / playgama / wavedash |
| `effects/` | 3 | 540 | Глобальные эффекты, particles |
| `audio/` | 1 | 505 | Audio system (WebAudio + ogg) |
| `debug/` | 4 | 403 | Debug tools |
| `systems/` | 2 | 344 | Core ECS systems |
| `storage/` | 2 | 217 | Save/load с версионированием |
| `loc/` | 1 | 164 | Localization RU/EN |
| `layout/` | 4 | 261 | Responsive layout (portrait/landscape) |
| `ecs/` | 1 | 173 | World class |
| `input/` | 1 | 131 | Touch + mouse |
| `camera/` | 1 | 124 | Camera utilities |

## Топ-5 ECS-систем

| Система | Строк | Что делает |
|---|---:|---|
| `HandGrabSystem.js` | 267 | Sticky finger + auto-grab hands — ядро механики |
| `BossSystem.js` | 251 | Skull-cycle босс, HP scaling, milestone events |
| `FingerSystem.js` | 217 | Логика "пальца" игрока (захват/перенос NPC) |
| `CollisionSystem.js` | 203 | Trolley × NPC, blade hits, kill events |
| `SpawnerSystem.js` | 150 | Респавн NPC по тирам, density curve |

## Что AI и я делали в каждой области

| Область | AI делал | Я делал |
|---|---|---|
| `core/` | Весь код Engine, ECS, audio, save, loc | Архитектурные решения (что в core vs feature) |
| `data/balance.js`, `upgradeBalance.js` | Писал таблицы коэффициентов | Pillars, ограничения (idle-first, finite, no prestige) |
| `data/trolleyChoices.js` | Писал 10 диалогов EN/RU | Идеи дилемм (Шрёдингер, Truck-kun, тёща) |
| `ui/TrolleyChoiceModal.js` | Весь Pixi-код модалки | Дизайн поведения (swap, revisit, journal) |
| `systems/BossSystem.js` | Реализация skull-cycle | Решение что таймер не работает в idle |
| Графика (covers, NPCs) | Генерировал варианты | Выбирал, отвергал, направлял стиль |
