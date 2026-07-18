#!/usr/bin/env python3
from __future__ import annotations
"""
Media downloader - 下载图片和视频到本地。

微信图片注意事项：mmbiz.qpic.cn 对 Google Referer 可能返回 140x140
缩略图，因此默认不发送第三方 Referer，并对下载结果做真实图片校验。
"""

import imghdr
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".flv"}


def _is_wechat_image(url: str) -> bool:
    host = url.lower()
    return "mmbiz.qpic.cn" in host or "mmbiz.qpic.cn" in host


def _guess_extension(url: str, content_type: str = "", body: bytes = b"") -> str:
    """从响应 Content-Type、文件内容或 URL 猜文件扩展名。"""
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    ct_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "application/pdf": ".pdf",
    }
    if ct in ct_map:
        return ct_map[ct]

    if body:
        detected = imghdr.what(None, h=body[:4096])
        if detected == "jpeg":
            return ".jpg"
        if detected in {"png", "gif", "webp"}:
            return f".{detected}"

    path = url.split("?")[0].split("#")[0]
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | {".pdf"}:
        return ext
    return ".bin"


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[^\w一-鿿-]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name[:100] if name else "media"


def _image_info(body: bytes) -> tuple[str, int, int]:
    """返回 (格式, 宽, 高)，无法识别时返回空值。"""
    try:
        from PIL import Image
        from io import BytesIO
        with Image.open(BytesIO(body)) as im:
            return im.format or "", int(im.width), int(im.height)
    except Exception:
        return "", 0, 0


def _validate_image(body: bytes, url: str) -> tuple[bool, dict]:
    """拒绝 HTTP 200 但实际为缩略图/错误响应的图片。"""
    fmt, width, height = _image_info(body)
    info = {
        "content_size": len(body),
        "detected_format": fmt.lower() if fmt else "",
        "width": width,
        "height": height,
    }
    if not fmt or width <= 0 or height <= 0:
        info["error"] = "响应不是可识别的图片"
        return False, info

    # 当前已验证的微信错误响应是固定的 140x140、约 2KB JPEG 缩略图。
    # 不能笼统拒绝所有小图：文章中的图标、二维码和徽标可能合法地小于 160px。
    if _is_wechat_image(url) and width == 140 and height == 140 and len(body) <= 5000:
        info["error"] = f"疑似微信错误缩略图（{width}x{height}，{len(body)} bytes）"
        return False, info

    return True, info


def _request_headers(url: str, referer: str = "") -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Collector/1.1",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    # 不使用 Google 等第三方 Referer；微信文章 Referer 可选且更合理。
    if referer and "google.com" not in referer.lower():
        headers["Referer"] = referer
    return headers


def _fetch_bytes(url: str, timeout: int = 30, referer: str = "") -> tuple[bytes, str, int]:
    req = urllib.request.Request(url, headers=_request_headers(url, referer))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", ""), int(getattr(resp, "status", 200) or 200)


def download_file(url: str, out_path: str, timeout: int = 30, referer: str = "") -> bool:
    """下载单个文件到本地。图片调用方会在此之前完成内容校验。"""
    try:
        body, _, status = _fetch_bytes(url, timeout=timeout, referer=referer)
        if status < 200 or status >= 300:
            return False
        Path(out_path).write_bytes(body)
        return True
    except Exception:
        return False


