"""Unit tests for the analysis engine and git-log parser."""

from datetime import datetime, timezone
from pathlib import Path

from repolens.analysis import (
    analyze,
    build_file_stats,
    compute_bus_factor,
    compute_coupling,
    compute_hotspots,
)
from repolens.git_reader import Commit, FileChange, parse_log

FIELD = "\x1f"
REC = "\x1e"


def _commit(h, author, ts, files):
    return Commit(
        hash=h,
        author=author,
        email=f"{author}@x.com",
        timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
        subject="msg",
        files=[FileChange(p, i, d) for (p, i, d) in files],
    )


def test_parse_log_basic():
    raw = (
        f"{REC}abc123{FIELD}Alice{FIELD}alice@x.com{FIELD}1700000000{FIELD}Add feature\n"
        "10\t2\tsrc/app.py\n"
        "-\t-\tlogo.png\n"
        f"{REC}def456{FIELD}Bob{FIELD}bob@x.com{FIELD}1700100000{FIELD}Fix bug\n"
        "1\t1\tsrc/app.py\n"
    )
    commits = parse_log(raw)
    assert len(commits) == 2
    assert commits[0].author == "Alice"
    assert commits[0].files[0].path == "src/app.py"
    assert commits[0].files[0].insertions == 10
    assert commits[0].files[1].binary is True


def test_parse_log_rename():
    raw = (
        f"{REC}aaa{FIELD}Alice{FIELD}a@x.com{FIELD}1700000000{FIELD}rename\n"
        "3\t1\tsrc/{old => new}/m.py\n"
    )
    commits = parse_log(raw)
    fc = commits[0].files[0]
    assert fc.path == "src/new/m.py"
    assert fc.renamed_from == "src/old/m.py"


def test_file_stats_and_hotspots(tmp_path: Path):
    commits = [
        _commit("c1", "Alice", 1700000000, [("a.py", 10, 0), ("b.py", 5, 0)]),
        _commit("c2", "Alice", 1700100000, [("a.py", 4, 2)]),
        _commit("c3", "Bob", 1700200000, [("a.py", 1, 1), ("b.py", 2, 0)]),
    ]
    stats = build_file_stats(commits, tmp_path)
    assert stats["a.py"].revisions == 3
    assert stats["b.py"].revisions == 2
    # a.py touched by 2 authors, Alice contributed the most.
    assert stats["a.py"].main_author == "Alice"
    assert stats["a.py"].num_authors == 2

    hotspots = compute_hotspots(stats)
    # a.py changes most -> should rank first.
    assert hotspots[0].path == "a.py"


def test_coupling_detects_co_change(tmp_path: Path):
    # x.py and y.py always change together; z.py is independent.
    commits = []
    for i in range(6):
        commits.append(_commit(f"c{i}", "Alice", 1700000000 + i * 1000, [("x.py", 1, 0), ("y.py", 1, 0)]))
    commits.append(_commit("cz", "Bob", 1700900000, [("z.py", 1, 0)]))

    stats = build_file_stats(commits, tmp_path)
    couplings = compute_coupling(commits, stats, min_shared=3, min_degree=0.5)
    assert len(couplings) == 1
    c = couplings[0]
    assert {c.file_a, c.file_b} == {"x.py", "y.py"}
    assert c.shared == 6
    assert c.degree == 1.0


def test_bus_factor_single_owner(tmp_path: Path):
    commits = [_commit(f"c{i}", "Solo", 1700000000 + i, [("a.py", 5, 0)]) for i in range(5)]
    stats = build_file_stats(commits, tmp_path)
    assert compute_bus_factor(stats) == 1


def test_analyze_end_to_end(tmp_path: Path):
    commits = [
        _commit("c1", "Alice", 1700000000, [("a.py", 10, 0)]),
        _commit("c2", "Bob", 1700100000, [("b.py", 8, 1)]),
    ]
    result = analyze(commits, tmp_path, "demo")
    assert result.repo_name == "demo"
    assert result.total_commits == 2
    assert result.total_files == 2
    assert len(result.contributors) == 2
    assert result.monthly_activity  # at least one month bucket
