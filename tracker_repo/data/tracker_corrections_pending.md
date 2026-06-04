# Tracker Corrections — Pending (to apply in rebuild)

Community-reported corrections to fold into `tracker_overrides.json` / completion
audit during the Oct→June rebuild. Provenance kept for the handoff.

## Attribution fixes (wrong artist)
1. **"Hated by Life Itself" / "Life Hates Us"** → artist = **MafuMafu** (cover;
   original by Iori Kanzaki). **NOT Ado** — "never covered by Ado."
   Category: J-Pop. _Source: Patreon JPop chat + Discord (Mr.UNAWARE_22, PlayChris310)._
2. **"Future Eve"** → artist = **Sasakure.uk** (with UKRampage). **NOT Eve.**
   Category: J-Pop. _Source: Patreon JPop chat._

## Category fixes (wrong genre)
3. **King Gnu — "Prayer X"** → category **J-Pop**. _Source: Kagari (Patreon chat)._

## Heart-count fixes (cross-month merge failing)
4. **King Gnu — "Prayer X"**: requested in **both April and May**, but the tracker
   **only counted May hearts**. April + May must be summed into one entry.
   ⇒ General bug: cross-month duplicates of the SAME song are not always merging.
   Verify the cross-month dedup in the rebuild (not just this entry).
   _Source: Kagari (Patreon chat)._

## Completion ("marked done when not done")
5. **Vocaloid songs**: "a lot of vocaloid songs are marked done that are not."
   Only songs actually reacted to (verified against the Patreon library) may carry
   a DONE badge. Audit every Vocaloid/utaite DONE badge; remove false positives.
   Known genuinely-done: iyowa "Heat Abnormal" only (per Discord).
   _Source: Patreon JPop chat + Discord (Mr.UNAWARE_22)._

## Notes for rebuild
- Cross-month merge (#4) is likely systemic — audit ALL songs requested in
  multiple months, not just King Gnu.
- The "any song by artist → mark whole artist done" generic rule is the most
  likely cause of #5 over-marking; tighten to specific-song matches for Vocaloid.
