#!/usr/bin/env python3
"""Sovereign bounty radar: find open cash bounties on GitHub, score them, log them.

Stdlib only. Reads sources.json, queries the public GitHub REST API (GITHUB_TOKEN
if set), enriches each issue with repo health, competition and AI-policy signals,
scores it with the rubric in RUBRIC.md and writes:

  data/candidates.json   current snapshot, best first
  data/ledger.csv        one row per candidate, first_seen preserved across runs
  data/DIGEST.md         human-readable top list
  data/run-log.jsonl     one line per run (query counts, errors)

It never comments, claims, forks or submits anything. Discovery only.
"""
import argparse
import csv
import hashlib
import subprocess
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UA = "sovereign-bounty-radar/1.0"

AI_BAN_PATTERNS = [
    r"\bno (?:ai|llm)[- ]generated\b",
    r"\b(?:ai|llm)[- ]generated (?:code|pull requests?|prs?|contributions?) (?:are|is|will be) (?:not (?:accepted|allowed|welcome)|rejected|closed|banned|prohibited)",
    r"\bdo not (?:use|submit) (?:ai|llms?|chatgpt|copilot|claude)\b",
    r"\b(?:ai|autonomous) agents? (?:are|is) (?:not allowed|banned|prohibited)",
    r"\bprohibit(?:s|ed)? (?:the use of )?(?:ai|llm|generative ai)",
    r"\bhuman[- ]authored only\b",
    r"\bbanned?\b[^.\n]{0,40}\b(?:ai|llm)\b[^.\n]{0,40}\b(?:contributions?|prs?|pull requests?)",
]
AI_BAN_RE = [re.compile(p, re.I) for p in AI_BAN_PATTERNS]

NONCASH_RE = re.compile(r"\b(points?|xp|karma|reputation only|swag|rtc|testnet|no cash|unpaid)\b", re.I)
CLAIMED_RE = re.compile(r"(/attempt|/claim|i(?:'| a)m working on|i will work on|assigned to me|working on this)", re.I)
AMOUNT_RE = re.compile(
    r"(?:US\$|\$|USD\s?)\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d{1,2})?)\s?(k\b)?|(\d+(?:\.\d+)?)\s?(?:USD|USDC|dollars)\b",
    re.I,
)
# Payout runs through a platform whose terms ban AI agents (Algora) or require human authorship (BountyHub).
BANNED_PLATFORM_RE = re.compile(r"algora\.io|\U0001F48E Bounty|bountyhub\.dev", re.I)
# Bounty aggregators, mirrors, digests and grant applications: not the canonical paid issue.
MIRROR_TITLE_RE = re.compile(r"bounty alert|digest|open bounties right now|bounty seguro|new opportunit|grant application|\bairdrop", re.I)
MIRROR_REPO_RE = re.compile(r"bount|earn|airdrop|sandbox|radar|scout|watcher|hunter", re.I)
PREFERRED_LANGS = {"Python", "TypeScript", "JavaScript", "Go", "HTML", "CSS", "Shell", "Markdown"}


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def iso(ts):
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s):
    if not s:
        return None
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


