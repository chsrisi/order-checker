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
- `src/stores/`: `session.ts` (tokens, login/logout/refresh), `live.ts` (WS state and frames;
  `snapshot(command)` re-requests a list on every reconnect), `workers.ts`, `orders.ts`
  (ongoing orders, picks and open scans from live frames; hand-ticks in `localStorage`).
- `src/lib/`: tested pure helpers (`orders.ts` progress/packed/filters, `workers.ts`,
  `time.ts`) and composables (`usePaged.ts` for `X-Total-Count` history pages, `usePolling.ts`,
  `theme.ts`: account menu → Theme → System / Light / Dark, kept in `localStorage`
  `oc.console.theme`; it also sets `data-theme` and `color-scheme` on `<html>`). Custom CSS
  colours that differ per theme come from Naive's `useThemeVars()`, not
  `prefers-color-scheme`, so they follow the toggle.
- `src/nav.ts`: the one menu definition (Dashboard; Administration, Orders, Warehouse groups) for
  the desktop sidebar and the mobile drawer (below 768 px); pages not rebuilt yet route to
  `PlaceholderView` with a link to the classic admin.
- `src/components/AppShell.vue` (header, sidebar/drawer), `src/views/` (one per screen),
  `src/router/` (routes generated from `nav.ts`), `src/stores/devices.ts` (live from the admin
  frame `devices_update`, reloaded over HTTP on every socket reconnect, polled every 30 s as a
  fallback).
- Device actions and the worker switch (T8.6, V2_UX §2.12): the rules (status line, actions per
  status, switch state, the dialog's worker list and summary) are pure functions in
  `src/lib/devices.ts` with tests; `src/lib/useDeviceActions.ts` runs them (Revoke asks first,
  Approve and Log out act at once); `SwitchWorkerDialog.vue` and `RenameDeviceDialog.vue` are
  rendered by the Dashboard and the Devices page; `DeviceCard.vue` is shared by both.
  Built pages: Dashboard, Workers, Devices, Settings (Shopee connection; config token in memory
  only), Orders (`src/components/orders/`), Warehouse → Tasks (`src/components/tasks/`).
- Tasks (T9.3, V2_UX §2.12): `stores/tasks.ts` keeps the default list from `tasks_update` frames
  (filtered by worker and type in `lib/tasks.ts`); a status filter loads `/admin/tasks?status=…`
  and reloads on each frame. Claimed orders (`/admin/order-tasks`) reload 300 ms after an order or
  pick event. The stock location mode comes from `/meta` (the count form asks for a bin only in
  `multi` mode). The Dashboard shows a "Blocked tasks" banner linking to `?status=blocked`.

## Hosting

Built in the admin image (`frontend/admin/Dockerfile`, `console` stage) from the named build
context `admin-web`, and served by the same nginx (`nginx.conf.template`, `location ^~
/console/`). See OPERATIONS "Frontend Admin Web Hosting & Deployment".
