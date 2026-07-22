---
name: chat-history-query
description: >
  当用户要求查询、搜索或分析历史群聊记录时使用。
  提供 ES 索引结构和 `search_es` 工具的使用指引。
---

# 聊天记录查询

## 工具

`search_es(body)`

- `body` — 标准 ES `_search` 请求体，直接透传给 ES。
- **务必在 body 中显式指定 `size`**。概览类查询建议 `100`，含 `messages` 的详细查询建议 `20~50`。
- 返回原始 ES 搜索结果 JSON。
- **群聊限定**：工具代码层自动按当前群 ID 过滤，**不要在 body 里手动加 `group.id` 或 `group.name` 过滤**，否则会导致双重过滤。
- **务必使用 `_source` 控制返回字段，节省 token**（见下方决策规则）。

### `_source` 决策规则

`messages` 字段包含完整消息链（嵌套结构），数据量极大。根据用户意图决定是否包含：

| 用户意图 | `_source` 写法 | 原因 |
|---------|---------------|------|
| 了解最近在聊什么、话题概览 | `["@timestamp", "summary", "sender", "group"]` | `summary` 已概括每条消息的内容 |
| 查看具体说了什么、原文 | 加上 `"messages"` | 需要查看完整消息细节 |
| 查找图片/视频/语音/文件/@/回复 | 加上 `"messages"` | 媒体类型信息在 `messages` 内 |
| 按消息类型搜索 | 加上 `"messages"` | 查询字段在 `messages` 内，结果也需要返回 |
| 统计/聚合 | 不需要 `_source`（`size: 0`） | 聚合不返回 hits |

> **原则**：能满足用户需求的最小字段集。不确定时先不加 `messages`，后续可按需再查。

## Body 结构

所有字段均为 body **顶层平级**，不可互相嵌套：

```json
{
  "query": { ... },
  "sort": [ ... ],
  "aggs": { ... },
  "size": 100,
  "_source": ["@timestamp", "summary", "sender", "group"]
}
```

> `track_total_hits` 等 ES `_search` API 参数同理，直接放 body 顶层。

## 索引结构

### 顶层字段

| 字段 | 类型 | 说明 |
|-------|------|------|
| `@timestamp` | `date` | 接受 `"2026-07-10"` 字符串格式 |
| `platform` | `keyword` | 支持：`aiocqhttp`、`wecom` |
| `platform_id` | `keyword` | 平台实例 ID |
| `message_id` | `keyword` | 消息 ID |
| `summary` | `text` | 消息文本摘要 |
| `types` | `keyword` | 消息包含的组件类型列表（去重），可直接 `term` 查询 |
| `group` | `nested` | `{id, name}` |
| `sender` | `nested` | `{id, name, nickname}`（nickname 仅部分平台支持） |
| `messages` | `nested` | 解析后的消息链，见下表 |

### `messages` 子字段

每条消息由 `type` 和对应字段组成，可递归嵌套（如 `Forward` → `messages[]` → `Node` → `messages[]`）：

| `type` | 有效字段 |
|--------|---------|
| `plain` | `text` |
| `image` | `url`, `path`, `sub_type`, `summary` |
| `video` | `url`, `path` |
| `record` | `url`, `path`, `text` |
| `file` | `url`, `path` |
| `at` | `qq` |
| `reply` | `id`, `summary` |
| `face` | `id` |
| `json` | `data` |
| `forward` | `id`, `messages[]` |
| `nodes` | `messages[]` |
| `node` | `user_id`, `nickname`, `messages[]` |


## 查询示例

### 查询模式速查

| 场景 | 查询方式 |
|------|---------|
| 文本搜索 | `{"match": {"summary": "搜索词"}}` |
| 精确匹配 | `{"term": {"platform": "aiocqhttp"}}` |
| 按消息类型 | `{"term": {"types": "image"}}` — 用顶层 `types` 字段，比 nested 更高效 |
| Nested 搜索 | `{"nested": {"path": "sender", "query": {"match": {"sender.name": "xxx"}}}}` |
| 时间范围 | `{"range": {"@timestamp": {"gte": "2026-07-01", "lte": "2026-07-10"}}}` |
| bool 组合 | `{"bool": {"must": [...], "filter": [...], "should": [...]}}` |
| 排序 | `"sort": [{"@timestamp": "desc"}]` — **放在 body 顶层** |

### 关键词搜索

同时搜索 `summary` 和 `messages.text`，需要包含 `messages` 字段：

```json
{
  "query": {
    "bool": {
      "should": [
        {"match": {"summary": "关键词"}},
        {"nested": {"path": "messages", "query": {"match": {"messages.text": "关键词"}}}}
      ]
    }
  },
  "sort": [{"@timestamp": "desc"}],
  "size": 50,
  "_source": ["@timestamp", "summary", "sender", "group", "messages"]
}
```

