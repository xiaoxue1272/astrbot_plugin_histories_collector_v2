# astrbot_plugin_histories_collector_v2 — 设计文档

> **状态**：待审计
> **版本**：v0.1.0（全新实现）
> **前置依赖**：Elasticsearch 8.x + AstrBot v4.x

---

## 1. 目标与定位

### 1.1 改造目标

将 v1（`astrbot_plugin_histories_collector`）从 **仅支持 QQ（aiocqhttp）** 升级为 **AstrBot 全平台群消息持久化插件**。

| 维度 | v1（现版本） | v2（目标） |
|---|---|---|
| 支持平台 | 仅 aiocqhttp (QQ) | AstrBot 全部 21 个平台适配器 |
| 消息类型 | 仅群消息 `GROUP_MESSAGE` | 仅群消息 `GROUP_MESSAGE`（同 v1） |
| 过滤粒度 | 平台 + 事件类型 | 仅事件类型（平台由 `ALL` 通配） |
| 群过滤 | `enable_groups: list[str]` 单一白名单 | `group_filter`：黑白名单模式可切换 + 各平台独立配置 |
| ES 索引 | `qq_messages` 硬编码 | 可配置 `alias`，默认 `message-histories-v2`（加 V2 后缀） |
| sender 字段 | `id`(int) + `name` + `nickname` | `id`(str) + `name`（单字段，放弃 QQ 群名片） |
| group ID 类型 | `int`（QQ 数字） | `str`（keyword，跨平台兼容） |

### 1.2 丢失细节评估

**唯一丢失项：QQ 群名片（card）**。QQ 有双重身份概念——QQ 昵称（跨群不变）和群名片（逐群不同），其他平台仅有一个 display name，`event.get_sender_name()` 返回的即是该值。对于历史检索场景，单一 `sender.name` 字段更利于跨平台聚合查询。

其它字段均有跨平台一等公民替代：

| v1 字段 | v2 替代 | 说明 |
|---|---|---|
| `raw_message["time"]` | `event.message_obj.timestamp` | `AstrBotMessage` 基类字段 |
| `raw_message["sender"]["user_id"]` | `event.get_sender_id()` | 基类方法 |
| `sender["nickname"]` | `event.get_sender_name()` | 基类方法 |
| `event.bot.get_group_member_info(...)` | 不需要 | `get_sender_name()` 已足够 |

---

## 2. 目录结构

```
astrbot_plugin_histories_collector_v2/
├── DESIGN.md            # 本文件
├── metadata.yaml        # 插件元数据
├── _conf_schema.json    # WebUI 配置 Schema
├── requirements.txt     # 依赖声明
├── main.py              # 插件入口：注册 + 生命周期 + 事件监听 + ES document 构建
├── message_parser.py    # 消息链递归解析（从 main.py 抽出）
├── group_filter.py      # 群组过滤器：黑白名单模式 + 各平台独立配置
├── es_helper.py         # ES 连接管理 + 索引生命周期 + 写入
├── config.py            # 配置数据类
└── README.md            # 用户文档
```

**模块划分原则**：

| 模块 | 职责 | 变更说明 |
|---|---|---|
| `main.py` | `@register` 注册、生命周期、事件监听、组装 ES document | 提纯：消息解析和群过滤均抽出 |
| `message_parser.py` | `parse_message_chain()` 递归解析消息链 | 从 main.py 独立抽取 |
| `group_filter.py` | `GroupFilter` 类：模式切换 + 各平台群 ID 匹配 | 新增，策略模式 |
| `es_helper.py` | ES 客户端管理、ILM 策略、索引模板、消息写入、连接关闭 | 改名 `helper.py` → `es_helper.py` |
| `config.py` | `ESConfig` + `GroupFilterConfig` + `HistoriesCollectorConfig` 数据类 | 重构：支持 group_filter 结构 |

---

## 3. ES 数据模型

### 3.1 Document 结构

```json
{
  "_id": "<snowflake_id>",

  "@timestamp":    1719600000000,
  "platform":      "aiocqhttp",
  "platform_id":   "aiocqhttp_0",
  "message_type":  "GroupMessage",
  "session_id":    "123456789",
  "message_id":    "msg_abc123",

  "group": {
    "id":   "123456789",
    "name": "测试群"
  },

  "sender": {
    "id":   "987654321",
    "name": "小明"
  },

  "summary": "你好 [图片]",
  "messages": [
    {
      "type": "Plain",
      "text": "你好",
      "data": { "text": "你好" }
    },
    {
      "type": "Image",
      "text": null,
      "data": { "url": "https://...", "path": "/tmp/img_xxx.jpg" }
    }
  ]
}
```

