#!/usr/bin/env python3
from __future__ import annotations
"""
Collector - 个人信息收集统一入口
接收 URL / 文件路径 / 文本，输出标准化 JSON
"""

import argparse
import json
import os
import sys
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 确保 extractors 目录在 path 中
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from extractors.web import extract_web
from extractors.wechat import extract_wechat
from extractors.xiaohongshu import extract_xiaohongshu
from extractors.pdf_extract import extract_pdf
from extractors.ocr import ocr_images
from extractors.media import download_media_batch
from extractors.cdp_fetch import fetch_via_cdp, _cdp_available
from extractors.scrapling_fetch import fetch_via_scrapling, _scrapling_available

CST = timezone(timedelta(hours=8))
ARCHIVE_ROOT = Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Niu" / "知识库" / "archive"


def detect_input_type(raw: str) -> tuple[str, str]:
    """识别输入类型，返回 (type, processed_input)"""
    text = raw.strip()

    # --text 模式由调用方处理
    if text.startswith("--text "):
        return "text", text[7:]
    if text.startswith("--text="):
        return "text", text[7:]

    # PDF 文件路径
    if text.lower().endswith(".pdf") and (os.path.isfile(text) or text.startswith("/")):
        return "pdf", text

    # URL 类型
    if re.match(r"https?://", text):
        if "mp.weixin.qq.com" in text:
            return "wechat", text
        if "xiaohongshu.com" in text or "xhslink.com" in text:
            return "xiaohongshu", text
        return "webpage", text

    # xhslink 短链
    if "xhslink.com" in text:
        return "xiaohongshu", text

    # 可能是本地文件
    if os.path.isfile(text):
        if text.lower().endswith(".pdf"):
            return "pdf", text
        return "file", text

    # 纯文本
    return "text", text


def build_result(source_type: str, source_url: str = "", **kwargs) -> dict:
    """构建统一输出格式"""
    now = datetime.now(CST).isoformat()
    return {
        "source_type": source_type,
        "source_url": source_url,
        "title": kwargs.get("title", ""),
        "content_md": kwargs.get("content_md", ""),
        "images": kwargs.get("images", []),
        "videos": kwargs.get("videos", []),
        "author": kwargs.get("author", ""),
        "published_at": kwargs.get("published_at", ""),
        "metadata": kwargs.get("metadata", {}),
        "extracted_at": now,
    }


def run_ocr_on_images(result: dict) -> dict:
    """对提取到的图片运行 OCR"""
    images = result.get("images", [])
    if not images:
        return result

    urls = [img.get("url", "") for img in images if img.get("url")]
    if not urls:
        return result

    ocr_texts = ocr_images(urls)
    for i, img in enumerate(images):
        if i < len(ocr_texts) and ocr_texts[i]:
            img["ocr_text"] = ocr_texts[i]

    return result


def _archive_dir_name(result: dict) -> str:
    """生成素材库目录名：日期_标题"""
    now = datetime.now(CST)
    date_prefix = now.strftime("%Y%m%d_%H%M%S")
    title = result.get("title", "").strip()
    if title:
        safe_title = re.sub(r'[^\w一-鿿-]', '_', title)[:40]
        return f"{date_prefix}_{safe_title}"
    return date_prefix


def save_raw_archive(result: dict) -> str | None:
    """
    保存原始素材到知识库 archive 目录
    结构：archive/{目录名}/raw.json + content.md + media/
    返回保存路径
    """
    dir_name = _archive_dir_name(result)
    archive_dir = ARCHIVE_ROOT / dir_name
    archive_dir.mkdir(parents=True, exist_ok=True)

    # 保存 raw.json（完整 collector 输出）
    raw_file = archive_dir / "raw.json"
    raw_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 保存 content.md（纯正文，方便快速浏览）
    content_md = result.get("content_md", "")
    if content_md:
        content_file = archive_dir / "content.md"
        content_file.write_text(content_md, encoding="utf-8")

    # 复制媒体文件到素材库
    images = result.get("images", [])
    videos = result.get("videos", [])
    has_media = any(img.get("local_path") for img in images) or any(vid.get("local_path") for vid in videos)

    if has_media:
        import shutil
        media_dir = archive_dir / "media"
        media_dir.mkdir(exist_ok=True)
        for img in images:
            src = img.get("local_path", "")
            if src and os.path.isfile(src):
                dst = media_dir / img.get("filename", os.path.basename(src))
                if not dst.exists():
                    shutil.copy2(src, dst)
        for vid in videos:
            src = vid.get("local_path", "")
            if src and os.path.isfile(src):
                dst = media_dir / vid.get("filename", os.path.basename(src))
                if not dst.exists():
                    shutil.copy2(src, dst)

    return str(archive_dir)


