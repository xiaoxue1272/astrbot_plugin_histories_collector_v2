# AstrBot 全平台群消息收集器 V2 (ES 版)

将 AstrBot 所有平台的群消息完整保存到 Elasticsearch，支持媒体文件下载缓存、QQ 合并转发展开、嵌套深度控制。

## 特性

- 🚀 **全平台支持** — aiocqhttp / Telegram / Discord / Lark / WeChat 等全平台群消息
- 📦 **消息完整保存** — 解析消息链为结构化 JSON，保留所有组件类型
- 🖼️ **媒体文件下载** — 图片/视频/文件/语音自动下载并本地缓存，MD5 内容去重（碰撞时回退 SHA-256）
- 🔄 **QQ 合并转发展开** — 自动调用 OneBot API 展开 Forward 消息为 Node
- 🎯 **群组过滤** — 支持白名单/黑名单模式，按平台分别配置
- 🤖 **可选收集机器人消息** — 开启后机器人自己发出的群消息也会入库，便于统计对话全貌
- 📂 **文件分级存储** — `image/YYYY/MM/hash.ext` 结构，按类型分目录
- ⚡ **ES 断连健壮** — ES 不可用时插件正常启动，消息不积压不崩溃
- 🔍 **IK 中文分词** — 默认开启，要求 ES 安装 `analysis-ik` 插件，否则插件无法启动（非中文环境可关闭）

## 快速开始

### 依赖

```bash
pip install elasticsearch[async]==8.19.3 snowflake-id==1.0.2 aiohttp>=3.9.0
```

### 配置

> **先配置群组过滤，否则插件不会收集任何消息。**
> 默认 `group_filter.mode = whitelist` 且群组列表为空，此时所有群都不会被收集。
> 请在 `group_filter.platforms` 中按平台填写需要收集的群组 ID，或把模式改为 `blacklist` 收集列表以外的全部群。

在 AstrBot WebUI 中配置以下项：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `es_config.hosts` | ES 集群地址 | `http://localhost:9200` |
| `es_config.user` | ES 用户名 | — |
| `es_config.password` | ES 密码 | — |
| `es_config.alias` | 索引别名 | `message-histories-v2` |
| `es_config.use_ik_analyzer` | 开启 IK 分词（ES 必须安装 analysis-ik，否则插件无法启动） | `true` |
| `group_filter.mode` | 过滤模式：whitelist / blacklist | `whitelist` |
| `group_filter.platforms` | 按平台配置群组 ID | `[]` |
| `max_file_size_mb` | 下载文件大小上限(MB) | `50` |
| `max_nesting_depth` | 合并消息最大嵌套层数 | `3` |
| `collect_bot_message` | 收集机器人自己发送的群消息（`sender.id` 为机器人账号，`message_id` 为空） | `false` |

### 群组过滤说明

| 模式 | 列表为空时 | 列表非空时 |
|------|-----------|-----------|
| `whitelist`（默认） | 不收集任何群消息 | 只收集列表中的群 |
| `blacklist` | 收集所有群消息 | 排除列表中的群，其余照常收集 |

群组 ID 填写平台原始 ID（QQ 群号、Telegram chat id 等），平台名需与配置项下拉框中的取值一致（如 `aiocqhttp`）。

## ES 文档结构

### 顶层