### 3.2 Index Mappings

```json
{
  "properties": {
    "@timestamp":    { "type": "date" },
    "platform":      { "type": "keyword" },
    "platform_id":   { "type": "keyword" },
    "message_type":  { "type": "keyword" },
    "session_id":    { "type": "keyword" },
    "message_id":    { "type": "keyword" },

    "group": {
      "type": "nested",
      "properties": {
        "id":   { "type": "keyword" },
        "name": { "type": "text" }
      }
    },

    "sender": {
      "type": "nested",
      "properties": {
        "id":   { "type": "keyword" },
        "name": { "type": "text" }
      }
    },

    "summary": { "type": "text" },

    "messages": {
      "type": "nested",
      "properties": {
        "type": { "type": "keyword" },
        "text": { "type": "text" },
        "data": { "type": "object", "enabled": false }
      }
    }
  }
}
```

### 3.3 与 v1 mapping 的关键差异

| 字段 | v1 | v2 | 原因 |
|---|---|---|---|
| `sender.nickname` | ✅ `text` | ❌ 删除 | 跨平台无等价物，单一 `name` 语义更清晰 |
| `sender.name` | `text`（存 QQ 昵称） | `text`（存 display name） | 复用字段，语义调整 |
| `group.id` | `keyword`（但代码 `int()` 存） | `keyword`（`str` 直接存） | 跨平台兼容：Telegram/Discord 等用非数字 ID |
| `sender.id` | `keyword`（但代码 `int()` 存） | `keyword`（`str` 直接存） | 同上 |
| `messages.data.data` | `nested` → `object` | 删除，`messages.data` 直接 `object` + `enabled: false` | 减少嵌套层级，放弃深嵌套查询 |
| `messages.content` | `text` | 重命名为 `messages.text` | 语义更明确 |
| `platform_id` | ❌ 不存在 | ✅ `keyword` | 区分同一平台类型的多个实例 |
| `message_type` | ❌ 不存在 | ✅ `keyword` | 消息类型（当前始终 `GroupMessage`） |
| `session_id` | ❌ 不存在 | ✅ `keyword` | 会话唯一标识 |
| `message_id` | ❌ 不存在 | ✅ `keyword` | 平台原始消息 ID，用于去重/引用 |

---

## 4. 核心模块设计

### 4.1 `main.py` — 插件入口

**设计模式**：`Star` 生命周期 + 依赖注入（`GroupFilter`、`ESHelper` 在 `initialize()` 阶段装配）。

```python
@register("astrbot_plugin_histories_collector_v2", "xiaoxue1272",
          "Astrbot 全平台群消息收集器(ES版)", "v0.1.0")
class HistoriesCollectorV2Plugin(Star):

    config: HistoriesCollectorConfig
    http_session: aiohttp.ClientSession
    group_filter: GroupFilter
    es_helper: ESHelper
    id_generator: SnowflakeGenerator

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.id_generator = SnowflakeGenerator(
            instance=config.get("snowflake_instance", 0)
        )
        self.config = HistoriesCollectorConfig(config)

    async def initialize(self):
        """Connect to ES and init group filter."""
        self.http_session = aiohttp.ClientSession()
        self.group_filter = GroupFilter(self.config.group_filter)

        es_config = self.config.es_config
        logger.info(f"Connecting to Elasticsearch: {es_config.hosts}")
        es = AsyncElasticsearch(
            es_config.hosts,
            http_compress=True,
            http_auth=(es_config.user, es_config.password),
            sniff_on_start=False,
            request_timeout=30,
        )
        if not await es.ping():
            await es.close()
            raise Exception("Elasticsearch connection failed")
        logger.info("Elasticsearch connected")
        self.es_helper = ESHelper(es, self.config)
        await self.es_helper.initial_required_indices()

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(PlatformAdapterType.ALL)
    async def on_group_message(self, event: AstrMessageEvent):
        """Handle group messages from all platforms."""
        platform_name = event.get_platform_name()
        group_id = event.get_group_id()
        if not self.group_filter.should_collect(platform_name, group_id):
            return

        doc = self._build_document(event)
        doc["messages"] = await parse_message_chain(
            chain=event.get_messages(),
            http_session=self.http_session,
            max_file_size_mb=self.config.max_file_size_mb,
        )
        await self.es_helper.save_message(next(self.id_generator), doc)

    async def terminate(self):
        if self.es_helper:
            await self.es_helper.close()
        if self.http_session:
            await self.http_session.close()

    # ---- private helpers ----

    def _build_document(self, event: AstrMessageEvent) -> dict:
        """Build ES document from cross-platform base-class API only."""
        group = event.message_obj.group
        return {
            "@timestamp": int(event.message_obj.timestamp * 1000),
            "platform": event.get_platform_name(),
            "platform_id": event.get_platform_id(),
            "message_type": event.get_message_type().value,
            "session_id": event.get_session_id(),
            "message_id": event.message_obj.message_id,
            "group": {
                "id": event.get_group_id(),
                "name": group.group_name if group else None,
            },
            "sender": {
                "id": event.get_sender_id(),
                "name": event.get_sender_name(),
            },
            "summary": event.get_message_outline(),
        }
```

