#!/usr/bin/env python3
"""将历史小红书评论区内容和媒体迁移到分类知识库笔记。

只新增/复制，不删除 archive 原始素材；重复执行具有幂等性。
"""
from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

MARKER = "<!-- collector-history-comments-migrated -->"
KB_ROOT = Path("/Users/nn/Library/Mobile Documents/iCloud~md~obsidian/Documents/Niu/知识库")
ARCHIVE_ROOT = Path("/Users/nn/Her工作间/knowledge-base/archive")

MIGRATIONS = [
    ("inbox/20260718_谁说第一届美臀大赛没人参加.md", "20260718_093001_谁说第一届美臀大赛没人参加_"),
    ("life/hobbies/20260718_大家说说看_妻子颜值太高是什么体验__男人的审美__妻子颜值.md", "20260718_100216"),
    ("life/hobbies/20260718_清凉吊带穿搭大赛_穿搭__夏日小吊带__女生穿衣自由__吊带穿搭__吊带内搭__这样穿超凉爽__今日快乐今日发__反差.md", "20260718_115920"),
    ("life/health/20260718_健身女请来.md", "20260718_143845_健身女请来"),
    ("life/health/20260718_身材就是这样练出来的.md", "20260718_164629_身材就是这样练出来的"),
    ("life/hobbies/20260718_美女.md", "20260718_164934_美女"),
    ("life/fashion/20260718_短裙到什么位置才是超短裙.md", "20260718_191818_短裙超短裙"),
    ("life/health/20260718_神奇的身体提高上臀线.md", "20260718_192126_神奇的身体"),
]


def _read_text_retry(path: Path) -> str:
    for attempt in range(31):
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            if getattr(exc, "errno", None) != 11 or attempt == 30:
                raise
            time.sleep(1.5)
    raise RuntimeError(f"unable to read {path}")


def _atomic_write_text(path: Path, content: str) -> None:
    """在目标目录内临时写入后替换，避免 iCloud 中途失败留下半截笔记。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def comment_body(note: str) -> str:
    """提取历史笔记中已有的当前可见评论内容，不凭空生成内容。"""
    start = note.find("<details>")
    end = note.find("</details>", start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return "历史笔记未包含可提取的评论正文；请以 archive 原始素材为准。"
    inner = note[start:end]
    for heading in ("## 当前可见评论", "当前可见评论摘要", "当前评论主要涉及", "当前评论涉及"):
        pos = inner.find(heading)
        if pos >= 0:
            return inner[pos:].strip()
    return inner.replace("<summary>", "### ").replace("</summary>", "").replace("<details>", "").strip()


def migrate(note_path: Path, archive_dir: Path, apply: bool) -> dict:
    if not note_path.is_file():
        return {"note": str(note_path), "status": "missing_note"}
    if not archive_dir.is_dir():
        return {"note": str(note_path), "status": "missing_archive"}

    text = _read_text_retry(note_path)
    media_sources = []
    for folder in ("media/comment_images", "media/comment_videos"):
        source_dir = archive_dir / folder
        if source_dir.is_dir():
            media_sources.extend(p for p in sorted(source_dir.iterdir()) if p.is_file())

    if MARKER in text:
        return {"note": str(note_path), "status": "already_migrated", "media": len(media_sources)}

    target_media = note_path.parent / "media" / "comments"
    links = [f"- ![](./media/comments/{src.name})" for src in media_sources]
    section = [
        "",
        MARKER,
        "## 评论区",
        "",
        "### 历史归档内容",
        "",
        comment_body(text),
        "",
    ]
    if links:
        section += ["### 评论区媒体", "", *links, ""]
    section.append("> 原始文件保留在对应的 `archive/` 目录；本节是分类知识库阅读入口。")
    new_text = text.rstrip() + "\n" + "\n".join(section) + "\n"

    if apply:
        target_media.mkdir(parents=True, exist_ok=True)
        for src in media_sources:
            dst = target_media / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
        _atomic_write_text(note_path, new_text)

    return {
        "note": str(note_path),
        "status": "migrated" if apply else "would_migrate",
        "media": len(media_sources),
        "comment_chars": len(comment_body(text)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只预览")
    args = parser.parse_args()
    results = []
    for relative_note, archive_name in MIGRATIONS:
        results.append(migrate(KB_ROOT / relative_note, ARCHIVE_ROOT / archive_name, args.apply))
    import json
    print(json.dumps({"apply": args.apply, "results": results}, ensure_ascii=False, indent=2))
    return 0 if all(r["status"] not in {"missing_note", "missing_archive"} for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
