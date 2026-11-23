-- Case 01 integrity assertions (Step 0 v2.1).
-- Dialect: BigQuery. Every assertion must return zero rows.
-- Buyer tables live in dataset `case01`. Designer-only tables live in dataset `designer`.
-- Constants: L = 2026-03-02 00:00:00 UTC, R = 2026-09-14 13:00:00 UTC, fixture horizon = 2026-09-28 13:00:00 UTC.
-- COUNTIF is written as SUM(CASE WHEN ... THEN 1 ELSE 0 END) on purpose: it returns 0, never NULL, in every dialect.
-- Blocks are separated by "-- @id" headers; "-- @scope designer" marks checks that need designer data.

-- @id R1
-- @desc Primary keys are unique in all seven tables (and entry_seq is unique)
-- @scope buyer
SELECT 'accounts' AS tbl, account_id AS id FROM case01.accounts GROUP BY account_id HAVING COUNT(*) > 1
UNION ALL SELECT 'account_access', access_id FROM case01.account_access GROUP BY access_id HAVING COUNT(*) > 1
UNION ALL SELECT 'payments', payment_id FROM case01.payments GROUP BY payment_id HAVING COUNT(*) > 1
UNION ALL SELECT 'wallet_ledger', entry_id FROM case01.wallet_ledger GROUP BY entry_id HAVING COUNT(*) > 1
UNION ALL SELECT 'wallet_ledger.entry_seq', CAST(entry_seq AS STRING) FROM case01.wallet_ledger GROUP BY entry_seq HAVING COUNT(*) > 1
UNION ALL SELECT 'bets', bet_id FROM case01.bets GROUP BY bet_id HAVING COUNT(*) > 1
UNION ALL SELECT 'events', event_id FROM case01.events GROUP BY event_id HAVING COUNT(*) > 1
UNION ALL SELECT 'disputes', dispute_id FROM case01.disputes GROUP BY dispute_id HAVING COUNT(*) > 1;

-- @id R2
-- @desc Every account_id, event_id, payment_id, bet_id and parent_payment_id resolves
-- @scope buyer
SELECT 'account_access.account_id' AS ref, x.access_id AS id FROM case01.account_access x LEFT JOIN case01.accounts a ON x.account_id = a.account_id WHERE a.account_id IS NULL
UNION ALL SELECT 'payments.account_id', x.payment_id FROM case01.payments x LEFT JOIN case01.accounts a ON x.account_id = a.account_id WHERE a.account_id IS NULL
UNION ALL SELECT 'wallet_ledger.account_id', x.entry_id FROM case01.wallet_ledger x LEFT JOIN case01.accounts a ON x.account_id = a.account_id WHERE a.account_id IS NULL
UNION ALL SELECT 'bets.account_id', x.bet_id FROM case01.bets x LEFT JOIN case01.accounts a ON x.account_id = a.account_id WHERE a.account_id IS NULL
UNION ALL SELECT 'disputes.account_id', x.dispute_id FROM case01.disputes x LEFT JOIN case01.accounts a ON x.account_id = a.account_id WHERE a.account_id IS NULL
UNION ALL SELECT 'bets.event_id', x.bet_id FROM case01.bets x LEFT JOIN case01.events e ON x.event_id = e.event_id WHERE e.event_id IS NULL
UNION ALL SELECT 'wallet_ledger.payment_id', x.entry_id FROM case01.wallet_ledger x LEFT JOIN case01.payments p ON x.payment_id = p.payment_id WHERE x.payment_id IS NOT NULL AND p.payment_id IS NULL
UNION ALL SELECT 'wallet_ledger.bet_id', x.entry_id FROM case01.wallet_ledger x LEFT JOIN case01.bets b ON x.bet_id = b.bet_id WHERE x.bet_id IS NOT NULL AND b.bet_id IS NULL
UNION ALL SELECT 'disputes.payment_id', x.dispute_id FROM case01.disputes x LEFT JOIN case01.payments p ON x.payment_id = p.payment_id WHERE p.payment_id IS NULL
UNION ALL SELECT 'payments.parent_payment_id', x.payment_id FROM case01.payments x LEFT JOIN case01.payments p ON x.parent_payment_id = p.payment_id WHERE x.parent_payment_id IS NOT NULL AND p.payment_id IS NULL;

