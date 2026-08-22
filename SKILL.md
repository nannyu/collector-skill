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

### 微信文章正文污染质量门槛

微信 HTTP 提取有时会在正文末尾附加整页 JavaScript、页面框架或广告脚本。归档前必须检查 `content_md`：若正文中出现大量 `localStorage`、`navigator.userAgent`、`function` 等页面脚本，不能直接交给 Organizer。

1. 保留 Collector 原始输出及其 `raw.json` 作为可复核证据，不覆盖或伪装为干净正文；
2. 仅在存在明确、可验证的文章结束标记时，生成单独的 `normalized.json` / 清洗版正文供 Organizer 使用，并记录删除范围与原因；
3. 若没有可靠结束边界，改用浏览器 DOM 回退提取，或明确标为提取污染失败；不得猜测截断位置；
4. 最终分类笔记必须验证不包含页面脚本，且图片、原始响应和清洗依据都保留在 archive。

### 小红书扫码登录与二次确认

小红书网页端扫码登录不应只依据手机端提示判断成功。部分账号在首次扫码后还会出现第二次扫码确认、网页端授权确认或安全验证；手机端显示“登录成功”时，网页端可能仍保留登录弹窗并限制完整评论。

处理流程：

1. 扫码后等待网页端登录弹窗自动消失，并确认页面不再显示“登录查看全部评论内容”；
2. 若手机端提示继续扫码/确认，必须完成第二次扫码或授权确认；
3. 只有网页端能够加载完整评论区后，才启动低频评论采集；
4. 二维码过期或扫码失败时，刷新当前登录弹窗重新截图，禁止复用旧二维码；
5. 采集器应把“登录后推荐”“登录查看全部评论内容”“扫码验证身份”等明确状态视为未登录，但不要用页面中普通的“登录”按钮文案误判限流；
6. 登录未真正同步前，不重复刷新短链、不启动全量采集，也不把当前可见评论冒充为全量结果。

### 国内网站直连与小红书网络前置

小红书及其他国内网站不得使用海外/云数据中心代理出口。开始采集前，先确认 Clash Verge/Mihomo 的规则满足：

- 小红书详情页、短链和媒体域名（`xiaohongshu.com`、`xhslink.com`、`xhslink.cn`、`xhscdn.com`）显式走 `DIRECT`；
- `GEOSITE,CN,DIRECT` 或等效中国域名直连规则必须排在 `gfw` / `proxy` 规则集之前；
- 直连 DNS、fake-IP 排除和 sniffer 跳过列表覆盖上述域名，避免国内域名解析/嗅探后重新落入代理；
- 用 Clash 日志/API 或无敏感信息的路由探针验证命中策略；仅看到网页能打开不等于使用了直连；
- 若出口仍显示海外云厂商 IP 或小红书返回 `300012`，停止刷新和重试，保留失败证据，不通过伪造请求绕过风控。

技能只记录路由策略与验证结果，不记录代理凭据、订阅内容或登录令牌。

### Agent Reach 平台原生增强

若本机已安装 `agent-reach`，Collector 会优先使用其中**已可用、只读**的原生后端处理下列 URL；结果仍输出为标准 Collector JSON，并记录 `metadata.fetcher: agent-reach`、平台和具体后端，随后照常进入媒体、OCR、archive 和 Organizer 流程。

| 来源 | 后端 | 采集范围 |
|------|------|----------|
| GitHub 仓库 | `gh api` | 仓库元数据与 README |
| V2EX 主题 | V2EX 公共 API | 正文与当前 API 返回的评论 |
| YouTube / B站视频 | `yt-dlp --dump-single-json` | 标题、描述、频道、时长与缩略图；默认不下载视频/字幕 |
| X / Twitter 单帖 | `xreach tweet` | 已有授权允许读取的正文 |

- 不适用于小红书、微信公众号：二者继续优先使用 Collector 的专用浏览器与归档流程，避免覆盖既有评论、媒体、OCR 和登录态规则。
- **禁止**在 Collector 中调用 `agent-reach configure --from-browser`，也不得导出、写入或归档 Cookie、Token、浏览器存储内容。
- 不启动 Docker、不安装可选渠道、不触发登录；后端不可用、无权限、超时或返回空内容时自动退回原有链路。
- 用 `--no-agent-reach` 可强制跳过此增强，便于复现旧提取路径或排障。

