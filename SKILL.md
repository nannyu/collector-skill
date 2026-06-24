---
name: collector
description: 个人信息收集整理助手——接收链接/文件/文本，自动提取内容、下载媒体、分类归档到知识库。
  触发场景：用户说"收录""保存这个""抓取这篇文章""把这个链接存下来"，或直接丢链接/文件路径。
---

# Collector Skill

信息收集 + 知识归档的完整流水线。

## 完整工作流

```
用户丢链接/文件 → collector 提取 → organizer 分类归档 → 知识库
```

## 第一步：Collector（内容提取）

```bash
# 收录链接（自动下载图片/视频）
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "https://mp.weixin.qq.com/s/xxxxx"

# 收录小红书
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "https://www.xiaohongshu.com/explore/xxxxx"

# 收录 PDF
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "/path/to/document.pdf"

# 收录纯文本
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" --text "要保存的文本内容"

# 跳过媒体下载
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "https://example.com" --no-download

# 指定媒体保存目录
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "https://example.com" --media-dir ~/Her工作间/collected/media
```

### 输入识别

| 输入特征 | 类型 | 提取策略 |
|---------|------|---------|
| `mp.weixin.qq.com` | 微信文章 | Jina → HTTP 解析 |
| `xiaohongshu.com` / `xhslink.com` | 小红书 | Jina → SSR state → HTML |
| `.pdf` 结尾 | PDF 文档 | pdfplumber → pdftotext |
| 其他 URL | 普通网页 | Jina → HTTP |
| `--text` 参数 | 纯文本 | 直接格式化 |

### 反爬策略

三级 fallback：
1. **Jina Reader**（秒级）—— 云端 headless Chrome，覆盖 80% 公开内容
2. **直接 HTTP**（秒级）—— HTML 解析
3. **CDP 浏览器**（十秒级）—— 连接用户本地 Chrome，复用登录态（需 web-access skill）

### 输出格式

JSON，包含 title / content_md / images / videos / author / metadata 等字段。

### 原始素材归档

每次收录自动保存原始素材到 `~/Her工作间/knowledge-base/archive/`：

```
archive/
└── 20260624_143059_GitHub_-_eze-is_web-access/
    ├── raw.json       # collector 完整输出
    ├── content.md     # 纯正文 Markdown
    └── media/         # 原始图片/视频
```

跳过归档：`--no-archive`

## 第二步：Organizer（分类归档）

Agent 读取 collector 输出后，调用 organizer 归档到知识库：

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/organizer.py" collector_output.json \
  --category tech \
  --subcategory ai-agent \
  --summary "文章摘要..." \
  --key-points "要点1" "要点2" \
  --tags "agent" "LLM" \
  --notes "我的感想..."
```

### 分类体系

| 一级分类 | 二级分类 | 适用内容 |
|---------|---------|---------|
| tech | web-dev / ai-agent / devops / tools | 技术文章 |
| product | design / growth / management | 产品相关 |
| life | parenting / health / hobbies | 生活相关 |
| reading | — | 读书笔记 |
| inspiration | — | 灵感收集 |
| inbox | — | 待整理 |

不确定分类时放 inbox，后续再整理。

## Agent 使用指南

1. 用户丢链接 → 调用 collector 提取内容
2. 读取 collector 的 JSON 输出
3. 分析内容，确定分类、生成摘要和关键知识点
4. 调用 organizer 归档到知识库
5. 告知用户收录结果

## 文件结构

```
collector-skill/
├── SKILL.md
├── scripts/
│   ├── collector.py          # 内容提取入口
│   ├── organizer.py          # 分类归档入口
│   └── extractors/
│       ├── web.py            # 网页提取
│       ├── wechat.py         # 微信文章
│       ├── xiaohongshu.py    # 小红书
│       ├── pdf_extract.py    # PDF
│       ├── media.py          # 媒体下载
│       └── ocr.py            # 图片 OCR
└── references/
    ├── output-schema.json
    └── organizer-guide.md
```

知识库位置：`~/Her工作间/knowledge-base/`
