# Отчёт: этапы 0–2 плана PLAN_STUDIO_V2 (ночной прогон 2026-07-16/17)

Исполнение: автономно, по docs/PLAN_STUDIO_V2.md. Все коммиты локальные
(main, не пушились). Тестовая suite выросла с 493 до 590+ тестов, зелёная.

---

## Этап 0 — 12 опасных дефектов: ЗАВЕРШЁН

Порядок и состав блоков — строго по «Порядку реализации этапа 0».
Каждый блок — отдельный коммит; каждый фикс начинался с regression-теста
на реальном поведении путей.

| Блок | Коммит | Дефекты | Суть |
|---|---|---|---|
| 1 | `599c66a` | 0.3, 0.12 | `--no-cache` больше не падает SameFileError (копия только при source≠dest); все text-mode subprocess-вызовы движка закреплены на `encoding="utf-8", errors="replace"` + AST-тест `test_subprocess_encoding.py`, запрещающий регресс во всём пакете |
| 2 | `38a52a2` | 0.1, 0.2, 0.6, 0.10 | **Один** bump формата кэша (`ENTRY_FORMAT_VERSION=2`): запись кэша = пара MP4+VO-stem (публикуются и восстанавливаются вместе, MP4-only не публикуется); `--stale` всегда материализует точный артефакт кэша поверх файла на диске; профили разрешений едины и orientation-aware (vertical 4k = 2160×3840, webui шлёт имя профиля `"540p"` вместо своих пикселей); файлы шрифтов (main/bold/accent) вошли в identity-хэш ключа, процессный font-кэш инвалидируется по (path, size, mtime+size) |
| 3 | `1958eb0` | 0.5, 0.11 | `verify_output` проверяет наличие video- И audio-стрима и длительность КАЖДОГО стрима против ожидаемой (контрпример video=1s/audio=3s/container=3s — падает, закреплено real-ffmpeg тестом); шрифты валидируются на загружаемость (probe: readable=False → ошибка VQ-ASSET; render: существующий-но-битый TTF = громкая ошибка, не bitmap-фолбэк) |
| 4 | `76eebe2` | 0.4 | `gate_pre_render_checks` — обязательный гейт перед compose/iter/render/final и API-рендером; checks идут по effective timeline (design после resize); ошибки блокируют на любом качестве, warnings — нет |
| 5 | `b271f7d` | 0.7, 0.9 | tmp-имена кэша получили nonce (PID-only коллидировал в ThreadPool API); render-джобы одного beat сериализуются per-beat lock'ом вокруг всей последовательности compile→cache→render→publish (второй джоб получает cache hit — закреплено тестом «ровно один рендер»); process-take под тем же lock'ом + atomic promotion (temp + `os.replace` обоих файлов только после успеха обеих стадий); рекордер webui: beat id пиннится в момент старта записи, смена бита/вкладки останавливает и СОХРАНЯЕТ запись в исходный beat |
| 6 | `4429af2` | 0.8 | Обязательный CI-job `dlstudio`: py3.12 + ffmpeg + вся suite (включая real-ffmpeg E2E) + Node 22 webui typecheck/build |

