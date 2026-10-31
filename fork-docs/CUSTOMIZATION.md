# Peach Custom Fork — Requirements and Change Log

Owner: `mrlauffy-prog`  
Upstream: `peach-mitao/peach`  
License: AGPL-3.0-or-later (this fork must remain AGPL and keep its source available)

This document is the single source of truth for the custom fork. It records:

- the current production setup and the issues already fixed there;
- the features this fork must add;
- the implementation notes, affected files, and acceptance criteria for each feature;
- the backup/restore and one-click-install design;
- known blockers and decisions.

No implementation should start from this document alone without checking the current upstream state and the tests that protect the affected modules.

---

## 1. Current production setup

Host: Arch Linux VM (Linode), Docker, host networking.

- Peach image: `longmeidao/peach:0.52.0`
- Container: `peach-peach-1`
- Peach listens on `127.0.0.1:8900` because the host kernel has no netfilter modules and Docker cannot publish ports.
- Public access: Cloudflare Tunnel `peach-tunnel.service` → `stuff.aduthekaddu.in`, protected by Cloudflare Access.
- Data directory: `/var/lib/peach` → `/data`
- Media mounts:
  - `/mnt/gdrive/jav` → `/media/gdrive` (`rslave`)
  - `/mnt/pikpak` → `/media/pikpak` (`rslave`)
  - `/home/desktop/Downloads` → `/media/downloads` (kept as staging; not a Peach library root)
- rclone:
  - `rclone-gdrive.service` mounts `gdrive:` at `/mnt/gdrive`.
  - `rclone-pikpak.service` mounts `pikpak:` (WebDAV) at `/mnt/pikpak`.
  - `rclone-gdrive-upload.timer` runs every 10 minutes:
    `rclone move /home/desktop/Downloads gdrive:jav/favourites --min-age 30m`.
  - A dedicated Google OAuth client ID/secret was created and authorized on 2026-10-31. The old shared rclone client ID is no longer used.
  - **Restart Peach after restarting either rclone mount.** The bind mounts use `rslave`, but they do not recover an already-running container from a remounted FUSE endpoint. Without a Peach restart, `/media/gdrive` or `/media/pikpak` reports `Transport endpoint is not connected`.
- PikPak:
  - Premium, WebDAV enabled, credential named `Peach`.
  - rclone remote `[pikpak]` → `https://dav.mypikpak.com`.
  - Peach media source `pikpak = R:\peach\pikpak`, mount `/media/pikpak`, library `PikPak`.
  - Peach download target `/My Pack/Peach`.
  - Direct provider configured; the refresh token is in `secrets/follow/download-pikpak.json`.
  - Full runbook: [PIKPAK.md](PIKPAK.md).
- OneDrive was removed completely on 2026-10-31:
  - config source removed
  - compose volume removed
  - `rclone-onedrive.service` removed
  - `[onedrive]` remote removed from `rclone.conf`
  - 23 document records removed from the Peach database
- Stale local records removed:
  - 8 `.torrent` records
  - 4 missing local video records (`BMW-361`, `JUR-719`, `MANX-030`)
- Dead JavDB subscriptions removed:
  - `21aq`, `91JV`, `K40nQ`, `p3p6b`
  - only `X6ab` remains
- JavDB session:
  - A fresh cookie from the server Chrome profile was imported on 2026-10-31.
  - JavDB `locale=en` produced US dates (`11/17/2026`), which the feed parser rejected.
  - The saved cookie was forced to `locale=zh`; the feed now parses 40 works correctly.
- Current library metadata:
  - 13 main videos were identified from filenames and enriched with JavDB public metadata.
  - 13 remaining 2 MB files are promotional/ad junk with no code.
  - `/performers` now lists performers from those 13 main videos.
  - Performer profile rows were backfilled from archived minnano-av pages on 2026-10-31. The batch source is `auto:performer-profile@manual-*`; see [PERFORMERS.md](PERFORMERS.md).
