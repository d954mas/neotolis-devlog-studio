# Studio v3 Web UI

Small local dashboard for one explicit Studio v3 production. It shows the
canonical `WorkflowRun` and exposes only the next valid action: advance,
exact-artifact review, or delivery.

The UI has no state framework, file browser, job queue, polling protocol,
research surface, or alternate workflow implementation. CLI, HTTP, and UI call
the same application use cases.

## Contract

FastAPI owns the OpenAPI schema. TypeScript types are generated; do not add
manual request or response mirrors.

```powershell
cd common\dlstudio\webui
npm run generate:client
npm run typecheck
npm test
npm run build
```

`generate:client` rewrites:

- `src/api/openapi.v3.json`
- `src/api/v3.gen.ts`

`src/api/v3.client.ts` is the only handwritten client file and contains only
the typed `openapi-fetch` initialization.

## Development

Run the Studio v3 FastAPI adapter on `127.0.0.1:8788`, then:

```powershell
cd common\dlstudio\webui
npm ci
npm run dev
```

Vite serves `http://127.0.0.1:5175` and proxies `/api` to the local adapter.
The production build is written to
`../src/dlstudio/adapters/static/`, where the same adapter serves it.

## API surface

- `GET /api/v3/status`
- `POST /api/v3/advance`
- `POST /api/v3/review`
- `POST /api/v3/deliver`
- `GET /api/v3/blobs/{sha256}?size=...`

There are no arbitrary filesystem paths or background-job endpoints.