**关键改动**：

1. 过滤器：`PlatformAdapterType.ALL` + `EventMessageType.GROUP_MESSAGE`（仅群消息）
2. `event: AstrMessageEvent` 基类，不依赖任何平台子类
3. 群过滤委派给 `GroupFilter.should_collect(platform_name, group_id)`
4. `http_session` 在 `initialize()` 创建、`terminate()` 关闭，整个插件生命周期复用
5. `_build_document()` 仅使用 `AstrMessageEvent` 基类 API，零平台耦合
6. `messages` 解析在事件处理方法中异步填充（先构建基础 doc，再补消息链）

### 4.2 `group_filter.py` — 群组过滤器

**设计模式**：策略模式。`mode` 决定过滤策略（whitelist / blacklist / disabled），`platforms` 按平台独立配置群 ID 列表。

```python
class GroupFilter:

    MODE_WHITELIST = "whitelist"
    MODE_BLACKLIST = "blacklist"
    MODE_DISABLED = "disabled"

    def __init__(self, config: GroupFilterConfig):
        self._mode = config.mode
        # { "aiocqhttp": {"123", "456"}, "telegram": {"-100xxx"}, ... }
        self._platform_groups: dict[str, set[str]] = {}
        for entry in config.platforms:
            platform = entry.get("platform", "")
            group_ids = entry.get("group_ids", [])
            if platform and group_ids:
                self._platform_groups[platform] = set(str(g) for g in group_ids)

    def should_collect(self, platform_name: str, group_id: str) -> bool:
        """Return True if the message should be collected.

        Args:
            platform_name: Platform type name, e.g. "aiocqhttp", "telegram".
            group_id: Group ID from event.get_group_id().

        Returns:
            True to collect, False to skip.
        """
        if self._mode == self.MODE_DISABLED:
            return True  # Collect all

        target_set = self._platform_groups.get(platform_name, set())
        if self._mode == self.MODE_WHITELIST:
            return group_id in target_set
        if self._mode == self.MODE_BLACKLIST:
            return group_id not in target_set
        return True  # Unknown mode fallback: collect
```

**过滤逻辑**：

| mode | platform 有群列表 | platform 无配置 | 行为 |
|---|---|---|---|
| `whitelist` | 仅 collection 列表中的群 | 不收集该平台任何群 | 精确控制 |
| `blacklist` | 收集列表中**之外**的所有群 | 收集该平台所有群 | 排除特定群 |
| `disabled` | — | — | 收集所有平台所有群 |

### 4.3 `message_parser.py` — 消息链解析

**从 v1 main.py 完整迁出**，同时修复已知 Bug：

```python
async def parse_message_chain(
    chain: list[BaseMessageComponent],
    http_session: aiohttp.ClientSession,
) -> list[dict]:
    """Recursively parse message chain into structured dicts.

    Args:
        chain: List of message components from event.get_messages().
        http_session: Shared aiohttp session for file size checks (HEAD requests).

    Returns:
        List of dicts with keys: type, text, data, path, warn.
    """
    elements = []
    for component in chain:
        try:
            element = await _parse_single_component(component, http_session)
            if element is not None:
                elements.append(element)
        except Exception:
            logger.warning(f"Failed to parse component type={component.type}, skipping")
    return elements
```

**v1 Bug 修复清单**：

| Bug | 修复方式 |
|---|---|
| Nodes 处理时过早 `return` 丢弃后续元素 | 改为 `continue`，不中断外层循环 |
| Record 类型文件下载缺失 | 在 `_get_download_url_by_type()` 中添加 Record 处理 |
| `_get_http_content_length()` 用 GET 下载整个文件 | 改为 `session.head(url)` |
| 单组件异常导致整条消息丢弃 | 外层 try/except 包裹每个 component |