-- @id R3
-- @desc Session links: in-session actions belong to an earlier successful login of the same account, within 12 hours; session fields follow the schema rules
-- @scope buyer
WITH logins AS (
  SELECT session_id, account_id, event_time AS login_time
  FROM case01.account_access
  WHERE event_type = 'login' AND success
),
actions AS (
  SELECT 'payments' AS src, payment_id AS id, account_id, session_id, created_at AS t FROM case01.payments WHERE payment_type IN ('deposit', 'withdrawal')
  UNION ALL SELECT 'bets', bet_id, account_id, session_id, placed_at FROM case01.bets
  UNION ALL SELECT 'account_access', access_id, account_id, session_id, event_time FROM case01.account_access WHERE event_type IN ('email_change', 'instrument_added')
)
SELECT a.src, a.id, 'bad session link' AS problem
FROM actions a LEFT JOIN logins l ON a.session_id = l.session_id
WHERE l.session_id IS NULL
   OR l.account_id != a.account_id
   OR a.t < l.login_time
   OR a.t >= TIMESTAMP_ADD(l.login_time, INTERVAL 12 HOUR)
UNION ALL
SELECT 'payments', payment_id, 'refund with a session, or deposit/withdrawal without one'
FROM case01.payments
WHERE (payment_type = 'refund' AND session_id IS NOT NULL)
   OR (payment_type IN ('deposit', 'withdrawal') AND session_id IS NULL)
UNION ALL
SELECT 'account_access', access_id, 'session_id present where it must be null, or missing'
FROM case01.account_access
WHERE ((event_type = 'login' AND NOT success) OR event_type = 'password_reset') AND session_id IS NOT NULL
   OR ((event_type = 'login' AND success) OR event_type IN ('email_change', 'instrument_added')) AND session_id IS NULL
UNION ALL
SELECT 'account_access', session_id, 'session opened by more than one login'
FROM logins GROUP BY session_id HAVING COUNT(*) > 1;

-- @id R4
-- @desc Each ledger entry references exactly one parent of the right kind, on the same account
-- @scope buyer
SELECT l.entry_id
FROM case01.wallet_ledger l
LEFT JOIN case01.payments p ON l.payment_id = p.payment_id
LEFT JOIN case01.bets b ON l.bet_id = b.bet_id
WHERE (l.payment_id IS NULL) = (l.bet_id IS NULL)
   OR (l.payment_id IS NOT NULL AND p.account_id != l.account_id)
   OR (l.bet_id IS NOT NULL AND b.account_id != l.account_id)
   OR (l.entry_type IN ('deposit_credit', 'withdrawal_hold', 'withdrawal_release') AND l.payment_id IS NULL)
   OR (l.entry_type IN ('stake', 'bet_payout', 'bet_void') AND l.bet_id IS NULL);

-- @id R5
-- @desc Disputes reference captured deposits only, at most one per payment, same account, equal amount
-- @scope buyer
SELECT d.dispute_id AS id, 'bad parent' AS problem
FROM case01.disputes d LEFT JOIN case01.payments p ON d.payment_id = p.payment_id
WHERE p.payment_id IS NULL OR p.payment_type != 'deposit' OR p.status != 'captured'
   OR p.account_id != d.account_id OR p.amount != d.amount
UNION ALL
SELECT payment_id, 'more than one dispute' FROM case01.disputes GROUP BY payment_id HAVING COUNT(*) > 1;

-- @id R6
-- @desc Every instrument used for deposits or withdrawals was added earlier on the same account; instrument_id only on instrument_added
-- @scope buyer
SELECT p.payment_id AS id, 'instrument never added' AS problem
FROM case01.payments p
WHERE p.payment_type IN ('deposit', 'withdrawal')
  AND NOT EXISTS (
    SELECT 1 FROM case01.account_access a
    WHERE a.event_type = 'instrument_added'
      AND a.instrument_id = p.instrument_id
      AND a.account_id = p.account_id
      AND a.event_time <= p.created_at)
UNION ALL
SELECT access_id, 'instrument_id misplaced'
FROM case01.account_access
WHERE (event_type = 'instrument_added') != (instrument_id IS NOT NULL);

