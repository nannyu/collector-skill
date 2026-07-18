#!/usr/bin/env python3
from __future__ import annotations
"""
Obsidian 集成模块
将 collector/organizer 的输出同步到 Obsidian vault，支持双向链接、MOC 和标签索引
"""

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
CONFIG_PATH = Path.home() / ".collector-config.json"
KB_ROOT = Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Niu" / "知识库"


def load_config() -> dict | None:
    """加载 collector 配置"""
    if not CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_config(config: dict):
    """保存 collector 配置"""
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def init_config_interactive():
    """交互式初始化 Obsidian 配置"""
    print("=== Obsidian Vault 配置 ===\n")

    # 读取已有配置
    existing = load_config() or {}
    default_vault = existing.get("obsidian_vault", "")

    vault = input(f"Obsidian vault 路径 [{default_vault}]: ").strip()
    if not vault:
        vault = default_vault
    if not vault:
        print("错误：必须提供 vault 路径")
        return None

    vault_path = Path(vault).expanduser()
    if not vault_path.exists():
        create = input(f"目录不存在，是否创建？(y/n): ").strip().lower()
        if create == "y":
            vault_path.mkdir(parents=True, exist_ok=True)
        else:
            print("取消配置")
            return None

    default_subdir = existing.get("vault_subdir", "Collector")
    subdir = input(f"Vault 子目录名 [{default_subdir}]: ").strip() or default_subdir

    config = {
        "obsidian_vault": str(vault_path),
        "obsidian_output": True,
        "vault_subdir": subdir,
        "auto_link": True,
        "auto_moc": True,
        "auto_tag_index": True,
        "max_links_per_note": 5,
    }
    save_config(config)
    print(f"\n配置已保存到 {CONFIG_PATH}")
    print(f"Vault: {vault_path}")
    print(f"子目录: {subdir}/")
    return config


def parse_frontmatter(content: str) -> dict:
    """从 Markdown 内容中解析 YAML frontmatter（纯 regex，无 PyYAML 依赖）"""
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).split('\n'):
        if ':' in line:
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # 解析数组 tags: ["a", "b"]
            if val.startswith('[') and val.endswith(']'):
                inner = val[1:-1]
                fm[key] = [t.strip().strip('"').strip("'") for t in inner.split(',') if t.strip()]
            else:
                fm[key] = val
    return fm


def _vault_dir(config: dict) -> Path:
    """vault 内 collector 输出根目录"""
    return Path(config["obsidian_vault"]) / config.get("vault_subdir", "Collector")


def _normalize_title(title: str) -> str:
    """标准化标题用于匹配"""
    return re.sub(r'[^\w一-鿿]', '', title).lower()


def build_note_index(vault_root: Path, subdir: str) -> dict:
    """
    扫描 vault 中已有笔记，建立索引
    返回: { "norm_title": {"path": Path, "title": str, "tags": [str], "filename_stem": str} }
    """
    base = vault_root / subdir
    index = {}
    if not base.exists():
        return index

    skip_dirs = {"_MOC", "_Tags", "media", "archive"}

    for md_file in base.rglob("*.md"):
        # 跳过索引目录和 media 目录
        rel = md_file.relative_to(base)
        if any(part in skip_dirs for part in rel.parts):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            continue

        fm = parse_frontmatter(content)
        title = fm.get("title", md_file.stem)
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        norm = _normalize_title(title)
        if norm:
            index[norm] = {
                "path": md_file,
                "title": title,
                "tags": tags,
                "filename_stem": md_file.stem,
            }

    return index


