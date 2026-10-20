---
name: codefactor
description: Query CodeFactor.io code-quality issues (lintr, cpplint, duplication, complexity) for a GitHub repo or pull request so they can be fixed locally. Use when the user mentions CodeFactor, code quality grades/badges, a failing CodeFactor check on a PR, or wants to fix lint issues reported on codefactor.io.
---

# CodeFactor issue querying

CodeFactor.io has no official API, but its public repo pages embed the full
issue model as inline JSON. The helper script extracts it:

```bash
python3 ~/.claude/skills/codefactor/scripts/codefactor.py <command> [owner/repo] [options]
```

If `owner/repo` is omitted, it is auto-detected from `git remote get-url origin`
in the current directory.

## Commands

**`summary [owner/repo] [--branch B]`** — total issue count, ignored count, and a
breakdown by language (with `lang-id`), category, and rule group (with `group-id`).
Always start here.

**`issues [owner/repo] [options]`** — list issues as `file:line [Severity/Category] message`.

**`pr N [owner/repo] [options]`** — the issues a pull request **introduces**, which is
what the GitHub `CodeFactor` check counts. Use this for "fix the CodeFactor issues on
this PR". Add `--fixed` for the issues the PR removes, or `--ignored`.

Options (both `issues` and `pr`):
- `--category C` — Style, Maintainability, Complexity, Duplication
- `--group-id N` — one rule group (id from summary); the best way to fix issues in batches
- `--lang-id N` — language id from summary
- `--branch B` — non-default branch (`issues` only)
- `--max-pages N` — pages fetched (10 issues/page, default 5); `--all` for everything
- `--format jsonl` — machine-readable output including all duplicate-code locations,
  columns, and metric values

## Fixing a PR's issues

A PR is analyzed **separately from its branch** — `summary`/`issues --branch <pr-branch>`
report 0, because the result lives at `/repository/github/{owner}/{repo}/pull/{N}`.
Reach for `pr N` and nothing else.

```bash
python3 ~/.claude/skills/codefactor/scripts/codefactor.py pr 1219 nlmixr2/rxode2
```

Confirm against the check itself, which also says how many to expect:

```bash
gh api repos/{owner}/{repo}/commits/$(git rev-parse HEAD)/status \
  --jq '.statuses[]|select(.context|test("CodeFactor";"i"))|{state,description}'
```

CodeFactor **deletes the PR page rather than serving an empty one**, so a clean PR
404s. The command reports that as `0 issue(s) ... nothing to fix` and exits 0; it
only errors if the repo itself is unknown. Re-analysis takes a minute or two after
a push, and the page can 404 transiently while it runs — re-check the GitHub status
before concluding a PR is clean.

## Recommended fixing workflow

1. `summary` to see rule groups ranked by count.
2. Pick one group (e.g. `lintr-semicolon_linter`) and run
   `issues --category X --group-id N --all` to get every `file:line`.
3. Fix them in the local clone (many groups are mechanical: trailing whitespace,
   semicolons, `T`/`F` → `TRUE`/`FALSE`, `1:length(x)` → `seq_along(x)`).
4. Line numbers refer to the analyzed branch head — if the local clone has moved on,
   re-locate by pattern rather than trusting the line number blindly.
5. CodeFactor re-analyzes on push, so counts update only after pushing.

## Notes and caveats

- Works only for repos publicly visible on codefactor.io (all nlmixr2 repos are).
- `Duplication` issues have multiple locations; text output shows extras as
  `also:` lines, jsonl includes them all in `locations`.
- Complexity groups are named like `2-3-1` with Description Moderate/High/Critical —
  these usually need refactoring, not mechanical fixes. A `Complex Method` with a
  `complexity` metric just over 20 is normally cured by extracting each branch of a
  dispatcher into a named function; verify it stayed a pure refactor by re-running
  the numeric tests, not just the build.
- Ignored issues live at `/repository/github/{owner}/{repo}/ignoredissues`
  (same page structure if ever needed).
- Big repos (rxode2 has ~2300 issues = 234 pages) — always narrow with
  `--group-id` before `--all`; the script sleeps 0.3s between pages.
- lintr issues follow the repo's own `.lintr` config as interpreted by CodeFactor;
  if a whole group is unwanted noise, it can be ignored on the CodeFactor web UI
  instead of fixed.
