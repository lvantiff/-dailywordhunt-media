import csv
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bounty_radar as br  # noqa: E402

br.time.sleep = lambda s: None

NOW = dt.datetime(2026, 10, 29, 21, 0, tzinfo=dt.timezone.utc)


def issue(number=1, repo="HHS/simpler-grants-gov", title="Pagination on saved searches", labels=("bounty:M", "status: open bounty"),
          body="Bounty: $200", assignees=(), created="2026-10-27T00:00:00Z"):
    return {
        "number": number, "title": title, "state": "open", "body": body,
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "labels": [{"name": l} for l in labels], "assignees": [{"login": a} for a in assignees],
        "created_at": created, "updated_at": created, "comments": 0,
    }


class FakeGitHub:
    def __init__(self, search, repos=None, timelines=None, files=None):
        self.search, self.repos, self.timelines, self.files = search, repos or {}, timelines or {}, files or {}
        self.calls, self.errors = 0, []

    def search_issues(self, query, max_pages=3):
        items = [i for q, its in self.search.items() if q in query for i in its]
        return items, len(items), True

    def get(self, path, params=None, accept=None):
        self.calls += 1
        if "/timeline" in path:
            return self.timelines.get(path, [])
        if "/contents/" in path:
            return self.files.get(path)
        return self.repos.get(path, {})


class AmountTests(unittest.TestCase):
    def test_label_amount_wins(self):
        self.assertEqual(br.extract_amount("bounty $250", "fix", "pays $1,000 later"), 250)

    def test_body_formats(self):
        self.assertEqual(br.extract_amount("", "", "Reward: 1.5k USD? no; $1.5k yes"), 1500)
        self.assertEqual(br.extract_amount("", "", "300 USDC on merge"), 300)
        self.assertIsNone(br.extract_amount("bounty", "Add docs", "no amount here"))

    def test_ignores_tiny_and_huge(self):
        self.assertIsNone(br.extract_amount("", "$1 fix", "$900000 raise"))


class AIPolicyTests(unittest.TestCase):
    def check(self, text):
        return any(rx.search(text) for rx in br.AI_BAN_RE)

    def test_detects_bans(self):
        self.assertTrue(self.check("AI-generated pull requests will be closed without review."))
        self.assertTrue(self.check("Please do not use ChatGPT or Copilot to write code."))
        self.assertTrue(self.check("Autonomous agents are not allowed to claim bounties."))

    def test_allows_neutral_text(self):
        self.assertFalse(self.check("We use AI to triage issues. Contributions welcome."))


class ScoreTests(unittest.TestCase):
    def base(self, **kw):
        c = {"state": "open", "tier": "sponsor_program", "amount_usd": 200, "open_prs": 0, "closed_prs": 0,
             "claim_comments": 0, "created_at": "2026-10-27T00:00:00Z", "eligibility": "us_citizen",
             "repo_language": "Python", "repo_stars": 300, "repo_pushed_at": "2026-10-28T00:00:00Z",
             "repo_created_at": "2023-01-01T00:00:00Z", "assignees": []}
        c.update(kw)
        return c

    def test_hhs_shape_is_deep_review(self):
        s, v, _ = br.score(self.base(), NOW)
        self.assertGreaterEqual(s, 80)
        self.assertEqual(v, "deep_review")

    def test_hard_gates(self):
        for kw, gate in [({"assignees": ["someone"]}, "assigned_to_other"), ({"ai_policy": {"banned": True}}, "ai_banned"),
                         ({"merged_prs": 1}, "already_solved"), ({"excluded": True}, "excluded_repo"),
                         ({"noncash": True}, "noncash_reward"), ({"banned_platform": True}, "platform_bans_ai_agents"), ({"repo_archived": True}, "archived_repo")]:
            s, v, reasons = br.score(self.base(**kw), NOW)
            self.assertEqual((s, v), (0, "rejected"))
            self.assertIn(gate, reasons)

    def test_mirrors_and_grants_rejected(self):
        for kw in ({"title": "\U0001F3AF Bounty Alert: 13 New Opportunities found"}, {"title": "Grant Application - X"},
                   {"repo": "someone/bounty-plaza", "title": "Fix parser"}, {"repo": "a/earn-ops", "title": "x"}):
            _, v, reasons = br.score(self.base(tier="label_only", **kw), NOW)
            self.assertEqual(v, "rejected")
            self.assertIn("aggregator_mirror_or_grant", reasons)
        _, v, _ = br.score(self.base(repo="HHS/simpler-grants-gov", title="Pagination"), NOW)
        self.assertEqual(v, "deep_review")

    def test_unenriched_cannot_be_deep_review(self):
        _, v, reasons = br.score(self.base(enriched=False), NOW)
        self.assertEqual(v, "watch")
        self.assertIn("not_enriched", reasons)

    def test_competition_lowers_score(self):
        clean, _, _ = br.score(self.base(), NOW)
        crowded, _, _ = br.score(self.base(open_prs=4, claim_comments=3), NOW)
        self.assertGreater(clean - crowded, 20)

    def test_bait_repo_penalty(self):
        s, v, reasons = br.score(self.base(tier="label_only", repo_created_at="2026-10-01T00:00:00Z", repo_stars=2,
                                           eligibility="open", amount_usd=None), NOW)
        self.assertIn("low_trust_new_repo-15", reasons)
        self.assertEqual(v, "logged")