class GitHub:
    def __init__(self, token=None, max_calls=900, max_seconds=1080):
        self.token = token
        self.deadline = time.time() + max_seconds
        self.calls = 0
        self.max_calls = max_calls
        self.errors = []

    def out_of_time(self):
        return time.time() > self.deadline

    def get(self, path, params=None, accept="application/vnd.github+json", retries=4):
        if self.calls >= self.max_calls:
            raise RuntimeError("call budget exhausted")
        url = path if path.startswith("http") else API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"Accept": accept, "User-Agent": UA, "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        for attempt in range(retries):
            self.calls += 1
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read().decode("utf-8")
                    remaining = r.headers.get("X-RateLimit-Remaining")
                    if remaining is not None and int(remaining) < 2:
                        reset = int(r.headers.get("X-RateLimit-Reset", "0"))
                        time.sleep(max(0, min(65, reset - time.time() + 1)))
                    if not body:
                        return None
                    try:
                        return json.loads(body)
                    except ValueError:
                        return body  # raw file contents
            except urllib.error.HTTPError as e:
                if e.code in (403, 429) and attempt < retries - 1:
                    retry = e.headers.get("Retry-After")
                    time.sleep(int(retry) if retry and retry.isdigit() else 20 * (attempt + 1))
                    continue
                if e.code == 404:
                    return None
                self.errors.append({"url": url, "status": e.code})
                return None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                self.errors.append({"url": url, "error": str(e)})
                return None
        return None

    def search_code(self, query):
        """Return (items, total_count). Code search allows ~10 requests a minute, so callers must pace."""
        res = self.get("/search/code", {"q": query, "per_page": 50}, retries=1)
        if res is None:
            return [], None
        return res.get("items", []), res.get("total_count", 0)

    def search_issues(self, query, max_pages=3):
        """Return (items, total_count, complete)."""
        items, total, complete = [], None, True
        for page in range(1, max_pages + 1):
            res = self.get("/search/issues", {"q": query, "per_page": 100, "page": page, "sort": "updated", "order": "desc"})
            if res is None:
                return items, total, False
            total = res.get("total_count", 0)
            if res.get("incomplete_results"):
                complete = False
            batch = res.get("items", [])
            items.extend(batch)
            if len(batch) < 100:
                break
            time.sleep(2.1)  # search API: 30 req/min authenticated
        if total is not None and len(items) < min(total, 1000):
            complete = False
        return items, total, complete


def discover_programs(gh, cfg, known):
    """Find repos whose own docs describe a paid-contributor or bounty program. Leads for review, not candidates."""
    leads, failures = {}, 0
    for q in cfg.get("program_discovery", []):
        if failures >= 2 or gh.out_of_time():
            break  # code search is rate limited hard; never let it eat the run
        items, total = gh.search_code(q["query"])
        if total is None:
            failures += 1
        for it in items:
            repo = (it.get("repository") or {}).get("full_name")
            if not repo or repo in known or repo.split("/")[0] in cfg.get("excluded_owners", []):
                continue
            lead = leads.setdefault(repo, {"repo": repo, "files": [], "queries": []})
            if it.get("path") not in lead["files"]:
                lead["files"].append(it.get("path"))
            if q["id"] not in lead["queries"]:
                lead["queries"].append(q["id"])
        time.sleep(7)
    return sorted(leads.values(), key=lambda l: (-len(l["queries"]), l["repo"]))


def expand(query, now):
    return (query.replace("{since7}", (now - dt.timedelta(days=7)).strftime("%Y-%m-%d"))
                 .replace("{since14}", (now - dt.timedelta(days=14)).strftime("%Y-%m-%d"))
                 .replace("{since30}", (now - dt.timedelta(days=30)).strftime("%Y-%m-%d")))


def extract_amount(*texts):
    """Largest plausible USD amount mentioned (labels/title first). None if none."""
    best = None
    for t in texts:
        if not t:
            continue
        for m in AMOUNT_RE.finditer(t):
            raw = m.group(1) or m.group(3)
            try:
                val = float(raw.replace(",", ""))
            except (TypeError, ValueError):
                continue
            if m.group(2):
                val *= 1000
            if 5 <= val <= 50000:
                best = val if best is None else max(best, val)
        if best is not None:
            return best
    return None


def repo_of(issue):
    return issue["repository_url"].split("/repos/", 1)[1]


def ai_policy(gh, repo, cache):
    if repo in cache:
        return cache[repo]
    found = None
    for path in ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md", "AI_POLICY.md", ".github/AI_POLICY.md"):
        res = gh.get(f"/repos/{repo}/contents/{path}", accept="application/vnd.github.raw+json")
        if res is None:
            continue
        text = res if isinstance(res, str) else json.dumps(res)
        for rx in AI_BAN_RE:
            m = rx.search(text)
            if m:
                found = {"banned": True, "file": path, "match": m.group(0)[:120]}
                break
        if found:
            break
    cache[repo] = found or {"banned": False}
    return cache[repo]


