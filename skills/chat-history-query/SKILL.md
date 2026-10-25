---
name: chat-history-query
description: >
  当用户要求查询、搜索、统计或总结历史群聊记录时使用。
  提供 ES 索引结构、字段可检索性和 `search_es` 工具的完整使用指引，
  含常用查询模板与大数据量聚合策略。
---

# 聊天记录查询

## 工具

`search_es(body)`

- `body` — 标准 ES `_search` 请求体，直接透传给 ES。`query`、`sort`、`aggs`、`size`、`from`、`_source`、`track_total_hits` 等参数均放在 body 顶层。
- 返回原始 ES 搜索结果 JSON（`hits.hits[]._source` 是文档内容，`hits.hits[]._id` 是文档 ID）。

### 使用约束

- **务必显式指定 `size`**。概览类查询用 `100`，含 `messages` 的详细查询用 `20~50`；`from + size` 不要超过 `10000`（ES `max_result_window` 上限）。
- **务必用 `_source` 裁剪返回字段**。`messages` 数据量极大，只在需要查看具体消息内容时才包含；概览类查询用 `["@timestamp", "summary", "sender", "group"]`。
- 不要在 body 中使用 `script`、`script_fields` 等脚本类参数。

### 群过滤规则

- **群聊场景**：工具代码层会自动按当前群 ID 注入过滤，**不要在 body 里手动加 `group` 过滤**，否则会双重过滤。
- **私聊场景**：不会自动过滤。用户指定了群名或群号时，需在 body 中自行添加：

```json
{
  "query": {
    "bool": {
      "must": [
        {"match": {"group.name": "群名关键词"}},
        {"term": {"group.id": "123456789"}}
      ]
    }
  }
}
```

> `group.name` 是 `keyword` 类型：精确匹配用 `term`，模糊匹配用 `match` 或 `wildcard`（如 `{"wildcard": {"group.name": "*开发*"}}`）。

## 索引结构

### 顶层字段

| 字段 | 类型 | 说明 |
|-------|------|------|
| `@timestamp` | `date` | 毫秒时间戳（epoch_millis），ES 日期数学如 `now-7d` 同样可用 |
| `platform` | `keyword` | 平台类型，如 `aiocqhttp`、`telegram` |
| `platform_id` | `keyword` | 平台实例 ID |
| `summary` | `text` | 消息文本摘要（已包含 @、图片、语音等占位描述） |
| `types` | `keyword` | 消息包含的组件类型数组（去重），顶层字段，查询无需 nested |
| `group` | `nested` | `{id(keyword), name(keyword)}` |
| `sender` | `nested` | `{id(keyword), name(keyword), nickname(keyword)}` |
| `messages` | `nested` | 解析后的消息链，见下表 |

> 文档 `_id` 由 `platform_id:group_id:message_id` 组成，`_source` 不再保存 `message_id`；按消息 ID 精确取文档时使用 `GET <alias>/_doc/<_id>`。

### sender 字段说明

| 字段 | 含义 | 展示优先级 |
|------|------|-----------|
| `sender.name` | 用户全局昵称 | 兜底 |
| `sender.nickname` | 群昵称/群名片（仅部分平台支持） | **优先展示** |

### `messages` 子字段

每条消息由 `type` 和对应字段组成，可递归嵌套（如 `forward` → `messages[]` → `node` → `messages[]`）：

| `type` | 有效字段 |
|--------|---------|
| `text` | `text` |
| `image` | `url`, `name`, `path`, `warn` |
| `sticker` | `url`, `name`, `path`, `summary`, `warn` |
| `video` | `url`, `name`, `path`, `warn` |
| `voice` | `url`, `name`, `path`, `text`, `warn` |
| `file` | `url`, `name`, `path`, `warn` |
| `mention` | `id`, `name`, `nickname` |
| `mention_all` | （无字段） |
| `reply` | `id`, `messages[]`, `sender_id`, `sender_name`, `sender_nickname`, `time` |
| `face` | `id` |
| `json` | `data`（合法 JSON 字符串） |
| `forward` | `id`, `summary`, `messages[]` |
| `nodes` | `summary`, `messages[]` |
| `node` | `sender`（`{id, name, nickname}`）, `messages[]`, `time` |
| `share` | `url`, `title`, `content`, `image` |
| `music` | `source`, `id`, `url`, `audio`, `title`, `content`, `image` |

