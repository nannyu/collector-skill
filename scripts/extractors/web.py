#!/usr/bin/env python3
from __future__ import annotations
"""
Web extractor - Jina Reader 优先，fallback 到直接 HTTP
"""

import json
import subprocess
import urllib.request
import urllib.error
import re
from html.parser import HTMLParser


class SimpleHTMLToMarkdown(HTMLParser):
    """轻量 HTML → Markdown 转换"""
    def __init__(self):
        super().__init__()
        self.md_parts = []
        self.current_tag = None
        self.skip_tags = {"script", "style", "nav", "footer", "header"}
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skip_depth += 1
            return
        self.current_tag = tag
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.md_parts.append("\n" + "#" * level + " ")
        elif tag == "p":
            self.md_parts.append("\n\n")
        elif tag == "br":
            self.md_parts.append("\n")
        elif tag == "strong" or tag == "b":
            self.md_parts.append("**")
        elif tag == "em" or tag == "i":
            self.md_parts.append("*")
        elif tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "")
            self.md_parts.append("[")
            self._pending_href = href
        elif tag == "img":
            attrs_dict = dict(attrs)
            src = attrs_dict.get("src", "")
            alt = attrs_dict.get("alt", "")
            if src:
                self.md_parts.append(f"\n![{alt}]({src})\n")
        elif tag == "li":
            self.md_parts.append("\n- ")
        elif tag == "blockquote":
            self.md_parts.append("\n> ")

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip_depth -= 1
            return
        if tag in ("strong", "b"):
            self.md_parts.append("**")
        elif tag in ("em", "i"):
            self.md_parts.append("*")
        elif tag == "a":
            href = getattr(self, "_pending_href", "")
            self.md_parts.append(f"]({href})")

    def handle_data(self, data):
        if self.skip_depth > 0:
            return
        self.md_parts.append(data)

    def get_markdown(self):
        text = "".join(self.md_parts)
        # 清理多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def fetch_via_jina(url: str, timeout: int = 15) -> dict | None:
    """通过 Jina Reader 抓取"""
    jina_url = f"https://r.jina.ai/{url}"
    req = urllib.request.Request(
        jina_url,
        headers={
            "Accept": "text/markdown",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Collector/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            if content and len(content.strip()) > 50:
                # Jina 格式: 第一行是 "Title: xxx"
                title = ""
                title_match = re.match(r"Title:\s*(.+)", content)
                if title_match:
                    title = title_match.group(1).strip()

                # 从 Markdown 提取图片
                images = []
                for m in re.finditer(r"!\[([^\]]*)\]\((https?://[^\)]+)\)", content):
                    alt = m.group(1)
                    img_url = m.group(2)
                    # 跳过 star history 等 badge 图片
                    if "star-history" in img_url or "skill-history" in img_url or "camo.githubusercontent" in img_url:
                        continue
                    images.append({"url": img_url, "alt": alt, "ocr_text": ""})

                return {"content_md": content, "title": title, "images": images, "source": "jina"}
    except Exception:
        pass
    return None


def fetch_via_http(url: str, timeout: int = 15) -> dict | None:
    """直接 HTTP 抓取 + HTML 解析"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")

            # 提取标题：og:title > h1 > <title>（<title> 经常是站点名，优先级最低）
            title = ""
            og_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if og_match:
                title = og_match.group(1).strip()
            if not title:
                h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
                if h1_match:
                    title = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
            if not title:
                title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
                title = title_match.group(1).strip() if title_match else ""

            # 提取正文区域（优先 article / main / .content）
            body_match = re.search(
                r"<(?:article|main)[^>]*>(.*?)</(?:article|main)>",
                html, re.DOTALL | re.IGNORECASE
            )
            if not body_match:
                body_match = re.search(
                    r'<div[^>]*class="[^"]*(?:content|article|post-body)[^"]*"[^>]*>(.*?)</div>',
                    html, re.DOTALL | re.IGNORECASE
                )
            body_html = body_match.group(1) if body_match else html

            # 提取图片
            images = []
            for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', body_html, re.IGNORECASE):
                img_url = m.group(1)
                if not img_url.startswith("http"):
                    from urllib.parse import urljoin
                    img_url = urljoin(url, img_url)
                images.append({"url": img_url, "alt": "", "ocr_text": ""})

            # 提取视频
            videos = []
            # <video src="...">
            for m in re.finditer(r'<video[^>]+src=["\']([^"\']+)["\']', body_html, re.IGNORECASE):
                vid_url = m.group(1)
                if not vid_url.startswith("http"):
                    from urllib.parse import urljoin
                    vid_url = urljoin(url, vid_url)
                videos.append({"url": vid_url, "type": "video"})
            # <video><source src="...">
            for m in re.finditer(r'<source[^>]+src=["\']([^"\']+)["\']', body_html, re.IGNORECASE):
                vid_url = m.group(1)
                if not vid_url.startswith("http"):
                    from urllib.parse import urljoin
                    vid_url = urljoin(url, vid_url)
                videos.append({"url": vid_url, "type": "video"})
            # <iframe> 嵌入视频（YouTube, Bilibili 等）
            for m in re.finditer(r'<iframe[^>]+src=["\']([^"\']+)["\']', body_html, re.IGNORECASE):
                iframe_url = m.group(1)
                if any(v in iframe_url for v in ["youtube.com", "bilibili.com", "player.vimeo.com"]):
                    videos.append({"url": iframe_url, "type": "iframe"})

            # HTML → Markdown
            parser = SimpleHTMLToMarkdown()
            parser.feed(body_html)
            content_md = parser.get_markdown()

            if title or content_md:
                return {
                    "content_md": f"# {title}\n\n{content_md}" if title else content_md,
                    "title": title,
                    "images": images,
                    "videos": videos,
                    "source": "http",
                }
    except Exception:
        pass
    return None


def extract_web(url: str) -> dict:
    """网页提取：Jina → 直接 HTTP"""
    from collector import build_result

    # Level 1: Jina Reader
    result = fetch_via_jina(url)
    if result:
        title = result.get("title", "") or _extract_title(result["content_md"])
        return build_result(
            "webpage", url,
            title=title,
            content_md=result["content_md"],
            images=result.get("images", []),
            metadata={"fetcher": "jina"},
        )

    # Level 2: 直接 HTTP
    result = fetch_via_http(url)
    if result:
        return build_result(
            "webpage", url,
            title=result.get("title", ""),
            content_md=result["content_md"],
            images=result.get("images", []),
            videos=result.get("videos", []),
            metadata={"fetcher": "http"},
        )

    return build_result("webpage", url, content_md="", metadata={"error": "所有提取方式均失败"})


def _extract_title(md: str) -> str:
    """从 Markdown 提取第一个标题"""
    m = re.match(r"^#\s+(.+)$", md, re.MULTILINE)
    return m.group(1).strip() if m else ""
