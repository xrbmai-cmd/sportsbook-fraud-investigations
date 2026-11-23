# Sportsbook Fraud Investigations: data engine and sample

This repository holds the engine that builds the synthetic sportsbook data behind the investigations in
Sportsbook Fraud Investigations, the integrity checks every dataset must pass, a small public sample and one
walkthrough. The cases are sold as **Sportsbook Fraud Investigations** on Whop: https://whop.com/cesar-miranda/sportsbook-fraud-investigations/. Their data, dossiers and answers are not in this repository.

By César Miranda.

## What is here

| Path | What it is |
| --- | --- |
| `engine/` | The generator, the published seven-table schema, a statistical report and the look-ahead test for prices |
| `assertions/` | Integrity assertions in BigQuery SQL, a local DuckDB runner, and a mutation test that proves each assertion can fail |
| `sample/` | A small dataset from the public seed `sample-2026`, with no investigation cases in it |
| `WALKTHROUGH.md`, `walkthrough.sql` | Measuring a base rate on the sample |

## How the data is made

- **A fictional operator.** Football only, fictional competitions and teams, three markets, US dollars.
- **A session engine per account.** Each account has its own random stream and its own habits: when it logs in, how
  much it deposits, how it bets, when it withdraws. Devices, countries, credential changes and payout instruments
  appear the way they would in an operator's access log.
- **Matches with a timeline.** Every match has a goal timeline. In-play prices come from the score and the minute at
  the moment of the bet, never from the final result; `engine/test_lookahead.py` rewrites the future of thousands of
  matches and confirms that no price changes.
- **Exact money.** Amounts are integer cents inside the engine and exact decimals in the files. The wallet is a ledger:
  there is no balance column, so balances are derived the way an analyst would derive them.
- **A cutoff.** The data is the operator's record as it stood at a cutoff, R: a withdrawal paid after R shows as
  pending, a bet settled after R shows as open, a dispute received after R is absent.
- **Random identifiers.** Identifiers are assigned after the simulation from their own random stream, so neither an
  identifier nor a row's position says anything about the account behind it.

Each investigation adds its cases to a background population through the same session engine. The case material,
the seeds used for the paid datasets and the answers are private.

## How it is verified

| Check | What it proves | Result | Date |
| --- | --- | --- | --- |
| Integrity assertions | Keys resolve, money reconciles between processor and wallet, every ledger entry is explained, states are consistent at the cutoff | Pass on the paid Case 01 data and on this sample | Nov 18 and Nov 20, 2026 |
| Mutation test | Every assertion catches a defect planted for it | 32 of 32 on Case 01; 29 of 29 here | Nov 18 and Nov 20, 2026 |
| Statistical acceptance criteria | The background behaves like a plausible operator | Pass on four seeds; pass on the Case 01 data | Nov 11 and Nov 18, 2026 |
| Look-ahead test | No price uses information from after the bet | Pass | Nov 20, 2026 |
| L1 Vocabulary | Case rows use the same closed lists of values as the background | Pass | Nov 18, 2026 |
| L2 Format | Identifiers, tokens, amounts and times follow the same patterns in case rows and background rows | Pass | Nov 18, 2026 |
| L3 Order | Files are sorted by random keys, so row position carries nothing | Pass | Nov 18, 2026 |
| L4 Tail | On features that are not evidence, each case account sits inside the background's 5th to 95th percentile range, or the deviation is part of its evidence | Pass | Nov 18, 2026 |
| L5 Ablation | Each case account, rebuilt without its scenario, no longer shows its evidence | Pass | Nov 18, 2026 |
| L6 Seed robustness | Three other background seeds, with the cases added, leave every conclusion unchanged | Pass | Nov 18, 2026 |
| L7 Identifier re-randomization | With new identifiers, every solution output is identical apart from the identifiers | Pass | Nov 18, 2026 |
| Native BigQuery run | The solution SQL runs in the BigQuery sandbox and returns the verified outputs, cell for cell | Pass, 14 of 14 | Nov 19, 2026 |
| Independent blind solves | Two solvers from different model families, given only the buyer package, reach the expected conclusions | Pass, 5 of 5 criteria each | Nov 19, 2026 |
| Release freeze | The Case 01 release is frozen with checksums | case01-data-v1.0.0 | Nov 20, 2026 |

## Run it

```
pip install -r requirements.txt
python3 engine/generate.py --seed sample-2026 --accounts 120 --out out/sample
python3 assertions/run_assertions.py out/sample/buyer out/sample/designer
python3 assertions/mutation_test.py out/sample/buyer out/sample/designer
python3 engine/test_lookahead.py sample-2026
```

The first command regenerates `sample/` byte for byte (its files are in `out/sample/buyer`). The statistical
report, `engine/report.py`, is calibrated for 500 accounts: generate with `--accounts 500` to run it.

## Seeds

The public sample uses the seed `sample-2026`. The seeds of the paid datasets are private, high-entropy values that
never appear in code or in this repository's history; with them, the paid data could be regenerated and compared with
the background to find the cases.

## License

The source code in this repository (`engine/`, `assertions/` and `walkthrough.sql`) is released under the MIT
license: see `LICENSE`. The MIT license covers that code only. It does not cover the sample data or the documentation
in this repository, and it does not cover any paid material of Sportsbook Fraud Investigations (case datasets,
dossiers, handbooks, solutions guides, model briefings, rubrics and solution SQL), none of which is in this repository.
