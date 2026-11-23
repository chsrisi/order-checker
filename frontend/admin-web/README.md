# Order Checker Console (Vue admin, v2)

The new admin app, served at **`/console/`** next to the Flutter admin at `/` until that one
retires (V2_DELTA D1, IMPLEMENTATION_PLAN step 7). Screens are rebuilt one at a time for better
UX, not ported (V2_DELTA Delta 5); each starts with a brief in `docs/V2_UX.md`.

Stack (V2_DELTA Q13): Vue 3, Vite, Vue Router, Pinia, Naive UI; API types from
`backend/openapi/admin.json` via `openapi-typescript`. Dev only: TypeScript 5, `vue-tsc`, Vitest,
jsdom.

## Develop

```bash
npm ci
npm run dev                    # http://localhost:5173/console/, API proxied to 127.0.0.1:8000
OC_BACKEND=http://host:8000 npm run dev   # another backend
npm run typecheck && npm test && npm run build
```

The dev server proxies the same paths as nginx (`/auth`, `/admin`, …, `/ws`), so the app is
same-origin in development and production.

## API types

`src/api/schema.d.ts` is generated and **committed** (the Docker build has no access to
`backend/`). After an admin API change, regenerate the export (`backend`: see TESTING "Client
contracts and OpenAPI exports"), then run `npm run gen:api`. CI runs `npm run check:api`, which
fails when the committed file is stale.

## Sessions (T7.2, P-20)

- Login: `POST /auth/admin`. The access token lives only in memory, and the refresh token in
  `sessionStorage`: a reload keeps the session, closing the tab ends it.
- A 401 triggers one refresh (shared by concurrent requests) and one retry. A failed refresh
  logs out with "Session ended".
- Live updates: the v1-framed `/ws` with a one-use ticket from `POST /auth/ws-token`, with
  endless backoff (1 s to 30 s). A revoked session is closed by the server; the reconnect's
  ticket request then fails, and the console returns to the login screen.

## Layout

- `src/api/`: `http.ts` (fetch + refresh-once), `ws.ts` + `backoff.ts`, `schema.d.ts`
  (generated), `index.ts` (app-wide client).
- `src/stores/`: `session.ts` (tokens, login/logout/refresh), `live.ts` (WS state and frames).
- `src/components/AppShell.vue` (header, menu), `src/views/` (one per screen), `src/router/`.

## Hosting

Built in the admin image (`frontend/admin/Dockerfile`, `console` stage) from the named build
context `admin-web`, and served by the same nginx (`nginx.conf.template`, `location ^~
/console/`). See OPERATIONS "Frontend Admin Web Hosting & Deployment".
