---
name: collector
description: 个人信息收集整理助手——接收链接/文件/文本，自动提取内容，输出统一格式的 Markdown + 元数据。
  触发场景：用户说"收录""保存这个""抓取这篇文章""把这个链接存下来"，或直接丢链接/文件路径。
---

# Collector Skill

信息收集的统一入口。接收任意来源，输出标准化内容。

## 使用方式

```bash
# 收录链接
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "https://mp.weixin.qq.com/s/xxxxx"

# 收录小红书
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "https://www.xiaohongshu.com/explore/xxxxx"

# 收录 PDF
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "/path/to/document.pdf"

# 收录纯文本
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" --text "要保存的文本内容"

# 指定输出目录（默认 ~/Her工作间/collected/）
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "https://example.com" --output-dir ~/Her工作间/collected
```

## 输入识别

脚本自动识别输入类型：

| 输入特征 | 类型 | 提取策略 |
|---------|------|---------|
| `mp.weixin.qq.com` | 微信文章 | WeChat extractor |
| `xiaohongshu.com` / `xhslink.com` | 小红书 | Xiaohongshu extractor |
| `.pdf` 结尾或 PDF 内容 | PDF 文档 | PDF extractor |
| 其他 URL | 普通网页 | Web extractor (Jina → CDP fallback) |
| `--text` 参数 | 纯文本 | 跳过提取，直接格式化 |

## 输出格式

JSON 输出到 stdout，包含：

```json
{
  "source_type": "wechat | xiaohongshu | pdf | webpage | text",
  "source_url": "原始链接",
  "title": "标题",
  "content_md": "正文 Markdown",
  "images": [{"url": "...", "alt": "...", "ocr_text": "..."}],
  "author": "作者",
  "published_at": "发布时间",
  "metadata": {},
  "extracted_at": "ISO 时间戳"
}
```

## 反爬策略

三级 fallback：
1. **Jina Reader**（秒级）—— 云端 headless Chrome，覆盖 80% 公开内容
2. **直接 HTTP**（秒级）—— cheerio / requests 解析
3. **CDP 浏览器**（十秒级）—— 连接用户本地 Chrome，复用登录态

## Agent 使用指南

1. 用户丢链接时，调用 collector 获取内容
2. 检查输出的 `content_md` 是否完整
3. 如果内容需要进一步整理（分类、摘要），交给 organizer 处理
4. 保存结果到 `~/Her工作间/collected/` 目录
