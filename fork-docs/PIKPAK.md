# PikPak setup

This runbook records the PikPak integration on this host. It is operational, not a generic tutorial. Credentials are **not** in this repository; they live in rclone and Peach's secrets directory.

---

## 1. Current status (2026-10-31)

| Item | Status |
|---|---|
| PikPak account | Premium, logged in through the browser session |
| WebDAV | Enabled through PikPak's own API |
| WebDAV app credential | Created, named `Peach` |
| rclone remote | `[pikpak]`, type `webdav` |
| Host mount | `/mnt/pikpak` via `rclone-pikpak.service` |
| Peach media root | `pikpak = R:\peach\pikpak` → `/media/pikpak` |
| Peach library | `PikPak` |
| Peach download target | `/My Pack/Peach` |
| Peach credential | `/var/lib/peach/secrets/follow/download-pikpak.json` |
| Direct provider | Configured; folder lookup and task listing work |
| Avatar/profile media | not PikPak-specific |

The PikPak files live under `My Pack`. The rclone remote mounts the account root, so the container sees:

```text
/media/pikpak/My Pack/Peach
```

The Peach storage root maps that to:

```text
R:\peach\pikpak\My Pack\Peach\...
```

---

## 2. PikPak WebDAV address and credential

PikPak Premium exposes a WebDAV endpoint at:

```text
https://dav.mypikpak.com
```

The web UI path is **Settings → Access & Integrations → WebDAV**. Enable WebDAV, then create a credential. PikPak returns:

- server address (`dav.mypikpak.com`)
- username (generated, e.g. a short alias)
- password (generated)

Do not reuse the PikPak account password for WebDAV. The generated credential can be revoked or regenerated independently.

### Creating it through PikPak's API

The web client calls these endpoints on `https://api-dav.mypikpak.com`:

```text
GET    /webdav/v1/applications
POST   /webdav/v1/toggle-enable      {"enable": true}
POST   /webdav/v1/application        {"application_name": "Peach"}
POST   /webdav/v1/renew-password     {"username": "...", "password": "..."}
DELETE /webdav/v1/application        {"username": "...", "password": "..."}
```

They require the same bearer token as the PikPak web session. The response to `POST /webdav/v1/application` contains the generated username/password. The current credential was created this way (`id 225156`, application name `Peach`); the values are stored only in rclone and are not repeated here.

If a new credential is needed:

```bash
# The token is in the browser session. Do not paste it into shell history if
# you can avoid it; use a temporary file with mode 600.
python3 - <<'PY'
# read the current token from the browser's Local Storage on this host,
# call POST https://api-dav.mypikpak.com/webdav/v1/application
# and save the returned username/password to /tmp/pikpak-webdav.json (0600)
PY
```

The same operation can be done manually from the PikPak web UI, which is simpler and avoids handling the token.

---

## 3. rclone remote

The remote is stored in `/home/desktop/.config/rclone/rclone.conf`:

```ini
[pikpak]
type = webdav
url = https://dav.mypikpak.com
vendor = other
user = <generated username>
pass = <rclone-obscured password>
```

Create or replace it with:

```bash
sudo -u desktop rclone config create pikpak webdav \
  url=https://dav.mypikpak.com \
  vendor=other \
  user='<generated username>' \
  pass="$(rclone obscure '<generated password>')" \
  --config /home/desktop/.config/rclone/rclone.conf \
  --non-interactive
```

Keep the file private:

```bash
chown desktop:desktop /home/desktop/.config/rclone/rclone.conf
chmod 600 /home/desktop/.config/rclone/rclone.conf
```

Verify:

```bash
sudo -u desktop rclone lsd pikpak: --config /home/desktop/.config/rclone/rclone.conf
```

Expected:

```text
-1 ... My Pack
```

Check a file the account already has:

```bash
sudo -u desktop rclone ls 'pikpak:My Pack' --config /home/desktop/.config/rclone/rclone.conf | head
```

---

## 4. Mount unit

`/etc/systemd/system/rclone-pikpak.service`:

```ini
[Unit]
Description=PikPak WebDAV mount for Peach (rclone)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=desktop
Group=desktop
Environment=HOME=/home/desktop
Environment=XDG_CONFIG_HOME=/home/desktop/.config
ExecStart=/usr/bin/rclone mount pikpak: /mnt/pikpak \
  --config /home/desktop/.config/rclone/rclone.conf \
  --vfs-cache-mode writes \
  --vfs-cache-max-size 20G \
  --dir-cache-time 1m \
  --poll-interval 15s \
  --uid 1000 --gid 1000 --umask 022 --allow-other
ExecStop=-/usr/bin/fusermount3 -u /mnt/pikpak
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo mkdir -p /mnt/pikpak
sudo chown desktop:desktop /mnt/pikpak
sudo systemctl daemon-reload
sudo systemctl enable --now rclone-pikpak.service
```

