# ES 文档结构说明

## 顶层文档 (`_build_document`)

```json
{
  "@timestamp": 1719676800000,
  "platform": "aiocqhttp",
  "platform_id": "qq-adapter-1",
  "message_type": "GROUP_MESSAGE",
  "session_id": "group_123456",
  "message_id": "msg_abc123",
  "group": {
    "id": "123456",
    "name": "技术交流群"
  },
  "sender": {
    "id": "10001",
    "name": "张三"
  },
  "summary": "[图片] 你好",
  "messages": [
    // ... 组件元素数组
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `@timestamp` | date (ms) | 消息时间戳 |
| `platform` | keyword | 平台名（aiocqhttp/telegram/discord...） |
| `platform_id` | keyword | 平台适配器实例 ID |
| `message_type` | keyword | 消息类型（GROUP_MESSAGE） |
| `session_id` | keyword | 会话 ID |
| `message_id` | keyword | 消息 ID |
| `group.id` | keyword | 群号 |
| `group.name` | text | 群名 |
| `sender.id` | keyword | 发送者 ID |
| `sender.name` | text | 发送者昵称 |
| `summary` | text | 消息摘要 |
| `messages` | nested | 消息组件数组 |

## `messages` 元素通用结构

每个元素固定包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | keyword | 组件类型标识 |
| `data` | object (enabled: false) | 组件原始数据，不做索引 |
| `path` | — | (可选) 下载到本地的文件路径，不在 mapping 中 |
| `warn` | — | (可选) 下载失败的警告信息，不在 mapping 中 |

---

## 各组件类型详解

### 1. Plain — 纯文本 (`plaintext`)

```json
{
  "type": "plaintext",
  "data": { "text": "你好世界" }
}
```

### 2. At — @某人 (`at`)

```json
{
  "type": "at",
  "data": { "qq": "10001" }
}
```

### 3. AtAll — @全体成员 (`at_all`)

```json
{
  "type": "at_all",
  "data": {}  // component.to_dict() 的结构
}
```

### 4. Reply — 引用回复 (`reply`)

```json
{
  "type": "reply",
  "data": {
    "time": 1719676800000,
    "message": "原始消息文本"
  }
}
```

### 5. Image — 图片 (`image`)

**下载成功：**

```json
{
  "type": "image",
  "data": {
    "url": "https://example.com/img.jpg",
    "file": "base64://..."
  },
  "path": "D:/.../file_cache/a1b2c3..."
}
```

**超大小限制 / 下载失败：**

```json
{
  "type": "image",
  "data": {
    "url": "https://example.com/img.jpg",
    "file": "base64://..."
  },
  "warn": "File exceeds 50MB limit (52428800 bytes)"
}
```

### 6. Video — 视频 (`video`)

```json
{
  "type": "video",
  "data": {
    "file": "https://example.com/video.mp4"
  },
  "path": "D:/.../file_cache/d4e5f6..."
}
```

### 7. Record — 语音 (`record`)

```json
{
  "type": "record",
  "data": {
    "url": "https://example.com/voice.amr",
    "file": "https://example.com/voice.amr"
  },
  "path": "D:/.../file_cache/g7h8i9..."
}
```

### 8. File — 文件 (`file`)

```json
{
  "type": "file",
  "data": {
    "url": "https://example.com/doc.pdf",
    "name": "doc.pdf"
  },
  "path": "D:/.../file_cache/j0k1l2..."
}
```

### 9. Share — 分享链接 (`share`)

```json
{
  "type": "share",
  "data": {
    "url": "https://example.com",
    "title": "分享标题"
  }
}
```

### 10. Contact — 联系人名片 (`contact`)

```json
{
  "type": "contact",
  "data": {
    "id": "10001",
    "name": "张三"
  }
}
```

### 11. Location — 地理位置 (`location`)

```json
{
  "type": "location",
  "data": {
    "lat": "39.90",
    "lon": "116.40",
    "title": "北京"
  }
}
```

### 12. Music — 音乐分享 (`music`)

```json
{
  "type": "music",
  "data": {
    "type": "qq",
    "url": "https://...",
    "title": "歌曲名"
  }
}
```

### 13. Json — JSON 消息 (`json`)

```json
{
  "type": "json",
  "data": {
    "data": "..."
  }
}
```

### 14. Node — 合并转发单条 (`node`)

```json
{
  "type": "node",
  "data": {
    "user_id": "10001",
    "nickname": "张三",
    "content": [
      // 递归解析的消息链，结构同 messages 数组
      { "type": "plaintext", "data": { "text": "你好" } },
      { "type": "image", "data": { ... }, "path": "..." }
    ]
  }
}
```

**超过嵌套深度时：**

```json
{
  "type": "node",
  "data": {
    "user_id": "10001",
    "nickname": "张三",
    "content": [{ "_truncated": true, "_depth": 4 }]
  }
}
```

### 15. Nodes — 合并转发多条 (`nodes`)

```json
{
  "type": "nodes",
  "data": [
    [
      // Node 0 的消息链
      { "type": "plaintext", "data": { "text": "你好" } }
    ],
    [
      // Node 1 的消息链
      { "type": "image", "data": { ... }, "path": "..." }
    ]
  ]
}
```

### 16. Forward — QQ 合并转发 (`forward`)

**未解析（非 QQ 平台或 API 不可用）：**

```json
{
  "type": "forward",
  "data": { "id": "fwd_abc123" }
}
```

**QQ 平台解析成功：**

```json
{
  "type": "forward",
  "data": {
    "id": "fwd_abc123",
    "resolved": [
      {
        "user_id": "10001",
        "nickname": "张三",
        "time": 1719676800,
        "content": [
          { "type": "plaintext", "data": { "text": "转发消息内容" } }
        ]
      },
      {
        "user_id": "10002",
        "nickname": "李四",
        "time": 1719676801,
        "content": [
          { "type": "image", "data": { ... }, "path": "..." }
        ]
      }
    ]
  }
}
```

**超过嵌套深度时：**

```json
{
  "type": "forward",
  "data": {
    "id": "fwd_abc123",
    "_truncated": true,
    "_depth": 3
  }
}
```

---

## 完整示例

一条包含"文本 + @ + 图片 + 引用回复的 QQ 合并转发"消息：

```json
{
  "@timestamp": 1719676800000,
  "platform": "aiocqhttp",
  "platform_id": "qq-adapter-1",
  "message_type": "GROUP_MESSAGE",
  "session_id": "group_123456",
  "message_id": "msg_abc123",
  "group": { "id": "123456", "name": "技术交流群" },
  "sender": { "id": "10001", "name": "张三" },
  "summary": "[图片] 来看这个",
  "messages": [
    {
      "type": "plaintext",
      "data": { "text": "来看这个" }
    },
    {
      "type": "at",
      "data": { "qq": "10002" }
    },
    {
      "type": "image",
      "data": { "url": "https://...", "file": "base64://..." },
      "path": "D:/data/plugins/.../file_cache/a1b2c3..."
    },
    {
      "type": "forward",
      "data": {
        "id": "fwd_xyz",
        "resolved": [
          {
            "user_id": "10003",
            "nickname": "李四",
            "time": 1719676700,
            "content": [
              { "type": "plaintext", "data": { "text": "之前的讨论" } }
            ]
          }
        ]
      }
    }
  ]
}
```