```json
{
  "@timestamp": 1719676800000,
  "platform": "aiocqhttp",
  "platform_id": "qq_main",
  "message_id": 1781177174,
  "group": { "id": "123456", "name": "示例群名" },
  "sender": { "id": "10001", "name": "用户", "nickname": "QQ昵称" },
  "summary": "[图片] 你好",
  "types": ["image", "text"],
  "messages": [ ... ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `@timestamp` | date | 毫秒时间戳 |
| `platform` | keyword | 平台类型，如 `aiocqhttp` |
| `platform_id` | keyword | 平台实例 ID |
| `message_id` | keyword | 消息 ID |
| `group` | nested | `{id(keyword), name(keyword)}` |
| `sender` | nested | `{id(keyword), name(keyword), nickname(keyword)}`，`nickname` 仅部分平台提供 |
| `summary` | text | 消息摘要 |
| `types` | keyword | 消息包含的组件类型列表（去重） |
| `messages` | nested | 消息链详情数组，见下文 |

> 文档 `_id` 为 Snowflake（每次收集生成唯一 ID）。同一条消息被多个平台实例收到或重放时会写入多条文档，可按 `message_id` + `platform_id` + `group.id` 组合去重。

### messages 元素

所有字段扁平展开在元素层级，通过 `type` 区分组件类型；空值字段不会出现在 JSON 中。

**Plain（文本，type 为 `text`）**
```json
{ "type": "text", "text": "你好世界" }
```

**Image / Sticker（图片 / 动画表情）**
```json
{ "type": "image", "url": "https://...", "name": "abc.jpg", "path": "image/2026/07/abc.jpg" }
```

```json
{ "type": "sticker", "url": "https://...", "name": "xxx.png", "path": "sticker/png/xxx.png", "summary": "[动画表情]" }
```

**Mention / MentionAll（@）**
```json
{ "type": "mention", "id": "10001", "name": "昵称", "nickname": "群名片" }
```

```json
{ "type": "mention_all" }
```

**Reply（引用回复）**
```json
{ "type": "reply", "id": "msg_id", "sender_id": "10001", "sender_name": "用户", "sender_nickname": "群名片", "time": 1719676800, "messages": [ ... ] }
```

**Face（QQ 表情）**
```json
{ "type": "face", "id": "123" }
```

**Json（JSON 卡片）**
```json
{ "type": "json", "data": "{\"app\":\"com.tencent.miniapp\"}" }
```

**File / Video / Voice（文件 / 视频 / 语音）**
```json
{ "type": "file", "url": "https://...", "name": "doc.pdf", "path": "file/2026/07/abc.pdf" }
```

```json
{ "type": "video", "url": "https://...", "name": "a.mp4", "path": "video/2026/07/abc.mp4" }
```

```json
{ "type": "voice", "url": "https://...", "name": "a.amr", "path": "record/2026/07/abc.wav", "text": "语音转写文本" }
```

**Forward / Nodes / Node（合并转发）**
```json
{ "type": "forward", "id": "fwd_xxx", "summary": "(标题)", "messages": [ ... ] }
```

```json
{ "type": "nodes", "summary": "(标题)", "messages": [ ... ] }
```

```json
{ "type": "node", "sender": { "id": "10001", "name": "A", "nickname": "群名片" }, "messages": [ ... ], "time": 1719676800 }
```

**Share / Music（分享 / 音乐）**
```json
{ "type": "share", "url": "https://...", "title": "标题", "content": "描述", "image": "https://..." }
```

```json
{ "type": "music", "source": "qq", "id": "123", "url": "https://...", "audio": "https://...", "title": "歌名", "content": "歌手", "image": "https://..." }
```

> `warn`：媒体下载/缓存失败时出现在对应组件上的警告信息。
> `path`：媒体缓存的相对路径，根目录见「文件存储」。

## 文件存储

下载的媒体文件存储在 `data/plugin_data/astrbot_plugin_histories_collector_v2/`：

```
├── image/2026/07/a1b2c3d4.jpg
├── video/2026/07/e5f6a7b8.mp4
├── record/2026/07/c9d0e1f2.amr
└── file/2026/07/g3h4i5j6.pdf
```

- 目录按 `类型/年/月` 分级（`sticker` 按扩展名分目录）
- 文件名 = MD5(content)[:16] + 扩展名
- MD5 碰撞时自动回退 SHA-256 文件名
- ES 文档中记录的 `path` 是**相对路径**，读取时需拼接插件数据目录根：

```text
<AstrBot 数据目录>/plugin_data/astrbot_plugin_histories_collector_v2/<path>
```

## 深度控制

`max_nesting_depth` 控制 Node/Forward/Reply 消息的递归解析层数。超过限制时停止展开，只保留最外层标识：

- `Forward` / `Nodes` 只保留 `id` 和 `summary`，不再拉取子消息；
- `Reply` 只保留 `id`，不再获取被引用内容；
- 嵌套层级内的 `Node` 不再继续解析。

```json
{ "type": "forward", "id": "fwd_xxx", "summary": "(标题)" }
```

## 与 V1 的区别

| | V1 | V2 |
|---|----|----|
| 索引 | `qq_messages` | `message-histories-v2`（可配置） |
| 字段层级 | `messages.data.data.xxx`（三层） | `messages[].xxx`（扁平） |
| 文档 `_id` | — | Snowflake |
| 文件下载 | 不下载 | 自动下载并缓存 |
| Forward | 不处理 | 自动展开为 Node |
| 嵌套控制 | 无 | 支持 |
| ES 断连 | 插件崩溃 | 优雅降级（连接失败不阻塞启动） |

## 依赖

- Python 3.12+
- Elasticsearch 8.x
- AstrBot v4.x
