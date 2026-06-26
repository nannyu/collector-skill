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
            target_id = data.get("targetId")
            if target_id:
                # 等待页面加载
                import time
                time.sleep(2)
            return target_id
    except Exception:
        return None


def _cdp_eval(target_id: str, js_code: str) -> str | None:
    """在 tab 中执行 JS 并返回结果（从 JSON value 字段提取）"""
    try:
        req = urllib.request.Request(
            f"{CDP_BASE}/eval?target={target_id}",
            data=js_code.encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            # web-access API 返回 {"value": "..."}
            try:
                data = json.loads(raw)
                return data.get("value", raw)
            except (json.JSONDecodeError, TypeError):
                return raw
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


def _is_xiaohongshu(url: str) -> bool:
    return "xiaohongshu.com" in url or "xhslink.com" in url


def _extract_xiaohongshu(target_id: str) -> dict | None:
    """小红书专用提取：#detail-title 标题 + #detail-desc 正文 + swiper 全部图片"""
    js = """
    (function() {
        // 标题：#detail-title 或 .note-content .title
        var titleEl = document.querySelector('#detail-title') ||
                      document.querySelector('.note-content .title');
        var title = titleEl ? titleEl.innerText.trim() : '';
        if (!title) title = document.title.replace(/ - 小红书$/, '');

        // 正文：#detail-desc（不含评论区）
        var descEl = document.querySelector('#detail-desc') ||
                     document.querySelector('.note-content .desc');
        var body = descEl ? descEl.innerText.trim() : '';

        // 图片：swiper 全部 slide（排除 duplicate 克隆 slide，保证正确顺序）
        // 小红书 swiper 用 loop 模式，会把最后一张图克隆到 slide 0
        var images = [];
        var seen = {};
        document.querySelectorAll('.swiper-slide, .slide-item').forEach(function(slide) {
            // 跳过 swiper 克隆的 duplicate slide
            if (slide.className.indexOf('duplicate') !== -1) return;
            var img = slide.querySelector('img');
            if (!img) return;
            var src = img.src || img.dataset.src || '';
            if (src && src.includes('http') && !src.startsWith('data:') && !seen[src]) {
                // 只要笔记图片（/n/ 结尾），排除评论图片（/co/ 结尾）和头像
                if (src.includes('/n') && !src.includes('avatar')) {
                    seen[src] = true;
                    images.push({url: src, alt: img.alt || ''});
                }
            }
        });
        // fallback: 大图
        if (images.length === 0) {
            document.querySelectorAll('img').forEach(function(img) {
                if (img.naturalWidth > 300 || img.width > 300) {
                    var src = img.src || '';
                    if (src && src.includes('http') && !src.startsWith('data:') && !seen[src]) {
                        seen[src] = true;
                        images.push({url: src, alt: img.alt || ''});
                    }
                }
            });
        }

        // 视频
        var videos = [];
        document.querySelectorAll('video, video source').forEach(function(v) {
            var src = v.src || '';
            if (src && src.includes('http')) videos.push({url: src, type: 'video'});
        });

        // 作者
        var author = '';
        var authorEl = document.querySelector('.author-wrapper .username') ||
                       document.querySelector('.note-content .author');
        if (authorEl) author = authorEl.innerText.trim();

        return JSON.stringify({title: title, body: body, images: images, videos: videos, author: author});
    })()
    """
    raw = _cdp_eval(target_id, js)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    title = data.get("title", "")
    body = data.get("body", "")
    if not body or len(body.strip()) < 10:
        return None

    content_md = f"# {title}\n\n{body}" if title else body
    images = [{"url": img["url"], "alt": img.get("alt", ""), "ocr_text": ""} for img in data.get("images", [])]
    videos = [{"url": v["url"], "type": v.get("type", "video")} for v in data.get("videos", [])]

    return {
        "content_md": content_md,
        "title": title,
        "author": data.get("author", ""),
        "images": images,
        "videos": videos,
        "source": "cdp",
    }


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
        # 小红书专用提取
        if _is_xiaohongshu(url):
            return _extract_xiaohongshu(target_id)

        # 通用提取
        # 标题：og:title > h1 > document.title（document.title 经常是站点名）
        title = ""
        og_raw = _cdp_eval(target_id, "(function(){var m=document.querySelector('meta[property=\"og:title\"]');return m?m.content:''})()")
        if og_raw and og_raw.strip():
            title = og_raw.strip()
        if not title:
            h1_raw = _cdp_eval(target_id, "(function(){var h=document.querySelector('h1');return h?h.innerText.trim():''})()")
            if h1_raw and h1_raw.strip():
                title = h1_raw.strip()
        if not title:
            title = _cdp_eval(target_id, "document.title") or ""

        js_extract = """
        (function() {
            var el = document.querySelector('article') ||
                     document.querySelector('main') ||
                     document.querySelector('.content') ||
                     document.querySelector('.post-body') ||
                     document.querySelector('#content') ||
                     document.body;
            if (!el) return JSON.stringify({text: '', html: ''});

            var text = el.innerText || '';

            var images = [];
            el.querySelectorAll('img').forEach(function(img) {
                var src = img.src || img.dataset.src || '';
                if (src && !src.startsWith('data:')) {
                    images.push({url: src, alt: img.alt || ''});
                }
            });

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

        content_md = f"# {title}\n\n{text}" if title else text

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
            author=result.get("author", ""),
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
