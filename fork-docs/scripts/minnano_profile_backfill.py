"""One-off minnano-av profile backfill (maintenance script).

The production follow-up is `performer_profile_followup`, but minnano-av is
Cloudflare-protected from the container. This script is a host-side fallback:

1. Yahoo Japan search for `site:minnano-av.com <name>`.
2. Last working Wayback Machine snapshot of the actress page.
3. Parse with `peach.minnano_av.profile()`.
4. Verify the page name/aliases match the ledger entity.
5. Write `performer_profile` and bind the minnano-av external id.

It writes with source `auto:performer-profile@<batch>` so the batch is
reversible. Back up the ledger first and do not run it concurrently with a
second writer.
"""
import hashlib
import json
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from peach import minnano_av
from peach.performer_profiles import write_profile
from peach.social_links import name_key

DB = '/var/lib/peach/database/ledger.db'  # override for a copy
CACHE = Path('/var/lib/peach/generated/provider-cache/minnano-yahoo')
CACHE.mkdir(parents=True, exist_ok=True)
BATCH = 'manual-yahoo-20261031'
SOURCE = f'auto:performer-profile@{BATCH}'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')


def sleep(seconds=2.0):
    time.sleep(seconds)


def http_text(url, *, tries=4, headers=None):
    hdrs = {'User-Agent': UA, 'Accept-Language': 'ja,en;q=0.8'}
    hdrs.update(headers or {})
    last = ''
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read()
                if response.headers.get('Content-Encoding') == 'gzip':
                    import gzip
                    raw = gzip.decompress(raw)
                return raw.decode('utf-8', 'replace')
        except urllib.error.HTTPError as error:
            last = f'HTTP {error.code}'
            if error.code in (429, 500, 502, 503, 504):
                sleep(12 * (attempt + 1))
                continue
            break
        except Exception as error:
            last = type(error).__name__
            sleep(3 * (attempt + 1))
    raise RuntimeError(last or 'request failed')


def search_ids(name):
    key = hashlib.sha1(name.encode('utf-8')).hexdigest()[:16]
    path = CACHE / f'search-{key}.html'
    if path.is_file() and path.stat().st_size > 500:
        text = path.read_text(encoding='utf-8')
    else:
        query = urllib.parse.quote(f'site:minnano-av.com {name}')
        text = http_text('https://search.yahoo.co.jp/search?p=' + query)
        path.write_text(text, encoding='utf-8')
        sleep(1.2)
    ids = re.findall(r'minnano-av\.com/actress(\d+)\.html', text)
    return list(dict.fromkeys(ids))


def wayback_html(actress_id):
    path = CACHE / f'actress-{actress_id}.html'
    if path.is_file() and path.stat().st_size > 1000:
        return path.read_text(encoding='utf-8')
    cdx_url = ('https://web.archive.org/cdx/search/cdx?url='
               f'www.minnano-av.com/actress{actress_id}.html&output=json'
               '&filter=statuscode:200&fl=timestamp,original&limit=-3')
    rows = json.loads(http_text(cdx_url))
    if len(rows) < 2:
        raise RuntimeError('no Wayback snapshot')
    timestamp, original = rows[-1][0], rows[-1][1]
    snapshot = f'https://web.archive.org/web/{timestamp}id_/{original}'
    for attempt in range(3):
        result = subprocess.run(
            ['curl', '-sS', '-L', '--compressed', '--max-time', '90', '-A', UA, snapshot],
            capture_output=True, text=True)
        if result.returncode == 0 and len(result.stdout) > 1000:
            break
        sleep(10 * (attempt + 1))
    else:
        raise RuntimeError('Wayback fetch failed')
    path.write_text(result.stdout, encoding='utf-8')
    sleep(1.5)
    return result.stdout


def with_canonical(html):
    if 'rel="canonical"' in html:
        return html
    match = re.search(r'<meta property=["\']og:url["\'] content=["\']([^"\']+)["\']', html)
    if match:
        return html.replace('<head>', '<head><link rel="canonical" href="%s">' % match.group(1), 1)
    return html


def matches(profile, canonical):
    wanted = name_key(canonical)
    names = [profile.get('name') or '']
    for value in (profile.get('raw') or {}).get('別名') or []:
        if isinstance(value, list):
            names += value
        else:
            names.append(value)
    return any(name_key(str(value)) == wanted for value in names if value)


def find_profile(name):
    candidates = search_ids(name)
    for actress_id in candidates[:5]:
        try:
            html = with_canonical(wayback_html(actress_id))
        except Exception as error:
            print(f'  snapshot {actress_id} failed: {error}', flush=True)
            continue
        profile = minnano_av.profile(html)
        if profile and matches(profile, name):
            return actress_id, profile
    return '', None


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT id,canonical_name FROM entity WHERE kind='performer' ORDER BY id").fetchall()
conn.close()
print(f'performers: {len(rows)}', flush=True)

done = skipped = failed = 0
results = []
for index, row in enumerate(rows, 1):
    entity_id, name = int(row['id']), str(row['canonical_name'])
    with sqlite3.connect(DB) as check:
        existing = check.execute(
            "SELECT source,birth_date,height_cm,debut_year FROM performer_profile WHERE entity_id=?",
            (entity_id,)).fetchone()
    if existing and (not str(existing[0]).startswith('auto:') or existing[1] or existing[2] or existing[3]):
        print(f'[{index}/{len(rows)}] {name}: already has profile, skipped', flush=True)
        skipped += 1
        continue
    try:
        actress_id, profile = find_profile(name)
    except Exception as error:
        print(f'[{index}/{len(rows)}] {name}: lookup failed: {error}', flush=True)
        failed += 1
        continue
    if profile is None:
        print(f'[{index}/{len(rows)}] {name}: no matching profile', flush=True)
        failed += 1
        continue
    page_url = f'https://www.minnano-av.com/actress{actress_id}.html'
    with sqlite3.connect(DB) as connection:
        connection.execute('BEGIN IMMEDIATE')
        write_profile(connection, entity_id, profile, source=SOURCE, source_url=page_url)
        meta = json.dumps({'source': SOURCE, 'batch': BATCH, 'url': page_url}, ensure_ascii=False)
        connection.execute(
            "INSERT INTO entity_external_ref(entity_id,provider,external_kind,external_id,"
            "metadata_json,last_synced_at) VALUES(?,?,'performer',?,?,?) "
            "ON CONFLICT(provider,external_kind,external_id) DO UPDATE SET "
            "metadata_json=excluded.metadata_json,last_synced_at=excluded.last_synced_at",
            (entity_id, 'minnano-av', str(actress_id), meta,
             datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))
    done += 1
    results.append((name, actress_id, profile.get('birth_date'), profile.get('height_cm')))
    print(f'[{index}/{len(rows)}] {name}: wrote {actress_id} '
          f'{profile.get("birth_date") or "-"} {profile.get("height_cm") or "-"}', flush=True)
    sleep(0.5)

print(json.dumps({'written': done, 'skipped': skipped, 'failed': failed,
                  'results': results}, ensure_ascii=False, indent=1))
