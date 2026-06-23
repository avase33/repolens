"""Read and parse Git history into structured records.

We shell out to `git log` once with a machine-friendly format and `--numstat`,
then parse the stream into commits and per-file changes. Using ASCII control
characters as field/record separators makes the parser robust against commit
messages that contain commas, pipes, or newlines.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

# ASCII control characters used as separators (will never appear in git fields).
RECORD_SEP = "\x1e"  # start of a new commit record
FIELD_SEP = "\x1f"   # separates fields within the commit header line

_PRETTY = (
    RECORD_SEP
    + "%H" + FIELD_SEP   # full hash
    + "%an" + FIELD_SEP  # author name
    + "%ae" + FIELD_SEP  # author email
    + "%ad" + FIELD_SEP  # author date (unix)
    + "%s"               # subject
)


@dataclass
class FileChange:
    """A single file touched by a commit."""

    path: str
    insertions: int
    deletions: int
    binary: bool = False
    renamed_from: str | None = None

    @property
    def churn(self) -> int:
        return self.insertions + self.deletions


@dataclass
class Commit:
    """A single commit and the files it changed."""

    hash: str
    author: str
    email: str
    timestamp: datetime
    subject: str
    files: list[FileChange] = field(default_factory=list)


class GitError(RuntimeError):
    """Raised when git is unavailable or the path is not a repository."""


def _run_git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:  # git not installed
        raise GitError("`git` was not found on your PATH. Please install Git.") from exc
    except subprocess.CalledProcessError as exc:
        raise GitError(
            f"git {' '.join(args)} failed: {exc.stderr.strip() or exc}"
        ) from exc
    return result.stdout


def is_git_repo(repo: Path) -> bool:
    try:
        out = _run_git(repo, "rev-parse", "--is-inside-work-tree")
        return out.strip() == "true"
    except GitError:
        return False


def _parse_numstat_path(raw: str) -> tuple[str, str | None]:
    """Resolve a numstat path field, handling rename notations.

    Git renders renames either as ``old => new`` or with a braced common
    prefix/suffix like ``src/{old => new}/file.py``. We return ``(new_path,
    old_path)``.
    """

    if "=>" not in raw:
        return raw, None

    if "{" in raw and "}" in raw:
        prefix, rest = raw.split("{", 1)
        middle, suffix = rest.split("}", 1)
        old_mid, new_mid = (part.strip() for part in middle.split("=>", 1))
        old = f"{prefix}{old_mid}{suffix}".replace("//", "/")
        new = f"{prefix}{new_mid}{suffix}".replace("//", "/")
        return new, old

    old, new = (part.strip() for part in raw.split("=>", 1))
    return new, old


def _iter_commit_blocks(raw: str) -> Iterator[str]:
    for block in raw.split(RECORD_SEP):
        block = block.strip("\n")
        if block:
            yield block


def parse_log(raw: str) -> list[Commit]:
    """Parse the raw `git log --numstat` output into Commit objects."""

    commits: list[Commit] = []
    for block in _iter_commit_blocks(raw):
        lines = block.split("\n")
        header = lines[0]
        parts = header.split(FIELD_SEP)
        if len(parts) < 5:
            continue
        chash, author, email, ts, subject = parts[0], parts[1], parts[2], parts[3], parts[4]
        try:
            when = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except (ValueError, OverflowError):
            continue

        commit = Commit(hash=chash, author=author, email=email, timestamp=when, subject=subject)
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            ins_raw, del_raw, path_raw = cols
            binary = ins_raw == "-" or del_raw == "-"
            insertions = 0 if binary else int(ins_raw)
            deletions = 0 if binary else int(del_raw)
            path, renamed_from = _parse_numstat_path(path_raw)
            commit.files.append(
                FileChange(
                    path=path,
                    insertions=insertions,
                    deletions=deletions,
                    binary=binary,
                    renamed_from=renamed_from,
                )
            )
        commits.append(commit)
    return commits


def read_history(
    repo_path: str | Path,
    max_commits: int | None = None,
    since: str | None = None,
    include_merges: bool = False,
) -> list[Commit]:
    """Return the commit history for ``repo_path``, newest first.

    Parameters
    ----------
    repo_path: path to a Git working tree.
    max_commits: cap on number of commits (most recent kept).
    since: a git date expression, e.g. ``"2 years ago"``.
    include_merges: keep merge commits (off by default — they add noise).
    """

    repo = Path(repo_path).expanduser().resolve()
    if not repo.exists():
        raise GitError(f"Path does not exist: {repo}")
    if not is_git_repo(repo):
        raise GitError(f"Not a Git repository: {repo}")

    args = ["log", "--numstat", "--date=unix", f"--pretty=format:{_PRETTY}"]
    if not include_merges:
        args.append("--no-merges")
    if max_commits:
        args.append(f"-n{int(max_commits)}")
    if since:
        args.append(f"--since={since}")

    raw = _run_git(repo, *args)
    return parse_log(raw)


def repo_name(repo_path: str | Path) -> str:
    repo = Path(repo_path).expanduser().resolve()
    try:
        top = _run_git(repo, "rev-parse", "--show-toplevel").strip()
        if top:
            return Path(top).name
    except GitError:
        pass
    return repo.name