def extract_with_fallback(url: str, source_type: str) -> dict:
    """
    带 fallback 的统一提取逻辑
    fallback 链: Jina/HTTP → Scrapling → CDP
    """
    # Level 1 & 2: Jina + 直接 HTTP（由各 extractor 内部处理）
    if source_type == "wechat":
        result = extract_wechat(url)
    elif source_type == "xiaohongshu":
        result = extract_xiaohongshu(url)
    else:
        result = extract_web(url)

    # 检查是否有有效内容（排除反爬/空壳页面）
    content = result.get("content_md", "")
    images = result.get("images", [])
    if _is_valid_content(content, source_type, images):
        return result

    # Level 3: Scrapling（TLS 指纹伪装，可选）
    if _scrapling_available():
        scrapling_result = fetch_via_scrapling(url)
        if scrapling_result and _is_valid_content(scrapling_result.get("content_md", ""), source_type, scrapling_result.get("images", [])):
            return build_result(
                source_type, url,
                title=scrapling_result.get("title", ""),
                content_md=scrapling_result["content_md"],
                images=scrapling_result.get("images", []),
                videos=scrapling_result.get("videos", []),
                metadata={"fetcher": "scrapling"},
            )

    # Level 4: CDP 浏览器（需要 web-access skill，复用登录态）
    if _cdp_available():
        cdp_result = fetch_via_cdp(url)
        if cdp_result and _is_valid_content(cdp_result.get("content_md", ""), source_type, cdp_result.get("images", [])):
            return build_result(
                source_type, url,
                title=cdp_result.get("title", ""),
                content_md=cdp_result["content_md"],
                images=cdp_result.get("images", []),
                videos=cdp_result.get("videos", []),
                author=cdp_result.get("author", ""),
                metadata={"fetcher": "cdp"},
            )

    # 全部失败，返回原始结果（可能有部分内容）
    return result


def _is_valid_content(content: str, source_type: str, images: list | None = None) -> bool:
    """检查提取到的内容是否有效（排除反爬页面、空壳页面）"""
    text_len = len(content.strip()) if content else 0
    image_count = len(images) if images else 0

    # 图片笔记判定：有 3+ 张图片时，文字要求极低（正文在图里）
    if image_count >= 3:
        min_len = 10
    elif image_count > 0:
        min_len = 30
    else:
        min_len = 100

    if text_len < min_len:
        return False

    # 反爬特征关键词
    anti_spider_patterns = [
        "请在微信客户端打开链接",
        "antispider",
        "验证码",
        "captcha",
        "人机验证",
        "access denied",
        "请证明您是真人",
        "Warning: This page maybe not yet fully loaded",
        "Warning: This page maybe requiring CAPTCHA",
        "登录后推荐更懂你的笔记",
        "手机号登录",
        "扫码登录",
        "请登录",
    ]
    content_lower = content.lower()
    for pattern in anti_spider_patterns:
        if pattern.lower() in content_lower:
            return False

    # 小红书特殊检查：如果内容只是导航和 footer，不算有效
    if source_type == "xiaohongshu":
        # 有效的小红书内容应该有 .note-text 或实际笔记文本
        # 如果内容主要是 "小红书 - 你的生活兴趣社区" 这种壳页面，跳过
        if "你的生活兴趣社区" in content and len(content) < 500:
            return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Collector - 信息收集统一入口")
    parser.add_argument("input", nargs="?", help="URL、文件路径或文本")
    parser.add_argument("--text", action="store_true", help="将输入作为纯文本处理")
    parser.add_argument("--no-ocr", action="store_true", help="跳过图片 OCR")
    parser.add_argument("--no-download", action="store_true", help="跳过媒体下载")
    parser.add_argument("--no-archive", action="store_true", help="跳过原始素材归档")
    parser.add_argument("--media-dir", help="媒体文件保存目录（默认与 JSON 同目录下的 media/）")
    parser.add_argument("--output-dir", help="保存结果到指定目录")
    args = parser.parse_args()

    if not args.input:
        parser.print_help()
        sys.exit(1)

    raw_input = args.input
    if args.text:
        raw_input = f"--text {raw_input}"

    source_type, processed = detect_input_type(raw_input)

    # 路由到对应提取器
    try:
        if source_type == "text":
            result = build_result("text", content_md=processed)
        elif source_type == "pdf":
            result = extract_pdf(processed)
        elif source_type in ("wechat", "xiaohongshu", "webpage"):
            result = extract_with_fallback(processed, source_type)
        else:
            print(json.dumps({"error": f"不支持的输入类型: {source_type}"}, ensure_ascii=False))
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e), "source_type": source_type}, ensure_ascii=False))
        sys.exit(1)

    # 下载媒体文件（图片 + 视频）
    if not args.no_download:
        images = result.get("images", [])
        videos = result.get("videos", [])
        if images or videos:
            # 确定媒体保存目录
            if args.media_dir:
                media_dir = str(Path(args.media_dir).expanduser())
            elif args.output_dir:
                media_dir = str(Path(args.output_dir).expanduser() / "media")
            else:
                media_dir = str(Path.home() / "Her工作间" / "collected" / "media")

            title = result.get("title", "")
            updated_images, updated_videos = download_media_batch(
                images, videos, media_dir, title=title, referer=result.get("source_url", "")
            )
            result["images"] = updated_images
            result["videos"] = updated_videos

    # OCR 处理
    if not args.no_ocr:
        result = run_ocr_on_images(result)

    # 保存原始素材到 archive
    if not args.no_archive:
        archive_path = save_raw_archive(result)
        if archive_path:
            result["_archive_path"] = archive_path

    # 输出
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)

    # 可选：保存到文件
    if args.output_dir:
        out_dir = Path(args.output_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        title = result.get("title", "").strip()
        if title:
            safe_name = re.sub(r'[^\w一-鿿-]', '_', title)[:80]
        else:
            safe_name = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
        out_file = out_dir / f"{safe_name}.json"
        out_file.write_text(output, encoding="utf-8")
        print(f"\n已保存到: {out_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
