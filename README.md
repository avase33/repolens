<div align="center">

# 🔭 RepoLens

### X-ray vision for any Git repository.

**Point it at a repo. Get an interactive report of where the risk really lives.**

[![CI](https://github.com/akhil/repolens/actions/workflows/ci.yml/badge.svg)](https://github.com/akhil/repolens/actions)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dependencies](https://img.shields.io/badge/runtime%20deps-0-brightgreen)](pyproject.toml)

</div>

---

Every codebase has a story buried in its Git history — which files are quietly
becoming unmaintainable, which knowledge lives in exactly one person's head, and
which modules are secretly joined at the hip. **RepoLens reads that history and
turns it into a single, self-contained HTML dashboard** you can open in any
browser, commit to a repo, or email to your team.

It runs in one command, has **zero runtime dependencies**, needs **no API keys**,
and works **completely offline**.

```bash
repolens /path/to/repo --open
```

> Think of it as a lightweight, open, hackable take on commercial tools like
> CodeScene — small enough to read in an afternoon, useful enough to run on
> every repo you own.

## ✨ What it surfaces

| Insight | What it answers | How it's computed |
|---|---|---|
| 🔥 **Hotspots** | *Where should I refactor first?* | Geometric mean of **change frequency** × **complexity** (current LOC). A file must be *both* volatile and large to score high. |
| 🔗 **Temporal coupling** | *What changes together that shouldn't?* | Files that co-occur in commits: `shared / min(revs_a, revs_b)`. Reveals hidden architectural dependencies. |
| 🧠 **Knowledge risk** | *What breaks if someone leaves?* | Per-file ownership concentration + a weighted **bus-factor** estimate, flagging single-owner "knowledge islands". |
| 📈 **Activity timeline** | *How has momentum changed?* | Commits per month across the project's entire life. |
| 👥 **Contributors** | *Who shaped this code?* | Commits, lines added/removed, and active span per author. |

## 🚀 Quick start

```bash
# 1. Install (no dependencies beyond Python 3.10+)
git clone https://github.com/akhil/repolens.git
cd repolens
pip install -e .

# 2. Analyse any repository
repolens /path/to/some/repo --open

# Handy options
repolens . -n 2000              # only the most recent 2000 commits
repolens . --since "1 year ago" # time-box the analysis
repolens . --json metrics.json  # also export raw metrics
repolens . --ai                 # add an AI briefing (see below)
```

The result is a single file — `repolens-report.html` — that you can open with no
server and no internet connection.

## 🤖 Optional AI briefing

RepoLens is fully useful without any AI. But if you set an API key, `--ai` adds a
short plain-English briefing ("biggest risk + one recommendation") generated from
the metrics — no extra Python packages required (it uses the standard library).

```bash
export ANTHROPIC_API_KEY=sk-...   # or OPENAI_API_KEY=sk-...
repolens . --ai --open
```

If no key is present, the flag is silently ignored and the rest of the report is
unaffected.

## 🧩 How it works

```
        git log --numstat
               │
        ┌──────▼───────┐
        │  git_reader  │  parse history → Commit / FileChange records
        └──────┬───────┘     (control-char delimited, rename-aware)
        ┌──────▼───────┐
        │   analysis   │  hotspots · coupling · ownership · bus factor
        └──────┬───────┘
        ┌──────▼───────┐
        │    report    │  self-contained HTML + inline SVG charts
        └──────────────┘
```

A few design choices worth calling out:

- **Rename-aware history.** File stats follow a file across `git mv` so churn
  isn't reset every time something is renamed.
- **Geometric mean for hotspots.** Using `sqrt(freq × complexity)` means a file
  has to be *both* frequently changed *and* large to rank — avoiding the trap of
  flagging a huge-but-stable vendored file or a tiny-but-noisy config.
- **Coupling noise control.** Sprawling commits (mass reformats, > 30 files) are
  excluded so they don't manufacture fake coupling between unrelated files.
- **No dependencies, offline first.** The report embeds its own data and draws
  its own SVG charts. Nothing phones home.

## 🛠️ Development

```bash
pip install -e ".[dev]"
pytest -q
```

CI runs the test suite on Python 3.10–3.12 and smoke-tests the CLI on this very
repository (see [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## 🗺️ Roadmap

- [ ] Cyclomatic-complexity proxy beyond raw LOC
- [ ] Author aliasing (merge `Name <a>` / `Name <b>`)
- [ ] Hotspot trend lines (is a file getting healthier or worse?)
- [ ] `--compare` two points in history
- [ ] GitHub Action that comments coupling/hotspot deltas on PRs

## 📄 License

MIT © Akhil — see [LICENSE](LICENSE).
