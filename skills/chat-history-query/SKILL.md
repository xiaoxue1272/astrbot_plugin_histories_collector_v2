---
name: chat-history-query
description: >
  当用户要求查询、搜索或分析历史群聊记录时使用。
  提供 ES 索引结构和 `search_es` 工具的使用指引。
---

# 聊天记录查询

## 工具

`search_es(body)`

- `body` — 标准 ES `_search` 请求体，直接透传给 ES。所有 ES `_search` API 参数（`query`、`sort`、`aggs`、`size`、`_source`、`track_total_hits` 等）均放 body 顶层。
- **务必显式指定 `size`**。概览类查询建议 `100`，含 `messages` 的详细查询建议 `20~50`。
- **务必使用 `_source` 控制返回字段**，节省 token。`messages` 字段数据量极大，仅在需要查看具体消息内容或按消息内字段搜索时才包含。概览类查询用 `["@timestamp", "summary", "sender", "group"]` 即可。
- 返回原始 ES 搜索结果 JSON。

### 群过滤规则

- **群聊场景**：工具代码层自动按当前群 ID 过滤，**不要在 body 里手动加 group 过滤**，否则会导致双重过滤。
- **私聊场景**：不会自动过滤。如果用户指定了群名或群号，需在 body 中自行添加 `group.name` 或 `group.id` 过滤：
  ```json
  {"query": {"nested": {"path": "group", "query": {"match": {"group.name": "xxx", "group.id": "123456789"}}}}}
  ```

## 大数据量总结策略

当数据量很大（数千条以上）时，不要仅靠采样 `hits` 来做总结。优先使用 ES 聚合在服务端完成统计，再对聚合结果做归纳：

1. **获取精确总数**：设置 `"track_total_hits": true`（ES 默认上限 10000）
2. **消息量趋势**：`date_histogram` 聚合 `@timestamp`，按天/小时统计
3. **高频关键词**：`significant_terms` 聚合 `summary` 字段
4. **活跃用户排名**：nested terms 聚合 `sender.name`，`size` 设 20~50
5. **消息类型分布**：nested terms 聚合 `messages.type`
6. **分时段抽样**：对每个时段用 `top_hits` + `_source` 取少量代表性消息（每个 bucket 取 3~5 条即可）

原则：让 ES 做统计，LLM 做归纳。不要试图把几千条消息拉回客户端再分析。

## 索引结构

### 顶层字段

| 字段 | 类型 | 说明 |
|-------|------|------|
| `@timestamp` | `date` | 毫秒时间戳，也接受 `"2026-07-10"` 字符串格式 |
| `platform` | `keyword` | 平台类型，如 `aiocqhttp`、`wecom` |
| `platform_id` | `keyword` | 平台实例 ID |
| `message_id` | `keyword` | 消息 ID |
| `summary` | `text` | 消息文本摘要（已包含 @、图片、语音等占位描述） |
| `types` | `keyword` | 消息包含的组件类型列表（去重），直接用 `term` 查询，无需 nested |
| `group` | `nested` | `{id(keyword), name(text)}` |
| `sender` | `nested` | `{id(keyword), name(keyword), nickname(keyword)}` |
| `messages` | `nested` | 解析后的消息链，见下表 |

### sender 字段说明

| 字段 | 含义 | 展示优先级 |
|------|------|-----------|
| `sender.name` | 用户全局昵称 | 兜底 |
| `sender.nickname` | 群昵称/群名片（仅部分平台支持） | **优先展示** |

> 展示发送者时优先用 `nickname`，不存在时回退到 `name`。

### `messages` 子字段

每条消息由 `type` 和对应字段组成，可递归嵌套（如 `forward` → `messages[]` → `node` → `messages[]`）：

| `type` | 有效字段 |
|--------|---------|
| `text` | `text` |
| `image` | `url`, `path`, `warn` |
| `sticker` | `url`, `path`, `summary`, `warn` |
| `video` | `url`, `path`, `warn` |
| `voice` | `url`, `path`, `text`, `warn` |
| `file` | `url`, `path`, `name`, `warn` |
| `mention` | `id`, `name` |
| `mention_all` | （无字段） |
| `reply` | `id`, `messages[]`, `sender_id`, `sender_name`, `sender_nickname`, `time` |
| `face` | `id` |
| `json` | `data` |
| `forward` | `id`, `summary`, `messages[]` |
| `nodes` | `summary`, `messages[]` |
| `node` | `sender`（`{id, name, nickname}`）, `messages[]`, `time` |
| `share` | `url`, `title`, `content`, `image` |
| `music` | `source`, `id`, `url`, `audio`, `title`, `content`, `image` |

> `warn`：媒体文件下载/缓存失败时的警告信息，仅在出错时出现。
> `summary` 在 `forward`/`nodes`/`sticker` 中为可选摘要文本。

## 注意事项

- `types` 是顶层 `keyword` 数组，用 `term` 查询无需 nested，比在 `messages` 内部搜索高效得多。优先使用。
- `group`、`sender`、`messages` 均为 `nested` 类型，查询时需用 `nested` query 包裹。
- `sender.name` 和 `sender.nickname` 均为 `keyword` 类型，可直接用于 `term` 查询和 `terms` 聚合。
- 聚合统计时设置 `"size": 0`，不需要 `_source`。
