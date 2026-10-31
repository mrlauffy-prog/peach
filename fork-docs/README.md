# Peach custom fork docs

Start here:

| Document | Contents |
|---|---|
| [CUSTOMIZATION.md](CUSTOMIZATION.md) | Full requirements, current setup, feature backlog, phases, tests, and acceptance criteria |
| [RCLONE.md](RCLONE.md) | rclone install, Google OAuth client, authorization, mount, upload timer, restart order, troubleshooting, and the Google verification problem |
| [CLOUD-PROVIDERS.md](CLOUD-PROVIDERS.md) | PikPak vs 115 vs CloudDrive2, costs, how Peach uses each, and registration links |
| [PIKPAK.md](PIKPAK.md) | Live PikPak setup: WebDAV, rclone mount, Peach media root, download credential, captcha fixes, verification |
| [TRAILERS.md](TRAILERS.md) | JavTrailers 1080p HLS integration, URL/slug rules, proxy flow, verification |
| [PERFORMERS.md](PERFORMERS.md) | Why performer profiles were empty, the 2026-10-31 backfill, and the required bulk-profile feature |

Short version of the current production setup:

- Peach runs in Docker with host networking on `127.0.0.1:8900`.
- Public access is through Cloudflare Tunnel + Access.
- Google Drive is mounted with rclone at `/mnt/gdrive/jav` and exposed to Peach as `/media/gdrive`.
- `/mnt/gdrive/jav` already includes both `jav/cast` and `jav/favourites`; no separate cast mount is needed.
- PikPak is mounted with rclone at `/mnt/pikpak` and exposed to Peach as `/media/pikpak`; it is a separate `PikPak` library.
- `/home/desktop/Downloads` is staging only. The rclone upload timer moves finished files to `gdrive:jav/favourites`.
- OneDrive was removed completely.
- JavDB uses a dedicated cookie; it must include `locale=zh` or the actor-page parser fails on US dates.
- Discovery trailers prefer JavTrailers' public 1080p HLS master; JavDB's 720p public preview is the fallback.
- Downloads policy: Google Drive is the library; PikPak is the optional cloud-download provider. PikPak downloads stay in PikPak.
- Performer profile rows were backfilled from archived minnano-av pages; incomplete rows are a manual-review/source-blocking issue, not a reason to guess.

Do not commit credentials, cookies, tokens, `rclone.conf`, or database dumps to this repository.
