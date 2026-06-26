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

四级 fallback：
1. **Jina Reader**（秒级）—— 云端 headless Chrome，覆盖 80% 公开内容
2. **直接 HTTP**（秒级）—— HTML 解析
3. **Scrapling**（秒级，可选）—— TLS 指纹伪装，绕过基础反爬
4. **CDP 浏览器**（十秒级）—— 连接用户本地 Chrome，复用登录态（需 web-access skill）

每级自动检测可用性，失败后自动降级到下一级。

### 输出格式

JSON，包含 title / content_md / images / videos / author / metadata 等字段。

### 图片笔记处理

小红书等平台的图片笔记，正文内容在图片里而非文字中。Collector 会：

1. **提取全部 swiper 图片**（去重，排除 `swiper-slide-duplicate` 克隆 slide，保证正确顺序）
2. **自动 OCR** 提取图片中的文字（需 tesseract + chi_sim 语言包）
3. **标记图片笔记**：`metadata.image_note: true`，body 短但图片多
4. **合并 OCR 文本**到 `content_md`，方便搜索和阅读

**Swiper Loop 注意事项**：小红书用无限循环模式，swiper 会把最后一张图克隆到 slide 0（开头），第一张图克隆到末尾。提取图片时必须跳过带 `swiper-slide-duplicate` class 的克隆 slide，否则顺序会错乱（最后一张排到最前面）。

Agent 处理图片笔记时，应将 OCR 文本视为主要内容，而非仅依赖 body 字段。

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

### 文件命名

归档的 md 文档**必须使用文章真实标题命名**，格式：`{日期}_{标题}.md`。标题提取优先级：og:title meta > h1 > 页面标题。Organizer 已自动处理。

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
4. **直接**调用 organizer 归档到知识库（无需询问用户确认）
5. 告知用户收录结果（标题、分类、关键知识点）

**自动归档原则**：收到链接后立即执行完整流水线（collector → organizer → 知识库），不要中途停下来问用户"要归档吗""分类放哪"。用户信任你来判断分类和摘要。

## Obsidian 集成

将笔记同步到 Obsidian vault，自动建立双向链接、MOC 索引和标签索引。

### 初始化

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/organizer.py" --init-obsidian
```

交互式配置 vault 路径和子目录名，配置保存到 `~/.collector-config.json`。

### 使用

```bash
# 归档到 knowledge-base + Obsidian vault
python3 "${CLAUDE_SKILL_DIR}/scripts/organizer.py" collector_output.json \
  --category tech --tags "AI-agent" --obsidian

# 只写入 Obsidian vault（跳过 knowledge-base）
python3 "${CLAUDE_SKILL_DIR}/scripts/organizer.py" collector_output.json \
  --category tech --tags "AI-agent" --obsidian-only

# 全量重建 vault 索引（MOC + tag 页面）
python3 "${CLAUDE_SKILL_DIR}/scripts/organizer.py" --refresh-index
```

### Vault 内部结构

```
{vault}/{vault_subdir}/
├── _MOC/           # 分类索引页（技术.md、产品.md…）
├── _Tags/          # 标签索引页（AI-agent.md、LLM.md…）
├── tech/ai-agent/  # 笔记按分类存放
├── tech/tools/
└── reading/
```

### 自动链接

收录新笔记时，自动扫描 vault 已有笔记，通过 tag 重叠和标题关键词匹配相关笔记，在"摘要"和"关键知识点"段落注入 `[[双向链接]]`。每篇最多 5 条链接。

## 文件结构

```
collector-skill/
├── SKILL.md
├── scripts/
│   ├── collector.py          # 内容提取入口（含 fallback 链）
│   ├── organizer.py          # 分类归档入口
│   ├── obsidian.py           # Obsidian vault 同步（双向链接、MOC、tag 索引）
│   └── extractors/
│       ├── web.py            # 网页提取（Jina + HTTP）
│       ├── wechat.py         # 微信文章
│       ├── xiaohongshu.py    # 小红书
│       ├── pdf_extract.py    # PDF
│       ├── media.py          # 媒体下载
│       ├── ocr.py            # 图片 OCR
│       ├── cdp_fetch.py      # CDP 浏览器（需 web-access）
│       └── scrapling_fetch.py # Scrapling TLS 指纹（可选）
└── references/
    ├── output-schema.json
    └── organizer-guide.md
```

知识库位置：`~/Her工作间/knowledge-base/`
