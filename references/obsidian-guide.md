# Obsidian 集成指南

## 概述

将 collector 的归档输出同步到 Obsidian vault，自动建立双向链接、MOC（内容地图）索引和标签索引。

## 配置

配置文件位于 `~/.collector-config.json`：

```json
{
  "obsidian_vault": "/path/to/your/vault",
  "obsidian_output": true,
  "vault_subdir": "Collector",
  "auto_link": true,
  "auto_moc": true,
  "auto_tag_index": true,
  "max_links_per_note": 5
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `obsidian_vault` | Obsidian vault 根目录的绝对路径 |
| `obsidian_output` | 总开关，false 则跳过所有 vault 操作 |
| `vault_subdir` | vault 内的子目录名（默认 Collector），避免与用户现有笔记冲突 |
| `auto_link` | 自动注入双向链接 |
| `auto_moc` | 自动生成/更新 MOC 索引页 |
| `auto_tag_index` | 自动生成/更新标签索引页 |
| `max_links_per_note` | 每篇笔记最多注入的链接数（默认 5） |

## 初始化

```bash
python3 scripts/organizer.py --init-obsidian
```

交互式引导：输入 vault 路径 → 输入子目录名 → 配置写入 `~/.collector-config.json`。

## 日常使用

### 归档到 vault

```bash
# 同时写入 knowledge-base 和 vault
python3 scripts/organizer.py collector_output.json \
  --category tech --tags "AI-agent" --obsidian

# 只写 vault
python3 scripts/organizer.py collector_output.json \
  --category tech --tags "AI-agent" --obsidian-only
```

### 重建索引

```bash
python3 scripts/organizer.py --refresh-index
```

全量重建所有 MOC 页面和标签索引页。适用于首次迁移或修复索引。

## Vault 内部结构

```
{vault}/Collector/
├── _MOC/                           # MOC 索引页
│   ├── 技术.md                      # tech 分类索引
│   ├── 产品.md                      # product 分类索引
│   ├── 生活.md                      # life 分类索引
│   ├── 阅读笔记.md                   # reading 分类索引
│   ├── 灵感收集.md                   # inspiration 分类索引
│   └── 待整理.md                     # inbox 分类索引
├── _Tags/                           # 标签索引页
│   ├── AI-agent.md
│   ├── LLM.md
│   └── ...
├── tech/
│   ├── ai-agent/
│   │   └── 20260626_为什么感觉现在AI_Agent都是雷声大雨点小.md
│   └── tools/
│       └── 20260625_微信公众平台.md
├── reading/
│   └── 20260626_美国是不是已经具备了亡国的所有条件.md
└── ...
```

## 自动链接机制

每次收录新笔记时，系统自动：

1. **扫描已有笔记**：遍历 vault 中所有笔记，提取标题和标签建立索引
2. **匹配相关笔记**：
   - 标题子串匹配（强关联）
   - 标签重叠匹配
   - 标题关键词匹配
3. **注入链接**：在新笔记的"摘要"和"关键知识点"段落，将匹配到的关键词替换为 `[[文件名|显示名]]` 格式的双向链接
4. **数量限制**：每篇笔记最多注入 N 条链接（由 `max_links_per_note` 控制）

### 示例

收录一篇关于 AI Agent 的文章后，vault 中的笔记内容：

```markdown
## 摘要

这篇文章分析了 [[20260626_为什么感觉现在AI_Agent都是雷声大雨点小|AI Agent 落地难]] 的核心原因...

## 关键知识点

- [[20260625_沃什路线推演|宏观环境]] 对科技资产的影响
- Agent 产品化的技术瓶颈
```

## MOC 索引页

每个分类自动生成一个 MOC 页面（如 `_MOC/技术.md`），列出该分类下所有笔记的双向链接，按子分类分组。

```markdown
---
title: "技术"
type: moc
updated: 2026-06-27
---

# 技术

## AI Agent
- [[20260626_为什么感觉现在AI_Agent都是雷声大雨点小|为什么感觉现在AI Agent都是雷声大雨点小]]
- [[20260625_沃什路线推演|沃什路线推演：如果美国真的要化债，未来会怎样]]

## 工具链
- [[20260625_微信公众平台|微信公众平台]]
```

## 标签索引页

每个使用的标签自动生成索引页（如 `_Tags/AI-agent.md`），列出所有带该标签的笔记。

```markdown
---
title: "AI-agent"
type: tag-index
updated: 2026-06-27
---

# AI-agent

- [[20260626_为什么感觉现在AI_Agent都是雷声大雨点小|为什么感觉现在AI Agent都是雷声大雨点小]] — 技术 > AI Agent
- [[20260625_沃什路线推演|沃什路线推演：如果美国真的要化债，未来会怎样]] — 技术 > AI Agent
```

## 向后兼容

- 不传 `--obsidian` 且无配置文件 → 行为与未安装 Obsidian 集成完全一致
- `knowledge-base` 写入始终执行（除非 `--obsidian-only`）
- 配置文件缺失 → vault 操作静默跳过，不影响正常归档
