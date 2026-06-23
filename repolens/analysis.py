"""The analysis engine.

Turns a list of commits into the metrics that power RepoLens:

* **Hotspots** — files that change often *and* are large/complex. These are the
  riskiest places in a codebase: high churn meeting high complexity.
* **Knowledge risk** — per-file ownership concentration and a repo-level bus
  factor estimate. Highlights "knowledge islands" only one person understands.
* **Temporal coupling** — pairs of files that keep changing in the same commit.
  Often reveals hidden architectural dependencies.
* **Timeline** — commit and contributor activity over time.

All metrics are computed from history alone; current line counts (used as a
complexity proxy for hotspots) are read from disk when available.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .git_reader import Commit

# File extensions we treat as source code when measuring complexity on disk.
_CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".rs", ".rb",
    ".php", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift", ".scala",
    ".sh", ".sql", ".css", ".scss", ".html", ".vue", ".dart", ".m", ".mm",
    ".lua", ".r", ".jl", ".ex", ".exs", ".clj",
}


@dataclass
class FileStat:
    path: str
    revisions: int = 0
    insertions: int = 0
    deletions: int = 0
    last_change: datetime | None = None
    first_change: datetime | None = None
    authors: Counter = field(default_factory=Counter)  # author -> lines contributed
    loc: int = 0  # current lines on disk (0 if deleted/unknown)

    @property
    def churn(self) -> int:
        return self.insertions + self.deletions

    @property
    def main_author(self) -> str | None:
        return self.authors.most_common(1)[0][0] if self.authors else None

    @property
    def ownership(self) -> float:
        """Share of contribution held by the main author (0..1)."""
        if not self.authors:
            return 0.0
        total = sum(self.authors.values())
        return self.authors.most_common(1)[0][1] / total if total else 0.0

    @property
    def num_authors(self) -> int:
        return len(self.authors)


@dataclass
class Hotspot:
    path: str
    revisions: int
    loc: int
    score: float
    ownership: float
    main_author: str | None
    num_authors: int


@dataclass
class Coupling:
    file_a: str
    file_b: str
    shared: int  # commits where both changed
    degree: float  # 0..1 coupling strength


@dataclass
class Contributor:
    name: str
    commits: int
    insertions: int
    deletions: int
    first: datetime
    last: datetime
    files_touched: int

    @property
    def churn(self) -> int:
        return self.insertions + self.deletions


@dataclass
class Analysis:
    repo_name: str
    generated_at: datetime
    total_commits: int
    total_files: int
    first_commit: datetime | None
    last_commit: datetime | None
    hotspots: list[Hotspot]
    couplings: list[Coupling]
    contributors: list[Contributor]
    monthly_activity: list[tuple[str, int]]  # (YYYY-MM, commits)
    bus_factor: int
    knowledge_islands: list[Hotspot]  # high-ownership, high-churn files


def _count_lines(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    if path.suffix.lower() not in _CODE_EXTS:
        return 0
    try:
        with path.open("rb") as fh:
            return sum(1 for _ in fh)
    except (OSError, ValueError):
        return 0


def _normalize(values: list[float]) -> list[float]:
    """Scale a list of values to 0..1 using log dampening for skewed data."""
    if not values:
        return []
    logged = [math.log1p(v) for v in values]
    lo, hi = min(logged), max(logged)
    if hi == lo:
        return [1.0 for _ in logged]
    return [(v - lo) / (hi - lo) for v in logged]


def build_file_stats(commits: list[Commit], repo_root: Path) -> dict[str, FileStat]:
    stats: dict[str, FileStat] = {}
    # Track renames so churn follows a file across its name changes.
    rename_map: dict[str, str] = {}

    for commit in reversed(commits):  # oldest -> newest for sensible first/last
        for change in commit.files:
            path = rename_map.get(change.path, change.path)
            if change.renamed_from:
                # Carry forward existing stats from the old name.
                old = rename_map.get(change.renamed_from, change.renamed_from)
                rename_map[change.renamed_from] = path
                if old in stats and path not in stats:
                    stats[path] = stats.pop(old)
                    stats[path].path = path

            fs = stats.setdefault(path, FileStat(path=path))
            fs.revisions += 1
            fs.insertions += change.insertions
            fs.deletions += change.deletions
            fs.authors[commit.author] += change.churn or 1
            if fs.first_change is None or commit.timestamp < fs.first_change:
                fs.first_change = commit.timestamp
            if fs.last_change is None or commit.timestamp > fs.last_change:
                fs.last_change = commit.timestamp

    for path, fs in stats.items():
        fs.loc = _count_lines(repo_root / path)
    return stats


def compute_hotspots(stats: dict[str, FileStat], limit: int = 40) -> list[Hotspot]:
    """Rank files by change-frequency × complexity.

    Complexity uses current LOC when available, otherwise total churn as a
    fallback so that recently deleted-but-volatile files still surface.
    """

    items = list(stats.values())
    revs = _normalize([s.revisions for s in items])
    complexity_raw = [s.loc if s.loc else s.churn for s in items]
    comp = _normalize(complexity_raw)

    hotspots: list[Hotspot] = []
    for s, r, c in zip(items, revs, comp):
        score = math.sqrt(r * c)  # geometric mean: both must be high
        hotspots.append(
            Hotspot(
                path=s.path,
                revisions=s.revisions,
                loc=s.loc,
                score=round(score, 4),
                ownership=round(s.ownership, 3),
                main_author=s.main_author,
                num_authors=s.num_authors,
            )
        )
    hotspots.sort(key=lambda h: h.score, reverse=True)
    return hotspots[:limit]


def compute_coupling(
    commits: list[Commit],
    stats: dict[str, FileStat],
    min_shared: int = 4,
    min_degree: float = 0.4,
    limit: int = 30,
) -> list[Coupling]:
    """Find pairs of files that frequently change together.

    degree = shared_changes / min(revisions_a, revisions_b)
    """

    pair_counts: Counter = Counter()
    for commit in commits:
        paths = sorted({f.path for f in commit.files if not f.binary})
        # Ignore sprawling commits (e.g. mass reformat) that distort coupling.
        if 2 <= len(paths) <= 30:
            for a, b in itertools.combinations(paths, 2):
                pair_counts[(a, b)] += 1

    couplings: list[Coupling] = []
    for (a, b), shared in pair_counts.items():
        if shared < min_shared:
            continue
        ra = stats[a].revisions if a in stats else shared
        rb = stats[b].revisions if b in stats else shared
        denom = min(ra, rb) or 1
        degree = shared / denom
        if degree >= min_degree:
            couplings.append(Coupling(a, b, shared, round(degree, 3)))

    couplings.sort(key=lambda c: (c.degree, c.shared), reverse=True)
    return couplings[:limit]


def compute_contributors(commits: list[Commit]) -> list[Contributor]:
    agg: dict[str, dict] = defaultdict(
        lambda: {"commits": 0, "ins": 0, "dels": 0, "first": None, "last": None, "files": set()}
    )
    for commit in commits:
        a = agg[commit.author]
        a["commits"] += 1
        for f in commit.files:
            a["ins"] += f.insertions
            a["dels"] += f.deletions
            a["files"].add(f.path)
        if a["first"] is None or commit.timestamp < a["first"]:
            a["first"] = commit.timestamp
        if a["last"] is None or commit.timestamp > a["last"]:
            a["last"] = commit.timestamp

    contributors = [
        Contributor(
            name=name,
            commits=d["commits"],
            insertions=d["ins"],
            deletions=d["dels"],
            first=d["first"],
            last=d["last"],
            files_touched=len(d["files"]),
        )
        for name, d in agg.items()
    ]
    contributors.sort(key=lambda c: c.commits, reverse=True)
    return contributors


def compute_bus_factor(stats: dict[str, FileStat], threshold: float = 0.5) -> int:
    """Estimate how many people hold the majority of code knowledge.

    We weight each file's primary-author ownership by the file's size and count
    the smallest set of authors covering ``threshold`` of total weighted
    ownership.
    """

    owner_weight: Counter = Counter()
    total = 0.0
    for s in stats.values():
        weight = s.loc or s.churn or 1
        if s.main_author:
            owner_weight[s.main_author] += weight * s.ownership
            total += weight * s.ownership
    if total == 0:
        return len(owner_weight) or 1

    cumulative = 0.0
    count = 0
    for _author, w in owner_weight.most_common():
        cumulative += w
        count += 1
        if cumulative / total >= threshold:
            break
    return max(count, 1)


def compute_monthly_activity(commits: list[Commit]) -> list[tuple[str, int]]:
    counts: Counter = Counter()
    for commit in commits:
        counts[commit.timestamp.strftime("%Y-%m")] += 1
    return sorted(counts.items())


def find_knowledge_islands(
    stats: dict[str, FileStat], min_ownership: float = 0.8, min_revisions: int = 5, limit: int = 15
) -> list[Hotspot]:
    islands = [
        Hotspot(
            path=s.path,
            revisions=s.revisions,
            loc=s.loc,
            score=round(s.ownership, 3),
            ownership=round(s.ownership, 3),
            main_author=s.main_author,
            num_authors=s.num_authors,
        )
        for s in stats.values()
        if s.ownership >= min_ownership and s.revisions >= min_revisions and s.num_authors == 1
    ]
    islands.sort(key=lambda h: (h.revisions, h.loc), reverse=True)
    return islands[:limit]


def analyze(commits: list[Commit], repo_root: Path, name: str) -> Analysis:
    stats = build_file_stats(commits, repo_root)
    timestamps = [c.timestamp for c in commits]
    return Analysis(
        repo_name=name,
        generated_at=datetime.now(),
        total_commits=len(commits),
        total_files=len(stats),
        first_commit=min(timestamps) if timestamps else None,
        last_commit=max(timestamps) if timestamps else None,
        hotspots=compute_hotspots(stats),
        couplings=compute_coupling(commits, stats),
        contributors=compute_contributors(commits),
        monthly_activity=compute_monthly_activity(commits),
        bus_factor=compute_bus_factor(stats),
        knowledge_islands=find_knowledge_islands(stats),
    )
