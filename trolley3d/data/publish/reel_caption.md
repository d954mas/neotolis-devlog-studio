# trolley3d / r01 (`main`) — publish package (Instagram/TikTok/Shorts)

Artifact: `data/finalize/final.mp4` — 1080x1920, 17.8s, music + on-screen
text, no VO. Written after ship because `dl2 publish` only emits a YouTube
package (`data/publish/youtube_package.md`) and this project has no
YouTube-format deliverable — see the reflection recommendation to add a
`dl2 publish --platform reel` mode. Until that exists, this file is the
manual equivalent for reel/short platforms; keep one per released reel in
`trolley3d.edits.<name>` under this convention.

## Caption text (copy-paste, edit per platform character limits)

Вернулся к разработке Not a Trolley Problem — теперь в 3D, на своём
движке. Начал со стиля (рефы + мудборд), первый человечек уже ходит,
дальше — толпа и трамвай. Дальше будет больше 👀

#gamedev #indiedev #devlog #notatrolleyproblem #3d #indiegame #trolley

## Attribution — REQUIRED in the post description/caption

Track: "Groove Grove" by Kevin MacLeod (incompetech.com), licensed under
Creative Commons: By Attribution 3.0 — https://creativecommons.org/licenses/by/3.0/

```
Music: "Groove Grove" by Kevin MacLeod (incompetech.com)
Licensed under Creative Commons: By Attribution 3.0 License
https://creativecommons.org/licenses/by/3.0/
```

## Pre-upload state (see `docs/CHECKLIST_VERTICAL_REEL.md`)

- [x] `dl2 check` clean, no VQ-RES bypass in the shipped cut (recaptured
      portrait/supersampled after the first cut used a landscape
      center-crop workaround — see `trolley3d/PROJECT.md`).
- [x] Text placement corrected to `y_ratio=0.73` on all band overlays
      after platform-crop feedback.
- [ ] `video-reviewer` blind pass — **not run this reel** (deadline).
      `data/review/` has no contact sheet/keyframes/feedback.json for
      this artifact. Run it before the next reel in the series ships the
      same way twice.
- [x] Attribution text above, ready to paste into the post description.
