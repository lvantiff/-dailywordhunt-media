# Bounty radar

Daily scan of public GitHub issues that offer cash bounties (GitHub Actions, 10:23 UTC). Discovery only: it never comments, claims, forks or submits.

The ranked results are encrypted (`data/*.enc`, readable only with a private key kept elsewhere). Public files here are code, `sources.json`, a counts-only `data/status.json`, and `data/seen.csv` (salted hashes, so the job can tell what is new). Tests: `python -I -m unittest discover -s bounty-radar/tests`.
