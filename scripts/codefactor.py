#!/usr/bin/env python3
"""Query CodeFactor.io code-quality issues for a public GitHub repository.

CodeFactor has no official API, but its issues pages embed the full data
model as inline JSON (an AngularJS `.value("model", {...})` call). This
script fetches those pages and emits the issues as text or JSONL.

Usage:
  codefactor.py summary [owner/repo] [--branch B]
  codefactor.py issues  [owner/repo] [--branch B] [--category C] [--group-id N]
                        [--lang-id N] [--max-pages N | --all] [--format text|jsonl]
  codefactor.py pr N    [owner/repo] [--fixed | --ignored] [--category C]
                        [--group-id N] [--lang-id N] [--max-pages N | --all]
                        [--format text|jsonl]

If owner/repo is omitted, it is detected from `git remote get-url origin`
in the current directory.

A pull request is analyzed separately from any branch: the `issues` command
with `--branch <pr-branch>` reports 0, because the result lives at
/repository/github/{owner}/{repo}/pull/{N}. Use `pr` for it. The default view
is the issues the PR INTRODUCES, which is what the GitHub check reports.
"""

import argparse
import html as htmllib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://www.codefactor.io/repository/github"
MODEL_RE = re.compile(
    r'\.value\(\s*["\']model["\']\s*,\s*(\{.*\})\s*\)\s*;?\s*</script>', re.S
)


def detect_repo():
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("error: no owner/repo given and no git remote found")
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url)
    if not m:
        sys.exit(f"error: cannot parse GitHub owner/repo from remote: {url}")
    return f"{m.group(1)}/{m.group(2)}"


def fetch_model(url, missing_ok=False):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        page = urllib.request.urlopen(req, timeout=30).read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404 and missing_ok:
            return None
        sys.exit(f"error: HTTP {e.code} fetching {url} "
                 "(is the repo analyzed on codefactor.io?)")
    m = MODEL_RE.search(page)
    if not m:
        sys.exit(f"error: no embedded issue model found at {url} "
                 "(private repo or page layout changed?)")
    return json.loads(m.group(1))


def issues_url(repo, branch, page=None, category=None, group_id=None, lang_id=None):
    url = f"{BASE}/{repo}/issues"
    if branch:
        url += f"/{urllib.parse.quote(branch, safe='')}"
    params = {}
    if category:
        params["category"] = category
    if group_id:
        params["groupId"] = group_id
    if lang_id:
        params["lang"] = lang_id
    if page and page > 1:
        params["page"] = page
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def pr_url(repo, number, view=None, page=None, category=None, group_id=None,
           lang_id=None):
    # /pull/{n} is what the PR introduces; /pull/fixed/{n} and /pull/ignored/{n}
    # put the view BEFORE the number, unlike the branch in issues_url().
    seg = f"pull/{view}/{number}" if view else f"pull/{number}"
    url = f"{BASE}/{repo}/{seg}"
    params = {}
    if category:
        params["category"] = category
    if group_id:
        params["groupId"] = group_id
    if lang_id:
        params["lang"] = lang_id
    if page and page > 1:
        params["page"] = page
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def strip_tags(s):
    return htmllib.unescape(re.sub(r"<[^>]+>", "", s or ""))


def issue_record(issue):
    locs = [
        {"path": l["Path"].replace("\\", "/"),
         "start_line": l["StartLine"], "end_line": l["EndLine"],
         "col": l["Col"]}
        for l in issue.get("Locations") or []
    ]
    return {
        "key": issue["Key"],
        "file": issue["FilePath"].replace("\\", "/"),
        "locations": locs,
        "severity": issue["Severity"],
        "category": issue["Category"],
        "rule": issue["Name"],
        "message": strip_tags(issue.get("Message") or issue["Name"]),
        "metric": issue.get("Metric"),
    }


def print_text(rec):
    loc = rec["locations"][0] if rec["locations"] else None
    where = rec["file"]
    if loc:
        where += f":{loc['start_line']}"
        if loc["end_line"] and loc["end_line"] != loc["start_line"]:
            where += f"-{loc['end_line']}"
    line = f"{where} [{rec['severity']}/{rec['category']}] {rec['message']}"
    if rec["metric"] and rec["metric"].get("Value"):
        line += f" ({rec['metric']['Name']}: {rec['metric']['Value']})"
    print(line)
    for extra in rec["locations"][1:]:
        print(f"    also: {extra['path']}:{extra['start_line']}-{extra['end_line']}")


