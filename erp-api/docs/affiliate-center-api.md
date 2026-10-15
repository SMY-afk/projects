# Affiliate Center stable API

All endpoints require an authenticated ERP session. Reads require
`affiliate_center:view`; sync also requires `sync:trigger`.

## Snapshot reads

```http
GET /api/affiliate-center/creators
    ?shopId=&from=&to=&currency=&page=&pageSize=&sort=&order=

GET /api/affiliate-center/videos
    ?shopId=&from=&to=&currency=&page=&pageSize=&sort=&order=&creatorOpenId=
```

`from` and `to` are inclusive shop-local dates. The backend resolves the active
shop timezone and converts the range to UTC. Reads never fall back to a partial
run: creators select the newest matching `complete` report revision and videos
select the newest matching `affiliate_video` browser run with status
`succeeded` and `account_type=AFFILIATE_ACCOUNTS`.

Both list responses contain `items`, `page`, `pageSize`, `total`, `sort`, and
`order`. Creator responses include `report`; video responses include `run` and
the resolved canonical `query`. The snapshot object is `null` when no complete
snapshot exists, and `items` is then empty.

## Local read-only export

```http
GET /api/affiliate-center/local-export?from=2026-07-01&to=2026-08-31
```

This endpoint is disabled in production and rejects non-loopback clients in
development. It still requires an authenticated ERP session and
`affiliate_center:view`. The date window is inclusive and limited to 93 days.

The response is a JSON attachment for the five configured business shops. It
contains only the creator username and GMV, video creator/date, and affiliate
live creator/date fields needed by the local screening skill. The implementation
only calls repository read methods: it does not enqueue sync work, write
business tables, inspect browser storage, or expose credentials. Pagination
totals are checked before the file is returned.

## Local Feishu merged-table export

```http
GET /api/affiliate-center/feishu-export
```

This endpoint has the same non-production, loopback, authenticated-session, and
`affiliate_center:view` restrictions as the ERP local export. It accepts no
table or field parameters. The backend reads only the fixed `达人建联总表` /
`达人主表` view, and every Feishu records request fixes `field_names` to
`帐号名称`, `BD负责人`, `同意样品日期`, and `数据来源`. `童车团队` maps to 童车;
`遥控玩具团队` maps to 遥控车. Unknown values block the export.

The downloaded JSON maps those fields to `accountName`, `bdOwner`, and
`sampleApprovedDate`. It retains two logical product-line groups for callers,
but is returned only after the single physical table finishes pagination,
its record IDs are unique, and its captured row count matches Feishu's total.
`FEISHU_NEW_APP_ID` and `FEISHU_NEW_APP_SECRET` stay server-side;
the endpoint never returns or logs the app secret or tenant access token.

## Service-to-service Skill exports

```http
GET /api/internal/affiliate-center/feishu-export
X-ERP-Service-Token: <service token>

GET /api/internal/affiliate-center/local-export?from=2026-07-01&to=2026-08-31
X-ERP-Service-Token: <service token>
```

These endpoints let the creator-invitation backend fetch the same read-only
exports without borrowing a browser session. Configure a random value of at
least 32 characters in `AFFILIATE_EXPORT_SERVICE_TOKEN`, bind the integration
to one tenant with `AFFILIATE_EXPORT_TENANT_ID`, and configure the same token in
the caller. Missing integration settings return `503`; missing or mismatched
tokens return `401`. The token, Feishu secret, and Feishu tenant access token
must never be sent to the browser or written to logs.

## Sync status

```http
GET /api/affiliate-center/sync-status?shopId=
```

The response contains `items` with independent `creators` and `videos` states,
plus a top-level `browser` health object. Browser health exposes only
`state`, `cdpAvailable`, `sessionAvailable`, `updatedAt`, and `recoveredAt`.
Possible states are `browser_offline`, `connecting`, `online`,
`session_expired`, and `captcha`. Each resource item includes
the latest run, its safe counts/status, and the last complete run ID/time. It
does not expose cursors, payload values, browser credentials, or request bodies.

## Manual sync boundary

```http
POST /api/affiliate-center/sync
Content-Type: application/json

{
  "shopId": "uuid",
  "from": "2026-08-01",
  "to": "2026-08-07",
  "currency": "USD",
  "resources": ["creators", "videos"]
}
```

The endpoint returns HTTP `202` after writing one `analytics_sync_runs` intent
per requested resource with status `queued`. Repeated requests for the same
active tenant/shop/window/currency/resource return the existing run.

## Scheduled video sync

The ARQ worker checks every ten minutes and enqueues the daily `videos` capture
for every active TikTok shop after 09:00 Asia/Shanghai. The capture uses the
latest seven-day shop-local window ending two days before the current shop date,
matching the Affiliate Center data-availability boundary. Worker startup runs
the same check so a missed daily execution is caught up after restart.

The scheduled video job creates the original browser capture intent. An exact
successful `affiliate_video` window is never queued again. Failed or partial
browser runs retry after ten minutes, up to three attempts. A later transition
from an offline, expired, or CAPTCHA state to `online` unlocks one further
attempt, so today's missed task is caught up automatically by the next
ten-minute scheduler check.

Browser capture remains owned by the listener daemon in the current logged-in
browser session. The daemon polls and atomically claims queued intents only
after it finds the matching TikTok page and validates the session. Missing
pages, expired sessions, CAPTCHA, HTTP 403/429, window mismatch, and window
control failures become explicit `failed` or `partial` run states. The API and
ARQ workers never receive a browser object, Cookie, request body, or dynamic
signature.

## Collector worker process

The HubStudio collector runs as a dedicated host worker process. FastAPI never
starts Playwright, owns a CDP connection, or waits for browser retries. The
worker reads queued capture intents, collects through the signed-in HubStudio
browser, and writes snapshots and health state to PostgreSQL/Redis. FastAPI
serves the persisted data and may enqueue an intent, but browser execution stays
outside the API process.

On Windows, start the worker separately because HubStudio process discovery and
its loopback CDP port belong to the host session:

```powershell
.\scripts\start-affiliate-collector.ps1 `
  -TenantId <tenant-uuid> `
  -ShopId <shop-uuid-1>,<shop-uuid-2>
```

The worker retries a failed or disconnected CDP session at 30, 60, and 300
seconds. After the third retry it waits 60 seconds, starts a fresh listener, and
repeats until the browser session is available again. The collector
closes pages it created when a capture session ends, removes duplicate managed
login/resource pages, and refuses to open another page when a browser context
has reached `AFFILIATE_MAX_BROWSER_TABS` (default `8`).

The listener discovers HubStudio's current `--remote-debugging-port` from the
local process list and validates the browser against the shop's stored platform
shop ID before connecting. An explicit loopback CDP URL remains optional for
diagnostics. When the port changes or the browser restarts, the listener finds
the replacement endpoint without writing the port to ERP storage or logs.

## Listener video persistence

For an observed `videos` page response, the listener maps each row to the shared
Affiliate video DTO and writes metadata to `tiktok_video_contents` before writing
the windowed metrics to `tiktok_video_performance_snapshots`. The performance row
is bound to the same tenant, shop, UTC window, currency, and `affiliate_video`
sync run. Only after both writes succeed does the listener persist the sanitized
raw page and recovery cursor.

The listener obtains the platform shop ID and request ID from the response in
memory. It does not export browser credentials, headers, signatures, or request
bodies. A terminal page marks the run complete only after total-count checks;
page persistence failures mark it partial and prevent automatic page advance.
