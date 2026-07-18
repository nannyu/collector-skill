# Organizer 使用指南

## 工作流

```
用户丢链接 → collector 提取 → JSON → organizer 分类归档 → 知识库
```

## 两步走

### 第一步：collector 提取内容

```bash
python3 ~/Her工作间/collector-skill/scripts/collector.py "https://example.com" \
  --output-dir ~/Her工作间/collected
```

### 第二步：organizer 归档

Agent 读取 collector 的 JSON 输出后，调用 organizer：

```bash
python3 ~/Her工作间/collector-skill/scripts/organizer.py /tmp/extracted.json \
  --category tech \
  --subcategory ai-agent \
  --summary "这篇文章讲了..." \
  --key-points "要点1" "要点2" "要点3" \
  --tags "agent" "LLM" "architecture" \
  --notes "我的想法是..."
```

## 分类体系

| 一级分类 | 二级分类 | 适用内容 |
|---------|---------|---------|
| tech | web-dev | 前后端开发、框架、性能优化 |
| tech | ai-agent | AI Agent、LLM、RAG、prompt |
| tech | devops | 部署、CI/CD、监控 |
| tech | tools | 开发工具、效率工具 |
| product | design | 产品设计、UX、交互 |
| product | growth | 增长、运营、数据 |
| product | management | 项目管理、团队协作 |
| life | parenting | 育儿、亲子 |
| life | health | 健康、运动、饮食 |
| life | hobbies | 兴趣爱好 |
| reading | — | 读书笔记、文章精读 |
| inspiration | — | 灵感、想法、片段 |
| inbox | — | 待整理（不确定分类时） |

## Agent 分类指南

1. 读取内容，判断主题
2. 从 categories.json 选择最匹配的分类
3. 不确定 → 放 inbox
4. 提取 3-5 个关键知识点
5. 生成 2-3 句摘要
6. 加上用户自己的笔记/感想
7. 调用 organizer 脚本保存

## 知识库位置

```
/Users/nn/Library/Mobile Documents/iCloud~md~obsidian/Documents/Niu/知识库/
├── index.json          # 全局索引（可搜索）
├── categories.json     # 分类体系
├── tech/               # 技术类
├── product/            # 产品类
├── life/               # 生活类
├── reading/            # 阅读笔记
├── inspiration/        # 灵感收集
└── inbox/              # 待整理
```
