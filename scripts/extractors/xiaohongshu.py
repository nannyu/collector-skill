#!/usr/bin/env python3
from __future__ import annotations
"""
Xiaohongshu extractor - Jina 优先，fallback 到直接 HTTP
CDP 浏览器方式由 agent 通过 web-access skill 处理
"""

import json
import re
import urllib.request
import urllib.error
from html.parser import HTMLParser


class XHSHTMLParser(HTMLParser):
    """解析小红书笔记页面"""
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.in_content = False
        self.in_author = False
        self.parts = []
        self.images = []
        self.title = ""
        self.author = ""
        self._in_desc = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")
        data_type = attrs_dict.get("data-type", "")

        # 标题
        if "title" in cls or tag == "h1":
            self.in_title = True

        # 正文描述
        if "desc" in cls or "note-text" in cls or "content" in cls:
            self.in_content = True
            self._in_desc = True

        # 图片
        if tag == "img":
            src = attrs_dict.get("src", attrs_dict.get("data-src", ""))
            if src and ("xhscdn" in src or "xiaohongshu" in src or "sns-img" in src):
                self.images.append({"url": src, "alt": "", "ocr_text": ""})

        # 作者
        if "author" in cls or "user-name" in cls:
            self.in_author = True

        if self.in_content:
            if tag in ("h1", "h2", "h3"):
                level = int(tag[1])
                self.parts.append("\n\n" + "#" * level + " ")
            elif tag == "p":
                self.parts.append("\n\n")
            elif tag == "br":
                self.parts.append("\n")
            elif tag in ("strong", "b"):
                self.parts.append("**")

    def handle_endtag(self, tag):
        if self.in_title and tag in ("h1", "h2", "div", "span"):
            self.in_title = False
        if self.in_author and tag in ("span", "div"):
            self.in_author = False
        if self._in_desc and tag in ("div", "span", "p"):
            # 简单判断：连续关闭可能结束描述
            pass

    def handle_data(self, data):
        text = data.strip()
        if self.in_title and text:
            self.title += text
        elif self.in_author and text:
            self.author += text
        elif self.in_content and text:
            self.parts.append(text)

    def get_result(self):
        content = "".join(self.parts)
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        return {
            "title": self.title.strip(),
            "author": self.author.strip(),
            "content_md": content,
            "images": self.images,
        }


def fetch_xhs_jina(url: str) -> dict | None:
    """通过 Jina Reader 抓取小红书"""
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
            if content and len(content.strip()) > 30:
                # Jina 格式: "Title: xxx"
                title = ""
                title_match = re.match(r"Title:\s*(.+)", content)
                if title_match:
                    title = title_match.group(1).strip()

                # 提取图片
                images = []
                for m in re.finditer(r"!\[.*?\]\((https?://[^\)]+)\)", content):
                    img_url = m.group(1)
                    if "xhscdn" in img_url or "xiaohongshu" in img_url or "sns-img" in img_url:
                        images.append({"url": img_url, "alt": "", "ocr_text": ""})

                return {"content_md": content, "title": title, "images": images, "source": "jina"}
    except Exception:
        pass
    return None


def fetch_xhs_http(url: str) -> dict | None:
    """直接 HTTP 抓取小红书页面"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.xiaohongshu.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

            # 提取 SSR 内容（小红书有服务端渲染）
            # 尝试提取 JSON-LD 或初始状态
            state_match = re.search(
                r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>',
                html, re.DOTALL
            )
            if state_match:
                try:
                    state = json.loads(state_match.group(1).replace("undefined", "null"))
                    note = state.get("note", {}).get("noteDetailMap", {})
                    if note:
                        first_note = next(iter(note.values()), {}).get("note", {})
                        title = first_note.get("title", "")
                        desc = first_note.get("desc", "")
                        images = []
                        videos = []
                        for img in first_note.get("imageList", []):
                            img_url = img.get("url", img.get("urlDefault", ""))
                            if img_url:
                                images.append({"url": img_url, "alt": "", "ocr_text": ""})
                        # 视频笔记
                        video_info = first_note.get("video", {})
                        if video_info:
                            vid_url = video_info.get("url", video_info.get("urlDefault", ""))
                            if vid_url:
                                videos.append({"url": vid_url, "type": "video"})
                        author = first_note.get("user", {}).get("nickname", "")
                        return {
                            "content_md": f"# {title}\n\n{desc}" if title else desc,
                            "title": title,
                            "author": author,
                            "images": images,
                            "videos": videos,
                            "source": "ssr_state",
                        }
                except (json.JSONDecodeError, StopIteration):
                    pass

            # fallback: HTML 解析
            parser = XHSHTMLParser()
            parser.feed(html)
            result = parser.get_result()
            if result["content_md"] and len(result["content_md"]) > 10:
                return {**result, "source": "http"}
    except Exception:
        pass
    return None


def extract_xiaohongshu(url: str) -> dict:
    """小红书提取：Jina → HTTP SSR → HTTP HTML"""
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from collector import build_result

    # Level 1: Jina
    result = fetch_xhs_jina(url)
    if result:
        return build_result(
            "xiaohongshu", url,
            title=result.get("title", ""),
            content_md=result["content_md"],
            images=result.get("images", []),
            videos=result.get("videos", []),
            metadata={"fetcher": "jina"},
        )

    # Level 2: HTTP (SSR state + HTML)
    result = fetch_xhs_http(url)
    if result:
        return build_result(
            "xiaohongshu", url,
            title=result.get("title", ""),
            author=result.get("author", ""),
            content_md=result["content_md"],
            images=result.get("images", []),
            videos=result.get("videos", []),
            metadata={"fetcher": result.get("source", "http")},
        )

    return build_result("xiaohongshu", url, content_md="", metadata={"error": "提取失败，可能需要 CDP 浏览器"})