### 4.4 `es_helper.py` — ES 操作封装

**从 v1 helper.py 迁出**，主要变更：

| 变更 | 说明 |
|---|---|
| 类名 `HistoriesHelper` → `ESHelper` | 更准确的职责描述 |
| `__index_alias` 类变量删除 | 直接使用 `config.es_config.alias`，无硬编码 |
| `_ensure_write_index_exists()` 异常处理 | `except Exception` → `except elasticsearch.NotFoundError` |
| ILM 创建失败 | 不 `raise`，改为 warning + 跳过（非致命） |
| `save_message()` | 增加可选重试逻辑（指数退避，最多 3 次） |
| Index settings | IK 分词器改为可选配置（`use_ik_analyzer: bool`），非中文环境可关闭 |

### 4.5 `config.py` — 配置

```python
class ESConfig:
    hosts: list[str]             # ES 集群地址列表
    user: str                     # ES 用户名
    password: str                 # ES 密码
    alias: str                    # 索引别名，默认 "message-histories-v2"
    use_ik_analyzer: bool         # 是否启用 IK 中文分词器，默认 True


class GroupFilterConfig:
    mode: str                     # "whitelist" / "blacklist" / "disabled"
    platforms: list[dict]         # [{"platform": "aiocqhttp", "group_ids": [...]}, ...]


class HistoriesCollectorConfig:
    es_config: ESConfig
    group_filter: GroupFilterConfig
    snowflake_instance: int       # Snowflake 实例 ID，默认 0，多实例部署需配置不同值
    max_file_size_mb: int         # 最大文件大小（MB），默认 50，超限跳过下载
```

**变更说明**：

1. `enable_groups: list[str]` → `group_filter: GroupFilterConfig` — 支持黑白名单模式切换 + 各平台独立配置
2. 移除 `collect_private: bool` — v2 仅收集群消息
3. `alias` 默认值 `"message-histories-v2"` — 加 V2 后缀避免影响现有 v1 数据

---

## 5. `_conf_schema.json` 配置 UI

```json
{
  "group_filter": {
    "description": "群组过滤配置",
    "type": "object",
    "items": {
      "mode": {
        "description": "过滤模式",
        "type": "string",
        "hint": "whitelist: 仅收集列表中群组; blacklist: 排除列表中群组; disabled: 收集所有群组",
        "default": "whitelist"
      },
      "platforms": {
        "description": "各平台群组列表",
        "type": "template_list",
        "hint": "按平台配置群组 ID 列表。platform: 平台名(aiocqhttp/telegram/discord...); group_ids: 群 ID 列表（字符串）",
        "default": [
          {"platform": "aiocqhttp", "group_ids": []},
          {"platform": "telegram", "group_ids": []},
          {"platform": "discord", "group_ids": []},
          {"platform": "lark", "group_ids": []},
          {"platform": "wecom", "group_ids": []},
          {"platform": "dingtalk", "group_ids": []},
          {"platform": "slack", "group_ids": []},
          {"platform": "kook", "group_ids": []}
        ]
      }
    }
  },
  "max_file_size_mb": {
    "description": "最大文件大小(MB)",
    "type": "int",
    "hint": "超过此大小的图片/文件/视频将跳过下载，仅记录元数据",
    "default": 50
  },
  "snowflake_instance": {
    "description": "Snowflake 实例 ID",
    "type": "int",
    "hint": "⚠️ 多实例部署时必须为每个实例设置不同值（0~31），否则会产生 ID 冲突导致消息丢失",
    "default": 0
  },
  "es_config": {
    "description": "Elasticsearch 配置",
    "type": "object",
    "items": {
      "hosts": {
        "description": "主机(集群)地址",
        "type": "list",
        "hint": "ES 主机(集群)的 URL 集合",
        "default": ["http://localhost:9200"]
      },
      "user": {
        "description": "用户名",
        "type": "string",
        "default": ""
      },
      "password": {
        "description": "密码",
        "type": "string",
        "default": ""
      },
      "alias": {
        "description": "索引别名",
        "type": "string",
        "hint": "ES 索引别名前缀，实际索引名为 {alias}-000001。注意：V2 默认有别于 V1，避免影响现有数据。",
        "default": "message-histories-v2"
      },
      "use_ik_analyzer": {
        "description": "启用 IK 分词器",
        "type": "bool",
        "hint": "中文环境建议开启，需要 ES 安装 IK 分词插件；非中文环境可关闭",
        "default": true
      }
    }
  }
}
```