class ScanAndLedgerTests(unittest.TestCase):
    def cfg(self):
        return {"program_watch": [{"id": "hhs", "query": "repo:HHS/simpler-grants-gov", "tier": "sponsor_program", "eligibility": "us_citizen"}],
                "discovery_queries": [{"id": "generic", "query": "label:bounty updated:>={since7}", "tier": "label_only"}],
                "excluded_repos": ["SecureBananaLabs/bug-bounty"], "excluded_owners": []}

    def test_scan_dedupes_keeps_best_tier_and_rejects_excluded(self):
        hhs = issue()
        bait = issue(number=9, repo="SecureBananaLabs/bug-bounty", title="$780 bounty", labels=("bounty",))
        gh = FakeGitHub(
            search={"repo:HHS": [hhs], "label:bounty": [hhs, bait]},
            repos={"/repos/HHS/simpler-grants-gov": {"language": "Python", "stargazers_count": 200,
                                                      "pushed_at": "2026-10-29T00:00:00Z", "created_at": "2023-05-01T00:00:00Z"}},
            timelines={"/repos/HHS/simpler-grants-gov/issues/1/timeline": [
                {"event": "cross-referenced", "source": {"issue": {"html_url": "pr1", "state": "open", "pull_request": {"url": "x"}}}},
                {"event": "commented", "body": "/claim"}]},
        )
        cands, run = br.scan(gh, self.cfg(), NOW)
        by_key = {c["key"]: c for c in cands}
        self.assertEqual(len(cands), 2)
        h = by_key["HHS/simpler-grants-gov#1"]
        self.assertEqual(h["tier"], "sponsor_program")
        self.assertEqual(sorted(h["sources"]), ["generic", "hhs"])
        self.assertEqual((h["open_prs"], h["claim_comments"]), (1, 1))
        self.assertEqual(by_key["SecureBananaLabs/bug-bounty#9"]["verdict"], "rejected")
        self.assertIn(">=2026-10-22", run["queries"][1]["query"])

    def test_algora_issue_flagged(self):
        c = br.build_candidate(issue(body="/bounty $100 via https://algora.io/acme"), {"id": "g", "tier": "label_only"}, self.cfg())
        self.assertTrue(c["banned_platform"])
        c = br.build_candidate(issue(labels=("\U0001F48E Bounty",), body=""), {"id": "g", "tier": "label_only"}, self.cfg())
        self.assertTrue(c["banned_platform"])
        self.assertFalse(br.build_candidate(issue(), {"id": "g"}, self.cfg())["banned_platform"])

    def test_ledger_preserves_first_seen(self):
        c = {"key": "a/b#1", "url": "u", "title": "t", "program": "p", "tier": "label_only", "amount_usd": 50.0, "score": 41,
             "verdict": "watch", "assignees": [], "reasons": ["x"]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ledger.csv")
            self.assertEqual(br.update_ledger(path, [c], NOW), ["a/b#1"])
            later = NOW + dt.timedelta(days=1)
            self.assertEqual(br.update_ledger(path, [c], later), [])
            with open(path, newline="") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["first_seen"], "2026-10-29T21:00:00Z")
            self.assertEqual(row["last_seen"], "2026-10-30T21:00:00Z")
            self.assertEqual(row["times_seen"], "2")

    def test_seen_state_is_hashed_and_tracks_new(self):
        c = {"key": "a/b#1"}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "seen.csv")
            new, info = br.update_seen(path, [c], NOW)
            self.assertEqual((new, info["a/b#1"][1]), (["a/b#1"], 1))
            new, info = br.update_seen(path, [c, {"key": "x/y#2"}], NOW + dt.timedelta(days=1))
            self.assertEqual(new, ["x/y#2"])
            self.assertEqual(info["a/b#1"], ("2026-10-29T21:00:00Z", 2))
            text = open(path).read()
            self.assertNotIn("a/b", text)
            self.assertNotIn("x/y", text)

    def test_ledger_first_seen_from_seen_state(self):
        c = {"key": "a/b#1", "url": "u", "title": "t", "program": "p", "tier": "label_only", "amount_usd": 50.0, "score": 41,
             "verdict": "watch", "assignees": [], "reasons": ["x"]}
        with tempfile.TemporaryDirectory() as d:
            info = {"a/b#1": ("2026-10-20T00:00:00Z", 5)}
            br.update_ledger(os.path.join(d, "l.csv"), [c], NOW, info)
            row = next(csv.DictReader(open(os.path.join(d, "l.csv"))))
            self.assertEqual((row["first_seen"], row["times_seen"]), ("2026-10-20T00:00:00Z", "5"))

    def test_encrypt_roundtrip_needs_private_key(self):
        import shutil, subprocess
        if not shutil.which("openssl"):
            self.skipTest("openssl missing")
        with tempfile.TemporaryDirectory() as d:
            key, cert, src, enc = (os.path.join(d, n) for n in ("k.pem", "c.pem", "s.txt", "s.enc"))
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                            "-days", "2", "-subj", "/CN=test"], check=True, capture_output=True)
            open(src, "w").write("secret ranking " * 1000)
            br.encrypt_file(src, enc, cert)
            self.assertNotIn(b"secret ranking", open(enc, "rb").read())
            out = subprocess.run(["openssl", "smime", "-decrypt", "-binary", "-in", enc, "-inform", "DER", "-inkey", key],
                                 check=True, capture_output=True).stdout.decode()
            self.assertEqual(out, "secret ranking " * 1000)

    def test_digest_mentions_no_money(self):
        cands, run = br.scan(FakeGitHub(search={"repo:HHS": [issue()]}), self.cfg(), NOW)
        text = br.digest(cands, run, [cands[0]["key"]], NOW)
        self.assertIn("not a claim, a submission or money", text)
        self.assertIn("**NEW**", text)


if __name__ == "__main__":
    unittest.main()