-- @id T1
-- @desc Every timestamp is in [L, R); only scheduled fixtures may start between R and the fixture horizon
-- @scope buyer
WITH ts AS (
  SELECT 'accounts.created_at' AS col, account_id AS id, created_at AS t FROM case01.accounts
  UNION ALL SELECT 'accounts.kyc_verified_at', account_id, kyc_verified_at FROM case01.accounts
  UNION ALL SELECT 'account_access.event_time', access_id, event_time FROM case01.account_access
  UNION ALL SELECT 'payments.created_at', payment_id, created_at FROM case01.payments
  UNION ALL SELECT 'payments.processed_at', payment_id, processed_at FROM case01.payments
  UNION ALL SELECT 'wallet_ledger.entry_time', entry_id, entry_time FROM case01.wallet_ledger
  UNION ALL SELECT 'bets.placed_at', bet_id, placed_at FROM case01.bets
  UNION ALL SELECT 'bets.settled_at', bet_id, settled_at FROM case01.bets
  UNION ALL SELECT 'events.ended_at', event_id, ended_at FROM case01.events
  UNION ALL SELECT 'disputes.filed_at', dispute_id, filed_at FROM case01.disputes
  UNION ALL SELECT 'disputes.received_at', dispute_id, received_at FROM case01.disputes
  UNION ALL SELECT 'disputes.resolved_at', dispute_id, resolved_at FROM case01.disputes
)
SELECT col, id, t FROM ts
WHERE t IS NOT NULL
  AND (t < TIMESTAMP '2026-03-02 00:00:00 UTC' OR t >= TIMESTAMP '2026-09-14 13:00:00 UTC')
UNION ALL
SELECT 'events.scheduled_start', event_id, scheduled_start
FROM case01.events
WHERE scheduled_start < TIMESTAMP '2026-03-02 00:00:00 UTC'
   OR scheduled_start >= TIMESTAMP '2026-09-28 13:00:00 UTC'
   OR (scheduled_start >= TIMESTAMP '2026-09-14 13:00:00 UTC' AND status != 'scheduled');

-- @id T2
-- @desc No account activity before created_at; KYC verification after creation
-- @scope buyer
WITH act AS (
  SELECT account_id, event_time AS t, access_id AS id FROM case01.account_access
  UNION ALL SELECT account_id, created_at, payment_id FROM case01.payments
  UNION ALL SELECT account_id, placed_at, bet_id FROM case01.bets
  UNION ALL SELECT account_id, entry_time, entry_id FROM case01.wallet_ledger
)
SELECT act.id FROM act JOIN case01.accounts a ON act.account_id = a.account_id
WHERE act.t < a.created_at
UNION ALL
SELECT account_id FROM case01.accounts WHERE kyc_verified_at <= created_at;

-- @id T3
-- @desc Deposits are captured 1 to 20 seconds after created_at and credited 1 to 30 seconds after capture; declined deposits have no processed_at
-- @scope buyer
SELECT payment_id AS id FROM case01.payments
WHERE payment_type = 'deposit' AND status = 'captured'
  AND (processed_at IS NULL OR TIMESTAMP_DIFF(processed_at, created_at, SECOND) NOT BETWEEN 1 AND 20)
UNION ALL
SELECT payment_id FROM case01.payments
WHERE payment_type = 'deposit' AND status = 'declined' AND processed_at IS NOT NULL
UNION ALL
SELECT l.entry_id FROM case01.wallet_ledger l JOIN case01.payments p ON l.payment_id = p.payment_id
WHERE l.entry_type = 'deposit_credit'
  AND TIMESTAMP_DIFF(l.entry_time, p.processed_at, SECOND) NOT BETWEEN 1 AND 30;

-- @id T4
-- @desc Withdrawals: paid 12 hours to 5 days after request, decided within 5 days, pending ones undecided, KYC verified before every request
-- @scope buyer
SELECT p.payment_id
FROM case01.payments p JOIN case01.accounts a ON p.account_id = a.account_id
WHERE p.payment_type = 'withdrawal'
  AND (
    (p.status = 'paid' AND (p.processed_at IS NULL OR TIMESTAMP_DIFF(p.processed_at, p.created_at, SECOND) NOT BETWEEN 43200 AND 432000))
    OR (p.status IN ('rejected', 'cancelled') AND (p.processed_at IS NULL OR p.processed_at <= p.created_at OR TIMESTAMP_DIFF(p.processed_at, p.created_at, SECOND) > 432000))
    OR (p.status = 'pending' AND p.processed_at IS NOT NULL)
    OR a.kyc_verified_at IS NULL
    OR a.kyc_verified_at >= p.created_at
  );

