#!/usr/bin/env python3
"""
PDF extractor - 基于 pdfplumber 提取文本和表格，图片走 OCR
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _check_pdfplumber():
    try:
        import pdfplumber
        return True
    except ImportError:
        return False


def _extract_images_from_pdf(pdf_path: str, out_dir: str) -> list[str]:
    """用 pdftoppm 提取 PDF 中的图片页面"""
    pngs = []
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-r", "200", pdf_path, os.path.join(out_dir, "page")],
            capture_output=True, timeout=60
        )
        for f in sorted(Path(out_dir).glob("page-*.png")):
            pngs.append(str(f))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return pngs


def extract_pdf(pdf_path: str) -> dict:
    """PDF 提取"""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from collector import build_result

    if not os.path.isfile(pdf_path):
        return build_result("pdf", pdf_path, content_md="", metadata={"error": "文件不存在"})

    # 方式 1: pdfplumber 提取文本
    if _check_pdfplumber():
        try:
            import pdfplumber
            parts = []
            all_images = []

            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    # 提取文本
                    text = page.extract_text()
                    if text:
                        parts.append(f"\n\n--- 第 {i+1} 页 ---\n\n{text}")

                    # 提取表格
                    tables = page.extract_tables()
                    for table in tables:
                        if table:
                            # 转 Markdown 表格
                            md_table = _table_to_markdown(table)
                            if md_table:
                                parts.append(f"\n\n{md_table}\n")

                    # 提取图片信息
                    for img in page.images:
                        all_images.append({
                            "url": f"page:{i+1}",
                            "alt": "",
                            "ocr_text": "",
                        })

            content = "".join(parts).strip()
            if content:
                title = Path(pdf_path).stem
                return build_result(
                    "pdf", pdf_path,
                    title=title,
                    content_md=content,
                    images=all_images,
                    metadata={"pages": i + 1 if 'i' in dir() else 0, "fetcher": "pdfplumber"},
                )
        except Exception as e:
            pass

    # 方式 2: pdftotext fallback
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            title = Path(pdf_path).stem
            return build_result(
                "pdf", pdf_path,
                title=title,
                content_md=result.stdout,
                metadata={"fetcher": "pdftotext"},
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return build_result("pdf", pdf_path, content_md="", metadata={"error": "PDF 提取失败"})


def _table_to_markdown(table: list[list]) -> str:
    """将表格数据转为 Markdown 格式"""
    if not table or not table[0]:
        return ""

    # 清理 None 值
    cleaned = []
    for row in table:
        cleaned.append([str(cell).strip() if cell else "" for cell in row])

    if len(cleaned) < 1:
        return ""

    # 表头
    header = cleaned[0]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    # 数据行
    for row in cleaned[1:]:
        # 补齐列数
        while len(row) < len(header):
            row.append("")
        lines.append("| " + " | ".join(row[:len(header)]) + " |")

    return "\n".join(lines)