def auto_link(content: str, note_index: dict, new_title: str, new_tags: list[str], max_links: int = 5) -> str:
    """
    在笔记内容中注入 [[wiki-links]]
    只修改"摘要"和"关键知识点"段落，不动折叠的原文内容
    """
    if not note_index:
        return content

    # 找到要注入的区域：从 "# {title}" 到 "<details>" 之间
    details_marker = "<details>"
    details_pos = content.find(details_marker)
    if details_pos == -1:
        injectable = content
    else:
        injectable = content[:details_pos]

    # 收集相关笔记：按匹配强度排序
    candidates = []
    new_norm = _normalize_title(new_title)

    for norm, info in note_index.items():
        if norm == new_norm:
            continue  # 跳过自己

        score = 0
        match_term = None

        # 1. 标题子串匹配（强）
        if new_norm in norm or norm in new_norm:
            score = 10
            match_term = info["title"]

        # 2. tag 重叠
        if not score and new_tags:
            overlap = set(new_tags) & set(info["tags"])
            if overlap:
                score = 5 + len(overlap)
                match_term = info["title"]

        # 3. 标题关键词匹配
        if not score:
            new_words = set(re.findall(r'[\w一-鿿]{2,}', new_title))
            existing_words = set(re.findall(r'[\w一-鿿]{2,}', info["title"]))
            common = new_words & existing_words
            if common:
                score = len(common)
                match_term = info["title"]

        if score > 0 and match_term:
            candidates.append((score, match_term, info["filename_stem"]))

    # 按分数降序，取 top N
    candidates.sort(key=lambda x: -x[0])
    candidates = candidates[:max_links]

    if not candidates:
        return content

    # 在可注入区域中替换关键词为 [[链接]]
    modified_injectable = injectable
    for _, term, stem in candidates:
        # 找到 term 在文本中的首次出现（排除已有的 [[ 和 frontmatter）
        # 只替换纯文本中的首次出现
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        # 跳过 frontmatter 区域
        fm_end = modified_injectable.find("---\n\n")
        if fm_end == -1:
            fm_end = 0
        else:
            fm_end += 5

        before = modified_injectable[:fm_end]
        after = modified_injectable[fm_end:]
        match = pattern.search(after)
        if match:
            link = f"[[{stem}|{match.group()}]]"
            after = after[:match.start()] + link + after[match.end():]
            modified_injectable = before + after

    # 重新组合
    if details_pos == -1:
        return modified_injectable
    else:
        return modified_injectable + content[details_pos:]


def write_to_vault(content: str, category: str, subcategory: str, filename: str, config: dict) -> Path | None:
    """写入 markdown 到 vault 目录"""
    vault_dir = _vault_dir(config)

    if category and subcategory:
        entry_dir = vault_dir / category / subcategory
    elif category:
        entry_dir = vault_dir / category
    else:
        entry_dir = vault_dir / "inbox"

    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / filename
    entry_path.write_text(content, encoding="utf-8")
    return entry_path


def copy_media_to_vault(collector_output: dict, entry_dir: Path):
    """复制媒体文件到 vault 目录"""
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


def refresh_moc(vault_root: Path, subdir: str, category: str, categories: dict):
    """刷新指定分类的 MOC 页面"""
    vault_dir = vault_root / subdir
    cat_info = categories.get("categories", {}).get(category, {})
    cat_label = cat_info.get("label", category)
    subs = cat_info.get("sub", {})

    moc_dir = vault_dir / "_MOC"
    moc_dir.mkdir(parents=True, exist_ok=True)
    moc_path = moc_dir / f"{cat_label}.md"

    now = datetime.now(CST).strftime("%Y-%m-%d")
    lines = [
        "---",
        f'title: "{cat_label}"',
        "type: moc",
        f"updated: {now}",
        "---",
        "",
        f"# {cat_label}",
        "",
    ]

    # 按 subcategory 分组
    cat_dir = vault_dir / category
    if cat_dir.exists():
        # 先处理有 subcategory 的笔记
        if subs:
            for sub_key, sub_label in subs.items():
                sub_dir = cat_dir / sub_key
                if sub_dir.exists():
                    notes = sorted(sub_dir.glob("*.md"))
                    if notes:
                        lines.append(f"## {sub_label}")
                        lines.append("")
                        for note in notes:
                            fm = parse_frontmatter(note.read_text(encoding="utf-8"))
                            title = fm.get("title", note.stem)
                            lines.append(f"- [[{note.stem}|{title}]]")
                        lines.append("")

        # 处理直接在 category 下的笔记（无 subcategory）
        direct_notes = [f for f in cat_dir.glob("*.md") if f.is_file()]
        if direct_notes:
            lines.append("## 其他")
            lines.append("")
            for note in sorted(direct_notes):
                fm = parse_frontmatter(note.read_text(encoding="utf-8"))
                title = fm.get("title", note.stem)
                lines.append(f"- [[{note.stem}|{title}]]")
            lines.append("")

    moc_path.write_text("\n".join(lines), encoding="utf-8")


def refresh_tag_page(vault_root: Path, subdir: str, tag: str, all_notes: list[dict]):
    """刷新单个 tag 索引页"""
    vault_dir = vault_root / subdir
    tags_dir = vault_dir / "_Tags"
    tags_dir.mkdir(parents=True, exist_ok=True)
    tag_path = tags_dir / f"{tag}.md"

    now = datetime.now(CST).strftime("%Y-%m-%d")
    lines = [
        "---",
        f'title: "{tag}"',
        "type: tag-index",
        f"updated: {now}",
        "---",
        "",
        f"# {tag}",
        "",
    ]

    for note in all_notes:
        stem = note["filename_stem"]
        title = note["title"]
        cat = note.get("category", "")
        sub = note.get("subcategory", "")
        location = f"{cat} > {sub}" if sub else cat
        lines.append(f"- [[{stem}|{title}]]{f' — {location}' if location else ''}")

    lines.append("")
    tag_path.write_text("\n".join(lines), encoding="utf-8")


