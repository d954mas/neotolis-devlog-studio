# Checklist — long-form devlog

Применяется к горизонтальному девлогу 6–12 минут. Section A нельзя
пропускать перед финальным VO; Section B нельзя пропускать перед
`dl2 final`.

## A. Story gate — до финального VO

- [ ] Есть один `macro_question`, на который реально отвечает финал.
- [ ] Cold open до 0:08 показывает реальный failure/anomaly и glimpse
      payoff; до 0:15 называет продукт и обещание эпизода.
- [ ] Story map лежит в `<production>/data/plan/story_map.json`.
- [ ] Есть минимум `max(4, ceil(duration / 90s))` законченных микроарок.
- [ ] Каждая микроарка содержит цель, failure, cause, solution, proof и
      reaction.
- [ ] Для каждой микроарки существуют `before`, `payoff` и хотя бы один
      `failure`/`process` source.
- [ ] `dl2 longform-check <product:production> --strict` завершился с 0 errors.
- [ ] Capture provenance соответствует `$devlog-record-media`; gameplay —
      real-time client-area stream, а debug proof правильно классифицирован.
- [ ] План VO держится в 150–165 wpm и содержит реакцию автора каждые
      45–75 секунд.
- [ ] Есть одна макропетля и 3–5 микропетель с запланированными выплатами.

## B. Ship gate — до `dl2 final`

- [ ] `dl2 check <edit>` не имеет errors.
- [ ] `dl2 preview <edit>` создан; просмотрены exact draft, contact sheet,
      first 15 seconds и tail.
- [ ] Exact draft проанализирован через `tools/devlog_reference_lab/analyze.py`;
      числовой профиль приложен к review, а аномально длинные интервалы
      объяснены точными semantic-change timestamps.
- [ ] Смысловое состояние кадра обычно меняется каждые 3–6 секунд; один
      master shot не висит >8 секунд без нового действия/ракурса/callout.
- [ ] Каждый обещанный payoff виден в gameplay/product proof, а не только
      описан VO.
- [ ] Текст короткий и читаемый; диаграммы объясняют причинность, а не
      украшают пустой кадр.
- [ ] Звук проверен по VQ-AUDIO; delivery target −14 LUFS, музыка не
      закрывает причины, шутки и payoffs.
- [ ] Есть 2–3 осмысленные музыкальные фазы и уместные stingers/SFX.
- [ ] Финал отвечает на `macro_question`, честно называет статус и держит
      deliberate ending frame.
- [ ] Thumbnail использует реальный proof, одну идею, один главный объект
      и 0–3 слова; title/thumbnail совпадают с первыми 15 секундами.
- [ ] Подготовлены три действительно разные title/thumbnail hypotheses для
      native YouTube A/B test; различается обещание зрителю, а не только цвет.
- [ ] Слепой `video-reviewer` назвал exact MP4 path, SHA-256, timestamp и
      verdict; сохранённый verdict не stale.
- [ ] Regression checklist: music, VO joins, glitches, safe text,
      real-product proof, ending, thumbnail QA.
- [ ] После готовности artifact/package запущен один `devlog-reflector`.
- [ ] После `dl2 deliver` полный publish-пакет SHA-verified в append-only
      архиве `YandexDisk/Devlogs/projects/`.

## Required evidence

- `story_map.json`, enriched `shot_manifest.json` и
  `data/review/longform_preflight.json` от strict gate;
- exact MP4 path + SHA-256;
- `ir.json` и `dl2 check` output;
- `review_pack.json`, sheet и точечные full-resolution frames;
- first-15-second transcript и последний frame/hold;
- thumbnail candidate;
- exact `longform_metrics/*/report.json` и три A/B package hypotheses;
- `data/review/feedback.json` с non-stale verdict.
