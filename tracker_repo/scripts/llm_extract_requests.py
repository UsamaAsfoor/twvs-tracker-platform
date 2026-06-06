#!/usr/bin/env python3
"""LLM-based request extractor. Replaces the brittle regex parser: each Patreon
comment is read by Claude (Haiku) and turned into {is_request, artist, song,
category}. Handles free-form prose (pre-April months) that the regex mangled.

- Batches comments per API call, caches by comment hash (resumable, no double-pay).
- Output: song_requests_llm.json  (consumed by the rebuild engine).

Usage:
  python3 llm_extract_requests.py            # full run (all comments)
  python3 llm_extract_requests.py --limit 15 # test on first 15 (validation)
"""
import os, sys, json, time, hashlib, urllib.request, urllib.error

sys.path.insert(0, os.environ.get("TWVS_SCRIPTS_DIR", os.path.expanduser("~/TWVS/scripts")))
from rebuild_tracker_allmonths import URL_MONTH, post_id

DATA = os.environ.get("TWVS_DATA_DIR", os.path.expanduser("~/TWVS/data"))

def _load_key():
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if k:
        return k
    key_path = os.path.join(os.path.dirname(DATA), "anthropic_api_key.txt")
    if os.path.isfile(key_path):
        return "".join(open(key_path).read().split())
    return ""

KEY = _load_key()
MODEL = "claude-haiku-4-5-20251001"
CACHE_PATH = os.path.join(DATA, "song_requests_llm_cache.json")
OUT_PATH = os.path.join(DATA, "song_requests_llm.json")
BATCH = 20

CATEGORIES = ("skz, bts, ateez, enhypen, morekpop, vtuber, jpop, anime, game, musical, euro, rock, other")
SYSTEM = (
    "You extract song requests for a vocal-coach reaction channel from Patreon comments. "
    "For EACH numbered comment return one JSON object with keys: i (the number), "
    "is_request (true if it recommends a specific song/artist/album to react to; false for "
    "pure thanks/chatter/meta with no recommendation), artist (the PERFORMER — for a cover, "
    "the person performing it, not the original writer; clean name only), song (the specific "
    "song/album, or 'catalog' if only an artist is named), category (EXACTLY one of: "
    f"{CATEGORIES}). Category guide: skz=Stray Kids; bts=BTS/members; ateez=ATEEZ; "
    "enhypen=ENHYPEN; morekpop=any other K-pop/Korean act; vtuber=VTubers (Hololive, "
    "Holostars, Neuro, indie vsingers); jpop=Japanese pop/rock/vocaloid/utaite; anime=anime "
    "openings/endings/OST or anime-series watch requests; game=video-game music/OST; "
    "musical=stage musicals / theatre / film & TV soundtracks (NOT video-game music, "
    "which is 'game'); euro=European/Eurovision artists; rock=Western rock/metal/alt/folk "
    "(incl. Mitski, Noah Kahan, Hozier, etc); other=everything else (Western pop, comedy "
    "music, Thai/Chinese/Latin one-offs). "
    "Output ONLY a JSON array of these objects, nothing else."
)


def chash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def call_api(batch):
    """batch: list of (idx, text). Returns dict idx->extraction."""
    numbered = "\n".join(f"[{i}] {t[:600]}" for i, t in batch)
    body = json.dumps({
        "model": MODEL, "max_tokens": 2000, "system": SYSTEM,
        "messages": [{"role": "user", "content": numbered}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(4):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=60))
            txt = r["content"][0]["text"].strip()
            if txt.startswith("```"):
                txt = txt.split("```")[1].lstrip("json").strip()
            arr = json.loads(txt)
            return {o["i"]: o for o in arr if "i" in o}
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            time.sleep(1)
    return {}


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    posts = json.load(open(os.path.join(DATA, "song_requests.json")))
    items = []
    for p in posts:
        mt = URL_MONTH.get(post_id(p.get("url", "")))
        if not mt:
            continue
        for c in p.get("structured", []):
            txt = (c.get("text") or "").strip()
            if not txt:
                continue
            items.append({"month": mt[0], "type": mt[1], "url": p.get("url", ""),
                          "commenter": c.get("name", "Anon"), "hearts": c.get("hearts", 0) or 0,
                          "text": txt, "hash": chash(txt)})
    if limit:
        items = items[:limit]

    cache = json.load(open(CACHE_PATH)) if os.path.exists(CACHE_PATH) else {}
    todo = [(idx, it) for idx, it in enumerate(items) if it["hash"] not in cache]
    print(f"  {len(items)} comments · {len(items) - len(todo)} cached · {len(todo)} to extract")

    done = 0
    for b in range(0, len(todo), BATCH):
        chunk = todo[b:b + BATCH]
        res = call_api([(idx, it["text"]) for idx, it in chunk])
        for idx, it in chunk:
            o = res.get(idx, {})
            cache[it["hash"]] = {
                "is_request": bool(o.get("is_request", True)),
                "artist": (o.get("artist") or "").strip(),
                "song": (o.get("song") or "").strip(),
                "category": (o.get("category") or "other").strip().lower(),
            }
        done += len(chunk)
        json.dump(cache, open(CACHE_PATH, "w"), ensure_ascii=False)
        print(f"    {done}/{len(todo)} extracted…", flush=True)
        time.sleep(0.3)

    # Emit final structured list.
    out = []
    for it in items:
        e = cache.get(it["hash"], {})
        out.append({**{k: it[k] for k in ("month", "type", "url", "commenter", "hearts", "text")}, **e})
    json.dump(out, open(OUT_PATH, "w"), ensure_ascii=False, indent=2)
    print(f"  ✅ Wrote {OUT_PATH} ({len(out)} comments)")

    if limit:
        print("\n  --- SAMPLE EXTRACTIONS ---")
        for it in out:
            tag = "" if it.get("is_request") else " [NOT A REQUEST]"
            print(f"  [{it['hearts']}♥ {it.get('category','?'):8}] {it.get('artist','')[:24]} — {it.get('song','')[:26]}{tag}")
            print(f"        raw: {it['text'][:80]}")


if __name__ == "__main__":
    main()
