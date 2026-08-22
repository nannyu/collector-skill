#!/usr/bin/env python3
"""Optional Agent Reach adapters for platform-native collection.

The adapter never imports browser cookies, starts containers, or performs login.
It only uses already-installed public/read-only Agent Reach backends and returns
the Collector's normalized extraction shape.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

_TIMEOUT_SECONDS = 25
_USER_AGENT = "agent-reach-collector/1.0"


def _run(command: list[str], timeout: int = _TIMEOUT_SECONDS) -> str | None:
    """Run a read-only local backend and return stdout only on success."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 and result.stdout.strip() else None


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _iso_from_epoch(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def agent_reach_available() -> bool:
    """Return whether the Agent Reach command is installed and responsive."""
    executable = shutil.which("agent-reach")
    return bool(executable and _run([executable, "version"], timeout=5))


def supported_platform(url: str) -> str | None:
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    if host in {"youtu.be", "www.youtu.be"} or host.endswith("youtube.com"):
        return "youtube"
    if host.endswith("bilibili.com") or host.endswith("b23.tv"):
        return "bilibili"
    if host.endswith("github.com"):
        return "github"
    if host.endswith("v2ex.com"):
        return "v2ex"
    if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}:
        return "twitter"
    return None


def _base_metadata(platform: str, backend: str) -> dict[str, str]:
    return {
        "fetcher": "agent-reach",
        "agent_reach_platform": platform,
        "agent_reach_backend": backend,
    }


def _extract_github(url: str) -> dict | None:
    match = re.match(r"https?://(?:www\.)?github\.com/([^/]+)/([^/?#]+)", url, re.I)
    if not match:
        return None
    owner, repo = match.group(1), match.group(2).removesuffix(".git")
    repo_id = f"{owner}/{repo}"
    raw = _run([
        "gh", "api", f"repos/{repo_id}",
        "--jq", "{full_name,description,html_url,homepage,language,license,topics,stargazers_count,forks_count,open_issues_count,default_branch,updated_at}",
    ])
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    readme = ""
    readme_raw = _run(["gh", "api", f"repos/{repo_id}/readme", "--jq", ".content"])
    if readme_raw:
        try:
            readme = base64.b64decode(re.sub(r"\s+", "", readme_raw)).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            pass

    title = data.get("full_name") or repo_id
    lines = [f"# {title}"]
    if data.get("description"):
        lines += ["", str(data["description"])]
    lines += [
        "", "## Repository metadata",
        f"- URL: {data.get('html_url') or url}",
        f"- Primary language: {data.get('language') or 'N/A'}",
        f"- Stars: {data.get('stargazers_count', 0)}",
        f"- Forks: {data.get('forks_count', 0)}",
        f"- Open issues: {data.get('open_issues_count', 0)}",
    ]
    if data.get("homepage"):
        lines.append(f"- Homepage: {data['homepage']}")
    if data.get("topics"):
        lines.append("- Topics: " + ", ".join(map(str, data["topics"])))
    if readme:
        lines += ["", "## README", "", readme]
    return {
        "title": title,
        "content_md": "\n".join(lines).strip(),
        "author": owner,
        "published_at": data.get("updated_at", ""),
        "images": [],
        "videos": [],
        "metadata": _base_metadata("github", "gh-api"),
    }


def _extract_v2ex(url: str) -> dict | None:
    match = re.search(r"/t/(\d+)", urllib.parse.urlparse(url).path)
    if not match:
        return None
    topic_id = match.group(1)
    try:
        topics = _get_json(f"https://www.v2ex.com/api/topics/show.json?id={topic_id}")
        topic = topics[0] if isinstance(topics, list) and topics else {}
        replies = _get_json(f"https://www.v2ex.com/api/replies/show.json?topic_id={topic_id}&page=1")
    except Exception:
        return None
    if not isinstance(topic, dict) or not topic.get("title"):
        return None

    member = topic.get("member") or {}
    node = topic.get("node") or {}
    lines = [f"# {topic['title']}", "", topic.get("content", "")]
    if node.get("title"):
        lines += ["", f"Node: {node['title']}"]
    if replies:
        lines += ["", "## Comments"]
        for reply in replies:
            reply_member = reply.get("member") or {}
            author = reply_member.get("username") or "unknown"
            body = (reply.get("content") or "").strip()
            if body:
                lines += ["", f"### {author}", body]
    return {
        "title": topic["title"],
        "content_md": "\n".join(lines).strip(),
        "author": member.get("username", ""),
        "published_at": _iso_from_epoch(topic.get("created")),
        "images": [],
        "videos": [],
        "metadata": {
            **_base_metadata("v2ex", "v2ex-public-api"),
            "comments_expected": topic.get("replies", 0),
            "comments_collected": len(replies) if isinstance(replies, list) else 0,
        },
    }


def _extract_video(url: str, platform: str) -> dict | None:
    raw = _run([
        "yt-dlp", "--dump-single-json", "--skip-download", "--no-warnings", url,
    ])
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    title = data.get("title") or ""
    description = data.get("description") or ""
    if not title and not description:
        return None
    lines = [f"# {title}" if title else "# Video", "", description]
    if data.get("channel") or data.get("uploader"):
        lines += ["", f"Channel: {data.get('channel') or data.get('uploader')}"]
    if data.get("duration") is not None:
        lines.append(f"Duration seconds: {data['duration']}")
    images = []
    if data.get("thumbnail"):
        images.append({"url": data["thumbnail"], "alt": "video thumbnail", "ocr_text": ""})
    return {
        "title": title,
        "content_md": "\n".join(lines).strip(),
        "author": data.get("channel") or data.get("uploader") or "",
        "published_at": data.get("upload_date") or data.get("release_date") or "",
        "images": images,
        "videos": [],
        "metadata": {
            **_base_metadata(platform, "yt-dlp"),
            "video_url": url,
            "video_status": "metadata_only",
            "transcript_status": "not_requested",
        },
    }


def _extract_twitter(url: str) -> dict | None:
    raw = _run(["xreach", "tweet", url, "--json"])
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    # xreach output has changed across releases; retain the stable text-like fields.
    text = data.get("text") or data.get("full_text") or data.get("content") or ""
    if not text:
        return None
    author = data.get("author") or data.get("username") or ""
    title = f"X post by {author}" if author else "X post"
    return {
        "title": title,
        "content_md": f"# {title}\n\n{text}",
        "author": str(author),
        "published_at": str(data.get("created_at") or ""),
        "images": [],
        "videos": [],
        "metadata": _base_metadata("twitter", "xreach"),
    }


def extract_via_agent_reach(url: str) -> dict | None:
    """Extract a supported URL with an installed, read-only Agent Reach backend."""
    if not agent_reach_available():
        return None
    platform = supported_platform(url)
    if platform == "github":
        return _extract_github(url)
    if platform == "v2ex":
        return _extract_v2ex(url)
    if platform in {"youtube", "bilibili"}:
        return _extract_video(url, platform)
    if platform == "twitter":
        return _extract_twitter(url)
    return None
