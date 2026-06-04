#!/usr/bin/env python3
"""Extract the COMPLETED-work set from the full library (Patreon posts +
YouTube videos) using the LLM. A title may cover multiple songs (e.g.
'5 SONG STUDY: A/B/C'). Livestreams / listening-parties / admin / request
posts are flagged is_reaction=false and excluded — per Tim: a stream listen-
through does NOT satisfy a song request (only a standalone study does).

Output: library_done.json  →  [{artist, song, date, source, title}]
Cache by title hash (resumable, no double-pay).
"""
import os, sys, json, csv, glob, time, hashlib, urllib.request, urllib.error

DATA = os.path.expanduser("~/TWVS/data")
KEY = "".join(open(os.path.join(os.path.dirname(DATA), "anthropic_api_key.txt")).read().split())
MODEL = "claude-haiku-4-5-20251001"
CACHE = os.path.join(DATA, "library_done_cache.json")
OUT = os.path.join(DATA, "library_done.json")
BATCH = 18

SYSTEM = (
    "You read titles of a vocal-coach's reaction videos/Patreon posts and list which songs were "
    "actually COVERED (reacted to / studied / analyzed). For each numbered title return one JSON "
    "object: {i, is_reaction, items}. is_reaction=FALSE for livestreams, live listening parties, "
    "music parties, song-request posts, schedules, announcements, Q&A, wheel-spins, polls, or "
    "anything that is a casual group listen-through rather than a dedicated study — these do NOT "
    "count as covering a song. is_reaction=TRUE for a real standalone reaction/study/analysis. "
    "items = list of {artist, song} for EVERY song the title says was covered (a '5 Song Study: "
    "A/B/C/D/E' lists all five; a Killing Voice / album reaction can be one entry with the album/"
    "medley name). For an artist deep-dive naming no specific song, use song='catalog'. artist = "
    "the performer (for a cover, the performer). Output ONLY a JSON array of these objects."
)


def chash(t):
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def call_api(batch):
    numbered = "\n".join(f"[{i}] {t[:200]}" for i, t in batch)
    body = json.dumps({"model": MODEL, "max_tokens": 3000, "system": SYSTEM,
                       "messages": [{"role": "user", "content": numbered}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(4):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=60))
            txt = r["content"][0]["text"].strip()
            if txt.startswith("```"):
                txt = txt.split("```")[1].lstrip("json").strip()
            return {o["i"]: o for o in json.loads(txt) if "i" in o}
        except Exception:
            time.sleep(2 * (attempt + 1))
    return {}


def main():
    # Gather library titles + dates from both sources.
    titles = []
    pf = sorted(f for f in glob.glob(os.path.join(DATA, "patreon_posts_2026*.csv"))
                if "export" not in f and "scraped" not in f)[-1]
    for r in csv.DictReader(open(pf, encoding="utf-8-sig")):
        t = (r.get("Post Title") or "").strip()
        if t:
            titles.append({"title": t, "date": (r.get("Publish Date (UTC)") or "")[:10], "source": "patreon"})
    for r in csv.DictReader(open(os.path.join(DATA, "twvs_youtube_complete_library.csv"), encoding="utf-8-sig")):
        t = (r.get("title") or "").strip()
        if t:
            titles.append({"title": t, "date": (r.get("publish_date") or "")[:10], "source": "youtube"})
    # Dedup identical titles (keep earliest date).
    seen = {}
    for it in titles:
        h = chash(it["title"])
        if h not in seen or it["date"] < seen[h]["date"]:
            seen[h] = it
    titles = list(seen.values())
    print(f"  {len(titles)} unique library titles to read")

    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    todo = [(i, it) for i, it in enumerate(titles) if chash(it["title"]) not in cache]
    print(f"  {len(titles) - len(todo)} cached · {len(todo)} to extract")

    for b in range(0, len(todo), BATCH):
        chunk = todo[b:b + BATCH]
        res = call_api([(i, it["title"]) for i, it in chunk])
        for i, it in chunk:
            o = res.get(i, {})
            cache[chash(it["title"])] = {"is_reaction": bool(o.get("is_reaction", True)),
                                         "items": o.get("items", []) if isinstance(o.get("items"), list) else []}
        json.dump(cache, open(CACHE, "w"), ensure_ascii=False)
        print(f"    {min(b + BATCH, len(todo))}/{len(todo)}…", flush=True)
        time.sleep(0.3)

    # Flatten to done items (specific songs only; skip non-reactions).
    done = []
    for it in titles:
        c = cache[chash(it["title"])]
        if not c["is_reaction"]:
            continue
        for itm in c["items"]:
            a = (itm.get("artist") or "").strip()
            s = (itm.get("song") or "").strip()
            if a and s:
                done.append({"artist": a, "song": s, "date": it["date"],
                             "source": it["source"], "title": it["title"]})
    json.dump(done, open(OUT, "w"), ensure_ascii=False, indent=2)
    reactions = sum(1 for it in titles if cache[chash(it["title"])]["is_reaction"])
    print(f"  ✅ {OUT}: {len(done)} done song-entries from {reactions} reaction titles "
          f"({len(titles) - reactions} excluded as streams/admin)")


if __name__ == "__main__":
    main()
