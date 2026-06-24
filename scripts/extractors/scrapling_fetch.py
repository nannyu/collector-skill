#!/usr/bin/env python3
"""
Scrapling extractor - 可选依赖，提供 TLS 指纹伪装能力
需要 scrapling + playwright（可选）

如果 scrapling 未安装或 playwright 不可用，自动降级跳过
"""

import json
import re
import sys
from pathlib import Path


def _scrapling_available() -> bool:
    """检查 scrapling 是否可用"""
    try:
        from scrapling import Fetcher
        return True
    except ImportError:
        return False


def _playwright_available() -> bool:
    """检查 playwright 是否可用"""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def fetch_via_scrapling(url: str) -> dict | None:
    """
    通过 Scrapling Fetcher 抓取（静态 HTTP + TLS 指纹伪装）
    不需要 playwright
    """
    if not _scrapling_available():
        return None

    try:
        from scrapling import Fetcher

        # Fetcher 使用 curl_cffi 的 TLS 指纹伪装
        # 能绕过基础的 TLS 指纹检测
        fetcher = Fetcher(auto_match=False)
        page = fetcher.get(url, timeout=15)

        if page.status != 200:
            return None

        # 提取标题
        title = ""
        title_el = page.css_first("title")
        if title_el:
            title = title_el.text.strip()

        # 提取正文
        article = (
            page.css_first("article") or
            page.css_first("main") or
            page.css_first(".content") or
            page.css_first(".post-body") or
            page.css_first("body")
        )

        if not article:
            return None

        text = article.text.strip()
        if len(text) < 20:
            return None

        # 提取图片
        images = []
        for img in page.css("img"):
            src = img.attrib.get("src", img.attrib.get("data-src", ""))
            if src and not src.startswith("data:"):
                images.append({"url": src, "alt": img.attrib.get("alt", ""), "ocr_text": ""})

        # 提取视频
        videos = []
        for vid in page.css("video"):
            src = vid.attrib.get("src", "")
            if src:
                videos.append({"url": src, "type": "video"})
            for source in vid.css("source"):
                src = source.attrib.get("src", "")
                if src:
                    videos.append({"url": src, "type": "video"})

        content_md = f"# {title}\n\n{text}" if title else text

        return {
            "content_md": content_md,
            "title": title,
            "images": images,
            "videos": videos,
            "source": "scrapling",
        }
    except Exception:
        return None


def fetch_via_scrapling_browser(url: str) -> dict | None:
    """
    通过 Scrapling StealthyFetcher 抓取（需要 playwright）
    提供浏览器级别的指纹伪装，能绕过 Cloudflare 等
    """
    if not _scrapling_available() or not _playwright_available():
        return None

    try:
        from scrapling import StealthyFetcher

        fetcher = StealthyFetcher()
        page = fetcher.fetch(url, headless=True, timeout=30)

        if not page or not page.body:
            return None

        text = page.body.text.strip()
        if len(text) < 20:
            return None

        title = ""
        title_el = page.css_first("title")
        if title_el:
            title = title_el.text.strip()

        images = []
        for img in page.css("img"):
            src = img.attrib.get("src", img.attrib.get("data-src", ""))
            if src and not src.startswith("data:"):
                images.append({"url": src, "alt": img.attrib.get("alt", ""), "ocr_text": ""})

        videos = []
        for vid in page.css("video"):
            src = vid.attrib.get("src", "")
            if src:
                videos.append({"url": src, "type": "video"})

        content_md = f"# {title}\n\n{text}" if title else text

        return {
            "content_md": content_md,
            "title": title,
            "images": images,
            "videos": videos,
            "source": "scrapling_browser",
        }
    except Exception:
        return None


def extract_via_scrapling(url: str) -> dict:
    """Scrapling 提取入口"""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from collector import build_result

    # Level 1: 静态 Fetcher（TLS 指纹）
    result = fetch_via_scrapling(url)
    if result:
        return build_result(
            _detect_type(url), url,
            title=result.get("title", ""),
            content_md=result["content_md"],
            images=result.get("images", []),
            videos=result.get("videos", []),
            metadata={"fetcher": "scrapling"},
        )

    # Level 2: StealthyFetcher（需要 playwright）
    result = fetch_via_scrapling_browser(url)
    if result:
        return build_result(
            _detect_type(url), url,
            title=result.get("title", ""),
            content_md=result["content_md"],
            images=result.get("images", []),
            videos=result.get("videos", []),
            metadata={"fetcher": "scrapling_browser"},
        )

    return build_result(
        _detect_type(url), url,
        content_md="",
        metadata={"error": "Scrapling 提取失败"},
    )


def _detect_type(url: str) -> str:
    if "mp.weixin.qq.com" in url:
        return "wechat"
    if "xiaohongshu.com" in url or "xhslink.com" in url:
        return "xiaohongshu"
    return "webpage"