-- @id T5
-- @desc Disputes: processed_at < filed_at <= received_at < R, receipt 1 to 7 days after filing, lag at most 60 days, resolution 10 to 45 days after receipt, open if and only if unresolved
-- @scope buyer
SELECT d.dispute_id
FROM case01.disputes d JOIN case01.payments p ON d.payment_id = p.payment_id
WHERE NOT (p.processed_at < d.filed_at AND d.filed_at <= d.received_at)
   OR TIMESTAMP_DIFF(d.received_at, d.filed_at, SECOND) NOT BETWEEN 86400 AND 604800
   OR TIMESTAMP_DIFF(d.received_at, p.processed_at, SECOND) > 5184000
   OR (d.status = 'open') != (d.resolved_at IS NULL)
   OR (d.resolved_at IS NOT NULL AND TIMESTAMP_DIFF(d.resolved_at, d.received_at, SECOND) NOT BETWEEN 864000 AND 3888000);

-- @id T6
-- @desc Bets: in-play bets placed before the event ended (or R); settled bets settle 1 to 30 minutes after ended_at
-- @scope buyer
SELECT b.bet_id
FROM case01.bets b JOIN case01.events e ON b.event_id = e.event_id
WHERE (b.placed_at >= e.scheduled_start AND b.placed_at >= COALESCE(e.ended_at, TIMESTAMP '2026-09-14 13:00:00 UTC'))
   OR (b.settled_at IS NOT NULL AND (e.ended_at IS NULL OR TIMESTAMP_DIFF(b.settled_at, e.ended_at, SECOND) NOT BETWEEN 60 AND 1800));

-- @id T7
-- @desc Refunds are created after their parent's processed_at
-- @scope buyer
SELECT r.payment_id
FROM case01.payments r JOIN case01.payments p ON r.parent_payment_id = p.payment_id
WHERE r.payment_type = 'refund' AND (p.processed_at IS NULL OR r.created_at <= p.processed_at);

-- @id T8
-- @desc entry_seq order agrees with entry_time order
-- @scope buyer
SELECT entry_id FROM (
  SELECT entry_id, entry_time, LAG(entry_time) OVER (ORDER BY entry_seq) AS prev_time
  FROM case01.wallet_ledger
) WHERE prev_time > entry_time;

