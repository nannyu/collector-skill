#!/usr/bin/env python3
from __future__ import annotations
"""
WeChat article extractor - Jina 优先，fallback 到直接 HTTP 解析
"""

import json
import re
import urllib.request
import urllib.error
from html.parser import HTMLParser
from urllib.parse import urljoin


class WeChatHTMLParser(HTMLParser):
    """解析微信文章 HTML，提取正文和图片"""
    def __init__(self):
        super().__init__()
        self.in_content = False
        self.in_title = False
        self.in_author = False
        self.parts = []
        self.images = []
        self.title = ""
        self.author = ""
        self.depth = 0
        self._skip = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        # 标题区域
        if "rich_media_title" in cls or "activity-name" in cls:
            self.in_title = True
            return

        # 作者区域
        if "rich_media_meta_text" in cls or "meta_author" in cls:
            self.in_author = True
            return

        # 正文区域
        if "rich_media_content" in cls or "js_content" in cls:
            self.in_content = True
            self.depth = 0
            return

        if self.in_content:
            self.depth += 1
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(tag[1])
                self.parts.append("\n\n" + "#" * level + " ")
            elif tag == "p":
                self.parts.append("\n\n")
            elif tag == "br":
                self.parts.append("\n")
            elif tag in ("strong", "b"):
                self.parts.append("**")
            elif tag in ("em", "i"):
                self.parts.append("*")
            elif tag == "img":
                src = attrs_dict.get("data-src", attrs_dict.get("src", ""))
                if src and not src.startswith("data:"):
                    self.images.append({"url": src, "alt": "", "ocr_text": ""})
                    self.parts.append(f"\n![img]({src})\n")
            elif tag == "blockquote":
                self.parts.append("\n> ")
            elif tag == "li":
                self.parts.append("\n- ")
            elif tag == "a":
                href = attrs_dict.get("href", "")
                self.parts.append("[")
                self._pending_href = href

    def handle_endtag(self, tag):
        if self.in_title and tag in ("h1", "h2", "div", "section"):
            self.in_title = False
        if self.in_author and tag in ("span", "div", "section"):
            self.in_author = False
        if self.in_content:
            if tag in ("strong", "b"):
                self.parts.append("**")
            elif tag in ("em", "i"):
                self.parts.append("*")
            elif tag == "a":
                href = getattr(self, "_pending_href", "")
                self.parts.append(f"]({href})")
            self.depth -= 1
            if self.depth < 0:
                self.in_content = False

    def handle_data(self, data):
        text = data.strip()
        if self.in_title and text:
            self.title += text
        elif self.in_author and text:
            self.author += text
        elif self.in_content:
            self.parts.append(data)

    def get_result(self):
        content = "".join(self.parts)
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        return {
            "title": self.title.strip(),
            "author": self.author.strip(),
            "content_md": content,
            "images": self.images,
        }


def fetch_wechat_jina(url: str) -> dict | None:
    """通过 Jina Reader 抓取微信文章"""
    jina_url = f"https://r.jina.ai/{url}"
    req = urllib.request.Request(
        jina_url,
        headers={
            "Accept": "text/markdown",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Collector/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            if content and len(content.strip()) > 50:
                # Jina 格式: "Title: xxx"
                title = ""
                title_match = re.match(r"Title:\s*(.+)", content)
                if title_match:
                    title = title_match.group(1).strip()

                # 从 Markdown 提取图片
                images = []
                for m in re.finditer(r"!\[([^\]]*)\]\((https?://[^\)]+)\)", content):
                    alt = m.group(1)
                    img_url = m.group(2)
                    images.append({"url": img_url, "alt": alt, "ocr_text": ""})

                return {"content_md": content, "title": title, "images": images, "source": "jina"}
    except Exception:
        pass
    return None


def fetch_wechat_http(url: str) -> dict | None:
    """直接 HTTP 抓取微信文章"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

            # 检查是否被反爬拦截
            if "请在微信客户端打开链接" in html or "antispider" in html.lower():
                return None

            parser = WeChatHTMLParser()
            parser.feed(html)
            result = parser.get_result()

            if result["content_md"] and len(result["content_md"]) > 20:
                return {**result, "source": "http"}
    except Exception:
        pass
    return None


def extract_wechat(url: str) -> dict:
    """微信文章提取：Jina → 直接 HTTP"""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from collector import build_result

    # Level 1: Jina
    result = fetch_wechat_jina(url)
    if result:
        return build_result(
            "wechat", url,
            title=result.get("title", ""),
            content_md=result["content_md"],
            images=result.get("images", []),
            metadata={"fetcher": "jina"},
        )

    # Level 2: 直接 HTTP
    result = fetch_wechat_http(url)
    if result:
        return build_result(
            "wechat", url,
            title=result["title"],
            author=result["author"],
            content_md=result["content_md"],
            images=result["images"],
            metadata={"fetcher": "http"},
        )

    return build_result("wechat", url, content_md="", metadata={"error": "提取失败，可能需要 CDP 浏览器"})