def refresh_all_tags(vault_root: Path, subdir: str):
    """全量重建所有 tag 索引页"""
    base = vault_root / subdir
    skip_dirs = {"_MOC", "_Tags", "media", "archive"}
    tag_notes = {}  # tag -> [note_info, ...]

    for md_file in base.rglob("*.md"):
        rel = md_file.relative_to(base)
        if any(part in skip_dirs for part in rel.parts):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = parse_frontmatter(content)
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if not tags:
            continue
        title = fm.get("title", md_file.stem)
        note_info = {
            "title": title,
            "filename_stem": md_file.stem,
            "category": fm.get("category", ""),
            "subcategory": fm.get("subcategory", ""),
        }
        for tag in tags:
            tag_notes.setdefault(tag, []).append(note_info)

    # 清理旧 tag 页
    tags_dir = base / "_Tags"
    if tags_dir.exists():
        for old in tags_dir.glob("*.md"):
            old.unlink()

    # 写入新 tag 页
    for tag, notes in tag_notes.items():
        refresh_tag_page(vault_root, subdir, tag, notes)


def refresh_all_moc(vault_root: Path, subdir: str, categories: dict):
    """全量重建所有 MOC 页面"""
    for cat_key in categories.get("categories", {}):
        refresh_moc(vault_root, subdir, cat_key, categories)


def sync_to_vault(
    entry_md: str,
    collector_output: dict,
    category: str,
    subcategory: str,
    filename: str,
    config: dict,
):
    """
    主入口：将笔记同步到 Obsidian vault
    1. 写入笔记文件
    2. 复制媒体
    3. 构建索引 + 自动链接
    4. 刷新 MOC
    5. 刷新 tag 索引
    """
    vault_root = Path(config["obsidian_vault"])
    subdir = config.get("vault_subdir", "Collector")

    # 1. 写入笔记
    entry_path = write_to_vault(entry_md, category, subcategory, filename, config)
    if not entry_path:
        print(json.dumps({"error": "vault 写入失败"}, ensure_ascii=False), file=sys.stderr)
        return

    # 2. 复制媒体
    copy_media_to_vault(collector_output, entry_path.parent)

    # 3. 自动链接
    if config.get("auto_link", True):
        note_index = build_note_index(vault_root, subdir)
        new_title = collector_output.get("title", "")
        new_tags = collector_output.get("tags", []) if isinstance(collector_output.get("tags"), list) else []
        max_links = config.get("max_links_per_note", 5)

        linked_md = auto_link(entry_md, note_index, new_title, new_tags, max_links)
        if linked_md != entry_md:
            entry_path.write_text(linked_md, encoding="utf-8")

    # 4. 刷新 MOC
    if config.get("auto_moc", True):
        categories = {}
        cat_file = KB_ROOT / "categories.json"
        if cat_file.exists():
            categories = json.loads(cat_file.read_text(encoding="utf-8"))
        refresh_moc(vault_root, subdir, category, categories)

    # 5. 刷新 tag 索引
    if config.get("auto_tag_index", True):
        tags = collector_output.get("tags", []) if isinstance(collector_output.get("tags"), list) else []
        if tags:
            # 增量更新：只更新涉及的 tag
            base = vault_root / subdir
            skip_dirs = {"_MOC", "_Tags", "media", "archive"}
            tag_notes = {}

            for md_file in base.rglob("*.md"):
                rel = md_file.relative_to(base)
                if any(part in skip_dirs for part in rel.parts):
                    continue
                try:
                    content = md_file.read_text(encoding="utf-8")
                except OSError:
                    continue
                fm = parse_frontmatter(content)
                file_tags = fm.get("tags", [])
                if isinstance(file_tags, str):
                    file_tags = [file_tags]
                # 收集使用了当前 tag 的笔记
                if set(tags) & set(file_tags):
                    note_info = {
                        "title": fm.get("title", md_file.stem),
                        "filename_stem": md_file.stem,
                        "category": fm.get("category", ""),
                        "subcategory": fm.get("subcategory", ""),
                    }
                    for t in file_tags:
                        tag_notes.setdefault(t, []).append(note_info)

            for tag in tags:
                if tag in tag_notes:
                    refresh_tag_page(vault_root, subdir, tag, tag_notes[tag])

    print(json.dumps({
        "vault_path": str(entry_path),
        "category": category,
        "subcategory": subcategory,
    }, ensure_ascii=False, indent=2))
