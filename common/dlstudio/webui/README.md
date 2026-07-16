# Studio v2 Web UI

Single-page Studio front-end for the dlstudio v2 engine. Vite + TypeScript +
Preact, hand-rolled dark theme (no CSS framework, no state libraries).

The record → process → render → review loop, plus a Timeline IR inspector with
a mix-timeline visualization, all driven by the frozen FastAPI contract in
`../src/dlstudio/api`.

## Stack

- **Vite 6** — dev server + production bundler.
- **Preact 10** — small, typed components. JSX via esbuild's automatic runtime
  (`jsxImportSource: "preact"`), so no `@preact/preset-vite` dependency.
- **TypeScript** — strict; all API payloads typed by hand in `src/api/types.ts`
  against the contract (no codegen).

Total runtime dep surface: `preact`. Dev deps: `vite`, `typescript`.

## Layout

```
webui/
  index.html            Vite entry
  vite.config.ts        base "./", /api proxy, build.outDir → package static
  tsconfig.json
  src/
    main.tsx            mounts <App/>
    app.tsx             top-level state + layout (header, tabs, panel, actions)
    styles.css          dark theme (borrows legacy studio's accent palette)
    api/
      types.ts          hand-written types for every endpoint / IR shape
      client.ts         typed fetch wrappers + pollJob()
    lib/
      recorder.ts       MicRecorder: MediaRecorder + WebAudio level meter
      takes.ts          per-session take model (see "Takes" below)
      format.ts         duration / bytes / basename helpers
    components/
      CheckBanner.tsx   errors/warnings banner across the top
      Sidebar.tsx       beat list w/ duration + rendered + check chips
      ScriptTab.tsx     VO + stage note; karaoke when IR words + audio exist
      Karaoke.tsx       word highlighting synced to VO audio playback
      RecordTab.tsx     device pickers, meters, capture, upload, process-take
      LevelMeter.tsx    single meter bar (dBFS → width)
      FeedbackPanel.tsx vo/video review cards
      IRInspector.tsx   mix timeline + collapsible Timeline JSON
      MixTimeline.tsx   plain-SVG time axis / beat lanes / music / sfx
      JsonTree.tsx      recursive collapsible JSON viewer
```

## Dev workflow

The UI expects the FastAPI backend on `127.0.0.1:8788`. The dev server proxies
`/api/*` there (see `vite.config.ts`), so you run both:

```bash
# terminal 1 — backend (whatever command the api serves on :8788)
dl2 studio           # or: uvicorn dlstudio.api:app --port 8788

# terminal 2 — UI with HMR
cd common/dlstudio/webui
npm install
npm run dev          # http://localhost:5175  (proxies /api → :8788)
```

Open the dev URL. All `/api/...` calls transparently hit the backend; media and
video previews stream through `GET /api/file?path=...`.

Note: mic/camera capture needs a secure context. `localhost` counts as secure,
so `getUserMedia` works on the dev server and on the packaged app served from
localhost.

## Build

```bash
cd common/dlstudio/webui
npm run build        # tsc --noEmit  &&  vite build
```

Output is written **into the Python package** so the API can serve it:

```
../src/dlstudio/api/static/
  index.html
  assets/index-*.js
  assets/index-*.css
```

`base: "./"` keeps asset URLs relative, so the bundle works whether the API
mounts `static/` at `/` or under `/static/`. `emptyOutDir` is enabled because
the output dir lives outside the Vite root.

Other scripts: `npm run typecheck` (`tsc --noEmit`), `npm run preview` (serve
the built bundle locally — API calls still need the backend/proxy).

## Notes on the API contract

Coded directly against the frozen endpoints:

- `GET /api/project`, `GET /api/ir` (Timeline), `GET /api/check`
- `GET/POST /api/feedback`
- `POST /api/takes/{beat_id}` (multipart `file`) → `{path}`
- `POST /api/actions/process-take` / `render-beat` → `{job_id}`,
  polled via `GET /api/jobs/{id}`
- `GET /api/file?path=...` for audio/video src

**Takes** are tracked per browser session (`lib/takes.ts`): the contract has no
"list takes" endpoint — upload returns only `{path}` — so the take list shows
what you recorded this session. Each take can be uploaded and then processed via
`process-take`; on success the project/IR reload and karaoke unlocks.

**Karaoke** uses `Timeline.beats[].words` (`{t0,t1,text}`) from `/api/ir` and
plays the processed VO (`beat.audio` via `/api/file`), highlighting the current
word on `timeupdate`/rAF. Click a word to seek.

**540p draft render** passes `width = round(design_w * 540 / design_h)` (even)
and `quality: "draft"`; the preview player points at the render result path, or
`data/finalize/<beat_id>.mp4` as a fallback.