def competition(gh, repo, number):
    """Count open/merged PRs that cross-reference the issue, and claim-style comments."""
    timeline = gh.get(f"/repos/{repo}/issues/{number}/timeline", {"per_page": 100}) or []
    open_prs, merged_prs, closed_prs = set(), set(), set()
    for ev in timeline:
        if ev.get("event") != "cross-referenced":
            continue
        src = (ev.get("source") or {}).get("issue") or {}
        if not src.get("pull_request"):
            continue
        key = src.get("html_url")
        if (src.get("pull_request") or {}).get("merged_at"):
            merged_prs.add(key)
        elif src.get("state") == "open":
            open_prs.add(key)
        else:
            closed_prs.add(key)
    claims, maintainer, others = 0, 0, 0
    for ev in timeline:
        if ev.get("event") != "commented":
            continue
        if CLAIMED_RE.search(ev.get("body") or ""):
            claims += 1
        if ev.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR"):
            maintainer += 1
        else:
            others += 1
    return {"open_prs": len(open_prs), "merged_prs": len(merged_prs), "closed_prs": len(closed_prs), "claim_comments": claims,
            "maintainer_comments": maintainer, "other_comments": others}


TIER_POINTS = {"sponsor_program": 25, "platform_escrow": 15, "label_only": 8, "unknown": 0}


def score(c, now):
    """Apply RUBRIC.md. Returns (score, verdict, reasons). Pure function for tests."""
    reasons = []
    gates = []
    if c.get("state") != "open":
        gates.append("closed")
    if c.get("excluded"):
        gates.append("excluded_repo")
    if c.get("repo_archived"):
        gates.append("archived_repo")
    if c.get("assignees") and not c.get("assignee_is_us"):
        gates.append("assigned_to_other")
    if (c.get("ai_policy") or {}).get("banned"):
        gates.append("ai_banned")
    if c.get("noncash"):
        gates.append("noncash_reward")
    if c.get("merged_prs", 0) > 0:
        gates.append("already_solved")
    if c.get("banned_platform"):
        gates.append("platform_bans_ai_agents")
    if c.get("tier") != "sponsor_program" and (MIRROR_TITLE_RE.search(c.get("title", "")) or
                                               MIRROR_REPO_RE.search(c.get("repo", "").split("/")[-1])):
        gates.append("aggregator_mirror_or_grant")
    if gates:
        return 0, "rejected", gates

    pts = TIER_POINTS.get(c.get("tier", "unknown"), 0)
    reasons.append(f"sponsor:{c.get('tier')}+{pts}")

    amt = c.get("amount_usd")
    if amt is None:
        a = 0
    elif amt >= 500:
        a = 20
    elif amt >= 200:
        a = 17
    elif amt >= 100:
        a = 13
    elif amt >= 50:
        a = 8
    else:
        a = 4
    pts += a
    reasons.append(f"amount:{amt}+{a}")

    comp = c.get("open_prs", 0) * 2 + c.get("closed_prs", 0) + c.get("claim_comments", 0)
    cp = 25 if comp == 0 else 18 if comp <= 1 else 12 if comp <= 3 else 5 if comp <= 6 else 0
    pts += cp
    reasons.append(f"competition:{comp}+{cp}")

    created = parse_ts(c.get("created_at"))
    age = (now - created).days if created else 999
    f = 10 if age <= 3 else 7 if age <= 14 else 4 if age <= 60 else 1
    pts += f
    reasons.append(f"age_days:{age}+{f}")

    elig = {"us_citizen": 10, "open": 6, "open_tiered": 3}.get(c.get("eligibility", "open"), 6)
    pts += elig
    reasons.append(f"eligibility:{c.get('eligibility', 'open')}+{elig}")

    fit = 0
    if c.get("repo_language") in PREFERRED_LANGS:
        fit += 5
    if (c.get("repo_stars") or 0) >= 50:
        fit += 3
    pushed = parse_ts(c.get("repo_pushed_at"))
    if pushed and (now - pushed).days <= 30:
        fit += 2
    pts += fit
    reasons.append(f"fit+{fit}")

    # Field test (Hackernoon, 2026): bounty threads where candidates ask about assignment/payment and no maintainer ever answers.
    if c.get("enriched") and c.get("maintainer_comments", 1) == 0 and c.get("other_comments", 0) >= 2:
        pts -= 12
        reasons.append("maintainer_silent-12")

    repo_created = parse_ts(c.get("repo_created_at"))
    if repo_created and (now - repo_created).days < 60 and (c.get("repo_stars") or 0) < 10:
        pts -= 15
        reasons.append("low_trust_new_repo-15")

    pts = max(0, min(100, pts))
    verdict = "deep_review" if pts >= 60 else "watch" if pts >= 40 else "logged"
    if verdict == "deep_review" and not c.get("enriched", True):
        verdict = "watch"  # competition and AI policy not checked yet
        reasons.append("not_enriched")
    if amt is None and c.get("tier") != "sponsor_program":
        verdict = "logged"  # no stated cash and no program terms: nothing to act on yet
        reasons.append("no_stated_amount")
    return pts, verdict, reasons


