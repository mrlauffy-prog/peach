# rclone + Google Drive setup

This is the runbook for the rclone side of Peach on this host. It covers installation, OAuth, the mount, the upload timer, restart order, and the Google verification problem.

---

## 1. Layout on this host

```text
Google Drive
  └── jav/
      ├── cast/
      └── favourites/

Host mount:
  gdrive:  ->  /mnt/gdrive

Peach container:
  /mnt/gdrive/jav  ->  /media/gdrive
```

`/mnt/gdrive/jav` is the Peach media root. It already contains **both** `jav/cast` and `jav/favourites`. Do **not** add a separate mount for `jav/cast` unless you intentionally want a separate Peach library; adding it would duplicate the same files under two storage roots.

Verified paths:

```text
Host:       /mnt/gdrive/jav/cast
Container:  /media/gdrive/cast
```

---

## 2. Install rclone

Arch:

```bash
sudo pacman -S rclone
```

Debian/Ubuntu:

```bash
sudo apt install rclone
```

macOS (for the authorization step):

```bash
brew install rclone
```

---

## 3. Create a Google OAuth client

Do **not** use a service account. A service account has its own Drive quota and cannot see your personal Drive unless you share everything with it.

1. Open <https://console.cloud.google.com/>.
2. Create a project, for example `peach-rclone`.
3. Enable **Google Drive API**:
   **APIs & Services → Library → Google Drive API → Enable**.
4. Open **Google Auth Platform** (older console: **OAuth consent screen**).
5. Configure:
   - **User type / Audience:** External
   - **App name:** `Peach rclone`
   - **User support email:** your Gmail
   - **Developer contact email:** your Gmail
6. Add the scope:
   ```text
   https://www.googleapis.com/auth/drive
   ```
7. If the app stays in **Testing**, add your Gmail under **Test users**.
8. Go to **Clients → Create client**:
   - Application type: **Desktop app**
   - Name: `Peach rclone desktop`
9. Copy:
   - **Client ID** — `....apps.googleusercontent.com`
   - **Client secret** — `GOCSPX-...`

---

## 4. Add the client to rclone

Edit the rclone config:

```bash
sudo -u desktop nano /home/desktop/.config/rclone/rclone.conf
```

Under `[gdrive]`:

```ini
[gdrive]
type = drive
client_id = YOUR_CLIENT_ID.apps.googleusercontent.com
client_secret = YOUR_CLIENT_SECRET
scope = drive
token = {...}
```

Keep the file private:

```bash
chown desktop:desktop /home/desktop/.config/rclone/rclone.conf
chmod 600 /home/desktop/.config/rclone/rclone.conf
```

---

## 5. Authorize / re-authorize

The token must be issued for the new client ID. Adding `client_id` alone is not enough.

### Option A — authorize from a Mac (recommended when the server has no browser)

On the Mac:

```bash
rclone authorize "drive" "YOUR_CLIENT_ID" "YOUR_CLIENT_SECRET"
```

Sign in with the Google account that owns the Drive, approve access, and copy the JSON token printed in the terminal.

On the server:

```bash
sudo -u desktop rclone config --config /home/desktop/.config/rclone/rclone.conf
```

Choose:

```text
e) Edit existing remote
gdrive
```

Paste the JSON token when asked. Save.

### Option B — authorize on the server desktop

The server has an Xfce desktop on `DISPLAY=:77`:

```bash
sudo -u desktop env \
  DISPLAY=:77 \
  XAUTHORITY=/run/remote-desktop/Xauthority \
  HOME=/home/desktop \
  XDG_CONFIG_HOME=/home/desktop/.config \
  rclone config reconnect gdrive: \
  --config /home/desktop/.config/rclone/rclone.conf
```

Chrome opens on the server desktop. Sign in there.

If asked:

```text
Configure this as a Shared Drive (Team Drive)?
```

Answer **No** for a normal personal Drive. If you answer Yes and have no Shared Drives, rclone reports “No Shared Drives found”.

---

## 6. Restart order — important

After any rclone mount restart:

```bash
sudo systemctl restart rclone-gdrive.service
sudo systemctl restart peach.service
```

Why: the Peach container bind-mounts `/mnt/gdrive/jav` with `rslave`. When rclone is restarted, the FUSE mount is replaced. An already-running container can be left pointing at the old mount and reports:

```text
Transport endpoint is not connected
```

Peach then returns `offline` even though the host mount is fine. Restarting Peach re-establishes the container mount.

---

## 7. Verify

```bash
systemctl status rclone-gdrive.service --no-pager
sudo -u desktop rclone about gdrive: --config /home/desktop/.config/rclone/rclone.conf
```

Expected:

```text
Total:   5 TiB
Used:    ...
Free:    ...
```

Test a cold file read:

```bash
time timeout 30 dd \
  if='/mnt/gdrive/jav/cast/hinako mori/MIDA-849/4k688.com@MIDA-849.mp4' \
  of=/dev/null bs=1M count=1
```

