# Self-hosting

This guide takes you from a fork of this repository to download progress on your phone, using **your own server and your own Firebase project**.

## Before you start: what self-hosting changes

How's My Download has three parts. Only one of them is hosted:

| Part | Runs on | Self-hosting means |
|---|---|---|
| Chrome extension | your PC | the same extension, pointed at your server |
| Server | a machine reachable over HTTPS | **your** server |
| Android app | your phone | **your own build** of the app |

You need your own app build because of how Firebase Cloud Messaging (FCM) works. The app registers with the Firebase project baked into it at build time (`google-services.json`). Only a server holding that same project's service-account key can push to it. A self-hosted server therefore can't push to someone else's build, and you need a Firebase project plus an APK built from it. The GitHub Actions workflow in this repo builds that APK for you.

**What you gain.** Filenames and file types are encrypted on the PC with a key that only ever travels inside the pairing QR code, so they are private on *any* server. Self-hosting additionally keeps the remaining metadata on your machine: PC name, byte counts, timing, IP addresses and your phone's FCM token. It also makes you independent of someone else's uptime.

**What you don't gain.** Pushes still travel through Google's FCM, because that is what wakes an Android phone in deep sleep. FCM carries only ciphertext filenames.

**Costs.** Firebase's free (Spark) plan covers FCM, which has no message charges, and a personal amount of Firestore use. Server auth lookups are cached for 30 s, so Firestore sees about one read per pairing per 30 s while downloading. The server runs comfortably on an [Oracle Cloud Always Free](https://www.oracle.com/cloud/free/) VM. A free [DuckDNS](https://www.duckdns.org) hostname works as the domain.

---

## 1. Firebase project

