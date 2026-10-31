# Preview trailers: JavTrailers 1080p

This note records why discovery previews were low quality and how the fork now prefers JavTrailers' 1080p HLS master.

---

## 1. The old behaviour

`q_jav_detail` used this order:

1. DMM / Prestige page preview
2. JavDB page preview
3. JavDB public signed preview

On this host, DMM's preview CDN (`cc3001.dmm.co.jp`) returns CloudFront `403`; JavDB's public preview works but tops out at **720p**. The result was a working but soft trailer.

---

## 2. JavTrailers source

JavTrailers publishes a public page per title and a three-rendition HLS master:

```text
https://javtrailers.com/video/mida00859
  └── https://media.javtrailers.com/hlsvideo/freepv/m/mid/mida00859/playlist.m3u8
        ├── mida00859mmb.m3u8  768x432
        ├── mida00859hmb.m3u8  1280x720
        └── mida00859hhb.m3u8  1920x1080
```

The media host serves the playlist and segments without a login. The video page states the DVD ID (`DVD ID: MIDA-859`); that is the identity check, so a search hit for the wrong title is never accepted.

### Slug rule

For standard codes the slug is the lower-case prefix plus a five-digit, zero-padded number:

| Code | Slug |
|---|---|
| `MIDA-859` | `mida00859` |
| `MIDA-849` | `mida00849` |
| `AARM-372` | `aarm00372` |
| `MYBA-097` | `myba00097` |

Non-standard codes (for example `h_1729goji00120`) fall back to:

```text
https://javtrailers.com/search/<code>
```

The search page returns `/video/...` links; each candidate page is checked by DVD ID before its playlist is used.

---

## 3. Implementation

New module:

```text
src/peach/javtrailers_preview.py
```

Public function:

```python
preview_url(code, cache=None) -> str
```

It:

- builds the direct slug for standard codes
- fetches the page with a browser UA and `Referer: https://javtrailers.com/`
- checks the DVD ID
- extracts the `media.javtrailers.com/.../playlist.m3u8` master
- falls back to site search for non-standard codes
- caches a positive result for 24 hours in `RemoteMediaCache`
- caches a negative result only through the cache's short failure marker, so a transient block does not hide a title for a day
- uses an 8-second timeout; a slow JavTrailers request falls through to JavDB instead of stalling the detail page

`web_jav_detail._preview_fields()` now tries:

1. JavTrailers 1080p master
2. JavDB public signed 720p HLS
3. DMM / Prestige / JavDB page preview

The proxy already allows any public HTTPS host for `/jav-preview` (`public_hosts=True`), so `media.javtrailers.com` needs no allowlist change. The existing HLS rewriter handles the master → variant → segment nesting:

```text
/jav-preview/MIDA-859/<master>.m3u8
  → /jav-preview/MIDA-859/<variant>.m3u8
    → /jav-preview/MIDA-859/<segment>
```

---

## 4. Live override on this host

The running container does not use the fork source directly. These files are mounted read-only:

```text
/var/lib/peach/overrides/web_jav_detail.py
/var/lib/peach/overrides/javtrailers_preview.py
```

`compose.yaml` mounts them into `site-packages/peach/`. The source of truth is the fork:

```text
src/peach/javtrailers_preview.py
src/peach/web_jav_detail.py
```

When changing the preview logic:

```bash
# edit in the fork, then copy to the override
cp src/peach/javtrailers_preview.py /var/lib/peach/overrides/javtrailers_preview.py
cp src/peach/web_jav_detail.py   /var/lib/peach/overrides/web_jav_detail.py
chown root:root /var/lib/peach/overrides/javtrailers_preview.py \
                 /var/lib/peach/overrides/web_jav_detail.py
chmod 644       /var/lib/peach/overrides/javtrailers_preview.py \
                 /var/lib/peach/overrides/web_jav_detail.py
systemctl restart peach.service
```

`compose.yaml` must contain:

```yaml
- /var/lib/peach/overrides/web_jav_detail.py:/app/.venv/lib/python3.15/site-packages/peach/web_jav_detail.py:ro
- /var/lib/peach/overrides/javtrailers_preview.py:/app/.venv/lib/python3.15/site-packages/peach/javtrailers_preview.py:ro
```

---

## 5. Verification

For each code:

```bash
TOK=$(cat /var/lib/peach/secrets/auth-token)
curl -sS -H "X-Token: $TOK" \
  "http://127.0.0.1:8900/api/jav/detail?code=MIDA-859&refresh=1" \
  -o /tmp/detail.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/detail.json'))
print(d['preview_state'], d['preview_video_url'])
PY
```

The returned URL must be a `/jav-preview/.../*.m3u8` master. Fetch it and look for a `RESOLUTION=1920x1080` line:

```bash
u=$(python3 -c "import json;print(json.load(open('/tmp/detail.json'))['preview_video_url'])")
curl -sS -H "X-Token: $TOK" "http://127.0.0.1:8900$u" | grep 1920x1080
```

Then fetch the 1080p variant and one segment:

```bash
curl -sS -H "X-Token: $TOK" "http://127.0.0.1:8900$variant" -o /tmp/variant.m3u8
seg=$(grep -m1 -v '^#' /tmp/variant.m3u8)
curl -sS -H "X-Token: $TOK" "http://127.0.0.1:8900$seg" -o /tmp/segment.ts
file /tmp/segment.ts
```

Verified on 2026-10-31:

| Code | Master | 1080p variant | Segment |
|---|---|---|---|
| `MIDA-859` | 200 | 200 | `MPEG transport stream` |
| `MIDA-849` | 200 | 200 | 200 |
| `AARM-372` | 200 | 200 | 200 |
| `MYBA-097` | 200 | 200 | 200 |

---

## 6. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `preview_state=ready` but only 432p/720p | JavTrailers has no page for the code; fell back to JavDB 720p | expected fallback |
| 404 on `/jav-preview/...` | neither JavTrailers nor JavDB/DMM has a preview | leave unavailable |
| 403 from `cc3001.dmm.co.jp` | DMM geo-block | expected; JavTrailers/JavDB are preferred |
| wrong title | a search result was accepted without DVD ID check | never bypass `_matches()` |
| 24h stale trailer | page layout changed but cached URL still valid | call detail with `refresh=1`, or clear `remote-media/javtrailers:*` |

JavTrailers page structure is not an API contract. If it changes, update `_DVD_ID` and `_VIDEO` in `javtrailers_preview.py` and add a fixture. Keep the DVD-ID check even if the slug rule stops working.

---

## 7. Fork acceptance criteria

- `MIDA-859` resolves to a master playlist with a 1920x1080 rendition.
- The 1080p variant and at least one segment return `200`.
- A title with no JavTrailers page still returns the JavDB 720p fallback.
- A JavTrailers page whose DVD ID does not match the requested code is rejected.
- A failed JavTrailers request does not make the detail page fail.
- Unit tests cover `standard_slug()` and `_matches()`/`_video()` parsing without network access.
- The same logic is in `src/peach/`, not only in `/var/lib/peach/overrides/`.
