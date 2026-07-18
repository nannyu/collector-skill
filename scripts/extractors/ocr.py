#!/usr/bin/env python3
from __future__ import annotations
"""
OCR helper - 对图片 URL 列表运行文字识别
优先 pytesseract，fallback 到跳过
"""

import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path


def _check_tesseract() -> bool:
    try:
        subprocess.run(["tesseract", "--version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _download_image(url: str, out_path: str, timeout: int = 10) -> bool:
    """下载图片到本地"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Collector/1.0",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with open(out_path, "wb") as f:
                f.write(resp.read())
        return True
    except Exception:
        return False


def _ocr_single(image_path: str) -> str:
    """对单张图片执行 OCR"""
    try:
        result = subprocess.run(
            ["tesseract", image_path, "stdout", "-l", "chi_sim+eng"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def ocr_images(urls: list[str], max_images: int = 10) -> list[str]:
    """
    对图片 URL 列表执行 OCR
    返回对应的 OCR 文本列表（与输入等长）
    """
    results = [""] * len(urls)

    if not _check_tesseract():
        return results

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, url in enumerate(urls[:max_images]):
            if not url or url.startswith("page:"):
                continue

            img_path = os.path.join(tmpdir, f"img_{i}.png")
            if _download_image(url, img_path):
                text = _ocr_single(img_path)
                results[i] = text

    return results