### 反爬策略
五级 fallback（平台原生增强仅对上述来源生效）：
1. **Agent Reach 原生后端**（秒级，可选）—— 已安装的公开/已授权只读渠道
2. **Jina Reader**（秒级）—— 云端 headless Chrome，覆盖 80% 公开内容
3. **直接 HTTP**（秒级）—— HTML 解析
4. **Scrapling**（秒级，可选）—— 仅用于公开页面的兼容性提取；不得启用或配置隐身、挑战绕过、指纹伪装等规避反爬能力
5. **CDP 浏览器**（十秒级）—— 连接用户已登录的本地 Chrome，以正常页面渲染和允许的交互完成采集（需 web-access skill）

每级自动检测可用性，失败后自动降级到下一级。

### 自动化稳定性、冷却与合规边界

将自动化访问视为**可观测、可恢复的浏览流程**，而不是“尽可能快地请求”。本节吸收了浏览器环境、行为节奏、状态持久化与失败退避的工程经验，但不允许通过隐藏自动化特征、伪造浏览器指纹或绕过平台访问控制来规避检测。

1. **优先级与授权**：优先使用公开 API、用户已登录的专用浏览器和平台允许的页面交互；遵守来源站点条款、robots 约束和用户授权范围。遇到登录墙、验证码、频控或明确禁止访问时，停止自动重试，记录状态并向用户说明。
2. **最小化采集**：只访问用户给出的目标链接及其完成任务必需的分页/评论资源；限制字段、媒体和评论采集范围，避免无目的遍历全站或批量打开页面。
3. **分层节奏**：在页面加载、滚动、展开评论和翻页之间采用低频、随机但有上限的等待；等待用于避免并发压力、让懒加载完成，不得作为伪装真人或绕过风控的手段。小红书默认沿用用户约定的低频节奏。
4. **断点与幂等**：长评论采集、分页或媒体下载必须写入可复用的 checkpoint，至少含来源 ID、已保存的稳定 ID、下一页/游标、已下载媒体和最后一次错误。重启后先读 checkpoint 去重续办，禁止从头高频重复。
5. **有限重试与冷却**：网络瞬断可以有限重试；连续出现 403、429、验证码、登录失效、“访问频繁”或无新增内容时立即停止当前循环，持久化失败原因并进入冷却。不得持续刷新、切换指纹或扩大并发来规避限制。
6. **状态卫生**：复用专用浏览器 profile 的正常登录态，但绝不导出、记录或在归档中写入 Cookie、Token、localStorage/sessionStorage 内容。任务结束关闭本次创建的标签页，保留用户已有页面；临时文件进入废纸篓，archive 和可复核 manifest 保留。
7. **数据质量验证**：分别记录页面显示总数、去重后已保存数、可见/折叠/不可访问内容数量及媒体下载状态。只有计数核对一致时才能称“完整”；否则明确标为 partial 并保留断点。

### 小红书视频：专用浏览器 → yt-dlp → ffprobe → Whisper

视频笔记必须先由本机小红书专用浏览器（9223 Profile）打开短链，取得可验证的详情页；详情页临时参数只在当前 `yt-dlp` 子进程中使用，**不得**写入 raw JSON、分类笔记或回复。随后按以下流水线执行：

1. `yt-dlp` 从完整详情页解析并下载视频；不导出 Cookie，不对 `xhscdn` 视频 URL 直接请求。
2. `ffprobe` 必须确认容器可读、存在视频流、时长大于 0 且文件非空。
3. Whisper 使用中文与领域提示词生成 `.srt`、`.txt`、`.json` 三种转写产物。
4. archive 保存视频和三种转写；Organizer 把它们复制到分类笔记的 `media/`，并生成“字幕与转写”链接。

任一步失败都必须分别写入 `metadata.video_status` / `transcript_status`；不得将已解析 URL、点击下载或只有简介文本说成视频/字幕已保存。

