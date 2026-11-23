"""Case 01 background generator (Step 1).

Simulates the fictional operator from L to H with a per-account session engine, assigns random IDs after the merge,
cuts an as-of-R snapshot and exports buyer CSVs plus designer files.

Usage: python3 engine/generate.py --seed <seed> --accounts 500 --out <dir>
Money is held in integer cents and odds in integer hundredths; times are integer epoch seconds (UTC).
"""
import argparse
import bisect
import csv
import hashlib
import heapq
import json
import math
import os
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import *  # noqa: F401,F403
from config import (ARCHETYPES, HOME_COUNTRIES, TRAVEL_COUNTRIES, HOUR_WEIGHTS, CROCKFORD, L, R, H, DAY, HOUR, MIN,
                    FIXTURE_HORIZON, DATA_VERSION)
import config as C
from schema import SCHEMA, DESIGNER_TABLES, bigquery_schema_json

RANK = {"deposit_credit": 1, "bet_payout": 2, "bet_void": 2, "withdrawal_release": 3, "stake": 4, "withdrawal_hold": 5}
MARKETS = {"match_result": ["home", "draw", "away"], "total_goals_2_5": ["over", "under"], "both_teams_score": ["yes", "no"]}
MARKET_WEIGHTS = [("match_result", 60), ("total_goals_2_5", 25), ("both_teams_score", 15)]
MARGIN = {"match_result": 0.06, "total_goals_2_5": 0.05, "both_teams_score": 0.06}

SYL1 = ["Vor", "Kel", "Mar", "Tav", "Dren", "Sol", "Bre", "Quin", "Ost", "Fal", "Lun", "Zer", "Hal", "Cor", "Ves",
        "Ryn", "Tor", "Ael", "Gav", "Nor", "Pell", "Dar", "Isk", "Wen", "Brak", "Elv", "Mor", "Sev"]
SYL2 = ["ano", "eth", "ova", "ira", "umar", "esk", "ond", "avia", "eld", "ura", "ith", "enza", "orra", "ast", "ivo", "elin"]
CLUB = ["FC", "SC", "Athletic", "United", "Sporting", "Rovers", "City", "Club"]
COMP = ["League", "Premier Division", "Super League", "First Division", "Championship", "Premier League"]
# (UTC offset of the league's home region, local kickoff slots)
LEAGUES = [(1, [(15, 0), (17, 30), (20, 0)]), (1, [(14, 0), (16, 0), (19, 45)]), (2, [(15, 0), (18, 0)]),
           (3, [(16, 0), (18, 30)]), (-4, [(13, 0), (16, 0), (19, 30)]), (8, [(17, 0), (19, 30)])]
# matches per round day, as (days after Saturday, count, fixed local slot or None)
PATTERNS = {5: [(0, 3, None), (1, 3, None), (2, 2, (20, 0))]}
DEFAULT_PATTERN = [(0, 5, None), (1, 3, None)]


# ---------------------------------------------------------------- helpers

def wchoice(rng, pairs):
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs], k=1)[0]