def build_candidate(issue, source, sources_cfg):
    repo = repo_of(issue)
    labels = [l["name"] for l in issue.get("labels", [])]
    text_labels = " ".join(labels)
    owner = repo.split("/")[0]
    return {
        "key": f"{repo}#{issue['number']}",
        "url": issue["html_url"],
        "repo": repo,
        "number": issue["number"],
        "title": issue["title"],
        "labels": labels,
        "state": issue["state"],
        "created_at": issue["created_at"],
        "updated_at": issue["updated_at"],
        "assignees": [a["login"] for a in issue.get("assignees") or []],
        "comments": issue.get("comments", 0),
        "amount_usd": extract_amount(text_labels, issue["title"], (issue.get("body") or "")[:4000]),
        "noncash": bool(NONCASH_RE.search(text_labels + " " + issue["title"])) and extract_amount(text_labels, issue["title"]) is None,
        "tier": source.get("tier", "unknown"),
        "eligibility": source.get("eligibility", "open"),
        "program": source.get("id"),
        "sources": [source["id"]],
        "banned_platform": bool(BANNED_PLATFORM_RE.search(text_labels + " " + (issue.get("body") or ""))),
        "excluded": repo in sources_cfg.get("excluded_repos", []) or owner in sources_cfg.get("excluded_owners", []),
    }


def scan(gh, cfg, now, max_enrich=150):
    run = {"started_at": iso(now), "queries": [], "errors": []}
    found = {}
    sources = [dict(s, kind="program") for s in cfg.get("program_watch", [])] + \
              [dict(s, kind="discovery") for s in cfg.get("discovery_queries", [])]
    for s in sources:
        q = expand(s["query"], now)
        items, total, complete = gh.search_issues(q)
        run["queries"].append({"id": s["id"], "query": q, "total_count": total, "retrieved": len(items), "complete": complete})
        for it in items:
            if it.get("pull_request"):
                continue
            c = build_candidate(it, s, cfg)
            if c["key"] in found:
                prev = found[c["key"]]
                prev["sources"] = sorted(set(prev["sources"] + c["sources"]))
                if TIER_POINTS.get(c["tier"], 0) > TIER_POINTS.get(prev["tier"], 0):
                    prev.update(tier=c["tier"], eligibility=c["eligibility"], program=c["program"])
            else:
                found[c["key"]] = c
        time.sleep(2.1)

    known = set(cfg.get("excluded_repos", []))
    known |= {q["query"].split("repo:")[1].split()[0] for q in cfg.get("program_watch", []) if "repo:" in q["query"]}
    run["program_leads"] = discover_programs(gh, cfg, known)

    repo_cache, policy_cache = {}, {}
    # Enrich the most promising first: program-watch, then amount, then freshness.
    order = sorted(found.values(), key=lambda c: (TIER_POINTS.get(c["tier"], 0), c["amount_usd"] or 0, c["updated_at"]), reverse=True)
    for i, c in enumerate(order):
        if c["excluded"] or i >= max_enrich or gh.out_of_time():
            c["enriched"] = False
            continue
        if c["repo"] not in repo_cache:
            repo_cache[c["repo"]] = gh.get(f"/repos/{c['repo']}") or {}
        r = repo_cache[c["repo"]]
        c.update(repo_archived=r.get("archived", False), repo_stars=r.get("stargazers_count"),
                 repo_language=r.get("language"), repo_pushed_at=r.get("pushed_at"), repo_created_at=r.get("created_at"))
        c.update(competition(gh, c["repo"], c["number"]))
        c["ai_policy"] = ai_policy(gh, c["repo"], policy_cache)
        c["enriched"] = True
    for c in found.values():
        c["score"], c["verdict"], c["reasons"] = score(c, now)
    run["errors"] = gh.errors[:20]
    run["api_calls"] = gh.calls
    run["candidates"] = len(found)
    return sorted(found.values(), key=lambda c: c["score"], reverse=True), run


