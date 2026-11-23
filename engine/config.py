"""Frozen constants from Step 0 v2.1. All times are integer seconds since the Unix epoch, UTC."""
from datetime import datetime, timezone


def _ts(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


MIN, HOUR, DAY = 60, 3600, 86400

L = _ts(2026, 3, 2, 0, 0, 0)            # operator launch
R = _ts(2026, 9, 14, 13, 0, 0)          # referral and extract cutoff
H = R + 60 * DAY                         # simulation horizon (designer only)
W_START = R - 30 * DAY                   # referral window and base-rate lookback start
MATURITY = R - 60 * DAY                  # deposits processed before this are mature
FIXTURE_HORIZON = R + 14 * DAY           # latest scheduled_start in the extract
DISPUTE_LAG_CAP = 60 * DAY
REFERRAL_THRESHOLD_CENTS = 8000

# The production seed is private and high-entropy, and never appears in code or public history.
# Robustness seeds and the public sample seed are not secret.
ROBUSTNESS_SEEDS = ("101", "202", "303")
PUBLIC_SAMPLE_SEED = "sample-2026"
DATA_VERSION = "case01-data-v0.3.0-step2"   # becomes case01-data-v1.0.0 at freeze

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# Home markets: (ISO code, weight, summer UTC offset in hours)
HOME_COUNTRIES = [("IE", 35, 1), ("SE", 25, 2), ("FI", 20, 3), ("CA", 20, -4)]
TRAVEL_COUNTRIES = ["PT", "ES", "GR", "IT", "HR", "US", "TH", "NL", "DE", "FR"]

ARCHETYPES = {
    #            share, sessions/day, bets per session, deposit presets (USD), weights, custom range, stakes (USD), weights
    "casual":  dict(share=55, rate=1 / 7, bets=(1, 3), dep=[10, 20, 25, 50], depw=[30, 35, 15, 20], dep_custom=(10, 60),
                    stakes=[1, 2, 5, 10], stakew=[20, 35, 35, 10]),
    "regular": dict(share=30, rate=3 / 7, bets=(2, 6), dep=[20, 25, 50, 100], depw=[20, 15, 40, 25], dep_custom=(20, 150),
                    stakes=[2, 5, 10, 20], stakew=[15, 35, 35, 15]),
    "heavy":   dict(share=10, rate=6 / 7, bets=(3, 12), dep=[50, 100, 200, 500], depw=[25, 40, 25, 10], dep_custom=(50, 600),
                    stakes=[5, 10, 20, 50, 100], stakew=[15, 30, 30, 18, 7]),
    "churned": dict(share=5, rate=2 / 7, bets=(1, 3), dep=[10, 20, 25, 50], depw=[30, 35, 15, 20], dep_custom=(10, 60),
                    stakes=[1, 2, 5, 10], stakew=[20, 35, 35, 10]),
}

# Local-time hour weights for session starts (0h to 23h)
HOUR_WEIGHTS = [0.3, 0.2, 0.1, 0.1, 0.1, 0.1, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8,
                1.0, 1.0, 1.0, 1.1, 1.3, 1.6, 2.0, 2.4, 2.4, 2.0, 1.4, 0.7]

# Behavioral rates (per day unless stated)
DEVICE_CHANGE_RATE = 0.012
TRIP_RATE = 0.0041
HOME_IP_ROTATION_RATE = 1 / 45
MOBILE_IP_ROTATION_RATE = 1 / 10
MOBILE_SESSION_SHARE = 0.35
RESET_ON_NEW_DEVICE = 0.15
RESET_PER_SESSION = 0.002
EMAIL_CHANGE_SHARE = 0.04
FAILED_LOGIN_SESSION_SHARE = 0.04
HOUSEHOLD_ACCOUNT_SHARE = 0.03
DECLINE_RATE = 0.08
RETRY_AFTER_DECLINE = 0.70
SECOND_CARD_SHARE = 0.05
KYC_SHARE = 0.88
NO_DEPOSIT_SHARE = 0.05
CLOSED_SHARE = 0.02
SELF_EXCLUDED_SHARE = 0.01
LATE_DROPOUT_CASUAL = 0.12
INPLAY_SHARE = 0.45
DISPUTE_PROB = [(5000, 0.004), (10000, 0.008), (10 ** 12, 0.020)]   # (amount below, probability), cents
DISPUTE_STOP_SHARE = 0.50
WITHDRAWAL_OUTCOME = [("paid", 94), ("rejected", 4), ("cancelled", 2)]
PAYOUT_PREFERENCE = [("card", 50), ("bank", 30), ("ewallet", 20)]
DISPUTE_REASON = [("unauthorized", 85), ("other", 15)]
DISPUTE_OUTCOME = [("accepted", 25), ("won", 30), ("lost", 45)]
ABANDON_RATE = 0.005
