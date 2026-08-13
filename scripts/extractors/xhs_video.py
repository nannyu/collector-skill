#!/usr/bin/env python3
"""小红书视频：专用浏览器解析详情页，再用 yt-dlp 下载与 Whisper 转写。

不导出 Cookie；浏览器返回的临时详情 URL 只在 yt-dlp 子进程中使用，写入
archive/raw.json 前会被清除。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

XHS_BROWSER_EXTRACTOR = Path.home() / ".hermes" / "scripts" / "xhs-browser" / "xhs_extract_note.mjs"
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".flv"}


def _safe_name(title: str) -> str:
    name = re.sub(r"[^\w一-鿿-]", "_", title or "xiaohongshu_video")
    return re.sub(r"_+", "_", name).strip("_")[:100] or "xiaohongshu_video"


def _command_available(command: str) -> bool:
    return shutil.which(command) is not None


def _run_json(command: list[str], timeout: int) -> dict[str, Any]:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
        raise RuntimeError(detail[0] if detail else f"command failed: {command[0]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON from {command[0]}: {exc}") from exc


def resolve_xhs_detail(url: str) -> dict[str, Any]:
    """在专用、已登录浏览器中解析短链到完整详情页。"""
    if not XHS_BROWSER_EXTRACTOR.is_file():
        raise RuntimeError(f"小红书专用浏览器解析器不存在: {XHS_BROWSER_EXTRACTOR}")
    if not _command_available("node"):
        raise RuntimeError("未安装 Node.js，无法调用小红书专用浏览器")
    result = _run_json(["node", str(XHS_BROWSER_EXTRACTOR), url], timeout=60)
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "小红书详情页解析失败")
    href = str(result.get("href") or "")
    title = str(result.get("title") or "")
    if "xiaohongshu.com/" not in href or not title:
        raise RuntimeError("专用浏览器未取得可验证的小红书详情页标题或地址")
    return result


def _ffprobe(path: Path) -> dict[str, Any]:
    if not _command_available("ffprobe"):
        raise RuntimeError("未安装 ffprobe，拒绝将未校验的视频标记为已保存")
    data = _run_json([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size,format_name:stream=codec_type,codec_name,width,height",
        "-of", "json", str(path),
    ], timeout=45)
    fmt = data.get("format") or {}
    duration = float(fmt.get("duration") or 0)
    size = int(fmt.get("size") or 0)
    has_video = any(s.get("codec_type") == "video" for s in data.get("streams") or [])
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams") or [])
    if duration <= 0 or size <= 1024 or not has_video:
        raise RuntimeError("ffprobe 校验失败：缺少有效视频流、时长或文件大小")
    return {"duration_seconds": duration, "size": size, "format": fmt.get("format_name", ""), "has_audio": has_audio, "streams": data.get("streams", [])}


def _transcribe(video_path: Path, out_dir: Path) -> dict[str, str]:
    if not _command_available("whisper"):
        raise RuntimeError("未安装 Whisper，无法生成字幕")
    # Whisper CLI outputs every requested format alongside the source basename.
    proc = subprocess.run([
        "whisper", str(video_path), "--language", "Chinese", "--model", "turbo",
        "--output_dir", str(out_dir), "--output_format", "all", "--verbose", "False",
        "--initial_prompt", "个人知识管理、播客、AI、知识库、知识资产、聊天框。",
    ], capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
        raise RuntimeError(detail[0] if detail else "Whisper 转写失败")
    base = video_path.stem
    expected = {"srt": out_dir / f"{base}.srt", "txt": out_dir / f"{base}.txt", "json": out_dir / f"{base}.json"}
    missing = [kind for kind, path in expected.items() if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError(f"Whisper 未生成有效文件: {', '.join(missing)}")
    return {kind: str(path) for kind, path in expected.items()}


def download_and_transcribe_xhs_video(resolved: dict[str, Any], out_dir: str) -> dict[str, Any]:
    """下载、ffprobe 校验、转写一个已由浏览器验证的详情页视频。"""
    if not _command_available("yt-dlp"):
        raise RuntimeError("未安装 yt-dlp，无法下载小红书视频")
    target_url = str(resolved["href"])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prefix = _safe_name(str(resolved.get("title") or ""))
    template = str(out / f"{prefix}.%(ext)s")
    proc = subprocess.run([
        "yt-dlp", "--no-warnings", "--no-progress", "--no-playlist", "-f", "best",
        "-o", template, target_url,
    ], capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
        raise RuntimeError(detail[0] if detail else "yt-dlp 下载失败")
    candidates = [p for p in out.glob(f"{prefix}.*") if p.suffix.lower() in VIDEO_EXTENSIONS]
    if not candidates:
        raise RuntimeError("yt-dlp 未产生视频文件")
    video_path = max(candidates, key=lambda p: p.stat().st_size)
    probe = _ffprobe(video_path)
    transcript = _transcribe(video_path, out)
    return {
        "type": "video", "local_path": str(video_path), "filename": video_path.name,
        "size": video_path.stat().st_size, "status": "downloaded", "validation": probe,
        "subtitle_paths": transcript, "transcript_status": "complete",
        # Do not persist resolved href: it contains a short-lived xsec_token.
        "download_method": "dedicated_browser_detail_then_ytdlp",
    }