- Discovery previews:
  - JavTrailers 1080p HLS is preferred, then JavDB 720p, then DMM/prestige page preview.
  - DMM's preview CDN is geo-blocked on this host; do not make it the first source.
  - Full runbook: [TRAILERS.md](TRAILERS.md).
- Safety backups made before the cleanup:
  - `/var/lib/peach/backups/peach-pre-cleanup.20261031-112130.tar.gz`
  - `/var/lib/peach/backups/ledger.pre-cleanup.20261031-112130.db`
  - `/var/lib/peach/backups/host-units.pre-cleanup.20261031-112130.tar.gz`
  - These are not encrypted. Replace them with the encrypted backup system below.

---

## 2. Problems found in the current setup

### 2.1 Credential save returned HTTP 500

Cause: `/data/secrets/follow` and `/data/backups` were owned by root, while Peach runs as UID 1000.

Symptom:

```text
PermissionError: [Errno 13] Permission denied:
'/data/secrets/follow/tmp...'
```

Fixed by:

```bash
chown -R 1000:1000 /var/lib/peach/secrets/follow /var/lib/peach/backups
chmod 700 /var/lib/peach/secrets/follow
```

### 2.2 JavDB feed parsed zero entries with a logged-in session

Cause: the JavDB cookie carried `locale=en`. JavDB then rendered dates as `11/17/2026`, while `feeds.parse_javdb_actor()` only accepts `YYYY-MM-DD`.

Immediate fix: save the JavDB cookie with `locale=zh`.

Permanent fork fix: accept ISO and US date formats in the actor-page parser, and add a regression fixture for both locales.

### 2.3 `/performers` was empty

Cause 1: all 30 videos had no `code` and no `asset_entity` rows.  
Cause 2: `/api/index?kind=performers` only lists performers with counted library assets, so followed performers with only feed discoveries never appear.  
Cause 3: the full `library-processing` job aborted before metadata because `/media/gdrive` timed out under rclone's shared Google Drive quota.

Immediate fixes:

- Identified 13 main videos from filenames.
- Fetched their metadata from JavDB's public API without reading the video files.
- Wrote `code`, titles, dates, duration, studio, series.
- Created performer/studio/series entities and `asset_entity` links.
- `/performers` now lists those performers.

Fork fixes:

- Include followed performers with discoveries even when they have zero local assets.
- Add a filename-only metadata path that does not require reading the media directory first.
- Add a retry/repair action for metadata that failed because of mount timeouts.

### 2.4 Playback and previews time out — fixed

Status: fixed on 2026-10-31 with a dedicated OAuth client ID. The notes below remain as the diagnosis and the fork acceptance criteria.

Cause: rclone used the shared Google Drive OAuth client ID. Google returned:

```text
Quota exceeded for quota metric 'Queries'
limit 'Previous quota: Requests per minute'
service 'drive.googleapis.com'
consumer 'project_number:202264815644'
reason: RATE_LIMIT_EXCEEDED
```

This causes 20–50 second reads and ffprobe/preview timeouts. Cached files play; cold files often fail.

Fix applied:

- Created a dedicated Google OAuth client ID/secret for rclone.
- Re-authorized `gdrive:`.
- Restarted `rclone-gdrive.service` and then `peach.service`.
- Verified a previously slow 7 GB file: 1 MB reads now complete in ~1–2 s, and Peach stream plans return in ~1–4 s.

Fork/ops follow-up:

- Keep the mount timeout/retry flags for future quota incidents.
- Add a health check that surfaces quota errors instead of silently timing out.
- Add a restart helper that restarts Peach after rclone so `rslave` remounts are picked up.

### 2.5 Stale local files and the Downloads/upload conflict

The existing upload timer moves finished torrents from `/home/desktop/Downloads` to `gdrive:jav/favourites` after 30 minutes. Making Downloads a permanent Peach library root while keeping `move` would make local records vanish and later create duplicate GDrive assets.

Chosen policy: **Option A — GDrive is the library; Downloads is staging only.**

- Do not add a `local` media root.
- Keep the rclone upload timer.
- Future torrent downloads appear in Peach after upload and scan.
- OneDrive is removed; no second cloud library is maintained.

