# Protocol Specification (Schema v1)

This document defines the communication contracts between all components in the **Download Notifs** ecosystem:
- **Source (Extension/Agents) ➔ Backend Server** (`POST /v1/samples`)
- **Backend Server ➔ FCM / Android App** (FCM Data Payload)
- **Backend Server ➔ LAN WebSocket / Android App** (WebSocket Frame)
- **Pairing Handshake** (`/v1/pairings`)

---

## 1. Source ➔ Backend Server: `POST /v1/samples`

Sent periodically (every 2 seconds while active) by the Chrome Extension or PC Source Agent.

### Headers
```http
Content-Type: application/json
Authorization: Bearer <pairing_secret>
```

### Request Body Schema
```json
{
  "pairing_id": "string (UUID)",
  "source": "chrome",
  "pc_name": "string",
  "timestamp": "string (ISO8601 UTC, e.g. 2026-10-08T00:15:00Z)",
  "downloads": [
    {
      "id": "string (unique ID per download item in source)",
      "filename": "string",
      "bytes_downloaded": 52428800,
      "total_bytes": 104857600,
      "state": "downloading",
      "mime_type": "string (optional, e.g. application/zip)"
    }
  ]
}
```

### Field Definitions
- `pairing_id` *(string, required)*: Identifier of the pairing between PC and Phone.
- `source` *(string, required)*: Source identifier: `"chrome"`, `"qbittorrent"`, `"aria2"`, `"steam"`, or `"watcher"`.
- `pc_name` *(string, required)*: Hostname / display name of the PC producing the download.
- `timestamp` *(string ISO8601, required)*: Generation timestamp on client.
- `downloads` *(array of objects, required)*: List of currently tracked downloads.
  - `id` *(string, required)*: ID assigned by source (e.g. Chrome download ID).
  - `filename` *(string, required)*: File name or display title.
  - `bytes_downloaded` *(integer, required)*: Current received bytes ($\ge 0$).
  - `total_bytes` *(integer or null, optional)*: Total expected bytes. `null` if chunked or unknown.
  - `state` *(string enum, required)*:
    - `"starting"`: Download initiated, awaiting first chunk.
    - `"downloading"`: Active transfer with progressing bytes.
    - `"paused"`: Transfer explicitly paused.
    - `"completed"`: Transfer finished successfully.
    - `"failed"`: Transfer interrupted, canceled, or network failed.
    - `"erased"`: Transfer removed from history/disk.
  - `mime_type` *(string, optional)*: Content MIME type if available.

### Response
- `200 OK`: `{"status": "ok", "processed": 1}`
- `401 Unauthorized`: Invalid or missing bearer token.
- `422 Unprocessable Entity`: Validation failure on payload schema.

---

## 2. Backend Server ➔ FCM / Android App (Data Payload)

FCM data message sent from Server to Firebase Cloud Messaging, delivered to the Android device.

> **Note:** We use FCM **data messages** (not notification messages) so that `NotifFcmService` handles the background execution and builds a rich, ongoing, custom-styled notification without system interference.

### FCM Message Parameters
- `android.priority`: `"high"`
- `ttl`: `30s` (to drop stale messages if phone is unreachable for long)

### FCM Data Payload (`data` dictionary)
```json
{
  "seq": "42",
  "sent_at": "2026-10-08T00:15:00Z",
  "source": "chrome",
  "pc_name": "Desktop-PC",
  "downloads": "[{\"id\":\"101\",\"filename\":\"archive.zip\",\"percentage\":50.0,\"speed\":5242880,\"eta_seconds\":10,\"state\":\"downloading\",\"bytes_downloaded\":52428800,\"total_bytes\":104857600}]"
}
```

*Note: In FCM data messages, values in key-value maps are strings. Complex structures (like `downloads`) are serialized to a JSON string or flattened.*

### Evaluated Download Item Fields
- `id` *(string)*: Unique download ID.
- `filename` *(string)*: Display name (or encrypted string if field encryption enabled).
- `percentage` *(float or null)*: `0.0` to `100.0` or `null` if total bytes unknown.
- `speed` *(integer)*: Smoothed bytes per second (EMA).
- `eta_seconds` *(integer or null)*: Estimated seconds remaining or `null` if indeterminate.
- `state` *(string)*: `"starting"`, `"downloading"`, `"paused"`, `"completed"`, `"failed"`, `"stale"`.
- `bytes_downloaded` *(integer)*: Current byte count.
- `total_bytes` *(integer or null)*: Total size in bytes.

---

## 3. Backend Server ➔ LAN WebSocket (`/v1/ws`)

When phone connects locally over WebSocket, frames are sent as JSON text frames matching the evaluated push payload.

```json
{
  "type": "update",
  "seq": 42,
  "sent_at": "2026-10-08T00:15:00Z",
  "source": "chrome",
  "pc_name": "Desktop-PC",
  "downloads": [
    {
      "id": "101",
      "filename": "archive.zip",
      "percentage": 50.0,
      "speed": 5242880,
      "eta_seconds": 10,
      "state": "downloading",
      "bytes_downloaded": 52428800,
      "total_bytes": 104857600
    }
  ]
}
```

Heartbeat:
- Server sends: `{"type": "ping"}` every 15s.
- Client responds: `{"type": "pong"}`.

---

## 4. Pairing Protocol

### Step 1: Create Pairing Request (PC Extension ➔ Server)
`POST /v1/pairings`
```json
{
  "pc_name": "Desktop-PC"
}
```

**Response (`201 Created`):**
```json
{
  "pairing_id": "d3b07384-d113-4632-9c12-706ca8976b92",
  "code": "739201",
  "secret": "sec_9a8f7b6c5d4e3f2a1b",
  "expires_in_seconds": 300
}
```
*The server hashes `secret` and stores `hash(secret)`. The raw `secret` is returned only once.*

### Step 2: QR Code Rendered by Extension
The extension encodes the following payload in the QR code:
```json
{
  "v": 1,
  "server_url": "https://notifs.yourdomain.com",
  "code": "739201",
  "pairing_id": "d3b07384-d113-4632-9c12-706ca8976b92",
  "enc_key": "base64_aes_key_if_encryption_enabled"
}
```

### Step 3: Claim Pairing (Android App ➔ Server)
`POST /v1/pairings/{code}/claim`
```json
{
  "fcm_token": "dKjs983...fcm_device_token...",
  "device_name": "Pixel 8 Pro"
}
```

**Response (`200 OK`):**
```json
{
  "pairing_id": "d3b07384-d113-4632-9c12-706ca8976b92",
  "pc_name": "Desktop-PC",
  "status": "paired"
}
```

### Step 4: Token Refresh (Android App ➔ Server)
`POST /v1/pairings/{pairing_id}/token`
```json
{
  "fcm_token": "new_refreshed_token"
}
```

### Step 5: Unpair (Either side ➔ Server)
`DELETE /v1/pairings/{pairing_id}`
Header: `Authorization: Bearer <pairing_secret>` (from extension) or signed request from device.
