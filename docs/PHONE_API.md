# Phone API (PC side of the companion app)

The Mitra Home companion app (Android now, iOS later) lives in its own private repository,
`rNetGit/mitra-home-companion`. This page is the contract between the two: what the PC app (this repository) serves
and what the phone may rely on. Change it here first, in the same commit as the server change.

## Versions
- `sync.version` in `/api/ping` (`data/sync_data.py` `VERSION`, now **1**) is the sync protocol version. Bump it only
  for a change an older phone cannot read. A phone (0.10.0 and later) that finds a higher number than it knows stops
  syncing and asks its person to update the phone app.
- Every `/api/` call from a phone (0.10.0 and later) carries `X-App-Version: <phone app version>`. A phone older than
  `MIN_PHONE` (`data/sync_data.py`, now **0.9.0**; also `min_phone` in `/api/ping`) is answered
  `426 {"error": "phone_too_old", "min_phone"}` on every call; it then shows "update the phone app" and changes
  nothing. A call without the header (phones before 0.10.0) is served as before. Raise `MIN_PHONE` in the same release
  as an API change older phones cannot handle.
- The edits a phone may send are the ones `/api/ping` lists in `sync.ops`; the phone offers no other (from 0.10.0;
  older phones used their own list).
- New fields may be added to any answer at any time; the phone ignores fields it does not know.
- The QR payload carries its own `"v"` (now 1).

## Transport
- Phones talk HTTPS only, to the app's LAN listener (app port + 100, `Start Mitra Home for phones`), with the
  self-signed certificate from `data/lan_tls.py`. The phone pins the certificate's SHA-256 from the QR; it never
  trusts the system CA store for this host. Plain http is answered `403 {"error": "https_only"}` (except from the PC
  itself, for tests).
- `/api/*` takes no cookies and is exempt from CSRF; every call except `/api/pair` carries
  `Authorization: Bearer <token>`.
- Errors are `{"error": "<code>"}` with an HTTP status. Codes a phone must handle everywhere:
  `unknown_device` (401: forget the pairing, keep waiting scans and edits), `revoked` (401 with `"wipe": true`: delete
  pairing, copy, queue, outbox, reminder, lock), `unavailable` (503: try later, change nothing), `https_only` (403),
  `phone_too_old` (426: ask for a phone app update, change nothing).

## Pairing
- QR (Settings > Phones > Add a phone, 5 minutes, single use): `{"v":1,"h":"<LAN ip>","p":<port>,"fp":"<sha256 hex of
  the certificate>","s":"<secret>"}`. The phone accepts only a home-network address in `h`.
- `POST /api/pair` `{"secret": "..."}` -> `{"token", "device": {id, name, member, role, scopes}, "app", "version"}`.
  Wrong codes: `401 bad_code`; too many: `429 wait`. Only the token's hash is stored on the PC.

## Calls (bearer)
| Call | Answer |
|---|---|
| `GET /api/ping` | `{ok, app, version, min_phone, device, upload, sync: {version, sources, ops, max_ops}, server_time}`. `upload` = `{max bytes, types, per day, left today}` or null without the `scan` scope. |
| `GET /api/sync/pull?cursor=` | `{cursor, reset, more, changes, sources, server_time, money}`; `changes` = upserts / deletes per source, at most 500 rows a page. `money` = `{currency, symbol}` of the household (the phone writes "$60.00"). `summary` (adult phones) = the PC's Today numbers `{needs, overdue, due_today, week}` (needs = overdue + due_today), so the phone can say what the PC counts. `reset` = drop the copy first; `more` = ask again now. Empty cursor = full copy. |
| `POST /api/sync/push` | `{"ops": [{"id": "<phone id>", "op": "<name>", ...}]}` (max 50, 64 KB) -> `{"results": [{id, status: ok / rejected / retry, message, repeat?}]}` in order. A repeated id returns the stored status and changes nothing. |
| `POST /api/upload` | Raw file body; headers `X-Filename` (percent-encoded), `X-Client-Id`, `X-Sha256`. -> `{ok, status: saved / duplicate, name?}`; errors `no_scope` 403, `too_large` 413, `client_id_reused` 409, `refused` 400 with a message. Adults with `scan` only. |
| `POST /api/session` | `{"open": "/phone/open?code=...", "expires_in"}` (60 s, one use). Needs the `web` scope (`403 no_web`) and a PIN for the person (`409 no_pin`). The web view then loads `GET /phone/open?code=` and gets the normal session cookie. |

## Scopes, sources, ops
- Scopes (`data/devices.py` `SCOPES`): own, bills, calendar, notes, lists, scan, finance, ids, web. The live role clamps
  them on every call; a person who left is revoked.
- Sources (`data/sync_data.py` `SOURCES`): people, own, life_items, appointments, events, activities, days, lists,
  list_items, bills, subscriptions, notes, accounts, budget, transactions, id_documents, vehicles, policies, wallet_cards; columns per role, rows per
  visibility. A phone keeps every source in its copy by name and ignores one it does not show yet (app 0.7.0 keeps
  `activities` and `days` without showing them). Adding a source changes the cursor signature, so each phone takes one
  full copy; no VERSION bump.
  - `activities` (scope calendar): weekly classes `{id, member, title, provider, weekdays "MO,WE", start_time, end_time
    "HH:MM", term_start, term_end, skip_dates "YYYY-MM-DD,...", school_days 0/1, status}`; limited = own rows only.
    A phone expands the weeks itself: no class on a skip date, outside the term, or (school_days 1) on a `days` row of
    kind `closure` for the household or that person.
  - `days` (scope calendar): `{id, day, end_day, kind holiday / festival / closure / early, name, member}`; limited =
    household and own rows. Public holidays from the country rules are not stored and not sent.
- Ops (`sync_data.OPS`): `list_add`, `list_tick`, `life_done`, `bill_paid`, `note_add`, each run through
  `edit_actions` as the phone's person.

## Tests
Server side: `tests/test_devices.py` (pairing, scopes, upload) and `tests/test_sync.py`.
Phone side: `npm test` in the companion repository (`www/copy.js` mirrors `data/today_data.py`).