-- @id F1
-- @desc The running available balance never drops below zero
-- @scope buyer
SELECT entry_id, account_id, balance FROM (
  SELECT entry_id, account_id,
         SUM(amount) OVER (PARTITION BY account_id ORDER BY entry_seq ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS balance
  FROM case01.wallet_ledger
) WHERE balance < 0;

-- @id F2
-- @desc Each captured deposit has at most one deposit_credit of equal amount; credits only reference captured deposits
-- @scope buyer
SELECT l.payment_id AS id, 'more than one credit' AS problem
FROM case01.wallet_ledger l
WHERE l.entry_type = 'deposit_credit'
GROUP BY l.payment_id HAVING COUNT(*) > 1
UNION ALL
SELECT l.entry_id, 'credit on a non-captured payment or wrong amount'
FROM case01.wallet_ledger l JOIN case01.payments p ON l.payment_id = p.payment_id
WHERE l.entry_type = 'deposit_credit'
  AND (p.payment_type != 'deposit' OR p.status != 'captured' OR l.amount != p.amount);

-- @id F3
-- @desc Every captured deposit is credited to the wallet
-- @scope buyer
SELECT p.payment_id, 'uncredited capture' AS problem FROM case01.payments p
WHERE p.payment_type = 'deposit' AND p.status = 'captured'
  AND NOT EXISTS (SELECT 1 FROM case01.wallet_ledger l WHERE l.payment_id = p.payment_id AND l.entry_type = 'deposit_credit');

-- @id F4
-- @desc Refunds return a captured, uncredited deposit: equal amount, same reference and card, one per parent, completed, never in the ledger
-- @scope buyer
SELECT r.payment_id AS id, 'bad refund' AS problem
FROM case01.payments r LEFT JOIN case01.payments p ON r.parent_payment_id = p.payment_id
WHERE r.payment_type = 'refund'
  AND (p.payment_id IS NULL OR p.payment_type != 'deposit' OR p.status != 'captured'
       OR r.amount != p.amount OR r.merchant_reference != p.merchant_reference
       OR r.instrument_id != p.instrument_id OR r.status != 'completed' OR r.processed_at IS NULL
       OR EXISTS (SELECT 1 FROM case01.wallet_ledger l WHERE l.payment_id = p.payment_id AND l.entry_type = 'deposit_credit'))
UNION ALL
SELECT parent_payment_id, 'refunded more than once' FROM case01.payments
WHERE payment_type = 'refund' GROUP BY parent_payment_id HAVING COUNT(*) > 1
UNION ALL
SELECT payment_id, 'parent_payment_id outside refunds' FROM case01.payments
WHERE (payment_type = 'refund') != (parent_payment_id IS NOT NULL)
UNION ALL
SELECT l.entry_id, 'ledger entry on a refund' FROM case01.wallet_ledger l JOIN case01.payments p ON l.payment_id = p.payment_id
WHERE p.payment_type = 'refund';

-- @id F5
-- @desc Each bet has one stake entry; settlement entries and payout match the status
-- @scope buyer
WITH s AS (
  SELECT b.bet_id, b.status, b.stake, b.odds, b.payout, b.settled_at,
         SUM(CASE WHEN l.entry_type = 'stake' THEN 1 ELSE 0 END) AS n_stake,
         SUM(CASE WHEN l.entry_type = 'stake' AND l.amount = -b.stake AND l.entry_time = b.placed_at THEN 1 ELSE 0 END) AS n_stake_ok,
         SUM(CASE WHEN l.entry_type = 'bet_payout' THEN 1 ELSE 0 END) AS n_pay,
         SUM(CASE WHEN l.entry_type = 'bet_payout' AND l.amount = b.payout AND l.entry_time = b.settled_at THEN 1 ELSE 0 END) AS n_pay_ok,
         SUM(CASE WHEN l.entry_type = 'bet_void' THEN 1 ELSE 0 END) AS n_void,
         SUM(CASE WHEN l.entry_type = 'bet_void' AND l.amount = b.stake AND l.entry_time = b.settled_at THEN 1 ELSE 0 END) AS n_void_ok
  FROM case01.bets b LEFT JOIN case01.wallet_ledger l ON l.bet_id = b.bet_id
  GROUP BY b.bet_id, b.status, b.stake, b.odds, b.payout, b.settled_at
)
SELECT bet_id, status FROM s
WHERE n_stake != 1 OR n_stake_ok != 1
   OR (status = 'won'  AND (n_pay != 1 OR n_pay_ok != 1 OR n_void != 0 OR payout != ROUND(stake * odds, 2) OR settled_at IS NULL))
   OR (status = 'void' AND (n_void != 1 OR n_void_ok != 1 OR n_pay != 0 OR payout != stake OR settled_at IS NULL))
   OR (status = 'lost' AND (n_pay != 0 OR n_void != 0 OR payout != 0 OR settled_at IS NULL))
   OR (status = 'open' AND (n_pay != 0 OR n_void != 0 OR payout IS NOT NULL OR settled_at IS NOT NULL));

-- @id F6
-- @desc Settled bets match the event's final score; settled bets on abandoned events are void
-- @scope buyer
WITH o AS (
  SELECT b.bet_id, b.status, b.selection, e.status AS event_status,
         CASE b.market
           WHEN 'match_result' THEN CASE WHEN e.home_score > e.away_score THEN 'home'
                                         WHEN e.home_score = e.away_score THEN 'draw'
                                         ELSE 'away' END
           WHEN 'total_goals_2_5' THEN IF(e.home_score + e.away_score >= 3, 'over', 'under')
           WHEN 'both_teams_score' THEN IF(e.home_score > 0 AND e.away_score > 0, 'yes', 'no')
         END AS winning_selection
  FROM case01.bets b JOIN case01.events e ON b.event_id = e.event_id
  WHERE b.status != 'open'
)
SELECT bet_id, status, event_status FROM o
WHERE event_status NOT IN ('completed', 'abandoned')
   OR (event_status = 'abandoned' AND status != 'void')
   OR (event_status = 'completed' AND status = 'void')
   OR (event_status = 'completed' AND status = 'won'  AND selection != winning_selection)
   OR (event_status = 'completed' AND status = 'lost' AND selection =  winning_selection);

-- @id F7
-- @desc Each withdrawal has one hold at the request; a release if and only if rejected or cancelled
-- @scope buyer
WITH w AS (
  SELECT p.payment_id, p.status,
         SUM(CASE WHEN l.entry_type = 'withdrawal_hold' THEN 1 ELSE 0 END) AS n_hold,
         SUM(CASE WHEN l.entry_type = 'withdrawal_hold' AND l.amount = -p.amount AND l.entry_time = p.created_at THEN 1 ELSE 0 END) AS n_hold_ok,
         SUM(CASE WHEN l.entry_type = 'withdrawal_release' THEN 1 ELSE 0 END) AS n_rel,
         SUM(CASE WHEN l.entry_type = 'withdrawal_release' AND l.amount = p.amount AND l.entry_time = p.processed_at THEN 1 ELSE 0 END) AS n_rel_ok,
         SUM(CASE WHEN l.entry_type NOT IN ('withdrawal_hold', 'withdrawal_release') THEN 1 ELSE 0 END) AS n_other
  FROM case01.payments p LEFT JOIN case01.wallet_ledger l ON l.payment_id = p.payment_id
  WHERE p.payment_type = 'withdrawal'
  GROUP BY p.payment_id, p.status
)
SELECT payment_id, status FROM w
WHERE n_hold != 1 OR n_hold_ok != 1 OR n_other > 0
   OR (status IN ('rejected', 'cancelled') AND (n_rel != 1 OR n_rel_ok != 1))
   OR (status IN ('paid', 'pending') AND n_rel != 0);

-- @id F8
-- @desc Merchant-reference reconciliation is zero, and deposit references are unique
-- @scope buyer
WITH caps AS (
  SELECT merchant_reference, payment_id, amount FROM case01.payments
  WHERE payment_type = 'deposit' AND status = 'captured'
),
captured AS (SELECT merchant_reference, SUM(amount) AS captured FROM caps GROUP BY merchant_reference),
credited AS (
  SELECT c.merchant_reference, SUM(l.amount) AS credited
  FROM caps c JOIN case01.wallet_ledger l ON l.payment_id = c.payment_id AND l.entry_type = 'deposit_credit'
  GROUP BY c.merchant_reference
),
refunded AS (
  SELECT c.merchant_reference, SUM(r.amount) AS refunded
  FROM caps c JOIN case01.payments r ON r.parent_payment_id = c.payment_id AND r.payment_type = 'refund' AND r.status = 'completed'
  GROUP BY c.merchant_reference
)
SELECT k.merchant_reference, 'unreconciled' AS problem
FROM captured k
LEFT JOIN credited cr ON k.merchant_reference = cr.merchant_reference
LEFT JOIN refunded rf ON k.merchant_reference = rf.merchant_reference
WHERE k.captured - COALESCE(cr.credited, 0) - COALESCE(rf.refunded, 0) != 0
UNION ALL
SELECT merchant_reference, 'reference shared by several deposit rows'
FROM case01.payments WHERE payment_type = 'deposit'
GROUP BY merchant_reference HAVING COUNT(*) > 1;

-- @id F9
-- @desc Amounts are positive with two decimals; stakes at least 1.00; odds at least 1.01; ledger amounts non-zero
-- @scope buyer
SELECT 'payments' AS tbl, payment_id AS id FROM case01.payments WHERE amount <= 0 OR amount != ROUND(amount, 2)
UNION ALL SELECT 'disputes', dispute_id FROM case01.disputes WHERE amount <= 0 OR amount != ROUND(amount, 2)
UNION ALL SELECT 'bets.stake', bet_id FROM case01.bets WHERE stake < 1 OR stake != ROUND(stake, 2)
UNION ALL SELECT 'bets.odds', bet_id FROM case01.bets WHERE odds < 1.01 OR odds != ROUND(odds, 2)
UNION ALL SELECT 'bets.payout', bet_id FROM case01.bets WHERE payout != ROUND(payout, 2) OR payout < 0
UNION ALL SELECT 'wallet_ledger', entry_id FROM case01.wallet_ledger WHERE amount = 0 OR amount != ROUND(amount, 2)
UNION ALL SELECT 'wallet_ledger.sign', entry_id FROM case01.wallet_ledger
  WHERE (entry_type IN ('deposit_credit', 'bet_payout', 'bet_void', 'withdrawal_release') AND amount < 0)
     OR (entry_type IN ('stake', 'withdrawal_hold') AND amount > 0);

-- @id S1
-- @desc Open bets, pending withdrawals and open disputes carry no post-R fields
-- @scope buyer
SELECT 'bets' AS tbl, bet_id AS id FROM case01.bets WHERE status = 'open' AND (settled_at IS NOT NULL OR payout IS NOT NULL)
UNION ALL SELECT 'payments', payment_id FROM case01.payments WHERE payment_type = 'withdrawal' AND status = 'pending' AND processed_at IS NOT NULL
UNION ALL SELECT 'disputes', dispute_id FROM case01.disputes WHERE status = 'open' AND resolved_at IS NOT NULL;

-- @id S2
-- @desc Every event is in exactly one of the four states at R, with realistic durations
-- @scope buyer
SELECT event_id, status FROM case01.events
WHERE NOT (
     (status = 'completed' AND scheduled_start < TIMESTAMP '2026-09-14 13:00:00 UTC'
        AND ended_at < TIMESTAMP '2026-09-14 13:00:00 UTC'
        AND home_score IS NOT NULL AND away_score IS NOT NULL
        AND TIMESTAMP_DIFF(ended_at, scheduled_start, MINUTE) BETWEEN 105 AND 130)
  OR (status = 'abandoned' AND scheduled_start < TIMESTAMP '2026-09-14 13:00:00 UTC'
        AND ended_at < TIMESTAMP '2026-09-14 13:00:00 UTC'
        AND home_score IS NULL AND away_score IS NULL
        AND TIMESTAMP_DIFF(ended_at, scheduled_start, MINUTE) BETWEEN 1 AND 130)
  OR (status = 'in_play' AND scheduled_start < TIMESTAMP '2026-09-14 13:00:00 UTC'
        AND scheduled_start >= TIMESTAMP_SUB(TIMESTAMP '2026-09-14 13:00:00 UTC', INTERVAL 130 MINUTE)
        AND ended_at IS NULL AND home_score IS NULL AND away_score IS NULL)
  OR (status = 'scheduled' AND scheduled_start >= TIMESTAMP '2026-09-14 13:00:00 UTC'
        AND scheduled_start < TIMESTAMP '2026-09-28 13:00:00 UTC'
        AND ended_at IS NULL AND home_score IS NULL AND away_score IS NULL)
);

-- @id S3
-- @desc Bet status agrees with event state at R
-- @scope buyer
SELECT b.bet_id, b.status, e.status AS event_status
FROM case01.bets b JOIN case01.events e ON b.event_id = e.event_id
WHERE (e.status IN ('scheduled', 'in_play') AND b.status != 'open')
   OR (e.status IN ('completed', 'abandoned') AND b.status = 'open'
       AND e.ended_at < TIMESTAMP_SUB(TIMESTAMP '2026-09-14 13:00:00 UTC', INTERVAL 30 MINUTE))
   OR (e.status = 'scheduled' AND b.placed_at >= e.scheduled_start);

-- @id V1
-- @desc Categorical columns hold only allowed values; required columns are never null
-- @scope buyer
SELECT 'accounts' AS tbl, account_id AS id FROM case01.accounts
WHERE status NOT IN ('active', 'closed', 'self_excluded') OR status IS NULL
   OR NOT REGEXP_CONTAINS(kyc_country, r'^[A-Z]{2}$') OR created_at IS NULL
UNION ALL
SELECT 'account_access', access_id FROM case01.account_access
WHERE event_type NOT IN ('login', 'password_reset', 'email_change', 'instrument_added') OR event_type IS NULL
   OR success IS NULL OR (NOT success AND event_type != 'login')
   OR device_id IS NULL OR ip_token IS NULL OR event_time IS NULL
   OR NOT REGEXP_CONTAINS(ip_country, r'^[A-Z]{2}$')
UNION ALL
SELECT 'payments', payment_id FROM case01.payments
WHERE currency != 'USD' OR currency IS NULL OR amount IS NULL OR created_at IS NULL OR merchant_reference IS NULL OR instrument_id IS NULL
   OR NOT ((payment_type = 'deposit' AND status IN ('captured', 'declined') AND STARTS_WITH(instrument_id, 'CARD-'))
        OR (payment_type = 'withdrawal' AND status IN ('pending', 'paid', 'rejected', 'cancelled'))
        OR (payment_type = 'refund' AND status = 'completed' AND STARTS_WITH(instrument_id, 'CARD-')))
UNION ALL
SELECT 'wallet_ledger', entry_id FROM case01.wallet_ledger
WHERE entry_type NOT IN ('deposit_credit', 'stake', 'bet_payout', 'bet_void', 'withdrawal_hold', 'withdrawal_release')
   OR entry_type IS NULL OR amount IS NULL OR entry_time IS NULL OR entry_seq IS NULL
UNION ALL
SELECT 'bets', bet_id FROM case01.bets
WHERE status NOT IN ('open', 'won', 'lost', 'void') OR status IS NULL OR stake IS NULL OR odds IS NULL OR placed_at IS NULL
   OR NOT ((market = 'match_result' AND selection IN ('home', 'draw', 'away'))
        OR (market = 'total_goals_2_5' AND selection IN ('over', 'under'))
        OR (market = 'both_teams_score' AND selection IN ('yes', 'no')))
UNION ALL
SELECT 'events', event_id FROM case01.events
WHERE sport != 'football' OR sport IS NULL OR status NOT IN ('scheduled', 'in_play', 'completed', 'abandoned')
   OR competition IS NULL OR home_team IS NULL OR away_team IS NULL OR home_team = away_team OR scheduled_start IS NULL
UNION ALL
SELECT 'disputes', dispute_id FROM case01.disputes
WHERE reason_code NOT IN ('unauthorized', 'duplicate_processing', 'other') OR reason_code IS NULL
   OR status NOT IN ('open', 'accepted', 'won', 'lost') OR status IS NULL
   OR filed_at IS NULL OR received_at IS NULL;

-- @id V2
-- @desc Every ID matches its format (prefix plus 8 Crockford base32 characters)
-- @scope buyer
SELECT 'account_id' AS col, account_id AS id FROM case01.accounts WHERE NOT REGEXP_CONTAINS(account_id, r'^ACC-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'access_id', access_id FROM case01.account_access WHERE NOT REGEXP_CONTAINS(access_id, r'^ACS-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'session_id', session_id FROM case01.account_access WHERE session_id IS NOT NULL AND NOT REGEXP_CONTAINS(session_id, r'^SES-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'device_id', device_id FROM case01.account_access WHERE NOT REGEXP_CONTAINS(device_id, r'^DEV-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'ip_token', ip_token FROM case01.account_access WHERE NOT REGEXP_CONTAINS(ip_token, r'^IPT-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'access.instrument_id', instrument_id FROM case01.account_access WHERE instrument_id IS NOT NULL AND NOT REGEXP_CONTAINS(instrument_id, r'^(CARD|EWAL|BANK)-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'payment_id', payment_id FROM case01.payments WHERE NOT REGEXP_CONTAINS(payment_id, r'^PAY-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'merchant_reference', merchant_reference FROM case01.payments WHERE NOT REGEXP_CONTAINS(merchant_reference, r'^ORD-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'payments.instrument_id', instrument_id FROM case01.payments WHERE NOT REGEXP_CONTAINS(instrument_id, r'^(CARD|EWAL|BANK)-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'entry_id', entry_id FROM case01.wallet_ledger WHERE NOT REGEXP_CONTAINS(entry_id, r'^LED-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'bet_id', bet_id FROM case01.bets WHERE NOT REGEXP_CONTAINS(bet_id, r'^BET-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'event_id', event_id FROM case01.events WHERE NOT REGEXP_CONTAINS(event_id, r'^EVT-[0-9A-HJKMNP-TV-Z]{8}$')
UNION ALL SELECT 'dispute_id', dispute_id FROM case01.disputes WHERE NOT REGEXP_CONTAINS(dispute_id, r'^DSP-[0-9A-HJKMNP-TV-Z]{8}$');
