"""Command-line interface for RepoLens."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .analysis import analyze
from .git_reader import GitError, read_history, repo_name
from .report import analysis_to_dict, write_report


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _print_summary(analysis) -> None:
    print(f"\n  RepoLens · {analysis.repo_name}")
    print("  " + "-" * 40)
    print(f"  Commits analysed : {analysis.total_commits:,}")
    print(f"  Files tracked    : {analysis.total_files:,}")
    print(f"  Contributors     : {len(analysis.contributors):,}")
    print(f"  Bus factor       : {analysis.bus_factor}")
    print(f"  Knowledge islands: {len(analysis.knowledge_islands)}")
    if analysis.hotspots:
        print("\n  Top hotspots:")
        for h in analysis.hotspots[:5]:
            print(f"    • {h.path}  ({h.revisions} changes, score {h.score})")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="repolens",
        description="X-ray vision for any Git repository — hotspots, knowledge "
        "risk, temporal coupling and activity, in one self-contained report.",
    )
    parser.add_argument("repo", nargs="?", default=".", help="path to a Git repository (default: .)")
    parser.add_argument("-o", "--output", default="repolens-report.html", help="HTML report output path")
    parser.add_argument("--json", dest="json_out", metavar="PATH", help="also write raw metrics as JSON")
    parser.add_argument("-n", "--max-commits", type=int, help="limit to the N most recent commits")
    parser.add_argument("--since", help="only commits since this git date (e.g. '2 years ago')")
    parser.add_argument("--ai", action="store_true", help="add an AI narrative (needs ANTHROPIC_API_KEY or OPENAI_API_KEY)")
    parser.add_argument("--open", dest="open_browser", action="store_true", help="open the report in your browser")
    parser.add_argument("--version", action="version", version=f"RepoLens {__version__}")
    args = parser.parse_args(argv)

    repo_path = Path(args.repo)
    try:
        _eprint(f"Reading history of {repo_path} ...")
        commits = read_history(repo_path, max_commits=args.max_commits, since=args.since)
    except GitError as exc:
        _eprint(f"error: {exc}")
        return 2

    if not commits:
        _eprint("error: no commits found (empty repo, or filters excluded everything).")
        return 1

    _eprint(f"Analysing {len(commits):,} commits ...")
    analysis = analyze(commits, repo_path.resolve(), repo_name(repo_path))

    narrative = None
    if args.ai:
        from .ai_narrative import generate_narrative

        _eprint("Requesting AI narrative ...")
        narrative = generate_narrative(analysis)
        if narrative is None:
            _eprint("note: AI narrative skipped (no API key set or request failed).")

    out = write_report(analysis, args.output, narrative, version=__version__)
    _print_summary(analysis)
    print(f"  Report written to: {out}")

    if args.json_out:
        data = analysis_to_dict(analysis, narrative)
        Path(args.json_out).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  JSON written to:   {Path(args.json_out).resolve()}")

    if args.open_browser:
        webbrowser.open(out.as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