### 2.6 Discovery preview video returned 404 / “media could not be loaded” — fixed

Symptom: `/works/MIDA-859` and many other discovery pages showed:

> This media could not be loaded. It may be unavailable, or your browser may not support its format.

Cause: Peach tried DMM’s preview CDN first. `cc3001.dmm.co.jp` returned CloudFront `403` from this host, so `/jav-preview/...` returned `404`. The JavDB public signed HLS preview was available and working, but it tops out at 720p.

Fix applied:

1. **JavTrailers 1080p HLS** is now the first source. It publishes a public master playlist with 432p/720p/1080p renditions on `media.javtrailers.com`. The page's `DVD ID` is checked so a search hit for another title is rejected.
2. JavDB's public signed 720p HLS is the fallback; its signature is refreshed when `t` is older than one hour.
3. DMM / Prestige / JavDB page preview is the last fallback.

New files:

- `src/peach/javtrailers_preview.py`
- `/var/lib/peach/overrides/javtrailers_preview.py` (live mount)

Changed files:

- `src/peach/web_jav_detail.py`
- `/var/lib/peach/overrides/web_jav_detail.py` (live mount)
- `compose.yaml` mounts both overrides read-only

Verified working for:

- `MIDA-859` — 1920x1080 rendition
- `MIDA-849` — 1920x1080 rendition
- `AARM-372` — 1920x1080 rendition
- `MYBA-097` — master + 720p/432p (JavTrailers has no 1080p variant for this title)

Fork change: keep this order in `src/peach/web_jav_detail.py`, add unit tests for the slug/DVD-ID parser, and add a regression test for an expired JavDB `t` signature and a DMM `403`. Full runbook: [TRAILERS.md](TRAILERS.md).

### 2.7 `jav/cast` is already included

`/mnt/gdrive/jav` is mounted to `/media/gdrive`, so Peach already sees:

```text
/media/gdrive/cast
/media/gdrive/favourites
```

Do not add a second storage root for `jav/cast`; that would duplicate the same files under two paths.

### 2.8 Cloud download sources

Peach supports cloud download through:

- PikPak direct API (no CloudDrive2 needed for submission), or
- CloudDrive2 API for 115 and any cloud root that reports offline-download capability.

It does not download to a plain local folder. It also never uploads cloud downloads to Google Drive; files stay in the cloud that performed the offline download.

Immediate production choice: **PikPak direct + PikPak WebDAV mount is configured.** CloudDrive2/115 is not configured. Google Drive remains the library.

### 2.9 PikPak integration

Completed on 2026-10-31:

- Enabled PikPak WebDAV through the account's own API.
- Created a WebDAV credential named `Peach`.
- Added rclone remote `[pikpak]` and `rclone-pikpak.service`.
- Added `/mnt/pikpak` → `/media/pikpak` to Compose.
- Added a `pikpak` storage root and `PikPak` library to `config.toml`.
- Created `/My Pack/Peach` and configured it as the download target.
- Saved the web session token to `secrets/follow/download-pikpak.json`.
- Fixed `captcha_invalid` on read endpoints (`GET /drive/v1/files`, `GET /drive/v1/tasks`) by requesting a captcha token before each paginated read.

Verified:

```text
folder_id("/My Pack/Peach") -> <id>
tasks() -> []
```

Full runbook: [PIKPAK.md](PIKPAK.md).

Known operational constraint: PikPak refresh tokens are single-use. Peach must be the only refresher, or the browser and Peach will invalidate each other. If Peach is refreshed first, re-login to the PikPak web UI when browser access is needed.

### 2.10 Empty performer profiles

Cause: `performer_profile` had 0 rows. The normal `performer_profile_followup` was never queued because the recent `library-processing` runs were explicit asset runs (`include_stock=False`) or their follow-up budget went to avatars.

Fix applied: one-off backfill from archived minnano-av pages, written as `auto:performer-profile@manual-*` with reversible batches. Full details, verification SQL, the Cloudflare limitation, and the required bulk action are in [PERFORMERS.md](PERFORMERS.md).

