# Not a Trolley Problem — devlog 01 production brief

Дата подготовки: 2026-07-17
Статус: подготовка; landscape-проект и новый gameplay capture ещё не созданы.

## Результат и ограничения

- Один YouTube devlog длительностью 3–4 минуты, landscape 16:9.
- Total production budget: 2–3 часа.
- Личное время автора: 20–30 минут вместе с записью и финальным review.
- История, а не обзор четырёх инструментов.
- Один основной вариант speaking cards; не перекладывать редактуру обратно
  на автора пятью сценариями и десятью хуками.

## История

Обещание ролика:

> Джемовая 2D-версия доказала, что идея работает. Для Steam я начинаю игру
> заново в 3D. AI Studio помогает найти геймдизайн и визуальное направление,
> Neotolis Engine исполняет прототип, отдельный видео-агент собирает этот
> devlog, а Neotolis Diary должен показать, помогает ли регулярный контент
> вишлистам.

Рабочий хук:

> У этой игры уже есть страница в Steam. Только самой Steam-версии пока нет.
> Джемовый прототип неожиданно хорошо себя показал — и теперь я выбрасываю
> почти всё и начинаю заново.

Честная граница текущего прогресса:

- уже есть выбранное art direction, несколько типов 3D-персонажей, толпа,
  анимация, рельсы и красный трамвай;
- это визуальный прототип, не готовый gameplay loop;
- drag, upgrades и dilemma loop пока нельзя показывать как реализованные;
- центральный рычаг в текущей сцене — placeholder.

## Роли инструментов

| Инструмент | Что он делает в истории |
|---|---|
| AI Studio | помогает делать игру: геймдизайн, canvas, рефы, варианты стиля и ассетов |
| Neotolis Engine | запускает и рендерит текущую 3D-версию |
| Devlog Studio / видео-агент | готовит speaking cards, запись, монтаж, review и reflection |
| Neotolis Diary | связывает продвижение с постами, кликами и wishlist-графиком |

Инструмент появляется в кадре только когда решает конкретную проблему. Не
делать отдельный рекламный блок «вот мой стек».

## Готовые визуалы

| Блок | Источник | Решение |
|---|---|---|
| старая 2D-игра | `trolley/data/trailer/clean_gameplay.mp4`, 1920×1080, ~34 с | использовать как главное доказательство старой версии |
| старый готовый devlog | `trolley/data/finalize/iter91.mp4`, 1920×1080, ~247 с | брать только короткие архивные фрагменты при необходимости |
| Canvas tour | `trolley3d/data/footage/canvas_tour.mp4`, ~22 с | готовый tour, но вертикальный; помещать в landscape-макет, не растягивать |
| Canvas short | `trolley3d/data/footage/canvas_beat.mp4`, ~9 с | быстрый фрагмент выбора направления |
| выбранный fake shot | `trolley3d/data/images/canvas/fake_a.png` | показать как цель, а не как готовый арт игры |
| варианты и probes | `trolley3d/data/images/canvas/fake_b.png`, `fake_c.png`, `probe_1.png`, `probe_2.png`, `probe_ui.png` | монтаж «поиск → отбор»; B/C отвергнуты, gold probe не принят |
| старый 3D capture | `trolley3d/data/footage/game.mp4`, `walker.mp4` | использовать только как fallback: они уже старее последних моделей |
| Diary | `neotolis_diary/data/screens/real_prod_new/` и `data/screens/prod_20260604_wishlist_graphs/tabs/` | показать реальный feed и wishlist-график; выбрать 2–3 кадра, не UI-tour |

Canvas source of truth:

```text
C:\projects\game-67-idle\games\private\game-not-a-trolley-problem\.ai_studio\canvas\projects\style-search-refs-moodboard-fake-shots-656919
```

В Canvas 33 элемента и 9 групп: старая игра, KIDS/The Trolley Solution refs,
три fake-shot направления, crowd/UI probes. Принято направление Fake Shot A:
строгий монохромный hand-drawn 3D, белые безликие фигурки и красный трамвай.
Сторонние рефы показывать как исследование, не как собственный финальный арт.

## Новый landscape capture

Точная игра:

```text
C:\projects\game-67-idle\games\private\game-not-a-trolley-problem
```

Перед захватом пересобрать DevAPI build: найденный `game.exe` был собран до
последнего исправления тяжёлых персонажей.

```powershell
cmake --build build/devapi-debug --target game
.\build\devapi-debug\bin\game.exe --devapi 17890 --window-size 1920x1080 --fresh-state --disable-autosave
```

Готовый `trolley3d/scripts/capture_gameplay.py` сейчас жёстко настроен на
portrait. Для этого devlog нужен отдельный landscape profile и новые output
имена; нельзя перезаписывать материалы рилса.

Снять только четыре коротких клипа:

1. `walker` — один новый персонаж, orbit/zoom, 5–6 секунд.
2. `crowd` — 400 персонажей, 5–6 секунд.
3. `game` — толпа, рельсы и красный трамвай, 8–10 секунд.
4. `game` close/detail — столкновения или смена крупности, 5–6 секунд.

Технические ограничения capture:

- не переключать повторно на `game` клавишей `3`: возможна повторная
  инициализация pinned pack;
- debug build показывает perf overlay и testbed UI; для чистого footage
  использовать DevAPI build с `GAME_TESTBED=OFF` либо аккуратный clean crop,
  который не скрывает состояние игры;
- плотный кадр даёт крупный payload — использовать имеющийся `FastFile`;
- в manual mode посылать `capture.frame`, затем `time.step` одной парой;
- 12 секунд PNG-последовательности могут занять около 427 МБ, поэтому не
  снимать длинные дубли.

## Производственный таймбокс

| Этап | Агентское / wall time | Время автора |
|---|---:|---:|
| inventory, speaking cards, scratch timing | 25–40 мин | 0–5 мин |
| запись 6–8 карточек отдельными takes | параллельная подготовка | 12–16 мин |
| capture + монтаж + preview | 60–90 мин | 0 мин |
| blind review + safe fixes | 20–30 мин | 0 мин |
| один просмотр draft и решение | — | 8–12 мин |

Если нужен второй полный VO-проход, production budget уже нарушен: остановиться
и назвать конкретный beat для перезаписи вместо начала сначала.

## Review, reflection и измерение результата

До final: `dl2 preview`, contact sheet/keyframes, blind `video-reviewer`, затем
только safe fixes. После готового run: один `devlog-reflector`, timestamped
report в `data/review/reflections/`, сравнение с 2–3 часами total и 20–30
минутами автора, максимум три улучшения и один эксперимент следующего ролика.

Через 48 часов и 7 дней отдельно сравнить YouTube retention/CTR/engagement с
событиями и wishlist-графиком Neotolis Diary. Быстрый монтаж сам по себе не
доказывает, что ролик помог игре.
