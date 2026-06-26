# Collector Skill

个人信息收集整理助手 —— 接收链接/文件/文本，自动提取内容、下载媒体、分类归档到知识库。

## 功能

- **多源收录**：微信文章、小红书、知乎、PDF、普通网页、纯文本
- **智能提取**：自动识别输入类型，路由到最佳提取器
- **四级反爬**：Jina Reader → HTTP → Scrapling TLS 指纹 → CDP 浏览器（复用登录态）
- **媒体下载**：自动下载图片/视频，支持图片 OCR（tesseract）
- **分类归档**：自动分类、生成摘要、关键知识点提取，写入知识库
- **图片笔记**：小红书等平台的图片笔记，提取全部图片并 OCR，正确处理 swiper 循环顺序

## 快速开始

```bash
# 收录链接
python3 scripts/collector.py "https://mp.weixin.qq.com/s/xxxxx"

# 收录小红书
python3 scripts/collector.py "https://www.xiaohongshu.com/explore/xxxxx"

# 收录 PDF
python3 scripts/collector.py "/path/to/document.pdf"

# 收录纯文本
python3 scripts/collector.py --text "要保存的文本内容"

# 跳过媒体下载
python3 scripts/collector.py "https://example.com" --no-download
```

## 归档到知识库

```bash
python3 scripts/organizer.py collector_output.json \
  --category tech \
  --subcategory ai-agent \
  --summary "文章摘要..." \
  --key-points "要点1" "要点2" \
  --tags "agent" "LLM"
```

## 依赖

- Python 3.10+
- tesseract OCR（可选，用于图片文字识别）
  ```bash
  brew install tesseract
  brew install tesseract-lang  # 中文语言包
  ```
- Scrapling（可选，TLS 指纹伪装）
  ```bash
  pip3 install scrapling
  ```

## 目录结构

```
collector-skill/
├── SKILL.md                    # Her Skill 定义
├── scripts/
│   ├── collector.py            # 内容提取入口（含 fallback 链）
│   ├── organizer.py            # 分类归档入口
│   └── extractors/
│       ├── web.py              # 网页提取（Jina + HTTP）
│       ├── wechat.py           # 微信文章
│       ├── xiaohongshu.py      # 小红书
│       ├── pdf_extract.py      # PDF
│       ├── media.py            # 媒体下载
│       ├── ocr.py              # 图片 OCR
│       ├── cdp_fetch.py        # CDP 浏览器（需 web-access）
│       └── scrapling_fetch.py  # Scrapling TLS 指纹
└── references/
    ├── output-schema.json
    └── organizer-guide.md
```

## 反爬策略

四级 fallback，每级自动检测可用性，失败后自动降级：

| 级别 | 方式 | 速度 | 说明 |
|------|------|------|------|
| 1 | Jina Reader | 秒级 | 云端 headless Chrome，覆盖 80% 公开内容 |
| 2 | 直接 HTTP | 秒级 | HTML 解析 |
| 3 | Scrapling | 秒级 | TLS 指纹伪装，绕过基础反爬 |
| 4 | CDP 浏览器 | 十秒级 | 连接本地 Chrome，复用登录态 |

## 作为 Her Skill 使用

将此目录放入 Her 的 skills 目录，或通过 Her 安装器安装：

```bash
python3 .claude/tools/skill_installer.py install /path/to/collector-skill
```

触发词：收录、保存这个、抓取这篇文章、把这个链接存下来。

## License

MIT
