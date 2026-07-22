# ES 文档结构说明 (V2)

## 顶层文档 (`_build_document`)

```json
{
  "@timestamp": 1719676800000,
  "platform": "aiocqhttp",
  "platform_id": "NapCatQQ",
  "message_id": "a3b6c522c5094d84968d908fb187a65a",
  "group": {
    "id": "1043876524",
    "name": "技术交流群"
  },
  "sender": {
    "id": "1132610635",
    "name": "1132610635",
    "nickname": "张三"
  },
  "summary": "[图片] 你好",
  "types": ["plain", "image"],
  "messages": [
    { "type": "plain", "text": "你好" },
    { "type": "image", "url": "https://...", "path": "image/2026/07/a1b2c3.jpg", "sub_type": 0 }
  ]
}
```

| 字段 | ES 类型 | 说明 |
|------|---------|------|
| `@timestamp` | `date` | 消息时间戳（毫秒） |
| `platform` | `keyword` | 平台名（aiocqhttp / wecom 等） |
| `platform_id` | `keyword` | 平台适配器实例 ID |
| `message_id` | `keyword` | 消息唯一 ID |
| `group` | `nested` | `{id, name}` — 群信息 |
| `sender` | `nested` | `{id, name, nickname}` — nickname 仅 aiocqhttp 等平台支持 |
| `summary` | `text` | 消息文本摘要（纯文本 + 媒体占位符） |
| `types` | `keyword` | 消息中包含的所有组件类型（去重） |
| `messages` | `nested` | 解析后的消息链，具体结构见下文 |

---

## `messages` 元素结构

所有元素均为**扁平结构**，无 `data` 子对象包装。可嵌套（Forward → messages[] → Node → messages[]）。

### 公共字段

| 字段 | 说明 |
|------|------|
| `type` | 组件类型标识（keyword） |
| `url` | 媒体文件原始 URL（Image/Video/Record/File） |
| `path` | 下载缓存的本地相对路径 |
| `warn` | 下载失败的警告信息（可选） |

---

## 各组件类型详解

### Plain — 纯文本

```json
{ "type": "plain", "text": "你好世界" }
```

| 字段 | 说明 |
|------|------|
| `text` | 文本内容 |

### Image — 图片

```json
{
  "type": "image",
  "url": "https://example.com/img.jpg",
  "path": "image/2026/07/a1b2c3d4e5f6g7h8.jpg",
  "sub_type": 0,
  "summary": "图片描述文本"
}
```

| 字段 | 说明 |
|------|------|
| `url` | 图片 URL |
| `path` | 本地缓存路径 |
| `sub_type` | 0=普通图片, 1=动画表情/GIF, 7=表情包/热图 |
| `summary` | 图片摘要（可选，部分平台） |
| `warn` | 下载失败警告（可选） |

### Video — 视频

```json
{ "type": "video", "url": "https://example.com/v.mp4", "path": "video/2026/07/b2c3d4e5.mp4" }
```

### Record — 语音

```json
{
  "type": "record",
  "url": "https://example.com/v.amr",
  "path": "record/2026/07/c3d4e5f6.amr",
  "text": "语音转文字结果"
}
```

| 字段 | 说明 |
|------|------|
| `text` | 语音转文字结果（可选，仅 aiocqhttp） |

### File — 文件

```json
{ "type": "file", "url": "https://example.com/doc.pdf", "path": "file/2026/07/d4e5f6g7.pdf", "name": "doc.pdf" }
```

### At — @某人 / @全体成员

```json
{ "type": "at", "qq": "1132610635", "name": "张三" }
```

@全体成员同样以 `at` 类型存储，`qq` 字段为 `"all"`：

```json
{ "type": "at", "qq": "all", "name": "全体成员" }
```

### Reply — 引用回复

```json
{ "type": "reply", "id": "msg_id_123", "summary": "被引用的消息摘要" }
```

| 字段 | 说明 |
|------|------|
| `id` | 被引用消息的 ID |
| `summary` | 被引用消息的文本摘要 |

### Face — 表情

```json
{ "type": "face", "id": "12" }
```

### Json — JSON 消息

```json
{ "type": "json", "data": "..." }
```

### Forward — 合并转发

```json
{
  "type": "forward",
  "id": "fwd_abc123",
  "messages": [
    { "type": "node", "user_id": "10001", "nickname": "张三", "messages": [...] },
    { "type": "node", "user_id": "10002", "nickname": "李四", "messages": [...] }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `id` | 转发消息 ID |
| `messages` | 解析后的子消息列表 |

> 非 aiocqhttp 平台的 Forward 无法调用 `get_forward_msg` API 展开，`messages` 为空数组。

### Nodes — 合并转发多条

```json
{
  "type": "nodes",
  "messages": [
    { "type": "node", "user_id": "10001", "nickname": "张三", "messages": [...] }
  ]
}
```

### Node — 合并转发单条

```json
{
  "type": "node",
  "user_id": "10001",
  "nickname": "张三",
  "messages": [
    { "type": "plain", "text": "转发的内容" }
  ]
}
```

### 其他类型

Share / Contact / Location / Music — 通过 `component.to_dict()` 序列化，字段与组件原始 data 一致。

---

## 完整示例

一条包含"文本 + @ + 图片 + 引用回复 + 合并转发"的消息：

```json
{
  "@timestamp": 1719676800000,
  "platform": "aiocqhttp",
  "platform_id": "NapCatQQ",
  "message_id": "msg_abc123",
  "group": { "id": "123456", "name": "技术交流群" },
  "sender": { "id": "10001", "name": "张三", "nickname": "张三" },
  "summary": "[图片] 来看这个 [@:李四] [引用消息:(王五:之前的讨论)] [聊天记录:(关于需求的讨论)]",
  "types": ["plain", "image", "at", "reply", "forward"],
  "messages": [
    { "type": "plain", "text": "来看这个" },
    { "type": "at", "qq": "10002" },
    {
      "type": "image",
      "url": "https://example.com/img.jpg",
      "path": "image/2026/07/a1b2c3d4e5f6g7h8.jpg",
      "sub_type": 0
    },
    { "type": "reply", "id": "msg_xyz", "summary": "之前的讨论" },
    {
      "type": "forward",
      "id": "fwd_xyz",
      "messages": [
        {
          "type": "node",
          "user_id": "10003",
          "nickname": "李四",
          "messages": [
            { "type": "plain", "text": "关于需求的讨论" }
          ]
        }
      ]
    }
  ]
}
```