def cmd_summary(args):
    model = fetch_model(issues_url(args.repo, args.branch))
    f = model["Filter"]
    print(f"CodeFactor issues for {args.repo}"
          + (f" (branch {args.branch})" if args.branch else "")
          + f": {f['TotalCount']} total, {f['PageCount']} pages of 10")
    ignored = (f.get("SwitchView") or {})
    if ignored.get("Name") == "Ignored":
        print(f"Ignored issues: {ignored.get('Count', 0)}")
    print()
    for lang in f.get("Langs") or []:
        print(f"Language {lang['Name']} (lang-id {lang['Id']}): {lang['Count']}")
    print()
    for item in f.get("Items") or []:
        for cat in item.get("Values") or []:
            print(f"{cat['Name']}: {cat['Count']}")
            for grp in cat.get("Items") or []:
                print(f"  group {grp['Id']:>5}  {grp['Name']:<45} "
                      f"{grp['Count']:>5}  {strip_tags(grp['Description'])}")


def collect(url_of_page, args, missing_ok=False):
    """Fetch issue records page by page. `url_of_page(n)` builds the nth URL."""
    first = fetch_model(url_of_page(1), missing_ok=missing_ok)
    if first is None:
        return [], 0, 0
    page_count = first["Filter"]["PageCount"]
    pages = page_count if args.all else min(page_count, args.max_pages)
    records = [issue_record(i) for i in first["Issues"]["List"]]
    for p in range(2, pages + 1):
        time.sleep(0.3)
        model = fetch_model(url_of_page(p))
        records.extend(issue_record(i) for i in model["Issues"]["List"])
        print(f"fetched page {p}/{pages}...", file=sys.stderr)
    return records, pages, page_count


def emit(records, pages, page_count, fmt):
    for r in records:
        if fmt == "jsonl":
            print(json.dumps(r))
        else:
            print_text(r)
    if pages < page_count:
        print(f"\n[showing {len(records)} issues from {pages} of {page_count} pages; "
              f"use --all or narrow with --category/--group-id/--lang-id]",
              file=sys.stderr)


def cmd_issues(args):
    records, pages, page_count = collect(
        lambda p: issues_url(args.repo, args.branch, page=p, category=args.category,
                             group_id=args.group_id, lang_id=args.lang_id), args)
    emit(records, pages, page_count, args.format)


def cmd_pr(args):
    view = "fixed" if args.fixed else ("ignored" if args.ignored else None)
    # CodeFactor drops the PR page entirely rather than serving an empty one, so
    # a 404 here means "nothing in this view", not a broken URL.  That is the
    # answer you most want from this command, so do not exit on it.
    records, pages, page_count = collect(
        lambda p: pr_url(args.repo, args.number, view=view, page=p,
                         category=args.category, group_id=args.group_id,
                         lang_id=args.lang_id), args, missing_ok=True)
    if page_count == 0 and fetch_model(issues_url(args.repo, None),
                                       missing_ok=True) is None:
        # The PR page 404s for an unanalyzed repo and a misspelled one exactly
        # as it does for a clean PR.  Reporting "nothing to fix" for those would
        # be a false all-clear, so confirm the repo itself is there.
        sys.exit(f"error: {args.repo} is not analyzed on codefactor.io "
                 "(check the owner/repo spelling)")
    if args.format != "jsonl":
        what = {"fixed": "fixed by", "ignored": "ignored on"}.get(view, "introduced by")
        print(f"{len(records)} issue(s) {what} {args.repo}#{args.number}"
              + ("" if records else " -- nothing to fix"))
    emit(records, pages, page_count, args.format)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("repo", nargs="?", help="owner/repo (default: from git remote)")
        p.add_argument("--branch", help="branch (default: repo default branch)")

    def filters(p):
        p.add_argument("--category", help="e.g. Style, Maintainability, Complexity, Duplication")
        p.add_argument("--group-id", type=int, help="rule group id (see summary)")
        p.add_argument("--lang-id", type=int, help="language id (see summary)")
        p.add_argument("--max-pages", type=int, default=5,
                       help="pages to fetch (10 issues/page, default 5)")
        p.add_argument("--all", action="store_true", help="fetch every page")
        p.add_argument("--format", choices=["text", "jsonl"], default="text")

    ps = sub.add_parser("summary", help="issue counts by language/category/rule group")
    common(ps)

    pi = sub.add_parser("issues", help="list issues with file:line and message")
    common(pi)
    filters(pi)

    pp = sub.add_parser("pr", help="issues a pull request introduces (what the GitHub check reports)")
    pp.add_argument("number", type=int, help="pull request number")
    pp.add_argument("repo", nargs="?", help="owner/repo (default: from git remote)")
    view = pp.add_mutually_exclusive_group()
    view.add_argument("--fixed", action="store_true", help="issues the PR fixes instead")
    view.add_argument("--ignored", action="store_true", help="ignored issues on the PR instead")
    filters(pp)

    args = ap.parse_args()
    if not args.repo:
        args.repo = detect_repo()
    if "/" not in args.repo:
        sys.exit("error: repo must be owner/repo")

    if args.cmd == "summary":
        cmd_summary(args)
    elif args.cmd == "pr":
        cmd_pr(args)
    else:
        cmd_issues(args)


if __name__ == "__main__":
    main()