LEDGER_FIELDS = ["key", "url", "title", "program", "tier", "amount_usd", "score", "verdict", "open_prs", "claim_comments",
                 "assignees", "ai_banned", "first_seen", "last_seen", "times_seen", "reasons"]


def update_ledger(path, candidates, now, info=None):
    rows = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows[row["key"]] = row
    stamp = iso(now)
    new_keys = []
    for c in candidates:
        prev = rows.get(c["key"])
        if info is not None:
            first, times = info[c["key"]]
            prev = None if times == 1 else {"first_seen": first, "times_seen": times - 1}
        if prev is None:
            new_keys.append(c["key"])
        rows[c["key"]] = {
            "key": c["key"], "url": c["url"], "title": c["title"][:140], "program": c.get("program") or "",
            "tier": c["tier"], "amount_usd": "" if c["amount_usd"] is None else f"{c['amount_usd']:.0f}",
            "score": c["score"], "verdict": c["verdict"], "open_prs": c.get("open_prs", ""),
            "claim_comments": c.get("claim_comments", ""), "assignees": " ".join(c["assignees"]),
            "ai_banned": (c.get("ai_policy") or {}).get("banned", ""),
            "first_seen": prev["first_seen"] if prev else stamp, "last_seen": stamp,
            "times_seen": int(prev["times_seen"]) + 1 if prev else 1, "reasons": ";".join(c["reasons"]),
        }
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        w.writeheader()
        for row in sorted(rows.values(), key=lambda r: (-int(r["score"] or 0), r["key"])):
            w.writerow(row)
    return new_keys


def key_hash(key):
    return hashlib.sha256(("sovereign-radar:" + key).encode()).hexdigest()[:20]


def update_seen(path, candidates, now):
    """Persist only salted hashes of candidate keys with first/last seen. Safe to publish.

    Returns (new_keys, info) where info maps key -> (first_seen, times_seen)."""
    seen = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seen[row["hash"]] = row
    stamp = iso(now)
    new_keys, info = [], {}
    for c in candidates:
        h = key_hash(c["key"])
        prev = seen.get(h)
        if prev is None:
            new_keys.append(c["key"])
        first = prev["first_seen"] if prev else stamp
        times = int(prev["times_seen"]) + 1 if prev else 1
        seen[h] = {"hash": h, "first_seen": first, "last_seen": stamp, "times_seen": times}
        info[c["key"]] = (first, times)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["hash", "first_seen", "last_seen", "times_seen"])
        w.writeheader()
        for row in sorted(seen.values(), key=lambda r: r["hash"]):
            w.writerow(row)
    return new_keys, info


def encrypt_file(src, dst, cert):
    """S/MIME-encrypt src to dst (DER) with the public certificate. Only the private key can read it."""
    subprocess.run(["openssl", "smime", "-encrypt", "-aes-256-cbc", "-binary", "-in", src, "-out", dst,
                    "-outform", "DER", cert], check=True)


