"""Look-ahead test for odds and in-play availability (Case 01, v0.2.1).

For many (event, time) pairs, rewrite everything that has not happened yet at time t and assert that the minute,
the probabilities, every offered price and in-play availability at t are unchanged. Rewritten future:
  - goals after the current minute (removed, and new late goals added for both sides),
  - second-half stoppage (so the final whistle moves),
  - first-half stoppage, when the first half has not ended yet at t,
  - the abandonment time of abandoned matches (always kept after t).
Usage: python3 engine/test_lookahead.py [seed]
"""
import copy
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate as G  # noqa: E402
from config import MIN  # noqa: E402


def snapshot(ev, t):
    probs = G.live_probs(ev, t) if t >= ev["start"] else ev["p"]
    prices = {k: G.price_at(ev, k[0], k[1], t, probs if t >= ev["start"] else None) for k in probs}
    minute = G.match_minute(ev, t) if t >= ev["start"] else None
    return minute, probs, prices, G.inplay_open(ev, t)


def rewrite_future(ev, t, rng):
    alt = copy.deepcopy(ev)
    minute = G.match_minute(ev, t) if t >= ev["start"] else -1.0
    keep_h = [g for g in alt["goals_h"] if g <= minute]
    keep_a = [g for g in alt["goals_a"] if g <= minute]
    late = [x for x in (minute + 0.5 + k * 3 for k in range(4)) if minute < x <= 90]
    alt["goals_h"] = sorted(keep_h + late[:2])
    alt["goals_a"] = sorted(keep_a + late[2:])
    if t < ev["start"] + 45 * MIN + ev["stop1"]:          # first half not over at t: its stoppage is still future
        floor = max(1 * MIN, t - ev["start"] - 45 * MIN + 1)
        if floor <= 5 * MIN:
            alt["stop1"] = rng.randint(floor, 5 * MIN)
    alt["stop2"] = rng.randint(2 * MIN, 8 * MIN)
    if alt["abandoned"]:
        alt["end"] = rng.randint(t + 1, ev["start"] + 120 * MIN) if t + 1 < ev["start"] + 120 * MIN else ev["end"]
    else:
        alt["end"] = alt["start"] + 105 * MIN + alt["stop1"] + alt["stop2"]
        if alt["end"] <= t:                                 # would rewrite the past (match already over): skip
            return None
        alt["hs"], alt["as"] = len(alt["goals_h"]), len(alt["goals_a"])
    return alt


def main():
    seed = sys.argv[1] if len(sys.argv) > 1 else "101"
    events = G.gen_fixtures(seed)
    rng = random.Random(f"{seed}:lookahead-test")
    checked = changed = skipped = 0
    sample = rng.sample(events, 600) + [e for e in events if e["abandoned"]]
    for ev in sample:
        for _ in range(6):
            t = rng.randint(ev["start"] - 2 * 86400, ev["end"] - 1)
            alt = rewrite_future(ev, t, rng)
            if alt is None:
                skipped += 1
                continue
            checked += 1
            if snapshot(ev, t) != snapshot(alt, t):
                changed += 1
                print("LOOK-AHEAD:", ev["key"], t - ev["start"])
    print(f"look-ahead test: {checked} (event, time) pairs, every price and the availability flag compared; "
          f"{changed} changed after rewriting the future ({skipped} skipped: rewrite would alter the past)")
    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