def download_image(url: str, out_dir: str, index: int = 0, title: str = "", referer: str = "") -> dict:
    """下载并校验单张图片。"""
    result = {
        "url": url,
        "local_path": "",
        "filename": "",
        "size": 0,
        "status": "failed",
        "error": "",
    }
    if not url or url.startswith("data:"):
        result["error"] = "空 URL 或 data URL"
        return result

    try:
        body, content_type, status = _fetch_bytes(url, timeout=30, referer=referer)
        result["http_status"] = status
        result["content_type"] = content_type
        if status < 200 or status >= 300:
            result["error"] = f"HTTP {status}"
            return result

        valid, info = _validate_image(body, url)
        result.update({k: v for k, v in info.items() if k != "error"})
        if not valid:
            result["error"] = info.get("error", "图片校验失败")
            return result

        ext = _guess_extension(url, content_type, body)
        prefix = _sanitize_filename(title) if title else "img"
        filename = f"{prefix}_{index:03d}{ext}"
        out_path = os.path.join(out_dir, filename)
        Path(out_path).write_bytes(body)
        result.update({
            "local_path": out_path,
            "filename": filename,
            "size": len(body),
            "status": "downloaded",
            "error": "",
        })
    except Exception as exc:
        result["error"] = str(exc)
    return result


def download_video(url: str, out_dir: str, title: str = "", referer: str = "") -> dict:
    """下载视频。优先 yt-dlp，fallback 到直接下载。"""
    result = {"url": url, "local_path": "", "filename": "", "size": 0, "status": "failed", "error": ""}
    if not url:
        result["error"] = "空 URL"
        return result

    prefix = _sanitize_filename(title) if title else "video"
    out_template = os.path.join(out_dir, f"{prefix}.%(ext)s")

    if _has_ytdlp():
        try:
            cmd = ["yt-dlp", "--no-warnings", "-f", "best", "-o", out_template, url]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode == 0:
                for f in Path(out_dir).glob(f"{prefix}.*"):
                    if f.suffix in VIDEO_EXTENSIONS:
                        result.update({"local_path": str(f), "filename": f.name, "size": f.stat().st_size, "status": "downloaded"})
                        return result
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            result["error"] = str(exc)

    try:
        body, content_type, status = _fetch_bytes(url, timeout=120, referer=referer)
        if status < 200 or status >= 300 or len(body) <= 1024:
            result["error"] = f"HTTP {status} 或响应过小"
            return result
        ext = _guess_extension(url, content_type, body)
        if ext == ".bin":
            ext = ".mp4"
        filename = f"{prefix}{ext}"
        out_path = os.path.join(out_dir, filename)
        Path(out_path).write_bytes(body)
        result.update({"local_path": out_path, "filename": filename, "size": len(body), "status": "downloaded", "error": ""})
    except Exception as exc:
        result["error"] = str(exc)
    return result


def download_media_batch(images: list[dict], videos: list[dict], out_dir: str, title: str = "", max_workers: int = 3, referer: str = "") -> tuple[list[dict], list[dict]]:
    """批量下载图片和视频，保留原始顺序并返回每项的校验状态。"""
    os.makedirs(out_dir, exist_ok=True)

    updated_images: List[Optional[dict]] = [None] * len(images)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_image, img.get("url", ""), out_dir, i, title, referer): (i, img)
            for i, img in enumerate(images)
            if img.get("url")
        }
        for future in as_completed(futures):
            i, original = futures[future]
            try:
                updated_images[i] = {**original, **future.result()}
            except Exception as exc:
                updated_images[i] = {**original, "status": "failed", "error": str(exc), "local_path": "", "filename": "", "size": 0}
    for i, item in enumerate(updated_images):
        if item is None:
            updated_images[i] = {**images[i], "status": "failed", "error": "没有可下载的 URL", "local_path": "", "filename": "", "size": 0}

    updated_videos = []
    for vid in videos:
        url = vid.get("url", "")
        if not url:
            updated_videos.append({**vid, "status": "failed", "error": "空 URL"})
            continue
        try:
            updated_videos.append({**vid, **download_video(url, out_dir, title, referer)})
        except Exception as exc:
            updated_videos.append({**vid, "status": "failed", "error": str(exc), "local_path": "", "filename": "", "size": 0})
    final_images = [item if item is not None else {"status": "failed", "error": "内部结果为空", "local_path": "", "filename": "", "size": 0} for item in updated_images]
    return final_images, updated_videos


def _has_ytdlp() -> bool:
    try:
        proc = subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=5)
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
