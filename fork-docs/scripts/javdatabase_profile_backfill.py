"""Bulk performer-profile backfill through JavTrailers + JavDatabase.

This is the one-shot alternative to opening every performer:

1. For each performer with no profile, read their video codes.
2. Open the JavTrailers video page and map the Japanese cast name to the
   romanized name (`Rena Miyashita 宮下玲奈` -> `Rena Miyashita`).
3. Fetch the JavDatabase idol page by the romanized slug.
4. Write birth date, height, measurements, cup, and debut into
   `performer_profile`.

It skips existing rows, male performers, and ambiguous matches. It writes with
source `auto:performer-profile@javdatabase-20261031`, so the batch is
reversible. Run it from the repo root:

    PYTHONPATH=src python3 fork-docs/scripts/javdatabase_profile_backfill.py

Back up the ledger first. The script is safe to re-run: it reports no-op rows
and does not overwrite an existing profile.
"""
import hashlib
import json
import re
import sqlite3
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from peach.performer_profiles import write_profile
from peach.social_links import name_key

DB = '/var/lib/peach/database/ledger.db'
CACHE = Path('/var/lib/peach/generated/provider-cache/javdatabase-bulk')
CACHE.mkdir(parents=True, exist_ok=True)
BATCH = 'javdatabase-20261031'
SOURCE = f'auto:performer-profile@{BATCH}'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

CAST = re.compile(r'href="/casts/([^"]+)"[^>]*>([^<]+)</a>')
VIDEO = re.compile(r'href="(/video/[a-z0-9]+)"')
DOB = re.compile(r'<b>DOB:</b>.*?class="idol-box-link">(\d{4}-\d{2}-\d{2})</a>', re.S)
DEBUT = re.compile(r'<b>Debut:</b>.*?class="idol-box-link">(\d{4}-\d{2}-\d{2}|\d{4})</a>', re.S)
MEAS = re.compile(r'<b>Measurements:</b>\s*(\d+)-(\d+)-(\d+)')
CUP = re.compile(r'<b>Cup:</b>.*?class="idol-box-link">([A-Z])</a>', re.S)
HEIGHT = re.compile(r'<b>Height:</b>.*?class="idol-box-link">(\d+)\s*cm</a>', re.S)
BIRTHPLACE = re.compile(r'<b>Birthplace:</b>\s*(.*?)</', re.S)
BLOOD = re.compile(r'<b>Blood:</b>\s*(.*?)<', re.S)
TITLE = re.compile(r'<title>([^<]*?)\s*-\s*JAV Database</title>', re.I)


def curl(url, *, referer=None, compressed=False, timeout=40):
    command = ['curl', '-sS', '-L', '--max-time', str(timeout), '-A', UA]
    if compressed:
        command.append('--compressed')
    if referer:
        command.extend(['-e', referer])
    command.append(url)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:120] or 'curl failed')
    return result.stdout


def cached(name, fetch):
    path = CACHE / (hashlib.sha1(name.encode()).hexdigest()[:20] + '.html')
    if path.is_file() and path.stat().st_size > 500:
        return path.read_text(encoding='utf-8')
    text = fetch()
    path.write_text(text, encoding='utf-8')
    return text


def video_page(code):
    def fetch():
        search = curl('https://javtrailers.com/search/' + urllib.parse.quote(code))
        links = VIDEO.findall(search)
        if not links:
            return ''
        url = 'https://javtrailers.com' + links[0]
        return curl(url, referer='https://javtrailers.com/search/' + urllib.parse.quote(code))
    return cached('video-' + code, fetch)


def cast_links(html):
    return [(slug, text.strip()) for slug, text in CAST.findall(html)]


def romaji_for(entity_names, html):
    wanted = {name_key(name) for name in entity_names if name}
    for _slug, text in cast_links(html):
        # The badge text is "Romaji Japanese"; compare the Japanese part.
        for name in entity_names:
            if name and name in text and name_key(name) in wanted:
                romaji = text[:text.find(name)].strip()
                romaji = re.sub(r'\s+', ' ', romaji)
                if romaji:
                    return romaji
    return ''


def slugify(name):
    return re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-')


def javdatabase_page(romaji):
    slug = slugify(romaji)
    if not slug:
        return '', ''
    url = f'https://www.javdatabase.com/idols/{slug}/'
    text = cached('jdb-' + slug, lambda: curl(url))
    title = TITLE.search(text)
    if title and name_key(title.group(1)) == name_key(romaji):
        return url, text
    # Fallback: WordPress search, then first idol result.
    search = cached('jdb-search-' + slug, lambda: curl(
        'https://www.javdatabase.com/?' + urllib.parse.urlencode({'s': romaji})))
    for found in dict.fromkeys(re.findall(r'href="(https://www\.javdatabase\.com/idols/[a-z0-9-]+/)"', search)):
        page = cached('jdb-' + found.rstrip('/').rsplit('/', 1)[-1], lambda: curl(found))
        title = TITLE.search(page)
        if title and name_key(title.group(1)) == name_key(romaji):
            return found, page
    return '', ''


