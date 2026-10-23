# Protocol Specification (Schema v1)

Contracts between the components of **How's My Download**:

1. **Extension ➔ Server**: `POST /v1/samples`
2. **Server ➔ FCM ➔ Android**: FCM data payload
3. **Pairing**: `/v1/pairings` (create, claim, status, token refresh, rotate, unpair)
4. **Field-level encryption** and the **security model**
5. **Download commands** (phone ➔ PC): pause, resume, restart

All IDs in paths are validated: `pairing_id` must be a UUID, `code` must be 6 alphanumerics and `command_id` 32 lowercase hex characters, otherwise `422`.

---

## 1. Extension ➔ Server: `POST /v1/samples`

Sent every 2 seconds while a download is active, plus immediately on state changes.

### Headers
```http
Content-Type: application/json
Authorization: Bearer <extension_secret>
```

### Request Body
```json
{
  "pairing_id": "d3b07384-d113-4632-9c12-706ca8976b92",
  "source": "chrome",
  "pc_name": "Desktop-PC",
  "timestamp": "2026-10-08T00:15:00Z",
  "downloads": [
    {
      "id": "101",
      "filename": "enc:v1:<b64 iv>:<b64 ciphertext+tag>",
      "bytes_downloaded": 52428800,
      "total_bytes": 104857600,
      "state": "downloading",
      "mime_type": "enc:v1:<b64 iv>:<b64 ciphertext+tag>"
    }
  ]
}
```

- `pairing_id`: ignored for authorization; the server uses the pairing that owns the bearer secret.
- `filename` *(required)* and `mime_type` *(optional)*: **always ciphertext** (section 4). The extension truncates filenames to 120 characters (keeping the extension) before encrypting, so a single item stays small.
- `total_bytes`: `null` if unknown.
- `state`: `starting | downloading | paused | completed | failed | erased`. The extension sends `erased` once for a download replaced by a phone `restart`.
- `can_resume` *(optional)*: `true` on a `failed` download Chrome can resume without starting over. Omitted otherwise.
- Limits: ≤ 100 downloads, filename ≤ 1024 chars, request body ≤ 50 KB.

### Responses
| Status | Meaning |
|---|---|
| `200` | `{"status": "ok", "processed": 1, "pairing_id": "...", "commands": [...]}`. `commands` hands over pending phone commands (section 5) and removes them from the queue. |
| `401` | Missing/invalid secret, or the secret of an unclaimed pairing whose code expired |
| `413` | Body > 50 KB (also enforced for chunked bodies without `Content-Length`) |
| `422` | Schema validation failure |
| `429` | More than 10 samples in 10 s for this pairing. `Retry-After` gives seconds to wait |

---

## 2. Server ➔ FCM ➔ Android (data message)

FCM **data** messages (not notification messages), so `NotifFcmService` renders the notification itself.

- `android.priority`: `high`
- `ttl`: `30s` (stale progress is worthless)

### Data map (all values are strings)
```json
{
  "seq": "42",
  "epoch": "1760918400123",
  "sent_at": "2026-10-08T00:15:00+00:00",
  "source": "chrome",
  "pc_name": "Desktop-PC",
  "pairing_id": "d3b07384-d113-4632-9c12-706ca8976b92",
  "downloads": "[{\"id\":\"101\",\"filename\":\"enc:v1:...\",\"percentage\":50.0,\"speed\":5242880,\"eta_seconds\":10,\"state\":\"downloading\",\"bytes_downloaded\":52428800,\"total_bytes\":104857600}]",
  "omitted": "3"
}
```

| Field | Notes |
|---|---|
| `seq` | Strictly increasing per pairing **within one server process**. Assigned at dispatch time, so there are no gaps from throttled samples. |
| `epoch` | Server boot time (ms). `seq` restarts at 1 when the server restarts, so the phone compares `seq` only within the same `epoch` and treats a new epoch as a new stream. |
| `downloads` | Compact JSON. `null` fields are omitted; `mime_type` is never forwarded (the phone does not use it). |
| `omitted` | Present only when the list was trimmed to fit FCM's 4096-byte data limit (the server budgets 3584 bytes). Terminal transitions (`completed`/`failed`/`erased`) are kept first. While `omitted > 0`, the phone keeps notifications for downloads missing from the list. |

Item fields: `id`, `filename` (ciphertext), `percentage` (0–100, absent if unknown), `speed` (EMA bytes/s), `eta_seconds` (absent if unknown), `state`, `bytes_downloaded`, `total_bytes`, `can_resume` (only present, as `true`, on a resumable `failed` download).

