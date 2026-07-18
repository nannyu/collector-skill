#!/usr/bin/env python3
from __future__ import annotations
"""
Organizer - 知识库归档整理
接收 collector 输出的 JSON，生成知识条目并写入知识库
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
KB_ROOT = Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Niu" / "知识库"


def load_categories() -> dict:
    """加载分类体系"""
    cat_file = KB_ROOT / "categories.json"
    if cat_file.exists():
        try:
            return json.loads(cat_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # iCloud Drive may temporarily return Resource deadlock avoided
            return {}
    return {}


def _archive_dir_from_input(input_path: str | None) -> Path | None:
    """返回 collector raw.json 所在的 archive 目录。"""
    if not input_path or input_path == "-":
        return None
    path = Path(input_path).expanduser()
    if path.is_file():
        return path.parent
    return path if path.is_dir() else None


def _format_comments(comments) -> str:
    """将常见评论 JSON 结构转换为可读 Markdown。"""
    if not isinstance(comments, list):
        return ""
    lines = []
    for item in comments:
        if isinstance(item, str):
            if item.strip():
                lines.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        author = item.get("author") or item.get("user") or item.get("nickname") or "匿名用户"
        text = str(item.get("content") or item.get("text") or item.get("comment") or "").strip()
        if text:
            lines.append(f"- **{author}**：{text.replace(chr(10), chr(10) + '  ')}")
    return "\n".join(lines)


def _collect_comment_media(data: dict, archive_dir: Path | None) -> list[dict]:
    """收集评论区媒体，支持输出字段、manifest 和续采进度文件。"""
    found: dict[str, dict] = {}

    def add(item, kind="image"):
        if isinstance(item, str):
            item = {"local_path": item}
        if not isinstance(item, dict):
            return
        src = item.get("local_path") or item.get("path") or item.get("file")
        if not src:
            return
        src_path = Path(str(src)).expanduser()
        if not src_path.is_file():
            return
        found[str(src_path.resolve())] = {
            "local_path": str(src_path.resolve()),
            "filename": item.get("filename") or src_path.name,
            "kind": item.get("kind", kind),
        }

    for key in ("comment_images", "comments_images", "comment_videos", "comments_videos", "comment_media", "comments_media"):
        value = data.get(key, [])
        for item in value if isinstance(value, list) else []:
            add(item, "video" if "video" in key else "image")

    if archive_dir and archive_dir.exists():
        progress = archive_dir / "root_comment_media_progress.json"
        if progress.is_file():
            try:
                raw = json.loads(progress.read_text(encoding="utf-8"))
                for item in raw.get("saved", {}).values():
                    add(item, "video" if item.get("kind") in {"video", "live"} else "image")
            except (OSError, json.JSONDecodeError):
                pass
        for folder, kind in (("media/comment_images", "image"), ("media/comment_videos", "video")):
            media_dir = archive_dir / folder
            if media_dir.is_dir():
                for src in sorted(media_dir.iterdir()):
                    if src.is_file():
                        add({"local_path": str(src), "filename": src.name, "kind": kind}, kind)
    return list(found.values())


def enrich_comments(data: dict, input_path: str | None = None) -> dict:
    """把 archive 中的完整评论和媒体挂回 collector 输出。"""
    enriched = dict(data)
    archive_dir = _archive_dir_from_input(input_path)
    comment_md = ""
    for key in ("comments_md", "comments_full_md", "comments_markdown"):
        if isinstance(enriched.get(key), str) and enriched[key].strip():
            comment_md = enriched[key].strip()
            break
    if not comment_md and archive_dir:
        for name in ("comments_full.md", "comments.md", "comments.txt"):
            candidate = archive_dir / name
            if candidate.is_file():
                try:
                    comment_md = candidate.read_text(encoding="utf-8").strip()
                except OSError:
                    pass
                if comment_md:
                    break
    if not comment_md:
        for key in ("comments_full", "comments"):
            comment_md = _format_comments(enriched.get(key))
            if comment_md:
                break
    if comment_md:
        enriched["_comments_markdown"] = comment_md
    enriched["_comment_media"] = _collect_comment_media(enriched, archive_dir)
    return enriched


def generate_entry_filename(title: str, source_type: str = "") -> str:
    """生成知识条目的文件名"""
    now = datetime.now(CST)
    date_prefix = now.strftime("%Y%m%d")
    # 清理标题
    safe_title = re.sub(r'[^\w一-鿿-]', '_', title).strip('_')
    safe_title = safe_title[:60] if safe_title else "untitled"
    return f"{date_prefix}_{safe_title}.md"


def build_knowledge_entry(
    collector_output: dict,
    category: str = "",
    subcategory: str = "",
    summary: str = "",
    key_points: list[str] = None,
    tags: list[str] = None,
    my_notes: str = "",
) -> str:
    """
    生成知识条目的 Markdown 内容
    collector_output: collector 的 JSON 输出
    category: 一级分类
    subcategory: 二级分类
    summary: AI 生成的摘要
    key_points: 关键知识点列表
    tags: 标签列表
    my_notes: 用户自己的笔记/感想
    """
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    title = collector_output.get("title", "无标题")
    source_url = collector_output.get("source_url", "")
    source_type = collector_output.get("source_type", "")
    author = collector_output.get("author", "")
    published_at = collector_output.get("published_at", "")
    images = collector_output.get("images", [])
    videos = collector_output.get("videos", [])

    # 构建 frontmatter
    lines = [
        "---",
        f"title: \"{title}\"",
        f"source: \"{source_url}\"",
        f"source_type: \"{source_type}\"",
    ]
    if author:
        lines.append(f"author: \"{author}\"")
    if published_at:
        lines.append(f"published_at: \"{published_at}\"")
    if category:
        lines.append(f"category: \"{category}\"")
    if subcategory:
        lines.append(f"subcategory: \"{subcategory}\"")
    if tags:
        tag_list = ", ".join(f"\"{t}\"" for t in tags)
        lines.append(f"tags: [{tag_list}]")
    lines.append(f"collected_at: \"{now}\"")
    lines.append("---")
    lines.append("")

    # 标题
    lines.append(f"# {title}")
    lines.append("")

    # 摘要
    if summary:
        lines.append("## 摘要")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # 关键知识点
    if key_points:
        lines.append("## 关键知识点")
        lines.append("")
        for kp in key_points:
            lines.append(f"- {kp}")
        lines.append("")

    # 媒体资源
    downloaded_images = [img for img in images if img.get("local_path")]
    downloaded_videos = [vid for vid in videos if vid.get("local_path")]
    if downloaded_images or downloaded_videos:
        lines.append("## 媒体资源")
        lines.append("")
        if downloaded_images:
            lines.append("### 图片")
            for img in downloaded_images:
                fn = img.get("filename", "")
                sz = img.get("size", 0)
                sz_str = f" ({sz // 1024}KB)" if sz > 1024 else f" ({sz}B)"
                lines.append(f"- ![](./media/{fn}){sz_str}")
            lines.append("")
        if downloaded_videos:
            lines.append("### 视频")
            for vid in downloaded_videos:
                fn = vid.get("filename", "")
                sz = vid.get("size", 0)
                sz_mb = f" ({sz // 1048576}MB)" if sz > 1048576 else f" ({sz // 1024}KB)"
                lines.append(f"- [{fn}](./media/{fn}){sz_mb}")
            lines.append("")

    # 用户笔记
    if my_notes:
        lines.append("## 我的笔记")
        lines.append("")
        lines.append(my_notes)
        lines.append("")

    # 原文内容（折叠）
    content_md = collector_output.get("content_md", "")
    if content_md:
        lines.append("<details>")
        lines.append("<summary>原文内容</summary>")
        lines.append("")
        lines.append(content_md)
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # 评论区必须位于正文之后，并与文章归档在同一篇知识库文档中。
    comments_md = collector_output.get("_comments_markdown", "")
    comment_media = collector_output.get("_comment_media", [])
    if comments_md or comment_media:
        lines.append("## 评论区")
        lines.append("")
        if comments_md:
            lines.append(comments_md)
            lines.append("")
        if comment_media:
            lines.append("### 评论区媒体")
            lines.append("")
            for item in comment_media:
                fn = item.get("filename", "")
                if not fn:
                    continue
                if item.get("kind") in {"video", "live"}:
                    lines.append(f"- [{fn}](./media/comments/{fn})")
                else:
                    lines.append(f"- ![](./media/comments/{fn})")
            lines.append("")

    return "\n".join(lines)


def save_entry(content: str, category: str, subcategory: str, filename: str) -> Path:
    """保存知识条目到知识库"""
    if category and subcategory:
        entry_dir = KB_ROOT / category / subcategory
    elif category:
        entry_dir = KB_ROOT / category
    else:
        entry_dir = KB_ROOT / "inbox"

    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / filename
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def copy_media_files(collector_output: dict, entry_dir: Path):
    """把 collector 下载的媒体文件复制到知识条目的 media 目录"""
    media_dir = entry_dir / "media"
    images = collector_output.get("images", [])
    videos = collector_output.get("videos", [])
    has_media = (
        any(img.get("local_path") for img in images)
        or any(vid.get("local_path") for vid in videos)
        or any(item.get("local_path") for item in collector_output.get("_comment_media", []))
    )
    if not has_media:
        return

    media_dir.mkdir(exist_ok=True)
    import shutil
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

    comment_media = collector_output.get("_comment_media", [])
    if comment_media:
        comment_dir = media_dir / "comments"
        comment_dir.mkdir(exist_ok=True)
        for item in comment_media:
            src = item.get("local_path", "")
            if src and os.path.isfile(src):
                dst = comment_dir / item.get("filename", os.path.basename(src))
                if not dst.exists():
                    shutil.copy2(src, dst)


def update_index(entry_path: Path, collector_output: dict, category: str, subcategory: str):
    """更新全局索引"""
    index_file = KB_ROOT / "index.json"
    index = []
    if index_file.exists():
        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            index = []

    entry = {
        "file": str(entry_path.relative_to(KB_ROOT)),
        "title": collector_output.get("title", ""),
        "source_url": collector_output.get("source_url", ""),
        "source_type": collector_output.get("source_type", ""),
        "category": category,
        "subcategory": subcategory,
        "collected_at": collector_output.get("extracted_at", ""),
    }

    # 避免重复（按 source_url 去重）
    index = [e for e in index if e.get("source_url") != entry["source_url"]]
    index.append(entry)

    # 按时间倒序
    index.sort(key=lambda x: x.get("collected_at", ""), reverse=True)

    index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Organizer - 知识库归档整理")
    parser.add_argument("input_json", nargs="?", help="collector 输出的 JSON 文件路径，或 - 从 stdin 读取")
    parser.add_argument("--category", "-c", help="一级分类（tech/product/life/reading/inspiration/inbox）")
    parser.add_argument("--subcategory", "-s", help="二级分类")
    parser.add_argument("--summary", help="AI 生成的摘要")
    parser.add_argument("--key-points", nargs="*", help="关键知识点列表")
    parser.add_argument("--tags", nargs="*", help="标签列表")
    parser.add_argument("--notes", help="用户自己的笔记")
    parser.add_argument("--list-categories", action="store_true", help="列出所有分类")
    parser.add_argument("--obsidian", action="store_true", help="同时写入 Obsidian vault")
    parser.add_argument("--obsidian-only", action="store_true", help="只写入 Obsidian vault（跳过 knowledge-base）")
    parser.add_argument("--no-obsidian", action="store_true", help="跳过 vault 写入")
    parser.add_argument("--init-obsidian", action="store_true", help="初始化 Obsidian 配置")
    parser.add_argument("--refresh-index", action="store_true", help="重建 vault 索引页（MOC + tag）")
    args = parser.parse_args()

    # Obsidian 初始化
    if args.init_obsidian:
        from obsidian import init_config_interactive
        init_config_interactive()
        return

    # 全量重建索引
    if args.refresh_index:
        from obsidian import load_config, refresh_all_moc, refresh_all_tags
        config = load_config()
        if not config:
            print("错误：未配置 Obsidian，请先运行 --init-obsidian", file=sys.stderr)
            sys.exit(1)
        vault_root = Path(config["obsidian_vault"])
        subdir = config.get("vault_subdir", "Collector")
        categories = load_categories()
        refresh_all_moc(vault_root, subdir, categories)
        refresh_all_tags(vault_root, subdir)
        print(json.dumps({"status": "ok", "message": "索引已重建"}, ensure_ascii=False))
        return

    if args.list_categories:
        cats = load_categories()
        for k, v in cats.get("categories", {}).items():
            label = v.get("label", k)
            subs = v.get("sub", {})
            if subs:
                sub_str = " / ".join(f"{sk}({sv})" for sk, sv in subs.items())
                print(f"  {k}: {label} → {sub_str}")
            else:
                print(f"  {k}: {label}")
        return

    # 以下操作需要 input_json
    if not args.input_json:
        parser.error("需要提供 collector 输出的 JSON 文件路径")

    # 读取 collector 输出
    if args.input_json == "-":
        data = json.load(sys.stdin)
    else:
        with open(args.input_json, encoding="utf-8") as f:
            data = json.load(f)
    data = enrich_comments(data, None if args.input_json == "-" else args.input_json)

    # 生成知识条目
    entry_md = build_knowledge_entry(
        data,
        category=args.category or "",
        subcategory=args.subcategory or "",
        summary=args.summary or "",
        key_points=args.key_points or [],
        tags=args.tags or [],
        my_notes=args.notes or "",
    )

    # 确定文件名
    title = data.get("title", "untitled")
    filename = generate_entry_filename(title, data.get("source_type", ""))

    # 确定分类
    category = args.category or "inbox"
    subcategory = args.subcategory or ""

    # 保存到 knowledge-base（除非 --obsidian-only）
    if not args.obsidian_only:
        entry_path = save_entry(entry_md, category, subcategory, filename)
        copy_media_files(data, entry_path.parent)
        update_index(entry_path, data, category, subcategory)
    else:
        entry_path = Path(filename)  # placeholder for output

    # Obsidian vault 同步
    use_obsidian = args.obsidian or (not args.no_obsidian and not args.obsidian_only)
    if use_obsidian:
        from obsidian import load_config, sync_to_vault
        config = load_config()
        if config and config.get("obsidian_output"):
            sync_to_vault(entry_md, data, category, subcategory, filename, config)

    print(json.dumps({
        "status": "ok",
        "entry_path": str(entry_path),
        "category": category,
        "subcategory": subcategory,
        "filename": filename,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
