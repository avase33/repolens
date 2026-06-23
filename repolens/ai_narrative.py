"""Optional AI narrative layer.

RepoLens works fully offline. If an API key is present in the environment, this
module turns the computed metrics into a short plain-English briefing. It uses
only the Python standard library (urllib) so there are no extra dependencies.

Supported providers (auto-detected):
* Anthropic  — env ANTHROPIC_API_KEY
* OpenAI     — env OPENAI_API_KEY
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .analysis import Analysis

_TIMEOUT = 40


def _facts(analysis: Analysis) -> str:
    top_hot = ", ".join(f"{h.path} ({h.revisions} changes)" for h in analysis.hotspots[:5])
    top_couple = "; ".join(
        f"{c.file_a} <-> {c.file_b} ({int(c.degree*100)}%)" for c in analysis.couplings[:4]
    )
    islands = ", ".join(f"{h.path} (owner: {h.main_author})" for h in analysis.knowledge_islands[:4])
    top_authors = ", ".join(f"{c.name} ({c.commits})" for c in analysis.contributors[:4])
    return (
        f"Repository: {analysis.repo_name}\n"
        f"Commits analysed: {analysis.total_commits}\n"
        f"Files tracked: {analysis.total_files}\n"
        f"Contributors: {len(analysis.contributors)} (top: {top_authors})\n"
        f"Estimated bus factor: {analysis.bus_factor}\n"
        f"Top hotspots: {top_hot or 'none'}\n"
        f"Strongest temporal coupling: {top_couple or 'none'}\n"
        f"Knowledge islands (single-owner hot files): {islands or 'none'}\n"
    )


_PROMPT = (
    "You are a principal engineer reviewing a codebase health report. Using ONLY "
    "the metrics below, write a concise briefing (max 150 words) for an engineering "
    "lead. Cover: overall health, the biggest risk, and one concrete recommendation. "
    "Be specific and reference file names. Do not invent metrics.\n\n"
)


def _call_anthropic(key: str, prompt: str) -> str:
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(
            {
                "model": os.environ.get("REPOLENS_MODEL", "claude-3-5-haiku-latest"),
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = json.loads(resp.read())
    return body["content"][0]["text"].strip()


def _call_openai(key: str, prompt: str) -> str:
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(
            {
                "model": os.environ.get("REPOLENS_MODEL", "gpt-4o-mini"),
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        body = json.loads(resp.read())
    return body["choices"][0]["message"]["content"].strip()


def generate_narrative(analysis: Analysis) -> str | None:
    """Return an AI briefing, or None if no provider is configured/reachable."""

    prompt = _PROMPT + _facts(analysis)
    try:
        if os.environ.get("ANTHROPIC_API_KEY"):
            return _call_anthropic(os.environ["ANTHROPIC_API_KEY"], prompt)
        if os.environ.get("OPENAI_API_KEY"):
            return _call_openai(os.environ["OPENAI_API_KEY"], prompt)
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError):
        return None
    return None