### Phone-side ordering (`SequenceGate.kt`)
1. Drop pushes whose `pairing_id` differs from the current pairing.
2. Same `epoch` as the last accepted push: accept only if `seq > lastSeq`.
3. Different `epoch` (server restarted): accept and start a new stream.

### Unpair event
```json
{ "event": "unpaired", "pairing_id": "..." }
```
Sent when the **extension** unpairs. The phone ignores it unless `pairing_id` matches its current pairing.

### Command result event
```json
{ "event": "command_result", "pairing_id": "...", "command_id": "<32 hex>", "download_id": "42", "action": "resume", "ok": "false", "error": "expired" }
```
Sent (high priority, TTL 60 s) when a phone command failed on the PC or expired uncollected. It has no `seq` and is handled before the sequence gate. Only failures are pushed today; a success shows up as the next progress push. See section 5.

### Throttling
At most one progress push per 2 s per pairing. Intermediate samples are merged into the latest one. State changes and added/removed downloads skip the wait and push immediately.

---

## 3. Pairing Protocol

There are two credentials per pairing. Each is a 256-bit random token (`secrets.token_urlsafe(32)`) shown exactly once. The server stores only its SHA-256 hash and compares in constant time.

| Credential | Issued by | Held by | Authorizes |
|---|---|---|---|
| extension secret | `POST /v1/pairings` | extension | samples, status, rotate, unpair, collect commands, report command results |
| device secret | `POST /v1/pairings/{code}/claim` | phone | status, FCM token refresh, unpair, send download commands |

### 3.1 Create (extension ➔ server)
`POST /v1/pairings`, rate limited to 10/min per IP.
```json
{ "pc_name": "Desktop-PC" }
```
`201 Created`:
```json
{
  "pairing_id": "d3b07384-d113-4632-9c12-706ca8976b92",
  "code": "K7QF3M",
  "secret": "<extension secret>",
  "expires_at": "2026-10-08T00:20:00Z"
}
```
The code lives 5 minutes and uses an alphabet without `0 O 1 I`. Expired unclaimed pairings are purged.

### 3.2 QR code (extension popup ➔ phone camera)
```json
{
  "server_url": "https://notifs.yourdomain.com",
  "code": "K7QF3M",
  "pc_name": "Desktop-PC",
  "enc_key": "<64 hex chars, AES-256 key>"
}
```
`enc_key` is generated in the popup with `crypto.getRandomValues` and **never sent to the server**. The phone rejects a QR whose `enc_key` is not 64 hex characters. Manual code entry pairs without a key, so filenames display as "Encrypted file".

### 3.3 Claim (phone ➔ server)
`POST /v1/pairings/{code}/claim`, rate limited to 10/min per IP. Codes are case-insensitive.
```json
{ "fcm_token": "<FCM registration token>" }
```
`200 OK`:
```json
{
  "status": "ok",
  "pairing_id": "d3b07384-d113-4632-9c12-706ca8976b92",
  "pc_name": "Desktop-PC",
  "device_secret": "<device secret>"
}
```
`400` if the code is unknown, expired, already claimed, or has had 5 attempts. The claim is a transaction in Firestore, so concurrent claims can't both succeed.

### 3.4 Status
`GET /v1/pairings/{pairing_id}` with `Authorization: Bearer <extension or device secret>`. The extension polls this while the QR is shown.

### 3.5 FCM token refresh (phone ➔ server)
`POST /v1/pairings/{pairing_id}/token` with `Authorization: Bearer <device secret>`
```json
{ "fcm_token": "<new token>" }
```
`403` if called with the extension secret: only the phone may say where its pushes go.

### 3.6 Rotate extension secret
`POST /v1/pairings/{pairing_id}/rotate-secret` with `Authorization: Bearer <extension secret>` returns `{"status": "ok", "pairing_id": "...", "new_secret": "..."}`. The old secret is rejected immediately, and the device secret is unaffected. If a sample was in flight with the old secret, the extension sees the `401`, notices the stored secret changed, and retries instead of unpairing.

### 3.7 Unpair
`DELETE /v1/pairings/{pairing_id}` with `Authorization: Bearer <extension or device secret>`. If the extension unpairs, the phone receives an `unpaired` FCM event. The server also drops the pairing's tracker and throttler state.

### Error semantics
For every `/{pairing_id}` route, an unknown pairing and a wrong secret both return `401`. This prevents probing for valid pairing IDs. `429` responses carry `Retry-After`.

---

## 4. Field-level encryption