Verify:

```bash
systemctl is-active rclone-pikpak.service
mount | grep pikpak
ls -la /mnt/pikpak
ls -la '/mnt/pikpak/My Pack'
```

### Restart order

PikPak has the same `rslave` rule as Google Drive:

```bash
sudo systemctl restart rclone-pikpak.service
sudo systemctl restart peach.service
```

If Peach keeps a stale FUSE handle, `/media/pikpak` reports `Transport endpoint is not connected`. Restarting Peach re-establishes the bind mount.

---

## 5. Compose and Peach config

`/opt/peach/compose.yaml` must contain:

```yaml
volumes:
  - /mnt/pikpak:/media/pikpak:rslave
```

`/var/lib/peach/config.toml`:

```toml
[media.locations]
mounted = 'R:\peach\mounted\a124d4bb7e102eef99c6e0be8a0e80d1'
pikpak = 'R:\peach\pikpak'

[media.mounts]
mounted = '/media/gdrive'
pikpak = '/media/pikpak'

[media.libraries]
'R:\peach\pikpak' = 'PikPak'

[media.library_icons]
'R:\peach\pikpak' = 'pikpak'

[media.costs]
'R:\peach\pikpak' = 'metered'

[media.library_catalog.a45f6c4d-b007-4c00-844b-f34483498b5e]
name = 'PikPak'
icon = 'pikpak'

[media.storage_roots.90266ea0-dfcd-45c9-bb5c-b7dcd3f97749]
root = 'R:\peach\pikpak'
location = 'pikpak'
library_id = 'a45f6c4d-b007-4c00-844b-f34483498b5e'
mount = '/media/pikpak'
cost = 'metered'
```

The UUIDs are local identities. If you add the root through the web UI, Peach generates its own; keep whichever pair is in `config.toml`.

After changing the mount or config:

```bash
systemctl restart peach.service
```

Verify:

```bash
TOK=$(cat /var/lib/peach/secrets/auth-token)
curl -sS -H "X-Token: $TOK" http://127.0.0.1:8900/api/sources
```

The `pikpak` source must be `online: true` with `resolved: /media/pikpak`.

---

## 6. Peach download credential

Peach stores the PikPak web session in:

```text
/var/lib/peach/secrets/follow/download-pikpak.json
```

Shape (values redacted):

```json
{
  "refresh_token": "<redacted>",
  "access_token": "<redacted>",
  "expires_at": "1793463607",
  "user_id": "<redacted>",
  "device_id": "<32 hex chars>",
  "client_id": "YUMx5nI8ZU8Ap8pm"
}
```

Permissions must be `0600`, owner `1000:1000`.

Peach refreshes this token shortly before `expires_at`. **A PikPak refresh token is single-use: every refresh rotates it.** Do not run two independent refreshers against the same account:

- Peach owns this token.
- Do not leave a second Peach/browser process refreshing the same token.
- If the PikPak web session refreshes first, Peach's refresh token becomes invalid and the download provider reports `invalid_grant`.
- If Peach refreshes first, the old browser session may be logged out.

If that happens, use the PikPak web UI to log in again and either:

1. let Peach's **browser login** flow capture a new token (when a browser is available), or
2. extract the current `credentials_<client_id>` value from the browser's Local Storage and replace `download-pikpak.json` (maintenance only), or
3. reset the credential and use PikPak only as a mount.

The mount itself does not need this token; it uses the WebDAV credential.

### Captcha on reads — fixed in the fork

PikPak's web token also requires a captcha token for **read** endpoints such as `GET /drive/v1/files` and `GET /drive/v1/tasks`. Without it the API returns:

```text
captcha_invalid
```

The fork patches `src/peach/downloads_pikpak.py` to request a captcha token for:

- `GET:/drive/v1/files`
- `GET:/drive/v1/tasks`

before each paginated read. `POST:/drive/v1/files` already had one for offline submission. The live override is mounted at:

```text
/var/lib/peach/overrides/downloads_pikpak.py
```

Verify in the container:

```bash
docker exec peach-peach-1 python -c '
import json
from peach.downloads_pikpak import PikPakClient
v = json.load(open("/data/secrets/follow/download-pikpak.json"))
c = PikPakClient(v, persist=lambda values: None)
print("folder", c.folder_id("/My Pack/Peach"))
print("tasks", len(c.tasks()))
c.close()
'
```

Expected:

```text
folder <folder id>
tasks 0
```

---

## 7. Peach download settings

Use the settings API (the GET route is POST-only in this version):

```bash
TOK=$(cat /var/lib/peach/secrets/auth-token)
curl -sS -X POST \
  -H "X-Token: $TOK" \
  -H 'Content-Type: application/json' \
  -d '{"pikpak_root":"R:\\peach\\pikpak","targets":{"pikpak":"/My Pack/Peach"},"wait_hours":168}' \
  http://127.0.0.1:8900/api/configuration/downloads
```

Expected provider row:

```json
{
  "key": "pikpak",
  "configured": true,
  "target": "/My Pack/Peach",
  "root": "R:\\peach\\pikpak"
}
```

The target folder must already exist in PikPak. Create it through the web UI or WebDAV:

```bash
curl -u '<webdav user>:<webdav password>' -X MKCOL \
  'https://dav.mypikpak.com/My%20Pack/Peach'
```

`folder_id()` deliberately does not create folders.

---

## 8. Verification checklist

```bash
# 1. WebDAV mount
systemctl is-active rclone-pikpak.service
ls -la '/mnt/pikpak/My Pack/Peach'

# 2. Peach sees the root
TOK=$(cat /var/lib/peach/secrets/auth-token)
curl -sS -H "X-Token: $TOK" http://127.0.0.1:8900/api/sources | \
  python3 -c 'import sys,json; d=json.load(sys.stdin); print([(s["location"],s["online"]) for s in d["sources"]])'

# 3. Peach configured the provider
curl -sS -X POST -H "X-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{}' http://127.0.0.1:8900/api/configuration/downloads | \
  python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["config"], d["providers"])'

# 4. Direct API read
docker exec peach-peach-1 python -c '
import json
from peach.downloads_pikpak import PikPakClient
v = json.load(open("/data/secrets/follow/download-pikpak.json"))
c = PikPakClient(v, persist=lambda values: None)
print(c.folder_id("/My Pack/Peach"), len(c.tasks()))
c.close()
'
```

A successful setup has all four:
- mount active
- `/media/pikpak` readable in the container
- `providers` contains a `pikpak` row
- `folder_id()` returns an id and `tasks()` returns a list

---

## 9. Troubleshooting

### `Transport endpoint is not connected`

Restart Peach after rclone:

```bash
systemctl restart rclone-pikpak.service
systemctl restart peach.service
```

### `401 captcha_invalid` on file listing or task listing

The live `downloads_pikpak.py` override is missing or the captcha token was rejected. Check:

```bash
grep -n 'GET:/drive/v1/files\|GET:/drive/v1/tasks' \
  /var/lib/peach/overrides/downloads_pikpak.py
```

If the lines are present, the web client constants may have changed. PikPak rotates its web client ID/salts; refresh the web session and update `WEB` in `downloads_pikpak.py`.

### `invalid_grant` / `RefreshToken ... has been refreshed by other process`

The refresh token was rotated by another process. Log in again and replace `download-pikpak.json`, or disable direct downloads and keep only the mount.

### WebDAV returns `401 Unauthorized`

- Confirm the credential is enabled in PikPak → Access & Integrations → WebDAV.
- Regenerate the password in PikPak and update rclone.
- The WebDAV credential is independent of the account password.

### `folder_id` says the folder does not exist

The target must be an existing PikPak folder. Create it with `MKCOL` or the web UI. The provider does not create directories automatically.

### Files appear in `My Pack` but not in Peach

Check the storage root mapping. PikPak's root contains `My Pack`, so the default target is `/My Pack/Peach`; the ledger path is `R:\peach\pikpak\My Pack\Peach\...`. If you mount `pikpak:My Pack` instead, change both the mount and `pikpak_root` consistently.

---

## 10. Security

- The WebDAV username/password are in `rclone.conf` (mode 600). Do not commit them.
- `download-pikpak.json` contains a refresh token. Mode 600, owner 1000.
- Do not put either file in `fork-docs/`, Git, logs, screenshots, or chat.
- Revoke the WebDAV app in PikPak → Access & Integrations if the host is rebuilt.
- PikPak WebDAV is read/write for files but cannot permanently delete or empty the trash; permanent deletion still needs the official app.