> `warn`：媒体文件下载/缓存失败时出现，仅在出错时存在。
> `summary` 在 `forward`/`nodes`/`sticker` 中为可选摘要文本。
> `path`：媒体缓存的**相对路径**，根目录为 `<AstrBot 数据目录>/plugin_data/astrbot_plugin_histories_collector_v2/`，读取文件时需自行拼接；下载失败时该字段不存在。

## 字段可检索性

| 可查询 | 不可查询（仅存在于 `_source`，能读取不能作为查询条件） |
|--------|------------------------------------------------------|
| `summary`（全文检索） | `messages[].text`（消息原文） |
| `types`（类型过滤） | `messages[].url` / `path` / `data` 等媒体与详情字段 |
| `group.id` / `group.name` | `messages[].sender` / `time` 等嵌套详情 |
| `sender.id` / `sender.name` / `sender.nickname` | |

实践含义：

- 想按**消息内容**搜索 → 用 `summary`（`match` / `match_phrase`）；
- 想按**消息类型**过滤（图片、语音、表情）→ 用顶层 `types` 的 `term` / `terms`，**不要**去查 `messages.type`；
- 想读取**具体消息链** → 只在 `_source` 里取 `messages`，且必须配合较小的 `size`。

## 常用查询模板

### 最近 N 条消息

```json
{"query": {"match_all": {}}, "sort": [{"@timestamp": "desc"}], "size": 10}
```

### 时间范围

```json
{
  "query": {"range": {"@timestamp": {"gte": "now-7d", "lte": "now"}}},
  "sort": [{"@timestamp": "desc"}],
  "size": 50
}
```

### 关键词搜索（summary 全文）

```json
{
  "query": {"match": {"summary": "关键词"}},
  "sort": [{"@timestamp": "desc"}],
  "size": 20
}
```

### 只看某类消息（图片 / 语音 / 表情 / 合并转发）

```json
{"query": {"terms": {"types": ["image", "sticker"]}}, "sort": [{"@timestamp": "desc"}], "size": 50}
```

`types` 可选值：`text`、`image`、`sticker`、`video`、`voice`、`file`、`mention`、`mention_all`、`reply`、`face`、`json`、`forward`、`nodes`、`node`、`share`、`music`。

### 某个用户的历史发言

```json
{
  "query": {
    "nested": {
      "path": "sender",
      "query": {"term": {"sender.id": "10001"}}
    }
  },
  "sort": [{"@timestamp": "desc"}],
  "size": 50
}
```

### 活跃用户排行

```json
{
  "size": 0,
  "aggs": {
    "top_users": {
      "nested": {"path": "sender"},
      "aggs": {
        "names": {
          "terms": {"field": "sender.name", "size": 20}
        }
      }
    }
  }
}
```

## 大数据量总结策略

数据量很大（数千条以上）时，不要仅靠采样 `hits` 做总结。优先用 ES 聚合在服务端完成统计，再对聚合结果归纳：

1. **获取精确总数**：设置 `"track_total_hits": true`（ES 默认上限 10000）
2. **消息量趋势**：`date_histogram` 聚合 `@timestamp`，按天/小时统计
3. **高频关键词**：`significant_terms` 聚合 `summary` 字段
4. **活跃用户排名**：`nested` + `terms` 聚合 `sender.name`，`size` 设 20~50
5. **消息类型分布**：`terms` 聚合顶层 `types` 字段（无需 nested）
6. **分时段抽样**：对每个时段用 `top_hits` + `_source` 取少量代表性消息（每个 bucket 3~5 条）

原则：让 ES 做统计，LLM 做归纳。不要试图把几千条消息拉回客户端再分析。

## 注意事项

- `group`、`sender`、`messages` 均为 `nested` 类型，查询时必须用 `nested` query 包裹；`types` 是顶层数组，直接 `term` / `terms` 即可。
- `keyword` 字段（`platform`、`platform_id`、`group.*`、`sender.*`、`types`）做精确匹配用 `term` / `terms`；用 `match` 会按整串匹配，`wildcard` 才支持通配符。
- 聚合统计时设置 `"size": 0`，不需要 `_source`。
- 展示发送者时优先用 `sender.nickname`，不存在时回退 `sender.name`。
- 私聊场景下该工具可以检索到所有群的数据，回答时注意不要泄露与当前对话无关的群信息。