---

## 6. 性能优化

| 优化项 | v1 现状 | v2 方案 |
|---|---|---|
| aiohttp Session 复用 | 每次请求 `new ClientSession()` | `initialize()` 创建，`terminate()` 关闭 |
| 文件大小检查 | HTTP GET（下载整个响应体） | HTTP HEAD（仅取 header） |
| 文件下载 | 先检查大小再下载（两次 HTTP 请求） | HEAD 检查 + 一次下载 |
| 日志级别 | `logger.info` 每个组件类型 | `logger.debug` |
| ES 写入 | 单条 `create`，无重试 | 可选指数退避重试（最多 3 次） |
| 消息解析 | 单组件崩溃整条丢弃 | 单组件 try/except 跳过 |

---

## 7. 错误处理策略

```
initialize() 阶段:
  ├── ES ping 失败 → 日志错误 + 抛出异常（阻止插件激活）
  ├── ILM 策略创建失败 → 日志 warning + 继续（非致命）
  ├── 索引模板创建失败 → 日志 error + 抛出异常
  └── 初始化写入索引失败 → 日志 error + 抛出异常

on_message() 阶段:
  ├── 单 component 解析失败 → 日志 warning + 跳过该 component
  ├── _parse_message_chain 整体失败 → 日志 error + 返回空 messages 列表
  ├── save_message ES 写入失败 → 日志 error + 重试 3 次 + 最终丢弃
  └── 文件下载超时 → 日志 warning + 记录 warn 字段 + 继续

terminate() 阶段:
  └── ES close 失败 → 日志 warning + 忽略
```

---

## 8. 与 v1 共存策略

1. **插件名不同**：`astrbot_plugin_histories_collector` vs `astrbot_plugin_histories_collector_v2`，可同时安装
2. **ES 别名默认不同**：v1 默认 `qq_messages`；v2 默认 `message-histories-v2`（加 V2 后缀），写入不同索引，互不干扰
3. **不迁移老数据**：v1 数据格式不兼容（int ID、嵌套 data.data），建议保留 v1 索引只读，v2 从零开始写新索引
4. **可独立启停**：AstrBot WebUI 中可分别管理两个插件的启用状态

---

## 9. 测试要点

- [ ] **群消息多平台**：QQ(aiocqhttp) / Telegram / Discord / 飞书 / 企业微信 各一份样本
- [ ] **消息组件覆盖**：Plain / Image / File / Video / Record / At / Reply / Nodes / Forward
- [ ] **文件大小限制**：<50MB 正常下载，>50MB 跳过并记录 warn
- [ ] **白名单模式**：platform 列表含目标群（收集）、不含（跳过）、空列表（该平台不收集）
- [ ] **黑名单模式**：platform 列表含目标群（跳过）、不含（收集）
- [ ] **disabled 模式**：全平台全群收集
- [ ] **platform 无配置**：未在 platform 列表中的平台，白名单模式不收集，黑名单模式全收集
- [ ] **QQ 群名片丢失确认**：sender.name 为 `get_sender_name()` 返回值，不再有 card 字段
- [ ] **ES 连接失败**：插件不激活
- [ ] **ILM 策略创建失败**：插件仍激活（降级运行）
- [ ] **多实例 Snowflake ID**：instance 不同则 ID 不冲突
- [ ] **`terminate()`** 正常关闭 ES 连接 + aiohttp Session
- [ ] **非 IK 分词环境**：`use_ik_analyzer=false` 正常创建索引
- [ ] **V2 索引隔离**：确认写入 `message-histories-v2`，不影响 v1 的 `qq_messages`

---

## 10. 依赖

```
elasticsearch[async]>=8.0.0
aiohttp>=3.9.0
snowflake-id>=1.0.2
```

与 v1 一致，无新增依赖。

---

## 11. 已确认决策

| # | 议题 | 决策 |
|---|---|---|
| 1 | QQ 群名片 card 字段 | ✅ 放弃，统一 `sender.name` 单字段 |
| 2 | ID 类型 | ✅ 统一为 `str`（keyword），不做 `int()` 强转 |
| 3 | 私聊消息收集 | ✅ 不收集，v2 仅处理群消息 |
| 4 | IK 分词器 | ✅ 默认 `true`，配置 UI 中可关闭 |
| 5 | Snowflake instance | ✅ 默认 `0`，配置 UI 中增加多实例冲突警告说明 |
