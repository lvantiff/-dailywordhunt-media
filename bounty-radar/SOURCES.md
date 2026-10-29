# Bounty sources, ranked

Prepared 2026-10-29 for Lucian's ask to make bounty hunting a main Sovereign revenue source. Ranked by expected cash per unit of work under Sovereign's rules: $0 spend, cash payout, AI work not banned, no contests, no CAPTCHA/KYC step that isn't already done, and no outbound submission without Lucian's approval.

## Why HHS paid (the pattern to copy)

The $200 came from [HHS/simpler-grants-gov #12569](https://github.com/HHS/simpler-grants-gov/issues/12569), fixed by our PR #12683. What made it work:

1. **The sponsor runs the program itself**, with written [terms](https://github.com/HHS/simpler-grants-gov/blob/main/documentation/bounties/paid-contributor-TOS.md), a fixed amount on the issue and a real payer (Tremendous, to the GitHub email).
2. **Low competition.** It is US-citizens-only and not listed on bounty aggregators, so few hunters see it or qualify.
3. **Small, well-scoped work** (labelled "2-6 hours"), with tests and CI we could run.
4. **Clear trigger:** `/claim` plus a terms acknowledgment, first valid merged PR is paid, $50 runner-up.

Open marketplaces are nearly empty by comparison. An independent hourly scanner that checks Algora, Opire, IssueHunt, BountyHub and TaskBounty reported only **2 verified open bounties worth $101 in total** on 2026-10-29 ([BountyOS board](https://bountyos.rovidev.com/en/github-bounty-board/)). Our own Worker C has searched GitHub bounty labels hourly since Oct 7 and qualified almost nothing outside HHS (see DISCOVERY.md). So the radar spends most of its effort finding and watching **sponsor-run programs**, and treats generic bounty labels as a wide, noisy net.

## Ranked sources

| # | Source | Pays | Fit and evidence | How the radar watches it |
|---|---|---|---|---|
| 1 | **HHS CommonGrants paid contributor program** (HHS/simpler-grants-protocol) | $50-$500 per issue, Tremendous, ~5 business days after merge | **New today.** Five funded issues announced 2026-10-29 (#1330): contribution issues #1228, #355, #356 and $500 implementation issues #1369, #1370. US persons only. First complete `/claim` is assigned; one active claim per person; 14-day deadline. [Terms](https://github.com/HHS/simpler-grants-protocol/blob/main/PAID_CONTRIBUTOR_TERMS.md). One AI-looking account already commented on #1370. | Labels `funded: contribution`, `funded: implementation` (label pages readable by WebFetch) |
| 2 | **HHS Simpler Grants paid contributor program** (HHS/simpler-grants-gov) | $200 seen (bounty:M), Tremendous | Proven: paid us $200. About one new bounty a month (Oct 7 audit); **0 open** on 2026-10-29. Up to 3 claims; first valid PR paid, $50 runner-up. | Label `status: open bounty` |
| 3 | **Copycat sponsor programs** | Varies | Both HHS programs share one design (CommonGrants is administered through Agile Six, agile6.com); other agencies or nonprofits may copy the labels or the "paid contributor program" wording. | Searches for those labels and phrases outside HHS |
| 4 | **AsyncAPI Bounty Program** | $200 medium / $400 advanced, Open Collective expense | ~4-8 issues a month, budget $19,200/yr. Outsiders are third priority and can be assigned only 3 days after the label, at maintainer discretion. Payout needs a verified Open Collective account in Lucian's legal name (one-time owner step). [Program](https://www.asyncapi.com/docs/community/010-contribution-guidelines/BOUNTY_PROGRAM) | `org:asyncapi label:bounty`; [project board](https://github.com/orgs/asyncapi/projects/36) |
| 5 | **Testcontainers for Go sponsor bounties** | Set per issue, Open Collective (maintainers may keep 20%) | Sporadic; 1-3 sponsor bounties a month at most. [Policy](https://golang.testcontainers.org/bounty/) | `label:bounty` in that repo |
| 6 | **FreeCAD FPA bugfix rewards** | FPA grant after merge | Sporadic, mostly C++. Worker E reviewed it Oct 20. | `label:Bounty` in FreeCAD |
| 7 | **Generic GitHub bounty labels and "$" titles** | Varies | High volume, mostly bait repos, saturated issues (5-8 PRs each) or no real funding. Useful only after the rubric's gates. | Daily searches, scored; only 60+ get a look |
| 8 | **Opire-backed issues** | Creator pays manually via Stripe | `/try` does not lock; payout needs owner Stripe setup. BountyOS saw 1 bounty ($10). | Comment search for Opire rewards |
| 9 | **Security bug bounties** (HackerOne, Bugcrowd, Intigriti, HackenProof, huntr) | Often large | Every report is an outbound submission that needs Lucian's approval; many programs reject AI-written reports; Immunefi needs KYC; Google OSS VRP paused product reports on 2026-10-01 over AI slop; active testing risks going out of scope. | Not scanned. Revisit only with a read-only, in-scope plan Lucian approves. |

## Excluded, with reasons

| Source | Reason |
|---|---|
| Algora (`💎 Bounty` label) | Terms ban AI agents (bounty/BOUNTY-FIRST-TIME-RIGHT-CHECKLIST-2026-10-03.md). The scanner rejects any issue that links algora.io. |
| BountyHub | Requires human authorship. |
| TaskBounty / taskmarket | "Best submission wins" contests. |
| Expensify ($250 issues) | Paid through Upwork contracts; Upwork is ChatGPT's lane. |
| Parse Platform | Program suspended over low-quality AI PRs. |
| Tenstorrent | Explicit AI-agent ban. |
| RustChain, testnet/points programs | No cash off-ramp. |
| SecureBananaLabs, UnsafeLabs, OphirPay, claude-builders-bounty and similar | Bait or no verified payout (team memory 2026-10-04, discovery-state.json). |
| Gitcoin, hackathons, Superteam | Contests. |
| IssueHunt, Gitpay, Bountysource | Stale, empty or defunct inventory (Worker E rotations, Oct 15-20). |

## Owner-only items this lane needs

- **Claim confirmation:** HHS programs require a `/claim` that confirms Lucian is a US person aged 18+ and eligible. That is a legal attestation in his name, so it needs his OK (asked 2026-10-29 as a standing approval).
- **Program emails:** CommonGrants asks the assignee to email commongrants-contributors@agile6.com after assignment. Outbound email needs his OK (included in the same question).
- **Open Collective / Stripe payout accounts** for AsyncAPI, Testcontainers or Opire: one-time identity setup, only worth doing once a real issue is won.