命令入口保持不变：

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/collector.py" "https://www.xiaohongshu.com/explore/..."
```

**完成判据：** archive 和分类笔记媒体目录中均存在可由 `ffprobe` 读取的视频，以及非空的 SRT、TXT、Whisper JSON；Markdown 的相对链接可用。

### 小红书正文图片：必须逐张触发懒加载并完整导出

**硬性规则（用户要求）：小红书图片禁止直接请求或使用 CDN URL。** 必须连接已登录的详情页浏览器上下文，逐张触发懒加载，并仅从浏览器原生网络响应导出本地文件。遇到 403、超时或响应读取失败时，保留失败证据和 manifest；不得把远程 CDN 链接、页面 URL 或截图冒充为已保存的正文原图。

对于图片笔记，不能只保存首屏图片或仅保存 DOM 中的 URL。正文图片完整下载必须遵循以下硬性流程：

1. 在详情页初始加载后，从 `.note-slider .swiper-slide[data-index]` / `.swiper-slide` 建立白名单；按 `data-index` 排序，排除所有 `swiper-slide-duplicate`，以 `max(data-index) + 1` 作为期望正文图片数，不根据当前已加载图片数估算。
2. 在 CDP 中先启用 `Network.enable`、`Network.setCacheDisabled({cacheDisabled:true})`，再刷新详情页；不得在页面已经加载完后才开始监听网络。
3. 通过详情页原生 Swiper 实例逐张调用 `swiper.slideTo(index)`，每张等待懒加载；必要时在同一页面上下文创建不带 `crossOrigin` 的 `new Image()` 预热同一 URL。禁止用 Node/Python 直接请求带签名的 CDN URL。
4. 只用 `Network.responseReceived` + `Network.getResponseBody` 导出白名单 URL 对应的成功 Image 响应；若资源在缓存中，使用 `Page.getResourceTree` + `Page.getResourceContent` 读取同一浏览器资源。URL 签名刷新时以当前 DOM 的 `currentSrc` 和对应请求为准。
5. 每个文件必须检查 MIME、非零字节并可由图像库解码；保存 `body-image-manifest.json`，记录 `expected_count`、每个 `data-index`、URL、文件、字节数和失败原因。
6. 只有 `expected_count == downloaded_count` 且全部文件验证通过时，才把 `metadata.image_download_status` 设为 `complete`，才可在回复中称“正文图片已全部保存”。浏览器截图只能作为明确标注的 `rendered_screenshot` 兜底，不能冒充原图。

若任一正文图缺失，状态必须是 `partial`，保留 manifest 和断点，禁止把部分图片交给 Organizer 后报告为完成。

### 小红书 CDN 403：使用已登录浏览器捕获原生响应

当页面能显示正文图片，但裸 CDN URL、Node/Python `GET` 或页面 `fetch()` 返回 `403` / `TypeError: Failed to fetch` 时，不要继续重试旧 URL，也不要只补 `User-Agent`、`Referer` 或伪造 Cookie。小红书图片 URL 可能包含短时效签名，并校验页面来源、浏览器会话和加载上下文。

按以下顺序处理：

1. **详情页先验证**：连接已登录的专用 Chrome CDP target，导航到目标短链/详情页；记录标题、笔记 ID 和正文轮播图片数。首页登录正常不能替代详情页验证。
2. **先取正文 DOM 清单**：从 `.swiper-slide img` / `.slide-item img` 读取 `currentSrc`，去重并排除 `swiper-slide-duplicate`、`avatar`、评论容器、登录弹窗、推荐区和尺寸小于正文图片的节点。这个清单是后续保存的白名单。
3. **预热延迟加载**：轮播图可能只有首图真正发起请求。对 DOM 白名单 URL 在页面上下文中创建 `new Image()` 并等待 `onload/onerror`，或逐张切换轮播；不要让 Node 进程直接请求 CDN。
4. **捕获 Network 响应**：开启 `Network.enable`，监听 `Network.responseReceived`，仅保留白名单 URL 对应的成功 Image 响应；用 `Network.getResponseBody(requestId)` 保存二进制。响应 URL 必须与正文白名单匹配，不能把头像、评论图和推荐图混入正文。
5. **验证后命名**：检查响应 MIME、文件大小和图片是否可解码；只有从浏览器 Network 响应保存的完整二进制才标记为“原图”。`Page.captureScreenshot` 只能标记为“浏览器渲染截图”，不能与原图混称。
6. **保留失败证据**：仍失败的 URL 写入 supplement/manifest，记录 `403`、超时或响应读取失败；不能创建空文件，也不能覆盖之前成功的媒体。最终报告分开列出原图、截图、失败项和 OCR 状态。

推荐的完成判据：正文 DOM 图片数 = 白名单数；每个白名单项都有非空文件；文件可被图像库解码；知识库 Markdown 的相对引用全部存在；原始 `raw.json` 和补抓 manifest 仍保留。若只能看到页面但不能导出响应，可逐张截图兜底并明确标注媒体来源。

**实战坑点**：不要在长时间滚动评论后才用当前页面的图片节点生成白名单；此时 DOM 可能已混入评论/推荐媒体，且正文签名 URL 可能已刷新。应在详情页初始加载后立即固定正文白名单，再在同一页面上下文预热这些 URL，最后只按白名单匹配 Network 响应。

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

每次收录自动保存原始素材到 `/Users/nn/Library/Mobile Documents/iCloud~md~obsidian/Documents/Niu/知识库/archive/`：

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

## 评论区与媒体整合（强制规则）

文章正文、完整评论区和评论区媒体必须归入同一个分类知识库文档，不能只把评论和媒体留在 `archive/`。Organizer 会在读取 `archive/<采集目录>/raw.json` 时自动发现并整合：

- `comments_full.md` / `comments.md` / `comments.txt`：原样追加到正文下方的 `## 评论区`
- JSON 中的 `comments` / `comments_full`：转换为可读 Markdown 后追加
- `media/comment_images/`、`media/comment_videos/` 和 `root_comment_media_progress.json`：复制到知识库文档旁的 `media/comments/`
- 评论区图片使用 `![](./media/comments/文件名)`，视频/Live 使用相对链接
- 重复执行按本地路径去重，保留 `archive/` 原始素材作为证据，但阅读入口是分类后的知识库文档