Fork requirement: a visible **Fill missing profiles** bulk action with progress, source-blocked reporting, idempotency, and no guessing on ambiguous names.

### 2.11 Trailer quality

JavTrailers provides a 1080p HLS master for many titles; JavDB's public preview is 720p and DMM's CDN is blocked here. The fork now prefers JavTrailers, then JavDB, then DMM. See [TRAILERS.md](TRAILERS.md).

---

## 3. Fork goals

1. **English-first UI** without requiring a full frontend rewrite in phase 1.
2. **One-click install** on a fresh machine.
3. **Encrypted backup and restore** built into the deployment.
4. **Performer pagination**: load older JavDB actor pages from the performer page.
5. **Performers index includes followed people** even with no local assets.
6. **Metadata repair** that works from filenames without reading media files.
7. **More metadata providers** (MissAV, Western sites) behind a safe, testable interface.
8. Keep the current deployment running; do not break its data or paths.

Non-goals for phase 1:

- Replacing the upstream database schema wholesale.
- Building a general-purpose plugin marketplace.
- Adding torrent-client integration to Peach itself.
- Redistributing copyrighted media or credentials.

---

## 4. Feature specifications

### 4.1 English-first UI

Current state:

- Upstream source strings are Chinese.
- The current deployment has a runtime translation shim at `/var/lib/peach/web/peach-en.js`.
- `web/index.html` and the page-shell override load this shim before the main bundle.
- The shim walks the DOM, translates text/attributes, and observes mutations.

Fork plan (phase 1):

- Move the shim into the fork (`web/peach-en.js` and a small loader in the page shell).
- Make English the default; keep Chinese available as an option.
- Add missing translations for:
  - settings and configuration pages
  - library-processing errors
  - credential/save errors
  - backup/restore pages
  - new pagination controls
- Translate common **server-side** error messages too, or return stable error codes with English messages.

Long-term (phase 2+):

- Replace the runtime shim with a real i18n dictionary in the React source.
- Keep Chinese strings as the source locale and ship an English catalogue.
- Add a language switcher in Settings.

Acceptance:

- A fresh install opens in English.
- Switching to Chinese still works.
- No raw Chinese text remains in the main navigation, settings, error toasts, or backup UI.
- Server errors shown in the UI have an English message.

### 4.2 One-click install

Deliverables:

- Custom image published to GHCR, e.g. `ghcr.io/mrlauffy-prog/peach-custom:<version>`.
- `compose.yaml` for:
  - Peach
  - backup sidecar
  - optional CloudDrive2
  - optional Cloudflare Tunnel
- `install.sh`:
  - checks Docker and Compose
  - asks for data directory, media roots, port, domain, backup destination
  - creates directories with UID 1000 ownership
  - writes `.env`
  - pulls the image
  - starts the stack
  - prints the login token (`peach token`)
- `restore.sh`:
  - lists encrypted snapshots
  - restores data, config, secrets, overrides, compose, systemd units
  - fixes ownership
  - starts the stack
- `README-INSTALL.md` with screenshots/commands.

Acceptance:

- On a clean Arch/Debian host with Docker, `./install.sh` produces a working Peach in under 10 minutes.
- The installer never writes credentials into the repository.
- Re-running the installer preserves existing data.

### 4.3 Encrypted backup and restore

Recommended implementation: **restic** in a sidecar container, with an rclone backend.

Why restic:

- encryption built in
- deduplication and incremental snapshots
- retention policies
- restore by snapshot/path
- supports `rclone:` repositories

Backup contents:

- SQLite snapshot of `database/ledger.db` (use `sqlite3 .backup`, not a raw copy)
- `config.toml`, `config.previous.toml`
- `secrets/` (cookies, tokens, TLS keys)
- `state/`
- `sources/`
- `review/`
- `generated/covers`
- `generated/cover-thumbs`
- custom `web/` and `overrides/`
- `compose.yaml`, `install.sh`, `restore.sh`
- systemd units
- rclone config
- `/etc/peach` tunnel token/config

Exclude:

- `generated/remote-media` (cache)
- `generated/transcodes`
- logs
- Docker layers