1. In the [Firebase console](https://console.firebase.google.com), **create a project**. Google Analytics is not needed.
2. **Add an Android app** with package name `com.notifs.app`. To install your build next to another build of How's My Download, pick your own package name instead (for example `dev.yourname.hmd`) and use it as the application ID in step 3. Download **`google-services.json`**.
3. **Firestore**: *Build → Firestore Database → Create database*, in production mode, in a region near your server.
   - **Rules**: paste [`deploy/firestore.rules`](../deploy/firestore.rules) into the *Rules* tab and publish. They deny all client access. The server uses admin credentials, and the app never talks to Firestore.
   - **TTL**: in the Google Cloud console, open *Firestore → Time-to-live* and create a policy for collection group `pairings`, field `purge_at`. This clears pairing codes that were shown but never scanned. Real pairings never carry that field.
4. **Service account key**: *Project settings → Service accounts → Generate new private key*. Save it as `service-account.json`. **This is the one real secret**: anyone holding it can push to your phones and read your database. It goes on the server only and is never committed (`.gitignore` already excludes it).
5. **Restrict the API key** (recommended). `google-services.json` is not a secret; it is embedded in every APK. Still, in the Google Cloud console under *APIs & Services → Credentials*, restrict the auto-created Android key to your package name plus your signing certificate's SHA-256 (see step 3). Then nobody else can use your project's quota.

## 2. Server

**Requirements**
- A Linux machine with a public IP, ports 80 and 443 open, and a domain pointing at it.
- **HTTPS with a publicly trusted certificate.** Release builds of the app refuse plain HTTP and self-signed certificates. Let's Encrypt via the included Nginx setup is the easy path.

**Steps**

The full walkthrough for Ubuntu on Oracle Cloud is [`deploy/docs/oracle-deploy.md`](../deploy/docs/oracle-deploy.md). In short:

```bash
git clone https://github.com/<you>/HowsMyDownload.git ~/notifs && cd ~/notifs
sudo ./deploy/oracle-setup.sh                 # Docker, Nginx, Certbot, firewall, systemd unit, /opt/notifs
sudo cp ~/service-account.json /opt/notifs/deploy/service-account.json
sudo chmod 600 /opt/notifs/deploy/service-account.json
sudo certbot certonly --webroot -w /var/www/certbot -d your.domain
# replace notifs.yourdomain.com with your domain in /opt/notifs/deploy/nginx.conf, then:
sudo cp /opt/notifs/deploy/nginx.conf /etc/nginx/sites-available/notifs.conf && sudo systemctl reload nginx
sudo systemctl restart notifs-api.service
curl https://your.domain/health                # {"status":"ok",...}
```

`/opt/notifs/deploy/.env` must have `STORE_TYPE=firestore` and `NOTIFIER_TYPE=fcm` (the defaults written by the setup script). The server must run as **one** Uvicorn worker, as the Dockerfile does. Tracking, push ordering, rate limits and the command queue live in process memory.

> **No Firestore?** `STORE_TYPE=memory` works, but every server restart forgets all pairings and you will have to re-pair.

## 3. Build the Android app

### Option A: GitHub Actions (no Android tooling needed)

The workflow [`.github/workflows/release.yml`](../.github/workflows/release.yml) builds a signed release APK and the extension zip.

**1. Create a signing key once, and keep it safe.** Android only installs an update if it is signed with the same key. Lose the key and you must uninstall and re-pair.

```bash
keytool -genkeypair -keystore hmd-release.jks -alias hmd -keyalg RSA -keysize 2048 -validity 10000
```

**2. Add repository secrets** (*Settings → Secrets and variables → Actions → Secrets*):

| Secret | Value |
|---|---|
| `GOOGLE_SERVICES_JSON` | the full contents of `google-services.json` |
| `ANDROID_KEYSTORE_BASE64` | the keystore, base64-encoded: `base64 -w0 hmd-release.jks` (Linux), `base64 -i hmd-release.jks` (macOS), or `[Convert]::ToBase64String([IO.File]::ReadAllBytes("hmd-release.jks"))` (PowerShell) |
| `ANDROID_KEYSTORE_PASSWORD` | the keystore password |
| `ANDROID_KEY_ALIAS` | `hmd` (or the alias you chose) |
| `ANDROID_KEY_PASSWORD` | the key password (by default the same as the keystore password) |

**3. Optional repository variables** (*… → Variables*):

| Variable | Purpose |
|---|---|
| `HMD_SERVER_URL` | Your server, e.g. `https://your.domain`. Used when pairing by typing the 6-character code; QR codes carry their own URL. |
| `HMD_APPLICATION_ID` | Your package name, if you didn't use `com.notifs.app`. It must exist in your Firebase project. |

**4. Run it.** Go to *Actions → Build APK & Release → Run workflow*. The build checks `google-services.json` against the package name, runs the unit tests, builds, verifies the APK signature, and uploads `hows-my-download-vX.Y.Z.apk`, the extension zip and `SHA256SUMS.txt` as artifacts. Pushing a tag such as `v0.2.0` also publishes them as a GitHub Release. The tag must match the app and extension versions.

> Artifacts of a public repository can be downloaded by anyone. They contain nothing secret (the keystore never leaves the runner), but the APK is wired to your Firebase project and your default server.

### Option B: build locally

Put `google-services.json` in `android/app/`, then:

```bash
cd android
./gradlew assembleRelease \
  -Phmd.defaultServerUrl=https://your.domain \
  -Phmd.keystoreFile=/path/hmd-release.jks -Phmd.keystorePassword=... \
  -Phmd.keyAlias=hmd -Phmd.keyPassword=...
# optional: -Phmd.applicationId=dev.yourname.hmd
```

The same settings can come from environment variables (`HMD_SERVER_URL`, `HMD_KEYSTORE_FILE`, …; see the top of [`android/app/build.gradle.kts`](../android/app/build.gradle.kts)). Without a keystore the release APK is unsigned. Android Studio's *Build → Generate Signed APK* can sign it instead.

**Install** the APK on your phone and allow installing from your browser or file manager. Play Protect may warn about an app it doesn't know.

For the API-key restriction in step 1.5, get your certificate's SHA-256 with `keytool -list -v -keystore hmd-release.jks -alias hmd`.

## 4. Chrome extension

1. Get the extension: the zip from the workflow (unzip it), or the `extension/` folder of your checkout.
2. Open `chrome://extensions`, enable *Developer mode*, and choose *Load unpacked*.
3. Open the extension popup, set `--server URL` to `https://your.domain`, and click **pair device**.
4. In the app, tap **> scan qr code**. The QR carries the server URL and the encryption key, so nothing else needs configuring.

## 5. Check that it works

Start a large download in Chrome. Within a few seconds the phone should show a progress bar with speed and ETA. Then:
- tap **Pause** on the notification: Chrome pauses within ~2 s and the bar shows *PAUSED* with **Resume**;
- tap **Resume**.

| Symptom | Likely cause |
|---|---|
| Pairing fails with a network error (release build) | Server isn't reachable over HTTPS with a trusted certificate (`curl https://your.domain/health` from mobile data). |
| Paired, but no notifications | Look in `sudo journalctl -u notifs-api.service` for `[FCM]` errors. `SenderIdMismatch` means the app and `service-account.json` come from **different** Firebase projects. The server then deletes that pairing, so fix the mismatch and re-pair. |
| Service won't start: `STORE_TYPE=firestore but Firebase could not be initialized` | `service-account.json` missing or unreadable in `/opt/notifs/deploy/`. |
| Filenames show as "Encrypted file" | Paired by typing the code instead of scanning the QR; the encryption key only travels in the QR. |
| Extension keeps unpairing itself | The server forgot the pairing (memory store and a restart), so re-pair. |

## 6. Updating

- **Server**: the setup script copies the code to `/opt/notifs`, so pull in your clone and copy again:
  ```bash
  cd ~/notifs && git pull
  sudo cp -r server deploy /opt/notifs/
  cd /opt/notifs/deploy && sudo docker compose build notifs-api && sudo systemctl restart notifs-api.service
  ```
  Your `.env`, `service-account.json` and the live Nginx config are not part of the repository, so this leaves them alone.
- **App**: bump `versionCode`/`versionName` in `android/app/build.gradle.kts`, run the workflow again with the **same keystore** secret, and install over the old version. Pairings survive.
- **Extension**: replace the folder or zip and click *Reload* in `chrome://extensions`.

Update the server first. Older apps and extensions ignore fields they don't know, so a newer server is safe with older clients.
