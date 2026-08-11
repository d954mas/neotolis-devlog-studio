---
created: 2026-08-11T17:05:43.562Z
title: Добавить виртуальный палец для записи видео
area: tooling
files:
  - not_a_trolley_problem/reels/2026_08_11_tutorial_gameplay_reel/tools/capture_tutorial_gameplay.py:188
  - C:/projects/game-67-idle/games/private/game-not-a-trolley-problem/src/game_input.h:34
  - C:/projects/game-67-idle/games/private/game-not-a-trolley-problem/src/render/game_render_pipeline.c:249
---

## Problem

При автоматической записи игрового видео реальные DevAPI-жесты управляют игрой,
но не имеют понятного зрителю визуального указателя. Монтажный PNG-палец оказался
визуально плохим и потребовал ручной синхронизации после записи. Нужен штатный,
детерминированный capture/demo-режим, который отображает фактический primary
pointer поверх игры и поэтому всегда совпадает с записываемым вводом.

Режим не должен быть debug UI, не должен появляться в обычной игре и не должен
менять gameplay input. Он включается только явно для маркетинговой записи.

## Solution

- Добавить off-by-default capture/demo touch-indicator поверх финального game
  render pipeline.
- Читать реальные координаты primary pointer из `game_input_frame_t`, включая
  источник mouse/touch и состояние кнопки.
- Поддержать визуальные состояния `move`, `press`, `drag`, `release`; положение
  кончика пальца должно совпадать с точкой фактического ввода.
- Использовать штатный игровой арт и отдельные open/grip состояния вместо
  системного курсора или debug-маркера.
- Экспонировать явное управление режимом через существующий capture/DevAPI путь,
  чтобы бот записи мог включить его перед сценой и выключить после неё.
- Сделать вывод seek/determinism-friendly: одинаковая последовательность input
  frames должна давать одинаковые позиции и состояния индикатора.
- Добавить тесты на преобразование координат, переходы press/drag/release,
  выключенное по умолчанию состояние и отсутствие индикатора в production run.