Schedule:

- daily at 03:00 local time
- retention: 7 daily, 4 weekly, 6 monthly

Destination:

- `rclone:gdrive:peach-backup` (outside the `jav` library so Peach never scans it)
- optional second destination (local/NAS) later

Secrets:

- restic password stored in a password manager.
- The sidecar reads `RESTIC_PASSWORD` from an env file with mode `600`.
- Never commit the password or the rclone token.

Restore runbook:

1. Install Docker + rclone on the new machine.
2. Restore rclone config.
3. Run `./restore.sh`.
4. Select the latest snapshot.
5. Verify `PRAGMA integrity_check` on the restored ledger.
6. Start Peach and check login, library paths, and playback.

Acceptance:

- A restore into an empty directory produces a working database and config.
- Credentials work after restore (JavDB cookie, CloudDrive2/PikPak tokens, tunnel token).
- A restore does not require re-scanning the media library.

### 4.4 Performer pagination / full profile

Current behavior:

- Feed polling reads only page 1 of a JavDB actor page (40 works).
- `X6ab` has 897 works across 23 pages.
- There is no UI to fetch older pages.

Desired behavior:

- On a performer page, show:
  - `Load older works` button
  - progress: `Page 2 of 23`
  - optional `Load all older works`
- Each page imports 40 works into `feed_discovery`, linked to the performer.
- Imported historical works are marked **read** so they do not create hundreds of unread notifications.
- New works from normal polling remain unread.

Schema:

- Add `feed_source.next_page INTEGER NOT NULL DEFAULT 2`
- Add `feed_source.total_works INTEGER`
- Add `feed_source.total_pages INTEGER`
- Migration must be reversible and tested on an existing 0.52 database.

Backend:

- Extend the JavDB actor parser to expose the page's total work count.
- Add `POST /api/feeds/actor/older`:
  - body: `{source_id, page?}`
  - fetch the actor page with the existing rate limiter (3 s)
  - parse entries
  - insert missing `feed_item` rows and `feed_discovery` shells
  - link `feed_discovery_entity`
  - set `read_at` for historical rows
  - update `next_page`, `total_works`, `total_pages`
  - return counts and the next page
- Add a background “load all” job using the existing task-run framework, with progress and cancel.

Frontend:

- Add the button/action to the performer hero or the “New works” row.
- Disable while running; show a toast/result.
- After completion, invalidate the feed and entity queries.

Acceptance:

- Loading page 2 adds 40 works and does not increase the unread count.
- Loading all 23 pages completes without violating the 3 s JavDB interval.
- The performer page can show 897 known works.
- A normal feed poll still only checks page 1 for new releases.

### 4.5 Performers index includes followed people

Current query only joins `asset_entity`, so people with only discoveries are invisible.

Fork change:

- For `kind=performers`, include:
  - performers with counted assets (current behavior)
  - performers with an enabled `feed_source`
  - performers with `feed_discovery_entity` rows
- Display count:
  - local asset count when available
  - otherwise discovery count
- Add a badge/label such as `Following` or `Known only`.
- Clicking opens the normal performer page, which already shows discoveries.

Acceptance:

- A followed performer with zero local videos appears on `/performers`.
- A performer with both local videos and discoveries shows the local count and still opens correctly.
- No duplicate rows for the same entity.

### 4.6 Filename-only metadata repair

Problem: `library-processing` checks media source directories before metadata. A slow/rate-limited GDrive mount aborts the whole job.

Fork change:

- Add a “Repair metadata from filenames” action.
- For each video:
  - derive the code from the filename (existing `release_code_from_filename`)
  - fetch metadata from JavDB public API / configured sources
  - write code, title, original title, date, duration, studio, series
  - create performer/studio/series entities and links
  - never read video bytes unless the user asks for previews
- Use the same write-owner and review rules as normal collection.
- Report per-asset failures; do not abort the whole batch.

Acceptance:

- The 26-video test library can be fully coded with GDrive offline.
- Assets that already have user-edited fields are not overwritten.
- The action is idempotent.

