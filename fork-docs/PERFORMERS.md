# Performer profiles

This note explains why performer pages were empty and what was backfilled on 2026-10-31.

---

## 1. Symptom

`/performers` listed the 60 performer entities created from the 13 identified videos, but opening a performer showed no birth date, height, measurements, debut, birthplace, or social links.

The entities themselves were fine:

- `entity.kind = 'performer'`
- names, gender, and avatar URL present
- `asset_entity` links present

The missing data was in `performer_profile`, a separate table keyed by `entity_id`.

---

## 2. Why it happened

`performer_profile` is written by the **补女优资料** follow-up (`performer_profile_followup.py`).

That follow-up is declared only when a full `library-processing` run settles. The recent processing runs were:

- explicit 8-asset or 2-asset runs (`asset_ids` set), which call
  `_entity_followups(..., include_stock=False)`, or
- runs whose 64-follow-up budget was consumed by avatar jobs.

No `performer-profile:*` follow-up row was ever queued. The 60 entities were created by the filename/metadata backfill *after* the last full scan, so the normal `plan()` path did not see them either.

`performer_profile` therefore had **0 rows**, not merely empty fields.

---

## 3. Source and parser

The built-in source is **みんなのAV** (`minnano-av.com`):

- search by performer name
- follow the unique actress page (`/actressNNNNNN.html`)
- parse the `act-profile` table
- write one row to `performer_profile`

The parser already exists in the fork:

```text
src/peach/minnano_av.py
src/peach/performer_profiles.py
src/peach/performer_profile_followup.py
```

Fields written:

```text
kana, romaji, birth_date, height_cm, bust_cm, cup, waist_cm, hip_cm,
blood_type, birthplace, hobbies, debut_year, active_until,
debut_title, debut_date, blog_url, site_url, tags_json, raw_json
```

The follow-up also binds the minnano-av actress id as `entity_external_ref(provider='minnano-av')`, so future runs can go straight to the profile page.

### Important: minnano-av is Cloudflare-protected

Direct requests from this host return `403` / “Just a moment…”. The built-in browser fallback needs a browser inside the Peach container; the container has no Chrome and no `DISPLAY`, so `browser_login` and the browser transport are unavailable there.

`/performers` profile enrichment therefore needs one of:

1. a Peach host with a real browser and `DISPLAY`, or
2. a one-off maintenance backfill over a path that is not blocked, or
3. a different profile source.

---

## 4. Backfill performed on 2026-10-31

A one-off maintenance script ran on the host (not in the container) and wrote profiles with:

```text
source = auto:performer-profile@manual-yahoo-20261031
```

The first attempt used `manual-jina-20261031` and `manual-wayback-20261031` for a few rows. All three batches are reversible.

The script:

1. searches DuckDuckGo HTML (`POST https://html.duckduckgo.com/html/`) for
   `site:minnano-av.com <name>`
2. extracts the unique `actressNNNNNN.html` id
3. fetches the last working Wayback Machine snapshot with
   `https://web.archive.org/web/<timestamp>id_/<url>` and `curl --compressed`
4. parses it with `peach.minnano_av.profile()`
5. verifies the page name/aliases match the ledger entity
6. writes `performer_profile` and binds the `minnano-av` external id in one transaction

The batch is reversible:

```bash
# list what was written
sqlite3 /var/lib/peach/database/ledger.db \
  "SELECT entity_id, source, source_url FROM performer_profile
   WHERE source LIKE 'auto:performer-profile@manual-%';"

# revert the whole batch
python3 scripts/revert_auto_landing.py --source auto:performer-profile@manual-wayback-20261031
python3 scripts/revert_auto_landing.py --source auto:performer-profile@manual-jina-20261031
python3 scripts/revert_auto_landing.py --source auto:performer-profile@manual-yahoo-20261031
```

The reusable maintenance script is now in the fork:

```text
fork-docs/scripts/minnano_profile_backfill.py
```

Usage:

```bash
# Back up first
sqlite3 /var/lib/peach/database/ledger.db \
  ".backup '/var/lib/peach/backups/ledger.before-profile-backfill.$(date +%Y%m%d-%H%M).db'"

cd /home/desktop/projects/peach
PYTHONPATH=src python3 fork-docs/scripts/minnano_profile_backfill.py
```

HTML snapshots are cached under:

```text
/var/lib/peach/generated/provider-cache/minnano-yahoo/
```

Backups made before the run:

```text
/var/lib/peach/backups/ledger.before-profile-backfill.20261031-1435.db
/var/lib/peach/backups/ledger.before-profile-wayback.20261031-1448.db
```

### Verification

```bash
sqlite3 -readonly /var/lib/peach/database/ledger.db <<'SQL'
SELECT count(*) AS rows FROM performer_profile;
SELECT count(*) AS filled
FROM performer_profile
WHERE coalesce(birth_date,'') <> '' OR coalesce(height_cm,0) > 0;
SELECT e.canonical_name, p.birth_date, p.height_cm, p.debut_year
FROM entity e JOIN performer_profile p ON p.entity_id=e.id
ORDER BY e.id LIMIT 20;
SQL
```

If a performer still has no profile:

- the name may not have an archived minnano-av page;
- the page may be a different person with the same name;
- the actor may be male (the 60 entities include male performers from the videos);
- the source may not list them at all.

Those are **manual review** cases, not reasons to guess a profile.

---

## 5. Fork requirement: bulk profile enrichment

The current one-at-a-time follow-up is too slow and too easy to starve behind avatar jobs. Add a visible bulk action.

### API

```text
POST /api/performers/profiles/backfill
body: { "entity_ids": [1,2,...], "refresh": false }   # omit ids = all missing
GET  /api/performers/profiles/backfill
```

The GET returns:

```json
{
  "status": "running",
  "checked": 12,
  "total": 60,
  "written": 10,
  "missing": 1,
  "blocked": 0,
  "failed": 1,
  "sources": {"minnano-av": "ok", "avwikidb": "blocked"},
  "current": "松本いちか"
}
```

### Behaviour

- Enqueue through the existing follow-up/task system; do not write from the HTTP thread.
- One task per performer, deduplicated by `entity_id`.
- Respect the source's rate limit and cooldown; do not retry a 403 in a loop.
- Skip human-authored rows (`source` not starting with `auto:`).
- Bind the source id even when the profile page is incomplete.
- Record the exact source URL and batch id for reversibility.
- Report partial success; one missing profile must not fail the batch.
- Add a "Refresh profiles older than N days" option.

### UI

- Add **Fill missing profiles** on `/performers`.
- Show progress and a result summary.
- Link failed rows to the performer, not a generic error page.
- Distinguish:
  - `not found`
  - `source blocked / captcha`
  - `name ambiguous`
  - `human row, not touched`

### Tests

- A performer with an existing human row is not overwritten.
- Two performers with the same name do not receive each other's profile.
- A source 403 cools down and the batch continues with the next row.
- Re-running the same batch is idempotent.
- A partial batch reports `written + missing + failed = checked`.

---

## 6. Related sources

`performer_profile_followup` can also use:

- **AVWikiDB** for cross-checking birth date and height
- **JavDB** to bind the actor id (not for profile fields)

AVWikiDB is also Cloudflare-protected from this host. The cross-check should be treated as optional: a missing AVWikiDB must not block the minnano-av write.

Avatars are a separate follow-up (`avatar_followup.py` + Gfriends/social sources). A missing avatar does not mean a missing profile, and vice versa.
