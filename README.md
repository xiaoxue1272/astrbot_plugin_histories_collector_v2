# AstrBot 全平台群消息收集器 V2 (ES 版)

将 AstrBot 所有平台的群消息完整保存到 Elasticsearch，支持媒体文件下载缓存、QQ 合并转发展开、嵌套深度控制。

## 特性

- 🚀 **全平台支持** — aiocqhttp / Telegram / Discord / Lark / WeChat 等全平台群消息
- 📦 **消息完整保存** — 解析消息链为结构化 JSON，保留所有组件类型
- 🖼️ **媒体文件下载** — 图片/视频/文件/语音自动下载并本地缓存，SHA-256 内容去重
- 🔄 **QQ 合并转发展开** — 自动调用 OneBot API 展开 Forward 消息为 Node
- 🎯 **群组过滤** — 支持白名单/黑名单模式，按平台分别配置
- 📂 **文件分级存储** — `image/YYYY/MM/hash.ext` 结构，按类型分目录
- ⚡ **ES 断连健壮** — ES 不可用时插件正常启动，消息不积压不崩溃
- 🔍 **IK 中文分词** — 可选开启，支持中文全文搜索

## 快速开始

### 依赖

```bash
pip install elasticsearch[async]==8.19.3 snowflake-id==1.0.2 aiohttp>=3.9.0
```

### 配置

在 AstrBot WebUI 中配置以下项：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `es_config.hosts` | ES 集群地址 | `http://localhost:9200` |
| `es_config.user` | ES 用户名 | — |
| `es_config.password` | ES 密码 | — |
| `es_config.alias` | 索引别名 | `message-histories-v2` |
| `es_config.use_ik_analyzer` | 开启 IK 分词 | `true` |
| `group_filter.mode` | 过滤模式：whitelist / blacklist | `whitelist` |
| `group_filter.platforms` | 按平台配置群组 ID | `[]` |
| `max_file_size_mb` | 下载文件大小上限(MB) | `50` |
| `max_nesting_depth` | 合并消息最大嵌套层数 | `3` |

## ES 文档结构

### 顶层

```json
{
  "@timestamp": 1719676800000,
  "platform": "aiocqhttp",
  "platform_id": "napcat",
  "group": { "id": "123456", "name": "群名" },
  "sender": { "id": "10001", "name": "用户", "nickname": "QQ昵称" },
  "summary": "[图片] 你好",
  "details": [ ... ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `@timestamp` | date | 消息时间戳 |
| `platform` | keyword | 平台类型 |
| `platform_id` | keyword | 平台实例 ID |
| `group` | nested | 群信息 |
| `sender` | nested | 发送者信息（aiocqhttp 平台额外含 nickname） |
| `summary` | text | 消息摘要 |
| `details` | nested | 消息链详情数组 |

### details 元素

所有字段扁平展开在元素层级，通过 `type` 区分组件类型：

**Plain（文本）**
```json
{ "type": "plaintext", "text": "你好世界" }
```

**Image（图片）**
```json
{ "type": "image", "url": "https://...", "file": "...", "path": "/data/.../image/2026/07/abc.jpg" }
```

**At（@）**
```json
{ "type": "at", "qq": "10001" }
```

**Reply（引用回复）**
```json
{ "type": "reply", "id": "msg_id", "origin_summary": "被引用的消息内容" }
```

**File / Video / Record（文件/视频/语音）**
```json
{ "type": "file", "url": "https://...", "file": "...", "name": "doc.pdf", "path": "..." }
```

**Node（合并转发单条）**
```json
{
  "type": "node",
  "user_id": "10001",
  "nickname": "用户",
  "content": [ ... ]
}
```

**Forward（QQ 合并转发 — 展开后同 Node）**
```json
{
  "type": "Forward",
  "id": "fwd_xxx",
  "message": [
    { "user_id": "10001", "nickname": "A", "content": [...] },
    { "user_id": "10002", "nickname": "B", "content": [...] }
  ]
}
```

**Nodes（多条合并转发 — 展开后同 Node）**
```json
{
  "type": "Nodes",
  "message": [ ... ]
}
```

## 文件存储

下载的媒体文件存储在 `data/plugin_data/astrbot_plugin_histories_collector_v2/`：

```
├── image/2026/07/a1b2c3d4.jpg
├── video/2026/07/e5f6a7b8.mp4
├── record/2026/07/c9d0e1f2.amr
└── file/2026/07/g3h4i5j6.pdf
```

- 目录按 `类型/年/月` 分级
- 文件名 = MD5(content)[:16] + 扩展名
- MD5 碰撞时自动回退 SHA-256 文件名

## 深度控制

`max_nesting_depth` 控制 Node/Forward 消息的递归解析层数。超过限制时标记 `_truncated: true` 和 `_depth`：

```json
{ "type": "node", "_truncated": true, "_depth": 4 }
```

## 与 V1 的区别

| | V1 | V2 |
|---|----|----|
| 索引 | `qq_messages` | `message-histories-v2` |
| 字段层级 | `messages.data.data.xxx`（三层） | `details.xxx`（扁平） |
| 文件下载 | 不下载 | 自动下载并缓存 |
| Forward | 不处理 | 自动展开为 Node |
| 嵌套控制 | 无 | 支持 |
| ES 断连 | 插件崩溃 | 优雅降级 |

## 依赖

- Python 3.12+
- Elasticsearch 8.x
- AstrBot v4.x