### 4.7 Metadata providers

Current built-ins:

- JavDB, JavBus, DMM/FANZA, MGStage, R18.dev, FC2, FC2PPVDB, FC2CMADB, JAVten, JavArchive, 1Pondo, AVBase, Seesaa wikis.

Gaps:

- MissAV is only used for performer links, not metadata.
- Western sites have partial identity/artwork support, not general metadata scraping.
- Custom metadata is JSON-only: no HTML/CSS selectors, no JSON-LD, no multi-step fetch.

Fork plan:

1. Add a **declarative HTML source** format:
   - URL template with `{code}`
   - CSS selectors for code, title, original title, performers, studio, series, release date, duration, tags, cover
   - optional detail-page follow-up
   - explicit host allowlist, timeout, size limit, rate limit
   - no JavaScript execution, no arbitrary redirects
2. Add specific adapters:
   - MissAV metadata page
   - one or two Western sites (IAFD/AdultEmpire/Babepedia-style, subject to terms)
3. Register adapters in:
   - `src/peach/sources/<site>.py`
   - `src/peach/sources/__init__.py`
   - `src/peach/scraping_access.py` (`SOURCES`)
   - metadata chain/routing tables
   - tests and fixtures
4. Add English docs and examples for adding a site.

Acceptance:

- A user can add a new JSON or HTML source without editing Python.
- A malformed selector fails with a clear error, not a crash.
- Source rate limits and cooldowns are respected.
- No custom source can read private/local addresses.

### 4.8 Download providers

Current providers:

- PikPak direct
- 115 through CloudDrive2
- any CloudDrive2 cloud root that reports `can_offline`

Not supported as Peach download targets:

- Google Drive (no offline-magnet API)
- OneDrive (no offline-magnet API)
- plain local folders

Fork plan:

- Keep 115/PikPak as first-class providers.
- Add a provider interface so new offline services can be added without touching the UI:
  - `submit(magnet, target)`
  - `status(task)`
  - `cancel(task)`
  - `landed(task)`
- Document that cloud-to-cloud copy to GDrive is a separate workflow:
  - CloudDrive2 Core Pro copy/backup, or
  - an rclone/WebDAV job.
- Do not pretend that Peach uploads PikPak/115 downloads to GDrive.

Acceptance:

- A disabled provider does not appear in the download dialog.
- A provider error is classified with an actionable message.
- Provider credentials never appear in logs or API responses.

### 4.9 Google Drive quota fix

Required user action:

1. Create a Google Cloud project.
2. Enable Google Drive API.
3. Configure OAuth consent screen.
4. Create a Desktop OAuth client ID.
5. Put `client_id` and `client_secret` into `rclone.conf`.
6. Re-authorize `gdrive:`.
7. Restart `rclone-gdrive`.

Fork/ops additions:

- `install.sh` asks whether to use an existing `rclone.conf`.
- A diagnostics card shows:
  - rclone version
  - remote auth status
  - last quota error
  - mount read latency probe
- Mount flags:
  - `--vfs-cache-mode writes`
  - `--vfs-read-chunk-size 8M`
  - `--vfs-read-chunk-size-limit 64M`
  - `--timeout 15s`
  - `--contimeout 5s`
  - `--low-level-retries 3`
- Optional full-file cache for selected folders.

Acceptance:

- A cold 1 MB read from a previously slow file completes in < 5 s.
- `ffprobe` on a 7 GB file completes within 20 s.
- The diagnostics card shows a clear error when the shared client ID quota is hit.

### 4.10 Bulk performer profile enrichment

Current state: profiles are filled by `performer_profile_followup`, one entity per task. It is slow, easy to starve behind avatar jobs, and blocked entirely when the source requires a browser the container does not have.

Required API:

```text
POST /api/performers/profiles/backfill
  {"entity_ids": [1, 2, ...], "refresh": false}   # omit ids = all missing
GET  /api/performers/profiles/backfill
```

Required behaviour:

