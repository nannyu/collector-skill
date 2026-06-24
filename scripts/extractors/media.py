#!/usr/bin/env python3
"""
Media downloader - 下载图片和视频到本地
"""

import os
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


def download_file(url: str, out_path: str, timeout: int = 30) -> bool:
    """下载单个文件到本地"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Collector/1.0",
            "Referer": "https://www.google.com/",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with open(out_path, "wb") as f:
                f.write(resp.read())
        return True
    except Exception:
        return False


def _guess_extension(url: str, content_type: str = "") -> str:
    """从 URL 或 Content-Type 猜文件扩展名"""
    # 先从 Content-Type 猜
    ct_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "application/pdf": ".pdf",
    }
    for ct, ext in ct_map.items():
        if ct in content_type:
            return ext

    # 从 URL 路径猜
    path = url.split("?")[0].split("#")[0]
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".mp4", ".webm", ".mov", ".pdf"):
        return ext

    return ".bin"


def _sanitize_filename(name: str) -> str:
    """清理文件名"""
    name = re.sub(r'[^\w一-鿿-]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name[:100] if name else "media"


def download_image(url: str, out_dir: str, index: int = 0, title: str = "") -> dict:
    """
    下载单张图片
    返回 {"url": 原始URL, "local_path": 本地路径, "filename": 文件名, "size": 字节}
    """
    result = {"url": url, "local_path": "", "filename": "", "size": 0}

    if not url or url.startswith("data:"):
        return result

    # 获取 Content-Type
    content_type = ""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Collector/1.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
    except Exception:
        pass

    ext = _guess_extension(url, content_type)
    prefix = _sanitize_filename(title) if title else "img"
    filename = f"{prefix}_{index:03d}{ext}"
    out_path = os.path.join(out_dir, filename)

    if download_file(url, out_path):
        size = os.path.getsize(out_path)
        result.update({
            "local_path": out_path,
            "filename": filename,
            "size": size,
        })

    return result


def download_video(url: str, out_dir: str, title: str = "") -> dict:
    """
    下载视频。优先 yt-dlp（支持 m3u8 等流媒体），fallback 到直接下载
    返回 {"url": 原始URL, "local_path": 本地路径, "filename": 文件名, "size": 字节}
    """
    result = {"url": url, "local_path": "", "filename": "", "size": 0}

    if not url:
        return result

    prefix = _sanitize_filename(title) if title else "video"
    out_template = os.path.join(out_dir, f"{prefix}.%(ext)s")

    # 方式 1: yt-dlp（处理 m3u8、需要解密的流等）
    if _has_ytdlp():
        try:
            cmd = [
                "yt-dlp",
                "--no-warnings",
                "-f", "best",
                "-o", out_template,
                url,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode == 0:
                # 找到下载的文件
                for f in Path(out_dir).glob(f"{prefix}.*"):
                    if f.suffix in (".mp4", ".webm", ".mov", ".mkv", ".flv"):
                        result.update({
                            "local_path": str(f),
                            "filename": f.name,
                            "size": f.stat().st_size,
                        })
                        return result
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # 方式 2: 直接下载
    ext = _guess_extension(url, "")
    if ext == ".bin":
        ext = ".mp4"
    filename = f"{prefix}{ext}"
    out_path = os.path.join(out_dir, filename)

    if download_file(url, out_path, timeout=120):
        size = os.path.getsize(out_path)
        # 过滤太小的文件（可能是错误页面）
        if size > 1024:
            result.update({
                "local_path": out_path,
                "filename": filename,
                "size": size,
            })
        else:
            os.remove(out_path)

    return result


def download_media_batch(
    images: list[dict],
    videos: list[dict],
    out_dir: str,
    title: str = "",
    max_workers: int = 3,
) -> tuple[list[dict], list[dict]]:
    """
    批量下载图片和视频
    返回更新后的 (images, videos) 列表，每项增加 local_path / filename / size
    """
    os.makedirs(out_dir, exist_ok=True)

    # 下载图片（并行）
    updated_images = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for i, img in enumerate(images):
            url = img.get("url", "")
            if url:
                futures[executor.submit(download_image, url, out_dir, i, title)] = img

        for future in as_completed(futures):
            original = futures[future]
            try:
                dl_result = future.result()
                updated_images.append({**original, **dl_result})
            except Exception:
                updated_images.append(original)

    # 按索引排序保持顺序
    updated_images.sort(key=lambda x: x.get("url", ""))

    # 下载视频（串行，文件大）
    updated_videos = []
    for vid in videos:
        url = vid.get("url", "")
        if url:
            try:
                dl_result = download_video(url, out_dir, title)
                updated_videos.append({**vid, **dl_result})
            except Exception:
                updated_videos.append(vid)

    return updated_images, updated_videos


def _has_ytdlp() -> bool:
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
