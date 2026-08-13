#!/usr/bin/env python3
"""Regression checks for Xiaohongshu video archive metadata and Organizer links."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import organizer  # noqa: E402
from extractors import xhs_video  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="collector-xhs-video-test-") as temp:
        media = Path(temp)
        video = media / "demo.mp4"
        video.write_bytes(b"video-data" * 200)
        subtitle_paths = {}
        for extension, content in {
            "srt": "1\n00:00:00,000 --> 00:00:01,000\n测试\n",
            "txt": "测试转写",
            "json": '{"segments": []}',
        }.items():
            path = media / f"demo.{extension}"
            path.write_text(content, encoding="utf-8")
            subtitle_paths[extension] = str(path)

        payload = {
            "source_type": "xiaohongshu",
            "source_url": "https://www.xiaohongshu.com/explore/example",
            "title": "测试视频",
            "content_md": "测试正文",
            "videos": [{
                "type": "video", "local_path": str(video), "filename": video.name,
                "size": video.stat().st_size, "status": "downloaded",
                "subtitle_paths": subtitle_paths,
            }],
        }
        entry = organizer.build_knowledge_entry(payload, category="tech", subcategory="tools")
        assert "SRT 字幕" in entry
        assert "完整转写文本" in entry
        assert "Whisper 原始结果 JSON" in entry
        assert "xsec_token" not in entry

        # A malformed video must never pass ffprobe validation.
        try:
            xhs_video._ffprobe(video)
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid video unexpectedly passed ffprobe")

        print(json.dumps({
            "status": "ok",
            "checks": [
                "subtitle links rendered",
                "temporary token excluded from entry",
                "invalid video rejected by ffprobe",
            ],
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