- Enqueue through the existing follow-up/task system, not the HTTP thread.
- One task per entity, deduplicated by `entity_id`.
- Respect source rate limits and cooldowns; a 403 must not be retried in a loop.
- Skip human-authored rows.
- Bind the source id even when the profile page is partial.
- Record `source_url` and batch id for reversibility.
- Return partial success with `checked`, `written`, `missing`, `blocked`, `failed`.
- Add a **Fill missing profiles** button on `/performers`.

Acceptance:

- A batch of 60 completes with per-row outcomes; one bad row does not fail the batch.
- Re-running the same batch does not duplicate rows.
- Ambiguous names are reported, never assigned by guess.
- A source block is visible in the UI with the source name and a retry hint.

---

## 5. CloudDrive2 and PikPak reference

### PikPak

- Cloud storage with offline download.
- Peach submits magnets directly to PikPak's API.
- Files stay in PikPak.
- PikPak is mounted as the `PikPak` media root through rclone WebDAV (`/mnt/pikpak` → `/media/pikpak`).
- Current target: `/My Pack/Peach`; ledger prefix: `R:\peach\pikpak`.
- Free tier is small (about 6 GB); paid tiers are needed for videos.
- PikPak's web token needs captcha tokens even for read endpoints; the fork supplies them for file and task listing.
- Refresh tokens are single-use; only one process may refresh them. See [PIKPAK.md](PIKPAK.md).

### CloudDrive2

- Cloud-drive aggregator and mount layer, not storage.
- Connects 115, PikPak, Google Drive, OneDrive, Aliyun, WebDAV, SMB, etc.
- Exposes a gRPC API; Peach uses an API token.
- Free tier: 2 cloud accounts + 1 local mount.
- Paid Core: unlimited clouds/mounts, cross-cloud copy, multi-cloud backup, encryption.
- Offline download is available through its API; quotas come from 115/PikPak.
- Google Drive can be mounted, but it has no offline-magnet API, so it is not a Peach download target.

---

## 6. Phased delivery

### Phase 0 — current setup stabilization (done)

- Fix credential directory permissions.
- Remove OneDrive completely.
- Remove dead JavDB feeds.
- Import a fresh JavDB session and force `locale=zh`.
- Remove stale local records.
- Backfill metadata for 13 main videos from filenames.
- Verify `/performers` and the remaining subscription.
- Create pre-change backups.
- Configure PikPak: WebDAV credential, rclone mount, Peach `PikPak` library, download target, direct-provider captcha fix.
- Prefer JavTrailers 1080p previews with JavDB/DMM fallback.
- Backfill performer profiles from archived minnano-av pages.

### Phase 1 — fork packaging and English

- Fork and clone under `mrlauffy-prog`.
- Move the English shim into the fork.
- Make English the default.
- Add one-click install scaffolding.
- Add encrypted backup sidecar and restore script.
- Add fork documentation (this file).

### Phase 2 — performer pagination and index

- Add `next_page`/`total_works` schema.
- Add `/api/feeds/actor/older`.
- Add UI button and progress.
- Include followed performers in `/performers`.
- Add tests.

### Phase 3 — metadata repair and providers

- Add filename-only metadata repair.
- Add declarative HTML metadata source.
- Add MissAV adapter.
- Add one or two Western adapters.
- Add tests and docs.

### Phase 4 — download provider extension

- Provider interface.
- Optional CloudDrive2/PikPak setup wizard.
- Document GDrive copy/backup workflows.
- Add tests.

---

## 7. Files likely to change

