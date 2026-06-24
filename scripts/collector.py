#!/usr/bin/env python3
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

CST = timezone(timedelta(hours=8))


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


def main():
    parser = argparse.ArgumentParser(description="Collector - 信息收集统一入口")
    parser.add_argument("input", nargs="?", help="URL、文件路径或文本")
    parser.add_argument("--text", action="store_true", help="将输入作为纯文本处理")
    parser.add_argument("--no-ocr", action="store_true", help="跳过图片 OCR")
    parser.add_argument("--no-download", action="store_true", help="跳过媒体下载")
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
        elif source_type == "wechat":
            result = extract_wechat(processed)
        elif source_type == "xiaohongshu":
            result = extract_xiaohongshu(processed)
        elif source_type == "pdf":
            result = extract_pdf(processed)
        elif source_type == "webpage":
            result = extract_web(processed)
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
                images, videos, media_dir, title=title
            )
            result["images"] = updated_images
            result["videos"] = updated_videos

    # OCR 处理
    if not args.no_ocr:
        result = run_ocr_on_images(result)

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
