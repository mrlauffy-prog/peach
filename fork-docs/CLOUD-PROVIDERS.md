# Cloud providers: PikPak, 115, CloudDrive2

This note explains which service does what, which one to choose, and the registration links.

---

## 1. What each product is

| Product | What it is | What it does for Peach |
|---|---|---|
| **PikPak** | Cloud storage with offline download | Stores files and can fetch magnets/torrents into the PikPak account |
| **115** | Chinese cloud storage with offline download | Stores files and can fetch magnets/torrents into the 115 account |
| **CloudDrive2** | Cloud-drive aggregator and mount layer | Mounts cloud accounts as local disks and exposes the API Peach uses for 115/offline operations |
| **Google Drive** | Cloud storage | Peach's main library, mounted through rclone; no offline-magnet API |

CloudDrive2 is **not** storage. It does not give you a drive by itself.

---

## 2. Recommended choice for this setup

### PikPak Premium + official WebDAV (current)

Why:

- PikPak is practical to register and pay for outside China (card/PayPal/crypto).
- Peach talks to PikPak directly for submission.
- Premium includes official WebDAV; no CloudDrive2 subscription is needed to mount PikPak.
- rclone mounts `https://dav.mypikpak.com` at `/mnt/pikpak`; Peach reads it as `/media/pikpak`.
- Google Drive stays the main library through rclone.
- 10 TB regional annual pricing is around **$57.59/year**; Global Premium costs more. Check the checkout price for your country.

Current deployment: PikPak is mounted and configured. See [PIKPAK.md](PIKPAK.md). CloudDrive2 is **not** required for PikPak and is not currently running.

### 115 + CloudDrive2

Choose this only if you can easily register and pay for 115. It is often cheaper per TB, but registration is China-focused.

115 registration:

- Official site: <https://115.com/>
- Registration page: <https://aq.115.com/index/register>
- VIP/purchase: <https://vip.115.com/?c=1>
- Developer/API platform: <https://open.115.com/>

The current registration page asks for a **+86 Chinese phone number**. If you do not have one, 115 is not practical; use PikPak.

---

## 3. How Peach uses them

### PikPak

1. Peach submits a magnet to PikPak's API.
2. PikPak downloads it into your PikPak account.
3. The file stays on PikPak.
4. PikPak is mounted through **official WebDAV** (rclone) and declared as a `pikpak` media root.
5. Peach reads/plays it from that mount.

The current target is `/My Pack/Peach`; the ledger prefix is `R:\peach\pikpak`.

PikPak's web token needs captcha tokens even for read endpoints. The fork supplies them for file and task listing; otherwise the provider reports `captcha_invalid`.

Peach does **not** download the file to this host and does **not** upload it to Google Drive.

### 115 through CloudDrive2

1. Peach submits the offline task through CloudDrive2 to 115.
2. The file stays on 115.
3. CloudDrive2 mounts 115 as a local folder.
4. Peach reads/plays it from the CloudDrive2 mount.

### Google Drive

- Google Drive has no offline-magnet API.
- It can be a mount/backup target, not a torrent download target.
- Torrents downloaded by qBittorrent are moved to `gdrive:jav/favourites` by the existing rclone timer.

---

## 4. CloudDrive2 tiers

- **Basic free:** up to 2 cloud accounts, 1 local mount. Browsing, playback, transfers, backup.
- **Core monthly:** ¥4.99/month.
- **Core yearly:** ¥49.99/year.
- **Lifetime:** ¥499 (and a lifetime-lite tier).
- Cross-cloud copy, multi-cloud backup, encrypted folders, file notifications, and more than 2 clouds are paid Core Pro features.

CloudDrive2 is only needed for 115 or for a cloud account without a usable native/WebDAV mount. PikPak does not need it.

---

## 5. Automatic copy to Google Drive?

- **qBittorrent → Downloads → GDrive:** already automated by `rclone-gdrive-upload.timer`.
- **PikPak/115 → GDrive:** not done by Peach. Options:
  - CloudDrive2 cloud-to-cloud copy/backup (Core Pro), or
  - a separate rclone/WebDAV job.
- Copying through a local mount works but uses local bandwidth and temporary disk.

---

## 6. Peach download provider support

Built in:

- PikPak direct
- 115 through CloudDrive2
- any CloudDrive2 cloud root that reports `can_offline`

Not built in:

- Google Drive offline download (not supported by Google)
- OneDrive offline download
- plain local-folder "cloud download"

Adding a new direct provider (TorBox, Real-Debrid, Premiumize, etc.) requires code changes; see `CUSTOMIZATION.md` §4.8.