def poisson(rng, lam):
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def pmf(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def fmt_ts(t):
    return "" if t is None else datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def fmt_cents(c):
    if c is None:
        return ""
    sign = "-" if c < 0 else ""
    return f"{sign}{abs(c) // 100}.{abs(c) % 100:02d}"


def fmt_bool(b):
    return "true" if b else "false"


# ---------------------------------------------------------------- fixtures

def gen_fixtures(seed):
    rng = random.Random(f"{seed}:fixtures")
    used, leagues = set(), []
    for li, (off, slots) in enumerate(LEAGUES):
        while True:
            comp = f"{rng.choice(SYL1)}{rng.choice(SYL2)} {COMP[li]}"
            if comp not in used:
                used.add(comp)
                break
        teams = []
        while len(teams) < 16:
            name = f"{rng.choice(SYL1)}{rng.choice(SYL2)} {rng.choice(CLUB)}"
            base = name.split(" ")[0]
            if name not in used and base not in {t["name"].split(" ")[0] for t in teams}:
                used.add(name)
                teams.append({"name": name, "att": rng.gauss(0, 0.2), "dfn": rng.gauss(0, 0.2)})
        leagues.append({"comp": comp, "off": off, "slots": slots, "teams": teams})

    events = []
    first_sat = L + 5 * DAY
    week = 0
    while first_sat + 7 * week * DAY < H + 3 * DAY:
        sat = first_sat + 7 * week * DAY
        for li, lg in enumerate(leagues):
            rounds = [(sat + d * DAY, n, slot) for d, n, slot in PATTERNS.get(li, DEFAULT_PATTERN)]
            if week % 4 == 2:
                rounds.append((sat - 3 * DAY, 8, (19, 45)))
            order = list(range(16))
            rng.shuffle(order)
            pairs = [(order[2 * k], order[2 * k + 1]) for k in range(8)]
            mid_order = list(range(16))
            rng.shuffle(mid_order)
            mid_pairs = [(mid_order[2 * k], mid_order[2 * k + 1]) for k in range(8)]
            p_iter = iter(pairs)
            for day, n, slot in rounds:
                src = mid_pairs if n == 8 else None
                for k in range(n):
                    h_i, a_i = src[k] if src else next(p_iter)
                    hh, mm = slot if slot else rng.choice(lg["slots"])
                    start = day + hh * HOUR + mm * MIN - lg["off"] * HOUR
                    events.append(make_event(rng, lg, h_i, a_i, start))
        week += 1
    events.sort(key=lambda e: (e["start"], e["home"]))
    for n, e in enumerate(events):
        e["key"] = f"e{n:05d}"
    return events


def make_event(rng, lg, h_i, a_i, start):
    th, ta = lg["teams"][h_i], lg["teams"][a_i]
    lh = 1.45 * math.exp(th["att"] - ta["dfn"])
    la = 1.15 * math.exp(ta["att"] - th["dfn"])
    abandoned = rng.random() < C.ABANDON_RATE
    # Goal timeline (match minutes 0 to 90). The final score is the count of goals, so in-play prices
    # computed from the score at minute t use only information available at t.
    goals_h = sorted(rng.uniform(0.5, 90.0) for _ in range(poisson(rng, lh)))
    goals_a = sorted(rng.uniform(0.5, 90.0) for _ in range(poisson(rng, la)))
    # Match clock: 45 minutes plus first-half stoppage, 15 minutes of half-time, 45 minutes plus second-half stoppage.
    stop1 = rng.randint(1 * MIN, 5 * MIN)
    stop2 = rng.randint(2 * MIN, 8 * MIN)
    if abandoned:
        end, hs, aws = start + rng.randint(5 * MIN, 120 * MIN), None, None
    else:
        end, hs, aws = start + 105 * MIN + stop1 + stop2, len(goals_h), len(goals_a)
    p = market_probs(lh, la)
    opening, drift, outcome = {}, {}, {}
    for m, sels in MARKETS.items():
        for s in sels:
            opening[(m, s)] = min(50.0, max(1.01, 1 / (p[(m, s)] * (1 + MARGIN[m]))))
            drift[(m, s)] = rng.gauss(0, 0.04)
            outcome[(m, s)] = None if abandoned else winning(m, s, hs, aws)
    return {"comp": lg["comp"], "home": th["name"], "away": ta["name"], "start": start, "end": end,
            "abandoned": abandoned, "hs": hs, "as": aws, "p": p, "open": opening, "drift": drift, "outcome": outcome,
            "lh": lh, "la": la, "goals_h": goals_h, "goals_a": goals_a, "stop1": stop1, "stop2": stop2}


def market_probs(lh, la, cur_h=0, cur_a=0):
    """Probabilities of each selection given the current score and the goals still expected."""
    ph = [pmf(lh, k) for k in range(11)]
    pa = [pmf(la, k) for k in range(11)]
    home = draw = away = over = btts = 0.0
    for i in range(11):
        for j in range(11):
            q = ph[i] * pa[j]
            fh, fa = cur_h + i, cur_a + j
            if fh > fa:
                home += q
            elif fh == fa:
                draw += q
            else:
                away += q
            if fh + fa >= 3:
                over += q
            if fh > 0 and fa > 0:
                btts += q
    tot = home + draw + away
    clip = lambda x: min(1.0, max(0.0, x))  # noqa: E731  (guards against tiny negative rounding errors)
    return {("match_result", "home"): clip(home / tot), ("match_result", "draw"): clip(draw / tot),
            ("match_result", "away"): clip(away / tot),
            ("total_goals_2_5", "over"): clip(over / tot), ("total_goals_2_5", "under"): clip(1 - over / tot),
            ("both_teams_score", "yes"): clip(btts / tot), ("both_teams_score", "no"): clip(1 - btts / tot)}


def match_minute(ev, t):
    """Match minute at wall-clock time t, using only what is known at t.
    First half: the clock runs to 45, then stays at 45 through stoppage until the half actually ends.
    Half-time: 45. Second half: 45 plus elapsed minutes, capped at 90 during stoppage.
    The eventual end of the match (second-half stoppage, abandonment) is never read."""
    elapsed = t - ev["start"]
    first_half_end = 45 * MIN + ev["stop1"]
    if elapsed < 45 * MIN:
        return elapsed / MIN
    if elapsed < first_half_end + 15 * MIN:        # first-half stoppage or half-time; only reached once 45 has passed
        return 45.0
    return min(90.0, 45.0 + (elapsed - first_half_end - 15 * MIN) / MIN)


def inplay_open(ev, t):
    """In-play betting is offered while the match is running at t (known at t) and the clock is below 85."""
    return ev["start"] <= t < ev["end"] and match_minute(ev, t) < 85


def live_probs(ev, t):
    """In-play probabilities from the score at time t and the expected goals in the remaining minutes."""
    minute = match_minute(ev, t)
    cur_h = sum(1 for g in ev["goals_h"] if g <= minute)
    cur_a = sum(1 for g in ev["goals_a"] if g <= minute)
    left = (90.0 - minute) / 90.0
    return market_probs(ev["lh"] * left, ev["la"] * left, cur_h, cur_a)


def winning(m, s, hs, aws):
    if m == "match_result":
        w = "home" if hs > aws else "draw" if hs == aws else "away"
    elif m == "total_goals_2_5":
        w = "over" if hs + aws >= 3 else "under"
    else:
        w = "yes" if hs > 0 and aws > 0 else "no"
    return s == w


def price_at(ev, m, s, t, probs=None):
    """Offered decimal odds in hundredths, or None when the market is suspended (selection near-certain either way).
    Uses only information available at t: pre-match from the opening model, in-play from the live score."""
    if t < ev["start"]:
        frac = min(1.0, max(0.0, (t - (ev["start"] - 3 * DAY)) / (3 * DAY)))
        price = ev["open"][(m, s)] * (1 + ev["drift"][(m, s)] * frac)
    else:
        p = (probs or live_probs(ev, t))[(m, s)]
        if p < 0.02 or p > 0.97:
            return None
        price = 1 / (p * (1 + MARGIN[m]))
    return max(101, min(5000, int(round(price * 100))))


# ---------------------------------------------------------------- accounts

class Out:
    def __init__(self):
        self.accounts, self.access, self.payments, self.ledger, self.bets, self.disputes = [], [], [], [], [], []


def prepass(seed, n):
    accts = []
    for i in range(n):
        rng = random.Random(f"{seed}:acct:{i}")
        a = {"i": i, "key": f"a{i:04d}", "rng": rng, "household": None}
        code = wchoice(rng, [(c, w) for c, w, _ in HOME_COUNTRIES])
        a["country"] = code
        a["offset"] = {c: o for c, _, o in HOME_COUNTRIES}[code]
        a["arch"] = wchoice(rng, [(k, v["share"]) for k, v in ARCHETYPES.items()])
        if rng.random() < 0.25:
            day = rng.randrange(0, 21)
        else:
            day = rng.randrange(0, (R - DAY - L) // DAY)
        hour = wchoice(rng, list(zip(range(24), HOUR_WEIGHTS)))
        a["created"] = min(R - DAY, max(L + 60, L + day * DAY + hour * HOUR - a["offset"] * HOUR + rng.randrange(HOUR)))
        accts.append(a)
    mrng = random.Random(f"{seed}:households")
    n_pairs = round(C.HOUSEHOLD_ACCOUNT_SHARE * n / 2)
    pool = list(range(n))
    mrng.shuffle(pool)
    paired = set()
    p = 0
    for x in pool:
        if p >= n_pairs:
            break
        if x in paired:
            continue
        mates = [y for y in pool if y != x and y not in paired and accts[y]["country"] == accts[x]["country"]]
        if not mates:
            continue
        y = mates[0]
        paired.update((x, y))
        for z in (x, y):
            accts[z]["household"] = f"hh{p:03d}"
        p += 1
    return accts


class AccountSim:
    def __init__(self, a, events, starts, out):
        self.a, self.rng, self.events, self.starts, self.out = a, a["rng"], events, starts, out
        self.arch = ARCHETYPES[a["arch"]]
        self.key = a["key"]
        self.balance = 0
        self.pending = []
        self.ctr = 0
        self.n_sess = self.n_acc = self.n_pay = self.n_led = self.n_bet = self.n_dsp = self.n_ref = 0
        self.used_devices = set()

    # ---- infrastructure
    def push(self, t, rank, fn):
        self.ctr += 1
        heapq.heappush(self.pending, (t, rank, self.ctr, fn))

    def advance(self, t, rank):
        while self.pending and (self.pending[0][0], self.pending[0][1]) < (t, rank):
            _, _, _, fn = heapq.heappop(self.pending)
            fn()

    def ledger(self, t, etype, amount, payment=None, bet=None):
        self.balance += amount
        if self.balance < 0:
            raise RuntimeError(f"negative balance on {self.key} at {t}")
        self.n_led += 1
        self.out.ledger.append({"key": f"{self.key}:l{self.n_led:06d}", "acct": self.key, "t": t, "type": etype,
                                "amount": amount, "payment": payment, "bet": bet, "rank": RANK[etype],
                                "balance_after": self.balance})

    def access(self, t, etype, success, session, device, ip, ctry, instrument=None):
        self.n_acc += 1
        self.out.access.append({"key": f"{self.key}:x{self.n_acc:05d}", "acct": self.key, "t": t, "type": etype,
                                "success": success, "session": session, "device": device, "ip": ip, "ctry": ctry,
                                "instrument": instrument})

    # ---- precomputed processes
    def setup(self):
        a, rng = self.a, self.rng
        created = a["created"]
        self.created = created
        self.kyc = created + rng.randint(2 * HOUR, 5 * DAY) if rng.random() < C.KYC_SHARE else None
        self.deposits_ever = rng.random() >= C.NO_DEPOSIT_SHARE
        end = H
        if a["arch"] == "churned":
            end = created + rng.randint(7 * DAY, 42 * DAY)
        elif a["arch"] == "casual" and rng.random() < C.LATE_DROPOUT_CASUAL:
            end = created + rng.randint(45 * DAY, 140 * DAY)
        u = rng.random()
        self.status_change = None
        if u < C.CLOSED_SHARE:
            self.status_change = ("closed", created + rng.randint(14 * DAY, 150 * DAY))
        elif u < C.CLOSED_SHARE + C.SELF_EXCLUDED_SHARE:
            self.status_change = ("self_excluded", created + rng.randint(14 * DAY, 150 * DAY))
        if self.status_change:
            end = min(end, self.status_change[1])
        self.stop = min(end, H)
        # devices
        first = f"{a['household']}:dev" if a["household"] else f"{self.key}:d0"
        self.devices = [first]
        self.device_changes, t, n = [], created, 0
        while True:
            t += int(rng.expovariate(C.DEVICE_CHANGE_RATE) * DAY)
            if t >= H:
                break
            n += 1
            self.device_changes.append((t, f"{self.key}:d{n}"))
        # ip rotations
        self.home_ips = self._rotations(C.HOME_IP_ROTATION_RATE, "iph")
        if a["household"]:
            self.home_ips = [(created, f"{a['household']}:ip")]
        self.mobile_ips = self._rotations(C.MOBILE_IP_ROTATION_RATE, "ipm")
        # trips
        self.trips, t, n = [], created, 0
        while True:
            t += int(rng.expovariate(C.TRIP_RATE) * DAY)
            if t >= H:
                break
            dur = rng.randint(3 * DAY, 10 * DAY)
            self.trips.append((t, t + dur, rng.choice(TRAVEL_COUNTRIES), f"{self.key}:ipt{n}"))
            n += 1
            t += dur
        # instruments and account events
        self.cards = [(created, f"{self.key}:card0")]
        if rng.random() < C.SECOND_CARD_SHARE:
            self.cards.append((created + rng.randint(30 * DAY, 150 * DAY), f"{self.key}:card1"))
        self.cards_added = set()
        self.last_card = None
        self.payout_pref = wchoice(rng, C.PAYOUT_PREFERENCE)
        self.payout_added = False
        self.email_change_at = created + rng.randint(DAY, 150 * DAY) if rng.random() < C.EMAIL_CHANGE_SHARE else None

    def _rotations(self, rate, tag):
        out, t, n = [(self.created, f"{self.key}:{tag}0")], self.created, 0
        while True:
            t += int(self.rng.expovariate(rate) * DAY)
            if t >= H:
                return out
            n += 1
            out.append((t, f"{self.key}:{tag}{n}"))

    @staticmethod
    def _current(rot, t):
        cur = rot[0][1]
        for when, key in rot:
            if when <= t:
                cur = key
            else:
                break
        return cur

    def pick_device(self, t):
        while self.device_changes and self.device_changes[0][0] <= t:
            _, new = self.device_changes.pop(0)
            if len(self.devices) < 3 and self.rng.random() < 0.4:
                self.devices.append(new)
            else:
                self.devices[-1 if len(self.devices) == 1 else self.rng.randrange(len(self.devices))] = new
                if new not in self.devices:
                    self.devices.append(new)
        if len(self.devices) == 1 or self.rng.random() < 0.6:
            return self.devices[-1]
        return self.rng.choice(self.devices)

    def pick_ip(self, t):
        for start, end, ctry, token in self.trips:
            if start <= t < end:
                return token, ctry
        if self.rng.random() < C.MOBILE_SESSION_SHARE:
            return self._current(self.mobile_ips, t), self.a["country"]
        return self._current(self.home_ips, t), self.a["country"]

    def session_times(self):
        rng, a = self.rng, self.a
        rate = self.arch["rate"]
        times = []
        d = self.created - self.created % DAY
        while d < self.stop:
            weekday = ((d - L) // DAY) % 7
            factor = 1.4 if weekday >= 5 else 0.84
            for _ in range(poisson(rng, rate * factor)):
                h = wchoice(rng, list(zip(range(24), HOUR_WEIGHTS)))
                t = d + h * HOUR - a["offset"] * HOUR + rng.randrange(HOUR)
                if self.created + 2 * HOUR < t < self.stop:
                    times.append(t)
            d += DAY
        times.sort()
        kept = []
        for t in times:
            if not kept or t - kept[-1] >= 3 * HOUR:
                kept.append(t)
        return kept

    # ---- actions
    def login(self, t, signup=False):
        rng = self.rng
        dev = self.pick_device(t)
        ip, ctry = self.pick_ip(t)
        first_use = dev not in self.used_devices
        self.reset_after = None
        if not signup:
            if (first_use and rng.random() < C.RESET_ON_NEW_DEVICE) or rng.random() < C.RESET_PER_SESSION:
                if rng.random() < 0.5:
                    # forgot the password: a few failed tries, then the reset, then the login
                    t_reset = t - rng.randint(120, 900)
                    for k in range(rng.randint(1, 3), 0, -1):
                        self.access(t_reset - k * rng.randint(10, 60), "login", False, None, dev, ip, ctry)
                    self.access(t_reset, "password_reset", True, None, dev, ip, ctry)
                else:
                    # changes the password later, through the emailed link
                    self.reset_after = (t + rng.randint(10 * MIN, 6 * HOUR), dev, ip, ctry)
            if rng.random() < C.FAILED_LOGIN_SESSION_SHARE:
                for k in range(rng.randint(1, 2), 0, -1):
                    self.access(t - k * rng.randint(5, 40), "login", False, None, dev, ip, ctry)
        self.n_sess += 1
        sess = f"{self.key}:s{self.n_sess:05d}"
        self.access(t, "login", True, sess, dev, ip, ctry)
        self.used_devices.add(dev)
        self.ctx = (sess, dev, ip, ctry)
        if self.reset_after:
            tr, d2, i2, c2 = self.reset_after
            self.access(tr, "password_reset", True, None, d2, i2, c2)
        return sess

    def in_session(self, t, etype, instrument=None):
        sess, dev, ip, ctry = self.ctx
        self.access(t, etype, True, sess, dev, ip, ctry, instrument)

    def current_card(self, t):
        card = self.cards[0][1]
        for when, key in self.cards:
            if when <= t:
                card = key
        return card

    def ensure_card(self, t):
        card = self.current_card(t)
        if card not in self.cards_added:
            self.in_session(t, "instrument_added", card)
            self.cards_added.add(card)
            self.last_card = card
            return card, t + self.rng.randint(15, 90)
        return card, t

    def new_payment(self, ptype, t, amount, instrument, status, processed, mref=None, parent=None, session=None):
        self.n_pay += 1
        key = f"{self.key}:p{self.n_pay:05d}"
        if mref is None:
            self.n_ref += 1
            mref = f"{self.key}:o{self.n_ref:05d}"
        self.out.payments.append({"key": key, "acct": self.key, "session": session, "type": ptype, "mref": mref,
                                  "parent": parent, "instrument": instrument, "amount": amount, "status": status,
                                  "created": t, "processed": processed})
        return key

    def deposit(self, t):
        rng, arch = self.rng, self.arch
        card, t = self.ensure_card(t)
        if rng.random() < 0.85:
            amount = rng.choices(arch["dep"], weights=arch["depw"], k=1)[0] * 100
        else:
            amount = rng.randint(*arch["dep_custom"]) * 100
        sess = self.ctx[0]
        for _attempt in range(2):
            if rng.random() < C.DECLINE_RATE:
                self.new_payment("deposit", t, amount, card, "declined", None, session=sess)
                if rng.random() >= C.RETRY_AFTER_DECLINE:
                    return t + rng.randint(30, 90), False
                t += rng.randint(30, 120)
                continue
            processed = t + rng.randint(1, 20)
            pay = self.new_payment("deposit", t, amount, card, "captured", processed, session=sess)
            credit_t = processed + rng.randint(1, 30)
            self.push(credit_t, RANK["deposit_credit"],
                      lambda ct=credit_t, a=amount, p=pay: self.ledger(ct, "deposit_credit", a, payment=p))
            self.maybe_dispute(pay, amount, processed)
            return credit_t + rng.randint(20, 60), True
        return t + rng.randint(30, 90), False

    def maybe_dispute(self, pay, amount, processed):
        rng = self.rng
        prob = next(p for limit, p in C.DISPUTE_PROB if amount < limit)
        if rng.random() >= prob:
            return
        receipt_delay = rng.randint(DAY, 7 * DAY)
        lag = int(min(rng.lognormvariate(math.log(10), 0.6), 55) * DAY)
        lag = max(lag, DAY)
        lag = min(lag, C.DISPUTE_LAG_CAP - receipt_delay - HOUR)
        filed = processed + lag
        received = filed + receipt_delay
        resolved = received + rng.randint(10 * DAY, 45 * DAY)
        self.n_dsp += 1
        self.out.disputes.append({"key": f"{self.key}:q{self.n_dsp:03d}", "payment": pay, "acct": self.key,
                                  "reason": wchoice(rng, C.DISPUTE_REASON), "amount": amount, "filed": filed,
                                  "received": received, "status": wchoice(rng, C.DISPUTE_OUTCOME),
                                  "resolved": resolved})
        if rng.random() < C.DISPUTE_STOP_SHARE:
            self.stop = min(self.stop, filed)

    def choose_event(self, t):
        rng = self.rng
        lo = bisect.bisect_left(self.starts, t - 130 * MIN)
        hi = bisect.bisect_right(self.starts, t + 6 * DAY)
        live, pre = [], []
        for ev in self.events[lo:hi]:
            if inplay_open(ev, t):
                live.append(ev)
            elif ev["start"] >= t + 10 * MIN:
                pre.append(ev)
        if live and (rng.random() < C.INPLAY_SHARE or not pre):
            return rng.choice(live)
        if not pre:
            return None
        weights = [math.exp(-(e["start"] - t) / (36 * HOUR)) for e in pre]
        return rng.choices(pre, weights=weights, k=1)[0]

    def bet(self, t):
        rng, arch = self.rng, self.arch
        self.advance(t, RANK["stake"])
        ev = self.choose_event(t)
        if ev is None:
            return False
        if rng.random() < 0.88:
            stake = rng.choices(arch["stakes"], weights=arch["stakew"], k=1)[0] * 100
        else:
            stake = rng.randint(1, 2 * max(arch["stakes"])) * 100
        if stake > self.balance:
            stake = (self.balance // 100) * 100
        if stake < 100:
            return False
        probs = ev["p"] if t < ev["start"] else live_probs(ev, t)
        m = wchoice(rng, MARKET_WEIGHTS)
        sels = MARKETS[m]
        s = rng.choices(sels, weights=[probs[(m, x)] ** 1.3 for x in sels], k=1)[0]
        odds = price_at(ev, m, s, t, probs)
        if odds is None:
            return True   # market suspended at this moment: no bet, the session carries on
        self.n_bet += 1
        bkey = f"{self.key}:b{self.n_bet:06d}"
        self.ledger(t, "stake", -stake, bet=bkey)
        settle = ev["end"] + rng.randint(60, 1800)
        if ev["abandoned"]:
            status, payout = "void", stake
        elif ev["outcome"][(m, s)]:
            status, payout = "won", (stake * odds + 50) // 100
        else:
            status, payout = "lost", 0
        if settle > H:
            status, payout, settle = "open", None, None
        self.out.bets.append({"key": bkey, "acct": self.key, "session": self.ctx[0], "event": ev["key"], "market": m,
                              "selection": s, "odds": odds, "stake": stake, "placed": t, "status": status,
                              "settled": settle, "payout": payout})
        if status in ("won", "void"):
            etype = "bet_payout" if status == "won" else "bet_void"
            self.push(settle, RANK[etype], lambda st=settle, e=etype, p=payout, b=bkey: self.ledger(st, e, p, bet=b))
        return True

    def maybe_withdraw(self, t, force=False):
        rng = self.rng
        self.advance(t, RANK["withdrawal_hold"])
        if self.kyc is None or self.kyc >= t:
            return t
        typical_dep = sum(self.arch["dep"]) / len(self.arch["dep"]) * 100
        threshold = 1000 if force else max(5000, 2 * typical_dep)
        if self.balance < threshold or (not force and rng.random() >= 0.55):
            return t
        amount = (int(self.balance * (1.0 if force else rng.uniform(0.7, 1.0))) // 100) * 100
        amount = max(1000, min(amount, (self.balance // 100) * 100))
        if self.payout_pref == "card" and self.last_card is not None:
            instrument = self.last_card   # return to the most recently added card
        else:
            instrument = f"{self.key}:{'ewal' if self.payout_pref == 'ewallet' else 'bank'}0"
            if not self.payout_added:
                self.in_session(t, "instrument_added", instrument)
                self.payout_added = True
                t += rng.randint(30, 120)
                self.advance(t, RANK["withdrawal_hold"])
                if self.balance < amount:
                    return t
        outcome = wchoice(rng, C.WITHDRAWAL_OUTCOME)
        if outcome == "paid":
            delay = rng.randint(12 * HOUR, 48 * HOUR) if rng.random() < 0.85 else rng.randint(48 * HOUR, 5 * DAY)
        elif outcome == "rejected":
            delay = rng.randint(HOUR, 72 * HOUR)
        else:
            delay = rng.randint(30 * MIN, 20 * HOUR)
        processed = t + delay
        pay = self.new_payment("withdrawal", t, amount, instrument, outcome, processed, session=self.ctx[0])
        self.ledger(t, "withdrawal_hold", -amount, payment=pay)
        if outcome in ("rejected", "cancelled"):
            self.push(processed, RANK["withdrawal_release"],
                      lambda pt=processed, a=amount, p=pay: self.ledger(pt, "withdrawal_release", a, payment=p))
        return t

    def session(self, t0, signup=False):
        rng, arch = self.rng, self.arch
        self.advance(t0, 0)
        self.login(t0, signup)
        t = t0 + rng.randint(15, 90)
        if self.email_change_at is not None and t >= self.email_change_at:
            self.in_session(t, "email_change")
            self.email_change_at = None
            t += rng.randint(20, 120)
        if self.deposits_ever:
            self.advance(t, 0)
            low = self.balance < 3 * min(arch["stakes"]) * 100 * 3
            if (signup and rng.random() < 0.8) or (not signup and ((low and rng.random() < 0.9) or rng.random() < 0.15)):
                t, _ = self.deposit(t)
        for _ in range(rng.randint(*arch["bets"])):
            t += rng.randint(20, 300)
            if not self.bet(t):
                break
        t += rng.randint(20, 200)
        self.maybe_withdraw(t)
        return t

    def run(self):
        a, rng = self.a, self.rng
        self.setup()
        last = self.session(self.created + rng.randint(10, 90), signup=True)
        for t in self.session_times():
            if t >= self.stop or t <= last + 10 * MIN:
                continue
            last = self.session(t)
        status_change = self.status_change
        if status_change and status_change[1] < H:
            t = max(status_change[1], last + 15 * MIN)
            if t < H - HOUR:
                # closing session: the customer withdraws what is left, then the status changes
                self.advance(t, 0)
                self.login(t)
                t_end = self.maybe_withdraw(t + rng.randint(30, 120), force=True)
                status_change = (status_change[0], t_end + rng.randint(5 * MIN, 30 * MIN))
            else:
                status_change = None
        self.advance(H, 99)
        self.out.accounts.append({"key": self.key, "created": self.created, "country": a["country"], "kyc": self.kyc,
                                  "status_change": status_change, "arch": a["arch"], "household": a["household"]})


# ---------------------------------------------------------------- IDs, snapshot, export

class IdMaker:
    def __init__(self, seed, id_seed=0):
        self.rng = random.Random(f"{seed}:ids:{id_seed}")
        self.used = set()

    def make(self, prefix):
        while True:
            tok = prefix + "-" + "".join(self.rng.choice(CROCKFORD) for _ in range(8))
            if tok not in self.used:
                self.used.add(tok)
                return tok


def assign_ids(seed, out, events, id_seed=0):
    mk = IdMaker(seed, id_seed)
    ids = {}

    def assign(prefix, keys):
        for k in sorted(set(keys)):
            if k is not None and k not in ids:
                ids[k] = mk.make(prefix)

    assign("ACC", [a["key"] for a in out.accounts])
    assign("EVT", [e["key"] for e in events])
    assign("SES", [x["session"] for x in out.access if x["session"]])
    assign("DEV", [x["device"] for x in out.access])
    assign("IPT", [x["ip"] for x in out.access])
    assign("ACS", [x["key"] for x in out.access])
    instruments = {x["instrument"] for x in out.access if x["instrument"]} | {p["instrument"] for p in out.payments}
    for kind, prefix in (("card", "CARD"), ("bank", "BANK"), ("ewal", "EWAL")):
        assign(prefix, [k for k in instruments if k.split(":")[-1].startswith(kind)])
    assign("PAY", [p["key"] for p in out.payments])
    assign("ORD", [p["mref"] for p in out.payments])
    assign("LED", [l["key"] for l in out.ledger])
    assign("BET", [b["key"] for b in out.bets])
    assign("DSP", [d["key"] for d in out.disputes])
    return ids


def snapshot(out, events):
    """Cut the full simulation down to what the operator knew at R (Step 0: As-of-R snapshot)."""
    snap = Out()
    for a in out.accounts:
        if a["created"] >= R:
            continue
        status = "active"
        if a["status_change"] and a["status_change"][1] < R:
            status = a["status_change"][0]
        snap.accounts.append(dict(a, kyc=a["kyc"] if a["kyc"] is not None and a["kyc"] < R else None, status=status))
    snap.access = [dict(x) for x in out.access if x["t"] < R]
    dropped_pay = set()
    for p in out.payments:
        if p["created"] >= R:
            dropped_pay.add(p["key"])
            continue
        q = dict(p)
        if q["type"] == "deposit" and q["processed"] is not None and q["processed"] >= R:
            dropped_pay.add(q["key"])
            continue
        if q["type"] == "refund" and q["processed"] >= R:
            dropped_pay.add(q["key"])
            continue
        if q["type"] == "withdrawal" and q["processed"] >= R:
            q["status"], q["processed"] = "pending", None
        snap.payments.append(q)
    snap.ledger = [dict(l) for l in out.ledger if l["t"] < R]
    for b in out.bets:
        if b["placed"] >= R:
            continue
        q = dict(b)
        if q["settled"] is None or q["settled"] >= R:
            q["status"], q["settled"], q["payout"] = "open", None, None
        snap.bets.append(q)
    for d in out.disputes:
        if d["received"] >= R or d["payment"] in dropped_pay:
            continue
        q = dict(d)
        if q["resolved"] >= R:
            q["status"], q["resolved"] = "open", None
        snap.disputes.append(q)
    snap_events = []
    for e in events:
        if e["start"] >= FIXTURE_HORIZON:
            continue
        q = {"key": e["key"], "comp": e["comp"], "home": e["home"], "away": e["away"], "start": e["start"]}
        if e["end"] < R:
            q.update(status="abandoned" if e["abandoned"] else "completed", end=e["end"], hs=e["hs"], aws=e["as"])
        else:
            q.update(status="in_play" if e["start"] < R else "scheduled", end=None, hs=None, aws=None)
        snap_events.append(q)
    return snap, snap_events


def sequence_ledger(ledger, ids):
    ledger.sort(key=lambda l: (l["t"], l["rank"], ids[l["key"]]))
    for n, l in enumerate(ledger, 1):
        l["seq"] = n


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def export_buyer(snap, snap_events, ids, folder):
    os.makedirs(folder, exist_ok=True)
    I = lambda k: "" if k is None else ids[k]  # noqa: E731
    tables = {
        "accounts": [[I(a["key"]), fmt_ts(a["created"]), a["country"], fmt_ts(a["kyc"]), a["status"]] for a in snap.accounts],
        "account_access": [[I(x["key"]), I(x["acct"]), fmt_ts(x["t"]), x["type"], fmt_bool(x["success"]), I(x["session"]),
                            I(x["device"]), I(x["ip"]), x["ctry"], I(x["instrument"])] for x in snap.access],
        "payments": [[I(p["key"]), I(p["acct"]), I(p["session"]), p["type"], I(p["mref"]), I(p["parent"]),
                      I(p["instrument"]), fmt_cents(p["amount"]), "USD", p["status"], fmt_ts(p["created"]),
                      fmt_ts(p["processed"])] for p in snap.payments],
        "wallet_ledger": [[I(l["key"]), l["seq"], I(l["acct"]), fmt_ts(l["t"]), l["type"], fmt_cents(l["amount"]),
                           I(l["payment"]), I(l["bet"])] for l in snap.ledger],
        "bets": [[I(b["key"]), I(b["acct"]), I(b["session"]), I(b["event"]), b["market"], b["selection"],
                  fmt_cents(b["odds"]), fmt_cents(b["stake"]), fmt_ts(b["placed"]), b["status"], fmt_ts(b["settled"]),
                  fmt_cents(b["payout"])] for b in snap.bets],
        "events": [[I(e["key"]), "football", e["comp"], e["home"], e["away"], fmt_ts(e["start"]), e["status"],
                    fmt_ts(e["end"]), "" if e["hs"] is None else e["hs"], "" if e["aws"] is None else e["aws"]]
                   for e in snap_events],
        "disputes": [[I(d["key"]), I(d["payment"]), I(d["acct"]), d["reason"], fmt_cents(d["amount"]),
                      fmt_ts(d["filed"]), fmt_ts(d["received"]), d["status"], fmt_ts(d["resolved"])]
                     for d in snap.disputes],
    }
    for name, rows in tables.items():
        rows.sort(key=lambda r: r[0])   # sorted by random primary key: row position carries nothing (L3)
        write_csv(os.path.join(folder, f"{name}.csv"), [c for c, _, _ in SCHEMA[name]], rows)
    schema_dir = os.path.join(folder, "schema")
    os.makedirs(schema_dir, exist_ok=True)
    for name in SCHEMA:
        with open(os.path.join(schema_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(bigquery_schema_json(name), f, indent=2)
    return {k: len(v) for k, v in tables.items()}


def export_designer(out, snap, events, ids, folder, meta, overlay_tables=None):
    """Designer-only files. overlay_tables (from a private overlay) maps table name to (columns, rows)."""
    os.makedirs(folder, exist_ok=True)
    overlay_tables = overlay_tables or {}
    for name, cols in DESIGNER_TABLES.items():
        rows = overlay_tables.get(name, (None, []))[1]
        write_csv(os.path.join(folder, f"{name}.csv"), [c for c, _, _ in cols], rows)
    extra = {name: cols for name, (cols, _) in overlay_tables.items() if name not in DESIGNER_TABLES}
    for name, cols in extra.items():
        write_csv(os.path.join(folder, f"{name}.csv"), cols, overlay_tables[name][1])
    if extra:
        with open(os.path.join(folder, "extra_tables.json"), "w", encoding="utf-8") as f:
            json.dump(extra, f, indent=2)
    # buyer ledger with balance_after (recomputed in entry_seq order) for designer-side checks
    bal, rows = {}, []
    for l in sorted(snap.ledger, key=lambda x: x["seq"]):
        bal[l["acct"]] = bal.get(l["acct"], 0) + l["amount"]
        rows.append([ids[l["key"]], l["seq"], fmt_cents(bal[l["acct"]])])
    write_csv(os.path.join(folder, "buyer_ledger_balance_after.csv"), ["entry_id", "entry_seq", "balance_after"], rows)
    # account profile map (internal, never shipped)
    write_csv(os.path.join(folder, "account_profiles.csv"),
              ["account_id", "internal_key", "archetype", "household", "status_change", "status_change_at"],
              [[ids[a["key"]], a["key"], a["arch"], a["household"] or "",
                a["status_change"][0] if a["status_change"] else "",
                fmt_ts(a["status_change"][1]) if a["status_change"] else ""] for a in out.accounts])
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def generate(seed, n_accounts, folder, id_seed=0, private_seed=False, overlay=None):
    """overlay: an optional private module whose build() adds scripted accounts after the background is simulated.
    The background accounts draw from their own streams, so an overlay never changes them; only IDs, which are
    assigned after the merge, differ."""
    events = gen_fixtures(seed)
    starts = [e["start"] for e in events]
    out = Out()
    for a in prepass(seed, n_accounts):
        AccountSim(a, events, starts, out).run()
    finish = overlay.build(seed, n_accounts, events, starts, out) if overlay else None
    ids = assign_ids(seed, out, events, id_seed)
    snap, snap_events = snapshot(out, events)
    sequence_ledger(snap.ledger, ids)
    counts = export_buyer(snap, snap_events, ids, os.path.join(folder, "buyer"))
    meta = {"data_version": DATA_VERSION, "seed": None if private_seed else seed,
            "seed_sha256_prefix": hashlib.sha256(str(seed).encode()).hexdigest()[:16],
            "id_seed": id_seed, "accounts_simulated": n_accounts, "overlay": bool(overlay),
            "buyer_row_counts": counts, "full_simulation_rows": {
                "accounts": len(out.accounts), "access": len(out.access), "payments": len(out.payments),
                "ledger": len(out.ledger), "bets": len(out.bets), "disputes": len(out.disputes), "events": len(events)}}
    overlay_tables = finish(snap, snap_events, ids, os.path.join(folder, "designer")) if finish else None
    export_designer(out, snap, events, ids, os.path.join(folder, "designer"), meta, overlay_tables)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True, help="any seed string; the public sample uses sample-2026")
    ap.add_argument("--accounts", type=int, default=500)
    ap.add_argument("--id-seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    meta = generate(args.seed, args.accounts, args.out, args.id_seed)
    print(json.dumps(meta, indent=2))
