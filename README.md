# codefactor.skill

A [Claude Code](https://docs.claude.com/en/docs/claude-code) skill for querying
[CodeFactor.io](https://www.codefactor.io) code-quality issues -- lintr, cpplint,
duplication, complexity -- for a public GitHub repository or pull request, so they
can be fixed locally.

CodeFactor has no official API, but its public repository pages embed the full
issue model as inline JSON.  `scripts/codefactor.py` (Python 3, standard library
only) pulls it out and prints the issues as `file:line [Severity/Category] message`
or as JSONL.

## Install

The skill has to live in a directory called `codefactor`:

```sh
git clone https://github.com/mattfidler/codefactor.skill ~/.claude/skills/codefactor
```

and `git -C ~/.claude/skills/codefactor pull` keeps it up to date.

## Use

Ask Claude about a CodeFactor grade, a failing CodeFactor check on a pull request,
or the lint issues codefactor.io reports, and it reaches for the skill.  The script
also works on its own:

```sh
python3 ~/.claude/skills/codefactor/scripts/codefactor.py summary nlmixr2/rxode2
python3 ~/.claude/skills/codefactor/scripts/codefactor.py issues --group-id 1234 --all
python3 ~/.claude/skills/codefactor/scripts/codefactor.py pr 1219 nlmixr2/rxode2
```

With no `owner/repo`, it is read from `git remote get-url origin`.  See
[SKILL.md](SKILL.md) for every command and option, and for how pull requests are
analyzed separately from their branches.