Дополнительно (найдено ночью, вне списка 12):
- `cec981c` — гонка `safe_join` на Windows: при параллельном создании/удалении
  каталогов `Path.resolve()` транзиентно возвращает `\\?\`-форму (или путь через
  NTFS `$Extend\$Deleted`), containment-проверка отвергала СОБСТВЕННЫЕ пути
  бита → флаки-ошибки джобов. Канонизация префикса + один повтор.
  Воспроизведено standalone-скриптом, traversal-защита не тронута (закреплено).

### Заменённые тесты (закрепляли дефектное поведение — предусмотрено приёмкой)

- `test_cmd_iter_stale_skips_restore_when_file_already_present` →
  `test_cmd_iter_stale_replaces_existing_file_with_cache_artifact` (0.1).
- No-cache моки `render_beat` с выдуманными именами файлов →
  `_realistic_fake_render_beat` (пишет `workdir/<beat>.mp4`, как настоящий) (0.3).
- `test_font_kind_not_probed_readable_undetermined` →
  `test_font_corrupt_file_readable_false` (0.11).
- Ассерты `test_process_take_job_lifecycle` (прямая запись в финальные пути) →
  temp+promote семантика (0.7).
- Фикстуры с мусорными `font.ttf` → реальный системный шрифт
  (`tests/_builders.find_system_font`), т.к. 0.11 валидирует загружаемость.

### Приёмка этапа 0 — пройдена

- Вся suite зелёная (после обновления тестов), новые regression-тесты зелёные.
- `--stale` не смешивает разрешения; кэш не смешивает MP4 и stem; `--no-cache`
  работает; рассинхрон audio/video отклоняется; вертикальный final = 1080×1920;
  два take не повреждают beat; два параллельных API-рендера не отравляют кэш;
  замена шрифта инвалидирует кэш, битый шрифт = ошибка check.
- **Real-FFmpeg smoke в папке с кириллицей и пробелом** («тест проект»):
  `check → iter (draft) → render 360p → final upload (двухпроходный loudnorm —
  место старого краша 0.12) → iter --stale` — все rc=0, mix-путь с музыкой,
  ducking и SFX, `verify_output` зелёный. Скрипт: `smoke_stage0.py` (scratchpad).

---

## Этап 1 — рабочий v2-шаблон: ЗАВЕРШЁН

| Пункт | Коммит | Что сделано |
|---|---|---|
| 1.1 + 1.2 | `3a40371` | Пакетный шаблон `dlstudio/template` (`__init__.py` c module-level EDIT + `beats.py` + `design.py` — конвенция loader'а/hot-reload, `edit.py` не вводился) с примерами Plate/Overlay/ImageShot/VideoShot/Scene/музыки/SFX/переходов/scratch-VO/инфографики; `dl2 new-video <project> --format landscape|vertical` копирует шаблон, создаёт data/-дерево, для vertical переписывает `RESOLUTION = (1080, 1920)` (поле формата не вводилось — ориентация это Design.resolution) |
| 1.3 | `8d61ef9` | `dl2 preview <edit>`: гейт checks → `iter --stale` 540p draft → полная сборка → `data/review/contact_sheet.jpg` (fps-сэмплинг + tile 4×4) → `data/review/keyframes/kf_NN.jpg` (8 шт., чистка stale-кадров). Реализация — ffmpeg-пассы по готовому MP4 (`services/review.py`), без связи с render-пайплайном |
| 1.4 | — | Путь scratch-VO подтверждён рабочим как есть (`scratch-tts` → `transcribe` → агент правит beats.py); описан в quickstart |
| 1.5 | `a5b35b9` | Порт HyperFrames-моста: `services/hyperframes.py` (`init_project`/`render_html`, `NODE_OPTIONS=--use-system-ca` сохранён, utf-8 subprocess) + `dl2 gen-html <dir> --init | --out ... --quality draft|final`; конвенции `data/hyperframes/<asset>/` → `data/infographics/<asset>.mp4`; 32 теста без Node |
| 1.6 | `9a0969a` | Caption-примитив: `Beat.subtitles=True` → compile группирует words во фразы (пауза >0.6s / 34 символа; фраза держится до начала следующей) → `IRBeat.captions` → render рисует их поверх всех overlay'ев (перенос строк, подложка-pill, нижняя safe-zone; стиль `Design.captions`). Караоке-подсветка не делалась (по плану опциональна). Субтитры входят в IR → ключ кэша меняется при их изменении |
| 1.7 | `51a1fb4` | `docs/QUICKSTART_V2.md` — одна страница полного draft-пути, только v2-команды, таблица путей вывода |

### Приёмка этапа 1 — механическая часть пройдена

Smoke (`smoke_stage1.py`, workspace «проект один» с кириллицей и пробелом):
`dl2 new-video --format vertical` → минимальный beats.py с `subtitles=True` →
`dl2 check` (0 ошибок) → `dl2 preview`: `final.mp4` (304×540 — вертикальный
draft-профиль), `contact_sheet.jpg`, 8 keyframes — всё существует, verify
зелёный. HyperFrames: `--init` + **реальный** `npx hyperframes`-рендер на пути
«хф тест/демо график» → валидный MP4. Полная приёмка «свежий чат проходит
workflow сам» — за пользователем (см. промпт в конце).

---

## Этап 2 — agents и skills под v2: ЗАВЕРШЁН

| Пункт | Коммит | Что сделано |
|---|---|---|
| 2.1–2.4 | `c4de198` | Канонический skill `dl-make-video` (.claude/skills/): workflow §2.1 из 17 шагов на реальных dl2-командах, списки «продолжай сам»/«остановись и спроси» (§2.2/§2.3 полностью), шаблон запроса footage (§2.4 дословно), дисциплина stale-feedback, таблица делегирования 7 агентам, бюджеты из §9 |
| 2.5 | `cfb91e5` | AGENTS.md переписан под v2 (198 строк, одна карантинная строка про legacy без единой команды); все 10 агентов .claude/agents переведены на v2 (motion-infographic-designer — только HyperFrames, PIL-путь удалён; ревьюеры обязаны штамповать artifact_path/artifact_sha256; hook-doctor/music-supervisor перенаправлены с legacy-доков на common/quality/VQ-*); user-level skills dl-iterate/dl-final/dl-improve/dl-reel/dl-watch (вне репо, ~/.claude/skills) помечены LEGACY-плашкой с перенаправлением на dl-make-video, тела не менялись — старые v1-проекты продолжают работать |
| 2.6 | `17869de` | POST /api/feedback сервер-сайд пиннит вердикты: `artifact_sha256` (стриминговый sha256 файла под project root) + `timestamp` для каждого узла с `artifact_path`; несуществующий/выходящий за root путь хэш не получает (unverifiable ≠ fresh) |
| — | `c43c014` | Обёртки `dl2.bat` / `dl2` в корне workspace (паритет с v1 dl.bat) + `python -m dlstudio` entry — dl2 доступен без pip scripts на PATH |

### Приёмка этапа 2

Содержательная приёмка («в новом чате агент сам находит skill … ≤2 вопроса»)
выполняется пользователем в свежем чате — не имитировалась. Механическая
самопроверка: полная suite 593 passed; схема sha256 закреплена API-тестами;
в новых skill/агентах и AGENTS.md нет ни одной v1-команды (grep-sweep обоих
агентов, каждая использованная dl2-подкоманда сверена с реальными парсерами
CLI); обёртки dl2 проверены из bash и PowerShell.

---

## Решения, принятые без пользователя (по критерию §11 — проще и надёжнее)

1. `cache.put` без stem-соседа: warning + отказ от публикации (не exception) —
   рендер остаётся успешным, просто некэшированным.
2. Assemble доверяет stem'у только при |длительность − beat.duration| ≤ 0.35s,
   иначе warn + переизвлечение аудио из MP4 (MP4 только что прошёл VQ-SYNC).
3. Профили: draft-тиры (360p/540p/720p) якорят ВЫСОТУ (совместимо с
   webui-превью), delivery (1080p/1440p/4k) — длинную сторону. Литеральный
   числовой `--width` остался шириной.
4. 0.11: битый-но-существующий шрифт — ошибка; ОТСУТСТВУЮЩИЙ путь шрифта —
   прежний PIL-фолбэк (ловится VQ-ASSET на check-гейте; фолбэк нужен тестовым
   средам без шрифтов).
5. 0.4: ошибки checks блокируют рендер на ЛЮБОМ качестве (включая draft);
   warnings печатаются и не блокируют.
6. Смена бита во время записи = авто-стоп с сохранением take в ИСХОДНЫЙ beat
   (вместо блокировки UI) — «требует остановки» из плана, но без потери дубля.
7. Тестовые фикстуры шрифтов используют системный TTF (arial/segoeui/DejaVu/
   Liberation) со skip'ом, если ни один не найден.
8. safe_join: канонизация `\\?\`-префикса + один повтор при транзиентном
   `$Deleted`-резолве (реальный Windows-баг, найден ночью, вне плана).
9. Feedback-схема обогащается СЕРВЕРОМ (skill'ам не нужно считать sha256 при
   записи — только при чтении/проверке актуальности).
10. HyperFrames `--quality`: draft→draft, final→high (маппинг на флаги
    инструмента); `--init` + `--out` в одном вызове = scaffold+render.
11. Legacy user-skills не переписаны на v2, а помечены LEGACY-плашкой с
    перенаправлением на dl-make-video — старые v1-проекты продолжают работать.
12. CI добавлен как job в существующий .github/workflows/tests.yml (не новый
    файл); Windows-smoke остаётся локальной командой (по плану допустимо).

## Отложенные пункты

- **Караоке-подсветка субтитров** — по плану опциональна; фразовых captions
  достаточно для приёмки. Отложено до реальной необходимости в этапе 3.
- **Проверка GitHub CI-job в действии** — job написан, но прогнать его можно
  только пушем; по плану локальная команда (full suite + smoke) уже заменяет
  его до пуша.
- **Приёмка этапов 1–2 свежим чатом и весь этап 3** — зона пользователя.

## Результаты тестов и smoke

- Полная suite: **зелёная** (590+ тестов; было 493). Real-ffmpeg E2E,
  интеграционные mix/caption/review-тесты включены.
- Smoke этапа 0: полный FFmpeg-путь в «тест проект» (кириллица+пробел) ✓.
- Smoke этапа 1: new-video → preview на «проект один» ✓; реальный
  HyperFrames-рендер на «хф тест» ✓.
- `dl2 verify --changed` использовался после каждого блока; webui собран.

---

## Промпт для приёмочного свежего чата (этап 2 / старт этапа 3)

```text
Сделай вертикальный reel 45–60 секунд о [ТЕМА] на движке Studio v2.
Проект создай сам (dl2 new-video), материалы возьми из [ПУТЬ К ассетам
или «сгенерируй placeholder-ы»], сделай scratch VO, включи субтитры,
подбери музыку из data/music, доведи до draft с contact sheet, прогони
blind review и безопасные правки (не более 3 итераций), затем final.
Спрашивай меня только если не хватает настоящего footage или нужен мой
финальный VO.
```

Ожидаемое поведение: агент сам находит skill `dl-make-video`, работает только
dl2-командами, использует `dl2 preview` для draft-артефактов, вердикты в
`data/review/feedback.json` содержат `artifact_sha256` текущих MP4, вопросов
пользователю ≤ 2.
