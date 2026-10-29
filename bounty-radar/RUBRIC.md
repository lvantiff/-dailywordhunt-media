# Bounty scoring rubric

Implemented in `score()` in `bounty_radar.py`. The scanner applies it automatically; the daily review checks the top items by hand before anything is worked.

## Hard gates (any one = rejected, score 0)

| Gate | Why |
|---|---|
| Issue closed | Nothing to win. |
| Repo or owner on the exclusion list | Bait repos, non-cash rewards, or explicit AI bans already verified (see SOURCES.md). |
| Repo archived | Nobody will merge. |
| Assigned to someone else | Taking over an exclusive assignment is not allowed. |
| CONTRIBUTING / AI policy bans AI-generated work or agents | We would be breaking the rules. |
| Reward is points, XP, testnet tokens, RTC or "unpaid" | Not cash. |
| A merged PR already references the issue | Already solved. |
| Payout runs through Algora or BountyHub | Their terms ban AI agents or need human authorship. |

Also rejected by the daily review, not by the scanner: any entry fee, deposit or paid tool (spend is $0), any step needing a CAPTCHA, KYC or owner sign-in that isn't already done, and contests or "best submission wins" prizes.

## Points (0 to 100)

| Factor | Points |
|---|---|
| **Sponsor credibility** | Sponsor-run program with written terms (like HHS) 25; platform escrow 15; repo label only 8; unknown 0 |
| **Stated cash** | $500+ 20; $200+ 17; $100+ 13; $50+ 8; under $50 4; none stated 0 |
| **Competition** (open PRs count double, plus closed PRs and claim comments) | 0 → 25; 1 → 18; 2-3 → 12; 4-6 → 5; 7+ → 0 |
| **Freshness** (issue age) | ≤3 days 10; ≤14 days 7; ≤60 days 4; older 1 |
| **Eligibility moat** | US-citizen-only programs 10 (fewer competitors, and Lucian qualifies); open to all 6; outsiders only at maintainer discretion 3 |
| **Fit** | Python/TS/JS/Go/docs repo 5; 50+ stars 3; pushed in last 30 days 2 |
| **Low-trust penalty** | Repo under 60 days old with under 10 stars: −15 |

## Verdicts

- **60+ deep review**: the daily review checks it against the submission gate the same day.
- **40-59 watch**: kept in the ledger and re-scored daily.
- **Under 40 logged**: recorded only.
- No stated amount and no sponsor program terms: capped at logged, because there is nothing to act on.

## What the score is not

A score is a triage order, not a probability of payment. A listing is not a claim, a submission or money. Money is recorded only as pending, payable or collected with a receipt.
