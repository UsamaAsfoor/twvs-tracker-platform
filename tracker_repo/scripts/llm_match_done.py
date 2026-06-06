#!/usr/bin/env python3
"""Semantic DONE matching. Strict text-matching missed real completions when
the request and the library title differ (typos like 'Chk Chk Boom' vs
'Chick Chick Boom', member-vs-group names, or a song covered inside a
multi-song study). This asks the LLM to judge — per tab, comparing each
request against that tab's list of already-studied songs.

Output: done_matches.json  →  { "<nk(artist)|nk(song)>": {date, study} }
"""
import os, sys, json, re, time, urllib.request, urllib.error
from collections import defaultdict

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
BATCH = 20

# Manual DONE calls from Tim that no library title will match cleanly.
MANUAL_DONE = [("changbin", "ultra")]   # done as part of another reaction; no longer wanted

SYSTEM = (
    "You decide whether a fan's song REQUEST has already been fulfilled. You're given a list of "
    "songs the vocal coach has ALREADY studied (DONE) and a batch of REQUESTS. For each request, "
    "set done=true ONLY if one of the DONE studies clearly covers the SAME song by the SAME artist. "
    "Account for: spelling/typo variants ('Chk Chk Boom' = 'Chick Chick Boom'), member-vs-group "
    "names (Felix = Stray Kids Felix; Agust D = Suga/BTS), live/MV/recording variants of the same "
    "song, and a song that was one track inside a multi-song study. Do NOT mark done for a different "
    "song by the same artist, or a catalog/'more please' request. When unsure, done=false. "
    "Return ONLY a JSON array: [{i, done, study}] where study = the matching DONE line (or '')."
)


def nk(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def call_api(prompt):
    body = json.dumps({"model": MODEL, "max_tokens": 1500, "system": SYSTEM,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    for attempt in range(4):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=60))
            t = r["content"][0]["text"].strip()
            if t.startswith("```"):
                t = t.split("```")[1].lstrip("json").strip()
            return {o["i"]: o for o in json.loads(t) if "i" in o}
        except Exception:
            time.sleep(2 * (attempt + 1))
    return {}


def main():
    eng = json.load(open(os.path.join(DATA, "tracker_allmonths_engine.json")))
    lib = json.load(open(os.path.join(DATA, "library_done.json")))
    requests = eng["cumulative"]

    # Tag each studied song to a tab by ARTIST-TOKEN OVERLAP (not exact name),
    # so "Felix (Stray Kids)" files under Stray Kids via shared felix/stray/kids
    # tokens. Over-inclusion is harmless (the LLM still only matches same song);
    # under-inclusion is what caused real misses, so we err inclusive.
    STOP = {"the", "and", "feat", "ft", "vs", "live", "cover", "official", "reaction",
            "analysis", "study", "song", "vocal", "deep", "dive", "full", "album", "mv"}

    def atoks(s):
        return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) >= 3 and t not in STOP}

    tab_tokens = defaultdict(set)
    for r in requests:
        tab_tokens[r["tab"]] |= atoks(r["artist"])

    done = [d for d in lib if nk(d.get("song")) not in ("catalog", "")]
    done_by_tab = defaultdict(list)
    for d in done:
        dt = atoks(d.get("artist"))
        for tab, toks in tab_tokens.items():
            if dt & toks:
                done_by_tab[tab].append(d)

    reqs_by_tab = defaultdict(list)
    for r in requests:
        reqs_by_tab[r["tab"]].append(r)

    result = {}
    total_calls = 0
    for tab, reqs in reqs_by_tab.items():
        dlist = done_by_tab.get(tab, [])
        if not dlist:
            continue
        done_text = "\n".join(f"- {d['artist']} — {d['song']} ({d.get('date','')})" for d in dlist[:80])
        for b in range(0, len(reqs), BATCH):
            batch = reqs[b:b + BATCH]
            reqtext = "\n".join(f"[{i}] {r['artist']} — {r['song']}" for i, r in enumerate(batch))
            res = call_api(f"DONE studies (tab: {tab}):\n{done_text}\n\nREQUESTS:\n{reqtext}")
            total_calls += 1
            for i, r in enumerate(batch):
                o = res.get(i, {})
                if o.get("done"):
                    study = o.get("study", "") or ""
                    date = ""
                    for d in dlist:  # find the date of the matched study
                        if d["song"] and nk(d["song"]) in nk(study):
                            date = d.get("date", ""); break
                    result[nk(r["artist"]) + "|" + nk(r["song"])] = {"date": date, "study": study}
        print(f"  {tab}: {len(reqs)} requests judged against {len(dlist)} done", flush=True)

    # Manual DONE calls
    for r in requests:
        blob = (r["artist"] + " " + r["song"]).lower()
        for a, s in MANUAL_DONE:
            if a in blob and s in blob:
                result[nk(r["artist"]) + "|" + nk(r["song"])] = {"date": "", "study": "manual (Tim)"}

    json.dump(result, open(os.path.join(DATA, "done_matches.json"), "w"), ensure_ascii=False, indent=2)
    print(f"  ✅ done_matches.json: {len(result)} requests matched DONE  ({total_calls} API calls)")


if __name__ == "__main__":
    main()
