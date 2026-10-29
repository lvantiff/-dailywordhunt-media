# Bounty radar

Daily scan of public GitHub issues that offer cash bounties (GitHub Actions, 10:23 UTC). Discovery only: it never comments, claims, forks or submits.

Results in `data/` come only from public GitHub issues and repo docs: `DIGEST.md` (ranked list), `candidates.json`, `ledger.csv`, `run-log.jsonl`, plus `seen.csv` (salted hashes used to flag what is new). Sources are in `sources.json`. Tests: `python -I -m unittest discover -s bounty-radar/tests`.