### 按发送者过滤

模糊昵称：`nested` + `match` 匹配 `sender.nickname`

```json
{
  "query": {
    "nested": {"path": "sender", "query": {"match": {"sender.nickname": "昵称"}}}
  },
  "size": 100,
  "_source": ["@timestamp", "summary", "sender", "group"]
}
```

精确 ID：`nested` + `term` 匹配 `sender.id`

```json
{
  "query": {
    "nested": {"path": "sender", "query": {"term": {"sender.id": "123456789"}}}
  },
  "size": 100,
  "_source": ["@timestamp", "summary", "sender", "group"]
}
```

> `sender.name` 同理，用 `match`/`term` 均可。

### 按平台 / 消息 ID 过滤

```json
{"query": {"term": {"platform": "aiocqhttp"}}, "size": 100, "_source": ["@timestamp", "summary", "sender", "group"]}
```

```json
{"query": {"term": {"platform_id": "NapCatQQ"}}, "size": 100, "_source": ["@timestamp", "summary", "sender", "group"]}
```

```json
{"query": {"term": {"message_id": "msg_id"}}, "size": 50, "_source": ["@timestamp", "summary", "sender", "group", "messages"]}
```

### 按群名过滤

> 仅私聊场景使用。群聊中工具已自动限定当前群，**勿加此过滤**。

```json
{
  "query": {
    "nested": {"path": "group", "query": {"match": {"group.name": "群名称"}}}
  },
  "size": 100,
  "_source": ["@timestamp", "summary", "sender", "group"]
}
```

### 时间范围

```json
{
  "query": {
    "bool": {
      "filter": [{"range": {"@timestamp": {"gte": "2026-07-01", "lte": "2026-07-10"}}}]
    }
  },
  "sort": [{"@timestamp": "desc"}],
  "size": 100,
  "_source": ["@timestamp", "summary", "sender", "group"]
}
```

### 按消息类型搜索

**推荐用顶层 `types` 字段**（无需 nested，性能更好）：

```json
{
  "query": {"term": {"types": "image"}},
  "sort": [{"@timestamp": "desc"}],
  "size": 50,
  "_source": ["@timestamp", "summary", "sender", "group", "messages"]
}
```

如需在 `messages` 内部嵌套搜索（如 Forward 子消息），用 nested：

```json
{
  "query": {
    "nested": {"path": "messages", "query": {"term": {"messages.type": "image"}}}
  },
  "sort": [{"@timestamp": "desc"}],
  "size": 50,
  "_source": ["@timestamp", "summary", "sender", "group", "messages"]
}
```

支持的 type：`plain`、`image`、`video`、`record`、`file`、`at`、`reply`、`forward`、`face`、`json`、`nodes`、`node`。

> 如需同时匹配多个 type，用 `bool` + `should`：
> ```json
> {
>   "nested": {
>     "path": "messages",
>     "query": {"bool": {"should": [
>       {"term": {"messages.type": "image"}},
>       {"term": {"messages.type": "video"}}
>     ]}}
>   }
> }
> ```

### 组合查询：关键词 + 发送者 + 时间

```json
{
  "query": {
    "bool": {
      "must": [{"match": {"summary": "关键词"}}],
      "filter": [
        {"range": {"@timestamp": {"gte": "2026-07-01"}}},
        {"nested": {"path": "sender", "query": {"term": {"sender.id": "123456789"}}}}
      ]
    }
  },
  "sort": [{"@timestamp": "desc"}],
  "size": 100,
  "_source": ["@timestamp", "summary", "sender", "group"]
}
```

### 聚合统计：按消息类型计数

```json
{
  "size": 0,
  "query": {"range": {"@timestamp": {"gte": "2026-07-01"}}},
  "aggs": {
    "by_type": {
      "nested": {"path": "messages"},
      "aggs": {
        "types": {"terms": {"field": "messages.type", "size": 50}}
      }
    }
  }
}
```

### 聚合统计：每日消息数

```json
{
  "size": 0,
  "query": {"range": {"@timestamp": {"gte": "2026-07-01"}}},
  "aggs": {
    "daily": {
      "date_histogram": {"field": "@timestamp", "calendar_interval": "day"}
    }
  }
}
```

### 聚合统计：按发送者消息数

```json
{
  "size": 0,
  "query": {"range": {"@timestamp": {"gte": "2026-07-01"}}},
  "aggs": {
    "by_sender": {
      "nested": {"path": "sender"},
      "aggs": {
        "senders": {"terms": {"field": "sender.nickname", "size": 50}}
      }
    }
  }
}
```
