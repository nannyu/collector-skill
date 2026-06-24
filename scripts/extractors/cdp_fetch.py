#!/usr/bin/env python3
"""
CDP extractor - 通过 web-access 的 CDP Proxy 连接本地浏览器
需要 web-access skill 的 CDP Proxy 运行在 localhost:3456
"""

import json
import re
import urllib.request
import urllib.error
from html.parser import HTMLParser

CDP_BASE = "http://localhost:3456"


def _cdp_available() -> bool:
    """检查 CDP Proxy 是否在线"""
    try:
        req = urllib.request.Request(f"{CDP_BASE}/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _cdp_new_tab(url: str) -> str | None:
    """创建新 tab 并等待加载，返回 targetId"""
    try:
        req = urllib.request.Request(
            f"{CDP_BASE}/new",
            data=url.encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("targetId")
    except Exception:
        return None


def _cdp_eval(target_id: str, js_code: str) -> str | None:
    """在 tab 中执行 JS 并返回结果"""
    try:
        req = urllib.request.Request(
            f"{CDP_BASE}/eval?target={target_id}",
            data=js_code.encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _cdp_close(target_id: str):
    """关闭 tab"""
    try:
        req = urllib.request.Request(f"{CDP_BASE}/close?target={target_id}")
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass


def _cdp_screenshot(target_id: str, path: str) -> bool:
    """截图"""
    try:
        req = urllib.request.Request(
            f"{CDP_BASE}/screenshot?target={target_id}&file={path}"
        )
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception:
        return False


def fetch_via_cdp(url: str) -> dict | None:
    """
    通过 CDP 浏览器抓取页面内容
    利用用户浏览器的登录态，能访问需要登录的内容
    """
    if not _cdp_available():
        return None

    target_id = _cdp_new_tab(url)
    if not target_id:
        return None

    try:
        # 提取标题
        title = _cdp_eval(target_id, "document.title") or ""

        # 提取正文内容（优先 article/main，fallback 到 body）
        js_extract = """
        (function() {
            var el = document.querySelector('article') ||
                     document.querySelector('main') ||
                     document.querySelector('.content') ||
                     document.querySelector('.post-body') ||
                     document.querySelector('#content') ||
                     document.body;
            if (!el) return JSON.stringify({text: '', html: ''});

            // 提取文本
            var text = el.innerText || '';

            // 提取图片
            var images = [];
            el.querySelectorAll('img').forEach(function(img) {
                var src = img.src || img.dataset.src || '';
                if (src && !src.startsWith('data:')) {
                    images.push({url: src, alt: img.alt || ''});
                }
            });

            // 提取视频
            var videos = [];
            el.querySelectorAll('video').forEach(function(v) {
                var src = v.src || '';
                if (src) videos.push({url: src, type: 'video'});
                v.querySelectorAll('source').forEach(function(s) {
                    if (s.src) videos.push({url: s.src, type: 'video'});
                });
            });

            return JSON.stringify({text: text, images: images, videos: videos});
        })()
        """
        result_raw = _cdp_eval(target_id, js_extract)
        if not result_raw:
            return None

        result_data = json.loads(result_raw)
        text = result_data.get("text", "")
        images = result_data.get("images", [])
        videos = result_data.get("videos", [])

        if not text or len(text.strip()) < 20:
            return None

        # 转为 Markdown（简单转换）
        content_md = f"# {title}\n\n{text}" if title else text

        # 标准化图片格式
        std_images = [{"url": img["url"], "alt": img.get("alt", ""), "ocr_text": ""} for img in images]
        std_videos = [{"url": vid["url"], "type": vid.get("type", "video")} for vid in videos]

        return {
            "content_md": content_md,
            "title": title,
            "images": std_images,
            "videos": std_videos,
            "source": "cdp",
        }
    finally:
        _cdp_close(target_id)


def extract_via_cdp(url: str) -> dict:
    """
    CDP 提取入口
    返回 collector 格式的 result dict
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from collector import build_result

    result = fetch_via_cdp(url)
    if result:
        return build_result(
            _detect_type(url), url,
            title=result.get("title", ""),
            content_md=result["content_md"],
            images=result.get("images", []),
            videos=result.get("videos", []),
            metadata={"fetcher": "cdp"},
        )
    return build_result(
        _detect_type(url), url,
        content_md="",
        metadata={"error": "CDP 提取失败"},
    )


def _detect_type(url: str) -> str:
    if "mp.weixin.qq.com" in url:
        return "wechat"
    if "xiaohongshu.com" in url or "xhslink.com" in url:
        return "xiaohongshu"
    return "webpage"