Expected: roughly 1–3 seconds. If it takes 20–50 seconds, check the Google quota/client-ID section.

Test Peach:

```bash
TOK=$(cat /var/lib/peach/secrets/auth-token)
curl -sS -H "X-Token: $TOK" \
  'http://127.0.0.1:8900/api/stream-plan?id=14&session=test'
```

Expected:

```json
{"protocol":"range","mime_type":"video/mp4", ...}
```

---

## 8. Upload timer

The host already has:

```ini
# /etc/systemd/system/rclone-gdrive-upload.service
ExecStart=/usr/bin/rclone move /home/desktop/Downloads gdrive:jav/favourites \
  --config /home/desktop/.config/rclone/rclone.conf \
  --min-age 30m --exclude *.part --exclude *.tmp --exclude *.downloading \
  --exclude *.!qB --exclude *.torrent --delete-empty-src-dirs --log-level INFO
```

Timer:

```ini
# /etc/systemd/system/rclone-gdrive-upload.timer
[Timer]
OnBootSec=5min
OnUnitActiveSec=10min
Persistent=true
```

This is why `/home/desktop/Downloads` is **staging only**, not a permanent Peach library root. Finished torrents move to `gdrive:jav/favourites` after 30 minutes.

Manual test:

```bash
systemctl start rclone-gdrive-upload.service
journalctl -u rclone-gdrive-upload.service -n 30 --no-pager
```

---

## 9. Google verification / “Publish” fails

Google requires OAuth verification for apps that request sensitive scopes such as full Drive access. For a personal single-user setup, **do not publish** the app unless you want to complete Google’s verification process.

Options:

### A. Keep the app in Testing (normal personal setup)

- No Google verification.
- Add your Gmail under **Test users**.
- Works immediately.
- **Refresh tokens expire after 7 days.** Re-authorize when Peach/rclone reports authentication failure.

Re-authorization is the same command as above:

```bash
sudo -u desktop env \
  DISPLAY=:77 \
  XAUTHORITY=/run/remote-desktop/Xauthority \
  HOME=/home/desktop \
  XDG_CONFIG_HOME=/home/desktop/.config \
  rclone config reconnect gdrive: \
  --config /home/desktop/.config/rclone/rclone.conf
```

Or use `rclone authorize` on the Mac and paste the token.

### B. Publish to Production

- Click **Publish app**.
- Google may require verification for the Drive scope.
- Verification asks for privacy policy, homepage, demo video, scope justification, etc.
- Not worth it for one person.

### C. Use a Google Workspace Internal app

If the Drive belongs to Google Workspace (not personal Gmail):

- Set **User type: Internal**.
- No verification is required.
- Refresh tokens do not have the 7-day Testing expiry.

### D. Do not use a service account

A service account has its own storage quota and cannot read your personal Drive unless every folder is explicitly shared with it. It is the wrong tool for this setup.

### What the fork should do

- Detect `invalid_grant` / `unauthorized_client` / 401 from Google.
- Show an English “Google Drive authorization expired — reconnect rclone” card.
- Provide a one-click reauth helper that runs `rclone config reconnect` or accepts a pasted `rclone authorize` token.
- Document that Testing-mode tokens expire every 7 days.

---

## 10. Troubleshooting

### `Quota exceeded ... project_number:202264815644`

This is rclone’s shared client ID. You are not using your own client ID, or the token was issued with the old one.

Check:

```bash
python3 - <<'PY'
import configparser
c=configparser.ConfigParser(); c.read('/home/desktop/.config/rclone/rclone.conf')
s=c['gdrive']
print('client_id_set', bool(s.get('client_id')))
print('token_present', bool(s.get('token')))
PY
```

Then re-authorize.

### `Transport endpoint is not connected`

Restart Peach after rclone:

```bash
sudo systemctl restart peach.service
```

### `invalid_grant` / `unauthorized_client`

The refresh token is expired or belongs to a deleted/old OAuth client. Re-authorize.

### 403 from `cc3001.dmm.co.jp`

That is DMM’s preview CDN, not Google Drive. DMM geo-blocks some hosts. Peach now prefers JavDB’s signed HLS preview and falls back to DMM only if JavDB has no preview.

### Slow reads but no quota error

Check the mount flags and the Google client ID. The current host uses the defaults; optional hardening:

```ini
--timeout 30s
--contimeout 10s
--low-level-retries 3
--vfs-read-chunk-size 8M
--vfs-read-chunk-size-limit 64M
```

Do not set these blindly on a different machine; measure first.

---

## 11. Security

- `rclone.conf` contains OAuth refresh tokens. Mode `600`, never commit.
- The OAuth client secret for a Desktop app is not a password, but still keep it private.
- Do not put `rclone.conf`, cookies, tunnel tokens, or database dumps in Git.
- If you publish the fork, keep the AGPL source available and never include real credentials.