评论区采集完成后（状态为 `status: complete`），必须删除对应续采定时任务，避免空转。

## 历史归档迁移（强制规则）

历史文章也必须逐步迁移到“正文下方嵌入评论区内容/媒体”的统一格式，不能因为已经存在于 `archive/` 就认为完成。迁移时遵循以下原则：

1. **只新增、不破坏**：保留原知识库笔记、`archive/` 原始素材和已有人工摘要；不得删除或覆盖原始采集文件。
2. **统一阅读入口**：在原文章正文末尾追加 `## 评论区`，把历史笔记中已有的评论正文原样或最小转换后放入正文下方；不要只保留折叠区、摘要或 archive 路径。
3. **媒体随文嵌入**：从 `archive/<采集目录>/media/comment_images/`、`media/comment_videos/` 和续采进度文件中收集媒体，复制到对应知识库笔记旁的 `media/comments/`，在 `## 评论区` 下用相对路径嵌入。
4. **不补写缺失内容**：历史笔记或 archive 中没有的评论和媒体不得推测；应明确标注“未包含可提取内容”，并保留 archive 作为后续核查依据。
5. **幂等执行**：迁移脚本必须使用稳定标记（如 `<!-- collector-history-comments-migrated -->`）和媒体文件去重；重复执行不能重复追加评论区或复制同名媒体。
6. **先预览、后应用**：批量迁移先运行 dry-run/预览，确认目标笔记和 archive 一一对应，再使用 `--apply`；应用后逐篇检查标记、评论正文和媒体引用数量。

### 历史迁移命令

规范迁移脚本：

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/migrate_comment_archives.py"
python3 "${CLAUDE_SKILL_DIR}/scripts/migrate_comment_archives.py" --apply
```

该脚本当前针对已确认的历史归档映射运行。扩展迁移范围前，必须先建立“知识库笔记 → archive 目录”的明确映射，不能按标题模糊匹配后直接写入。

### iCloud Drive 操作注意事项

知识库位于 iCloud Drive 时，读取或写入文件可能暂时失败，常见错误包括 `Resource deadlock avoided`、`errno 11` 或文件仅存在 `dataless` 占位。遇到这些情况：

- 不要把临时读取失败当成内容缺失，也不要删除或重建笔记；
- 对单个文件采用有限次数、带间隔的重试，失败时记录该文件并继续其他文件；
- 若 Organizer 在 `index.json` 写入时持续报 `Resource deadlock avoided`，它可能已在此前成功写入分类笔记、媒体和 archive：先验证这些交付物，避免盲目重跑造成重复；将索引状态单独标记为暂时不可写，待 iCloud 解锁后再补写索引。
- `dataless` 文件先触发下载/等待本地内容可用，再读取和迁移；
- 批量写入应使用临时副本或原子替换，避免中途失败留下半截笔记；
- 批量任务中途被打断后，先检查迁移标记和末尾 `## 评论区`，再重试，禁止盲目重复追加；
- 最终报告必须区分 `migrated`、`already_migrated`、`missing_note`、`missing_archive` 和暂时不可读文件。

迁移完成后不要只检查脚本退出码；至少验证：目标笔记包含迁移标记、评论区位于正文末尾、媒体文件实际存在且 Markdown 相对路径可用，并确认 `archive/` 原始素材仍保留。

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
│   ├── migrate_comment_archives.py # 历史评论区/媒体迁移（预览 + 幂等应用）
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

知识库位置：`/Users/nn/Library/Mobile Documents/iCloud~md~obsidian/Documents/Niu/知识库/`