| Area | Files |
|---|---|
| Feed pagination | `src/peach/feeds.py`, `src/peach/web_feeds.py`, `migrations/*`, `frontend/src/react/entity-hero/*`, `frontend/src/react/feed-new/*` |
| Performer index | `src/peach/web_entity.py`, `frontend/src/react/index/*`, tests |
| Metadata repair | `src/peach/library_processing.py`, `src/peach/web_library_processing.py`, `src/peach/web_router.py` |
| Providers | `src/peach/sources/*`, `src/peach/scraping_access.py`, `src/peach/metadata_routes.py`, `docs/SOURCING.md` |
| English | `web/index.html`, `web/peach-en.js`, `src/peach/web_entry.py`, `src/peach/routes_pages.py` |
| Backup | `compose.yaml`, `scripts/backup.sh`, `scripts/restore.sh`, `Dockerfile` or sidecar image |
| Installer | `install.sh`, `.env.example`, `compose.yaml`, `README-INSTALL.md` |
| GDrive diagnostics | `src/peach/diagnostics.py`, settings page, systemd unit |
| PikPak | `src/peach/downloads_pikpak.py`, `src/peach/downloads_channels.py`, `compose.yaml`, `config.toml`, `rclone-pikpak.service` |
| Trailers | `src/peach/javtrailers_preview.py`, `src/peach/web_jav_detail.py`, `src/peach/preview_cache.py`, `/jav-preview` route |
| Performer profiles | `src/peach/performer_profile_followup.py`, `src/peach/minnano_av.py`, `src/peach/performer_profiles.py`, `/performers` UI |

---

## 8. Testing and acceptance

- `pytest` / existing test suite must pass.
- Add fixtures for:
  - JavDB actor page with ISO dates (`2026-11-17`)
  - JavDB actor page with US dates (`11/17/2026`)
  - actor page with 897 works across 23 pages
  - performer with discoveries but zero assets
  - filename-only metadata repair with a dead media mount
- Add an end-to-end Docker test:
  - install
  - create data
  - restore
  - scan a synthetic file
  - play a synthetic video
- Backup restore test must verify `PRAGMA integrity_check = ok`.

---

## 9. Decisions and blockers

- GitHub owner: `mrlauffy-prog` (active).
- Fork URL: `https://github.com/mrlauffy-prog/peach`.
- License: AGPL-3.0-or-later; keep source available.
- OneDrive: removed; do not re-add.
- Downloads policy: GDrive is the library; Downloads is staging only.
- GDrive OAuth client ID: created and authorized on 2026-10-31; keep the client secret in `rclone.conf` only, never in Git.
- rclone restart rule: restart Peach after any `rclone-gdrive` or `rclone-pikpak` restart to refresh the bind mount.
- JavDB session: must be refreshed when JavDB expires it. The fork should detect login pages and explain how to refresh.
- PikPak: WebDAV mount and direct provider are configured. Keep the WebDAV credential separate from the account password. Only one process may refresh the PikPak token.
- PikPak captcha: read endpoints now request a captcha token; if PikPak changes its web client constants, refresh the session and update `WEB` in `downloads_pikpak.py`.
- Performer profiles: minnano-av and avwikidb are Cloudflare-blocked from the container. The backfill used archived snapshots; the long-term fork fix is a bulk action plus a browser/host fallback or a different source.
- Trailer source: JavTrailers is not an API; it can change. Keep the DVD-ID identity check and the JavDB/DMM fallback.
- No secrets, cookies, tokens, or database dumps belong in this repository.

---

## 10. Current setup runbook after changes

```bash
# Peach
systemctl status peach.service
docker logs --tail 100 peach-peach-1

# GDrive mount
systemctl status rclone-gdrive.service
systemctl status rclone-gdrive-upload.timer

# PikPak mount
systemctl status rclone-pikpak.service
ls -la '/mnt/pikpak/My Pack/Peach'

# Cloudflare tunnel
systemctl status peach-tunnel.service

# Backups
ls -lh /var/lib/peach/backups
```

Important paths:

- `/var/lib/peach/config.toml`
- `/var/lib/peach/database/ledger.db`
- `/var/lib/peach/secrets/`
- `/var/lib/peach/secrets/follow/download-pikpak.json`
- `/var/lib/peach/backups/`
- `/opt/peach/compose.yaml`
- `/home/desktop/.config/rclone/rclone.conf`
- `/etc/systemd/system/peach*.service`
- `/etc/systemd/system/rclone-*.service`
- `/etc/peach/`
- `/var/lib/peach/overrides/web_jav_detail.py`
- `/var/lib/peach/overrides/javtrailers_preview.py`
- `/var/lib/peach/overrides/downloads_pikpak.py`