def digest(candidates, run, new_keys, now, top=25):
    lines = [f"# Bounty radar digest {now.strftime('%Y-%m-%d %H:%MZ')}", "",
             "Discovery only. A listing here is not a claim, a submission or money. Deep-review items still need the "
             "submission gate (sponsor terms, claim rules, competing PRs, payout path) before anyone works them.", "",
             f"Candidates: {len(candidates)}. New this run: {len(new_keys)}. API calls: {run['api_calls']}.", ""]
    for verdict in ("deep_review", "watch"):
        sel = [c for c in candidates if c["verdict"] == verdict][:top]
        lines.append(f"## {verdict.replace('_', ' ').title()} ({len([c for c in candidates if c['verdict'] == verdict])})")
        lines.append("")
        if not sel:
            lines.append("None.")
        for c in sel:
            amt = "amount unknown" if c["amount_usd"] is None else f"${c['amount_usd']:.0f}"
            new = " **NEW**" if c["key"] in new_keys else ""
            lines.append(f"- {c['score']} | [{c['key']}]({c['url']}) | {amt} | {c['tier']} | open PRs {c.get('open_prs', '?')}, "
                         f"claims {c.get('claim_comments', '?')}{new}  ")
            lines.append(f"  {c['title'][:120]}")
        lines.append("")
    rej = {}
    for c in candidates:
        if c["verdict"] == "rejected":
            for r in c["reasons"]:
                rej[r] = rej.get(r, 0) + 1
    leads = run.get("program_leads") or []
    lines.append(f"## Program leads ({len(leads)}): repos whose docs describe a paid program, not yet reviewed")
    lines.append("")
    for l in leads[:40]:
        lines.append(f"- [{l['repo']}](https://github.com/{l['repo']}) | {', '.join(l['files'][:3])} | via {', '.join(l['queries'])}")
    if not leads:
        lines.append("None.")
    lines.append("")
    lines.append("## Rejections by gate")
    lines.append("")
    lines += [f"- {k}: {v}" for k, v in sorted(rej.items(), key=lambda kv: -kv[1])] or ["None."]
    lines += ["", "## Source coverage", ""]
    for q in run["queries"]:
        lines.append(f"- {q['id']}: total {q['total_count']}, retrieved {q['retrieved']}, complete {q['complete']}")
    if run["errors"]:
        lines += ["", "## Errors", ""] + [f"- {json.dumps(e)}" for e in run["errors"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=os.path.join(here, "sources.json"))
    ap.add_argument("--out", default=os.path.join(here, "data"), help="plaintext results directory")
    ap.add_argument("--max-enrich", type=int, default=150)
    ap.add_argument("--public-dir", help="with --encrypt-cert: where encrypted results and the hashed seen-state go")
    ap.add_argument("--encrypt-cert", help="PEM certificate; results are written encrypted to --public-dir")
    args = ap.parse_args(argv)
    with open(args.sources, encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(args.out, exist_ok=True)
    now = utcnow()
    gh = GitHub(os.environ.get("GITHUB_TOKEN"))
    candidates, run = scan(gh, cfg, now, args.max_enrich)
    state_dir = args.public_dir or args.out
    os.makedirs(state_dir, exist_ok=True)
    new_keys, info = update_seen(os.path.join(state_dir, "seen.csv"), candidates, now)
    update_ledger(os.path.join(args.out, "ledger.csv"), candidates, now, info)
    run["new"] = new_keys
    run["finished_at"] = iso(utcnow())
    with open(os.path.join(args.out, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": iso(now), "candidates": candidates}, f, indent=1)
    with open(os.path.join(args.out, "DIGEST.md"), "w", encoding="utf-8") as f:
        f.write(digest(candidates, run, new_keys, now))
    with open(os.path.join(args.out, "run-log.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({k: run[k] for k in ("started_at", "finished_at", "api_calls", "candidates", "new", "queries", "errors", "program_leads")}) + "\n")
    if args.encrypt_cert:
        for name in ("DIGEST.md", "candidates.json", "ledger.csv", "run-log.jsonl"):
            encrypt_file(os.path.join(args.out, name), os.path.join(state_dir, name + ".enc"), args.encrypt_cert)
        counts = {v: sum(1 for c in candidates if c["verdict"] == v) for v in ("deep_review", "watch", "logged", "rejected")}
        with open(os.path.join(state_dir, "status.json"), "w", encoding="utf-8") as f:
            json.dump({"last_run": iso(now), "candidates": len(candidates), "new": len(new_keys), "verdicts": counts,
                       "errors": len(run["errors"])}, f, indent=1)
            f.write("\n")
    print(f"candidates={len(candidates)} new={len(new_keys)} calls={gh.calls} errors={len(gh.errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
