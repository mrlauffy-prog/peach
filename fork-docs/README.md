# Peach custom fork docs

Start here:

| Document | Contents |
|---|---|
| [CUSTOMIZATION.md](CUSTOMIZATION.md) | Full requirements, current setup, feature backlog, phases, tests, and acceptance criteria |
| [RCLONE.md](RCLONE.md) | rclone install, Google OAuth client, authorization, mount, upload timer, restart order, troubleshooting, and the Google verification problem |
| [CLOUD-PROVIDERS.md](CLOUD-PROVIDERS.md) | PikPak vs 115 vs CloudDrive2, costs, how Peach uses each, and registration links |

Short version of the current production setup:

- Peach runs in Docker with host networking on `127.0.0.1:8900`.
- Public access is through Cloudflare Tunnel + Access.
- Google Drive is mounted with rclone at `/mnt/gdrive/jav` and exposed to Peach as `/media/gdrive`.
- `/mnt/gdrive/jav` already includes both `jav/cast` and `jav/favourites`; no separate cast mount is needed.
- `/home/desktop/Downloads` is staging only. The rclone upload timer moves finished files to `gdrive:jav/favourites`.
- OneDrive was removed completely.
- JavDB uses a dedicated cookie; it must include `locale=zh` or the actor-page parser fails on US dates.
- Downloads policy: Google Drive is the library; PikPak or 115 is the optional cloud-download provider.

Do not commit credentials, cookies, tokens, `rclone.conf`, or database dumps to this repository.