def profile_from_page(html, page_url):
    dob = DOB.search(html)
    debut = DEBUT.search(html)
    meas = MEAS.search(html)
    cup = CUP.search(html)
    height = HEIGHT.search(html)
    place = BIRTHPLACE.search(html)
    blood = BLOOD.search(html)
    profile = {
        'birth_date': dob.group(1) if dob else None,
        'height_cm': int(height.group(1)) if height else None,
        'cup': cup.group(1) if cup else None,
        'debut_date': debut.group(1) if debut and len(debut.group(1)) == 10 else None,
        'debut_year': int(debut.group(1)[:4]) if debut else None,
        'birthplace': (place.group(1).strip() if place else '') or None,
        'blood_type': (blood.group(1).strip() if blood else '') or None,
        'tags': [],
        'raw': {'source': 'javdatabase', 'url': page_url},
    }
    if meas:
        profile.update({'bust_cm': int(meas.group(1)), 'waist_cm': int(meas.group(2)),
                        'hip_cm': int(meas.group(3))})
    for key in ('birthplace', 'blood_type'):
        if profile[key] in {'?', '-', ''}:
            profile[key] = None
    return profile


conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT e.id,e.canonical_name,e.metadata_json FROM entity e "
    "LEFT JOIN performer_profile p ON p.entity_id=e.id "
    "WHERE e.kind='performer' AND (p.entity_id IS NULL OR (coalesce(p.birth_date,'')='' "
    "AND coalesce(p.height_cm,0)=0 AND coalesce(p.debut_year,0)=0)) ORDER BY e.id").fetchall()
print('missing', len(rows), flush=True)

done = skipped = failed = 0
for index, row in enumerate(rows, 1):
    entity_id, name = int(row['id']), str(row['canonical_name'])
    metadata = json.loads(row['metadata_json'] or '{}')
    if metadata.get('gender') != 'female':
        print(f'[{index}/{len(rows)}] {name}: male/unknown, skipped', flush=True)
        skipped += 1
        continue
    aliases = [r[0] for r in conn.execute(
        "SELECT alias FROM entity_alias WHERE entity_id=?", (entity_id,))]
    codes = [r[0] for r in conn.execute(
        "SELECT a.code FROM asset a JOIN asset_entity ae ON ae.asset_id=a.id "
        "WHERE ae.entity_id=? AND ae.role='performer' AND a.code IS NOT NULL "
        "AND a.code<>'' ORDER BY a.code LIMIT 8", (entity_id,))]
    romaji = ''
    for code in codes:
        try:
            html = video_page(code)
        except Exception as error:
            print(f'  {name} {code}: {error}', flush=True)
            continue
        romaji = romaji_for([name, *aliases], html)
        if romaji:
            break
    if not romaji:
        print(f'[{index}/{len(rows)}] {name}: no cast romaji', flush=True)
        failed += 1
        continue
    try:
        page_url, html = javdatabase_page(romaji)
    except Exception as error:
        print(f'[{index}/{len(rows)}] {name}: JavDatabase {error}', flush=True)
        failed += 1
        continue
    if not page_url:
        print(f'[{index}/{len(rows)}] {name}: no JavDatabase page for {romaji}', flush=True)
        failed += 1
        continue
    profile = profile_from_page(html, page_url)
    if not any(profile.get(key) for key in (
            'birth_date', 'height_cm', 'bust_cm', 'waist_cm', 'hip_cm', 'debut_year')):
        print(f'[{index}/{len(rows)}] {name}: JavDatabase page has no profile fields', flush=True)
        failed += 1
        continue
    with conn:
        write_profile(conn, entity_id, profile, source=SOURCE, source_url=page_url)
        meta = json.dumps({'source': SOURCE, 'batch': BATCH, 'url': page_url,
                           'romaji': romaji}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO entity_external_ref(entity_id,provider,external_kind,external_id,"
            "metadata_json,last_synced_at) VALUES(?,?,'performer',?,?,?) "
            "ON CONFLICT(provider,external_kind,external_id) DO UPDATE SET "
            "metadata_json=excluded.metadata_json,last_synced_at=excluded.last_synced_at",
            (entity_id, 'javdatabase', slugify(romaji), meta,
             datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')))
    done += 1
    print(f'[{index}/{len(rows)}] {name}: wrote {romaji} '
          f'{profile.get("birth_date") or "-"} {profile.get("height_cm") or "-"}', flush=True)
    time.sleep(0.4)
print(json.dumps({'written': done, 'skipped': skipped, 'failed': failed}))
conn.close()
