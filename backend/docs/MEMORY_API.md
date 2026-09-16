# 用户记忆与菜单接口

以下接口均要求有效的 `recipe_session` Cookie，路径不变：

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | `/memory` | 当前用户的长期记忆 |
| POST | `/memory/confirm` | 从确认菜单提取并合并当前用户偏好 |
| POST | `/memory/clear` | 清空当前用户的 profile，version 加一 |
| POST | `/menu/plan` | 使用当前用户的记忆快照规划菜品 |
| POST | `/menu/stream` | 使用当前用户快照生成菜谱，SSE 返回 |
| POST | `/research` | 使用当前用户快照生成完整菜单 |

先按 [认证接口文档](AUTH_API.md) 登录。前端跨端口请求需要 `credentials: 'include'`；写请求必须带允许的 Origin，浏览器会自动添加。curl/Postman 需显式添加。没有 Cookie 或会话过期返回 401，非法/缺失 Origin 的写请求返回 403，数据库不可用返回 503。业务调用不占用注册或登录限流额度。

## 记忆示例

```sh
curl -b /tmp/recipe-auth-cookies.txt http://localhost:8000/memory

curl -b /tmp/recipe-auth-cookies.txt http://localhost:8000/memory/confirm \
  -H 'Origin: http://localhost:5173' -H 'Content-Type: application/json' \
  -d '{"user_requirement":"两人餐，少油，虾过敏","dish_list":[{"id":1,"name":"清炒青菜"}]}'

curl -X POST -b /tmp/recipe-auth-cookies.txt http://localhost:8000/memory/clear \
  -H 'Origin: http://localhost:5173'
```

响应沿用 `memory` 和 `memory_summary` 结构。`memory` 额外包含数据库 `version`、带时区的 `updated_at`，这些元数据不写入 profile JSONB。兼容已有的人数字符串；注册初始值为 null。

用户 ID 只来自后端验证过的会话。客户端不能通过请求体中的 user_id 改变访问对象；规划和确认请求拒绝未定义的顶层字段。

## 数据隔离和事务

- 所有 HTTP 记忆读写使用 `user_memories WHERE user_id = 当前用户`。
- 缺失记忆行只初始化当前用户的空偏好，旧 JSON 不作为默认数据。
- 确认时使用短事务和行锁读取最新 profile 后合并，避免同一用户并发确认覆盖。
- 清空与确认按数据库锁获取顺序提交；清空之后的新确认可以再次建立偏好。
- DB 事务结束后才启动 AI，生成期间使用请求内快照，不持有数据库连接。
- 每次生成使用 `NOTES_WORKSPACE/users/<可信 UUID>/<服务端生成的运行 ID>`，不同用户和请求不共享笔记索引。
- 流请求中的 note_id、note_path、stream_token、memory_used 和 memory_conflicts 为兼容旧前端可以接收，但不用于创建服务端任务。笔记 ID 不能包含路径或越出当前目录。

`user_memory.json` 未被迁移或删除。HTTP 不再读写该文件；只有离线评估显式指定 memory_path 时仍允许文件存储。CLI/Graph 未注入记忆时使用空的进程内记忆，不再隐式读取共享文件。

## SSE 与登录过期

进入 `/menu/stream` 前完成鉴权与记忆加载：失败返回普通 JSON 401/503，不打开事件流。流打开后的生成失败以 `type=error` 事件返回通用提示，不包含原始异常详情。

会话在请求开始时验证；已开始的流不会因后续退出自动撤销，使用的是已授权的当前用户快照。前端退出时应主动中止该流。如果需要服务端即时中断已启动任务，应另行加入会话撤销通知/任务取消机制。

## 验证与前端范围

运行 `TEST_DATABASE_URL=... .venv/bin/python -m pytest tests -q`，测试使用独立 PostgreSQL 随机 schema；Agent 使用测试替身，不调用外部 AI。覆盖双用户隔离、并发确认、清空、SSE 鉴权、内部字段忽略、Origin、数据库失败和笔记路径约束。

本次为后端改造。原先未携带 Cookie 的前端请求将无法访问受保护接口；前端登录页、统一 credentials 和 401 跳转需后续接入。未迁移任何旧用户数据。