- **Algorithm**: AES-256-GCM, a random 96-bit IV per field, and a 128-bit tag.
- **Wire format**: `enc:v1:<base64 iv>:<base64 ciphertext||tag>`
- **Encrypted fields**: `filename` and `mime_type`.
- **Not encrypted** (the server needs them, or they are metadata): byte counts, state, download IDs, timing, `pc_name`.
- **Fails closed**: if the extension is paired but has no valid key, or encryption throws, the sample is dropped and never sent in plaintext.
- **Phone**: decrypts locally. Anything it cannot authenticate (missing key, wrong key, tampered data) is shown as `Encrypted file`, never as ciphertext.
- **Cross-implementation test**: `CryptoUtilsTest.testDecryptsCiphertextFromTheExtension` decrypts vectors produced by `extension/background/crypto.js`.

---

## 5. Download commands (phone ➔ server ➔ extension)

The phone can **pause**, **resume** or **restart** a download on the PC. The extension has no push channel, so the server queues commands until the extension collects them:

- **While a transfer is active**, the `/v1/samples` response carries them (`commands`), so a command costs no extra request and lands within ~2 s.
- **While nothing is transferring but something is controllable** (a paused download, or one that failed in the last hour), the extension polls `GET /v1/pairings/{pairing_id}/commands` every 3 s for 10 minutes after the last activity, then every 30 s (`chrome.alarms`, Chrome's minimum).

Delivery is **at most once**: a command is removed from the queue when it is handed over. The queue lives in server memory (single worker, like the tracker). A restart drops pending commands.

### 5.1 Send (phone ➔ server)
`POST /v1/pairings/{pairing_id}/commands` with `Authorization: Bearer <device secret>`, rate limited to 20/min per pairing.
```json
{ "download_id": "42", "action": "pause" }
```
`action`: `pause | resume | restart`. `download_id` matches `^[A-Za-z0-9_-]{1,128}$` (the extension also requires digits).

`202 Accepted`:
```json
{
  "status": "queued",
  "command": { "command_id": "<32 hex>", "download_id": "42", "action": "pause", "issued_at": "..." },
  "expires_in_sec": 75,
  "pc_last_seen_sec": 3
}
```
`pc_last_seen_sec` is the time since the extension last collected commands or sent a sample (`null` if never since the server started). It is a hint only, because an idle extension with nothing to control does not poll.

There is one pending command per download. A newer tap replaces an older one that hasn't been collected yet (pause, then resume, before the PC picks it up, delivers only resume). An identical tap returns the existing command. `403` with the extension secret.

### 5.2 Collect (extension ➔ server)
`GET /v1/pairings/{pairing_id}/commands` with `Authorization: Bearer <extension secret>`, rate limited to 20 per 30 s per pairing. Returns `{"commands": [...]}` and removes them. `403` with the device secret.

### 5.3 Execute (extension)
| Action | Running | Paused | Failed (interrupted) | Completed |
|---|---|---|---|---|
| `pause` | `chrome.downloads.pause` | no-op | `invalid_state` | `invalid_state` |
| `resume` | no-op | `chrome.downloads.resume` | resume if `canResume`, else `not_resumable` | `invalid_state` |
| `restart` | cancel, then download the original `url` again | same | download the original `url` again | `invalid_state` |

A restart only re-fetches the item's own `http(s)`/`ftp` URL (`blob:`/`data:` → `unsupported_url`). The new download gets a new id. The old entry is erased from Chrome's list and reported once with state `erased`, so the phone drops it instead of showing "failed". Unknown ids → `not_found`; Chrome API errors → `browser_error`. After acting, the extension samples immediately.

### 5.4 Report result (extension ➔ server)
`POST /v1/pairings/{pairing_id}/commands/{command_id}/result` with `Authorization: Bearer <extension secret>`:
```json
{ "download_id": "42", "action": "resume", "ok": false, "error": "not_resumable" }
```
`error` must be one of `not_found | invalid_state | not_resumable | unsupported_url | browser_error`, never free text, so nothing about the PC leaks to the phone. Failures are forwarded to the phone as a `command_result` event (section 2). The extension reports only failures.

### 5.5 Expiry
Commands not collected within **75 s** expire. A server task checks every 5 s and sends the phone `command_result` with `error: "expired"` ("PC didn't respond").

### 5.6 Phone behaviour
- Notification buttons: running → **Pause**; paused → **Resume**, **Restart**; failed → **Restart** (+ **Resume** if `can_resume`). Restart is left off running downloads in the shade because a notification can't ask for confirmation. The app offers it with a confirmation dialog.
- On tap, the buttons are replaced by "Pausing…" etc. until the state changes, a `command_result` failure arrives (the message is shown and the buttons come back), or 90 s pass.
- A paused download's notification lives 30 minutes (`setTimeoutAfter`) instead of 150 s, because a paused download sends no further updates.
- The app keeps failed downloads listed for an hour so they can still be restarted.