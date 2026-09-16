# 用户名密码认证接口实施规范

> 本文是提供给 AI 编码助手和开发者的实施与验收依据。阅读本文不代表已经实现认证；只有收到用户实施指令后才执行代码改动。用户最新明确指令优先于本文。

## 1. 目标与边界

为现有 FastAPI 后端实现用户名密码注册、登录、查询当前用户和退出登录。采用 PostgreSQL 服务端会话和 HttpOnly Cookie，为后续多用户业务提供 `get_current_user` 依赖。

本阶段实现：

- 四个 `/api/v1` 认证接口。
- PostgreSQL 连接池、事务、密码哈希、会话管理。
- 认证请求校验、统一错误响应、来源校验和基础限流。
- 独立测试数据库上的自动化验证与启动说明。

本阶段不包含：前端登录页、JWT、第三方登录、找回密码、旧 JSON 记忆迁移、菜单与记忆业务接口改造。不得将本阶段完成描述为全应用已实现多用户隔离。保留既有业务接口路径和行为。

## 2. 实施前检查

1. 阅读适用的 `AGENTS.md`、现有 `src/main.py`、依赖文件及数据库初始化 SQL。
2. 以 `database/init.sql` 为已有表结构依据；连接实际数据库时只读核对结构。不要重复运行初始化 SQL、自动重建表或删除用户数据。
3. 检查数据库配置是否存在，但不得展示真实连接密码、API 密钥或完整含密码连接串。
4. 沿用项目的导入和配置风格，避免因引入认证破坏已有启动方式。
5. 如实际表结构与本文不一致，先报告具体差异，再确定兼容方式；不要静默改表。

## 3. 技术方案与文件职责

采用 Psycopg 3、连接池和参数化 SQL，不为本阶段额外引入 ORM。密码使用成熟 Argon2id 库，例如 `argon2-cffi`。同步数据库操作使用同步 FastAPI 路由/依赖，不在异步事件循环中直接执行阻塞数据库查询或密码哈希。

建议文件布局（路径相对于后端目录）：

| 文件 | 职责 |
| --- | --- |
| `src/database.py` | 连接池、事务和连接依赖 |
| `src/auth/__init__.py` | 包入口 |
| `src/auth/config.py` | 认证环境配置及有效性检查 |
| `src/auth/schemas.py` | 请求、响应和错误模型 |
| `src/auth/security.py` | 密码哈希验证、会话凭证生成与摘要 |
| `src/auth/service.py` | 用户和会话的参数化 SQL 操作 |
| `src/auth/dependencies.py` | `get_current_user`、来源验证、限流依赖 |
| `src/auth/router.py` | HTTP 路由及 Cookie 处理 |
| `src/main.py` | 挂载路由、连接池生命周期、明确的 CORS 来源 |
| `tests/test_auth.py` | 认证集成测试 |
| `requirements.txt` | 补充运行依赖 |
| `requirements-dev.txt` | 测试依赖（如采用此文件） |
| `.env.example` | 无真实凭证的配置示例 |
| `README.md` | 配置、运行、测试和调用示例 |

允许按仓库实际结构小幅调整，但保持 HTTP 层、业务逻辑和数据库职责清晰。认证模块应可独立挂载到测试 FastAPI 应用，不要求加载 LLM、向量库或调用外部 AI 服务。

## 4. 已有数据库契约

### users

- `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `username VARCHAR(64) NOT NULL UNIQUE`
- `password_hash TEXT NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

### user_sessions

- `token_hash TEXT PRIMARY KEY`
- `user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `expires_at TIMESTAMPTZ NOT NULL`
- 已有 `user_id`、`expires_at` 索引。

### user_memories

- `user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE`
- `profile JSONB NOT NULL DEFAULT '{}'::jsonb`
- `version INTEGER NOT NULL DEFAULT 1`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- 已有 profile GIN 索引和更新 `updated_at` 的触发器。

注册时显式初始化以下 profile，不依赖空对象默认值，也不读入现有 `user_memory.json`：

```json
{
  "diet_preferences": [],
  "allergies": [],
  "disliked_ingredients": [],
  "favorite_ingredients": [],
  "common_serving_size": null,
  "recent_dishes": [],
  "rejected_patterns": []
}
```

`recent_dishes` 暂保留兼容性。后续记忆迁移需另行处理旧服务中的人数字符串格式，本阶段不改变旧服务。

## 5. 公共 HTTP 约定

- 请求和响应使用 JSON；`204` 无响应体。
- UUID 输出为字符串，时间输出为带 UTC 时区的 RFC 3339 字符串。
- 注册和登录只接受 `application/json`（允许 charset 参数），其他媒体类型返回 `415`。
- 请求模型拒绝未定义字段，不允许通过传入 `id`、`user_id`、`password_hash` 等控制内部数据。
- 认证响应添加 `Cache-Control: no-store`。
- 统一错误结构如下，不向客户端泄露堆栈、SQL、哈希、Cookie 或配置内容：

```json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "用户名或密码错误"
  }
}
```

| 状态码 | code 示例 | 场景 |
| --- | --- | --- |
| 401 | `INVALID_CREDENTIALS` | 登录失败 |
| 401 | `UNAUTHENTICATED` | 会话缺失、无效或过期 |
| 403 | `ORIGIN_NOT_ALLOWED` | 写请求来源不允许 |
| 409 | `USERNAME_TAKEN` | 用户名已占用 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | 注册/登录请求媒体类型不支持 |
| 422 | `VALIDATION_ERROR` | JSON 格式或字段校验失败 |
| 429 | `RATE_LIMITED` | 注册或登录请求过频 |
| 500 | `INTERNAL_ERROR` | 未预期内部异常 |
| 503 | `SERVICE_UNAVAILABLE` | 数据库连接不可用 |

认证路由的校验错误也必须使用该结构，不回显密码输入。错误转换应限定认证接口，避免改变已有业务接口的错误契约。

## 6. 用户名与密码规则

### 用户名

- 注册和登录均先执行首尾空白去除、转小写。
- 规范化后满足 `^[a-z0-9_]{3,64}$`。
- 数据库保存规范化值，昵称不在本阶段范围。
- 用户名唯一约束是并发注册时的最终保障；不能只先查后插。
- 如已有非规范化用户名，先报告兼容问题，不自动改写已有账户。

### 密码

- 注册密码长度为 8～128 个字符，由字母、数字和符号组成。
- 登录按相同输入长度范围校验；今后若调整策略，应单独考虑既有密码兼容。
- 密码不得 trim、转小写、截断或写入日志。
- 用 Argon2id 库生成含随机盐和参数的编码哈希，用库提供的验证函数校验。
- 参数至少达到 OWASP Argon2id 基线：内存 19 MiB、迭代 2、并行度 1；最终配置需结合运行环境验证资源开销。
- 用户不存在时也执行固定的有效占位哈希校验，减少明显的处理时间差异；不存在与密码不正确使用相同的 401 响应。
- 注册前的确认密码由前端负责，不保存第二份密码字段。

## 7. 接口契约

### 7.1 注册用户

`POST /api/v1/users`

请求：

```json
{
  "username": "cammy",
  "password": "a sufficiently long example password"
}
```

处理顺序：校验来源和限流 → 校验/规范化字段 → 计算密码哈希 → 在一个事务内插入用户与空记忆 → 提交 → 返回结果。

密码哈希尽量在打开写事务之前完成。捕获用户名唯一约束冲突并返回 409，其他数据库错误不能误报为重复用户名。事务任一步失败必须全部回滚。

成功 `201 Created`：

```json
{
  "id": "b652d664-0d55-4ad6-a31f-1e6607d77eab",
  "username": "cammy",
  "created_at": "2026-09-14T08:00:00Z"
}
```

注册成功不自动登录，也不创建会话。

### 7.2 登录并创建会话

`POST /api/v1/sessions`

请求字段与注册相同。验证成功后使用密码学安全随机源生成至少 32 字节随机凭证，例如 `secrets.token_urlsafe(32)`；每次登录都生成新凭证。

- 原始凭证只通过 Cookie 下发。
- 数据库保存原始凭证的 SHA-256 十六进制摘要，不存原始凭证。
- SHA-256 仅用于高熵会话凭证，不能用于用户密码存储。
- 到期时间为创建时间加配置的固定会话时长，不自动续期。
- 如果请求带有旧会话，登录成功后在同一事务中删除该旧会话并写入新会话；登录失败不删除原会话。
- 其他设备的会话保持有效。
- 数据库提交成功后才能设置 Cookie。

成功 `201 Created`：

```json
{
  "user": {
    "id": "b652d664-0d55-4ad6-a31f-1e6607d77eab",
    "username": "cammy"
  },
  "expires_at": "2026-09-21T08:00:00Z"
}
```

Cookie 名称统一为 `recipe_session`：

- `HttpOnly=true`
- `SameSite=Lax`
- `Path=/`
- 不设置 `Domain`，使用 host-only Cookie。
- `Max-Age` 与固定会话有效期一致，默认 604800 秒。
- 本地 HTTP 开发允许 `Secure=false`；生产环境强制 `Secure=true` 并使用 HTTPS。

### 7.3 获取当前用户

`GET /api/v1/users/me`

使用 `get_current_user` 依赖执行：读取 Cookie → 检查凭证长度/格式 → 计算摘要 → 查询会话及关联用户 → 检查 `expires_at > 当前时间` → 返回公开用户字段。

成功 `200 OK`：

```json
{
  "id": "b652d664-0d55-4ad6-a31f-1e6607d77eab",
  "username": "cammy"
}
```

缺失、畸形、伪造、过期或无法关联用户的会话统一返回 401。数据库故障返回服务错误，不伪装为未登录。该依赖应可被后续记忆和菜单接口复用，且不读取前端提供的 user_id。

### 7.4 退出当前会话

`DELETE /api/v1/sessions/current`

- 必须通过来源校验。
- 不使用会强制返回 401 的当前用户依赖：无 Cookie、无效 Cookie、会话已过期或已删除时仍应可退出。
- 如有合法格式的凭证，按摘要删除对应会话，不影响其他设备。
- 删除提交成功后，以相同 Cookie 名、Path 和 Domain 策略清除 Cookie，返回 `204 No Content`。
- 重复退出返回 204。
- 数据库删除失败时返回服务错误，不宣称已成功撤销有效会话。

## 8. 来源校验、CORS 和限流

### 来源校验

四个接口中的 POST/DELETE 请求必须携带配置白名单中的 `Origin`。精确匹配 scheme、host 和 port；缺失、`null` 或不匹配均返回 403。GET `/users/me` 不要求 Origin。

这是一套面向自家浏览器前端的 API。curl、Postman 和自动化测试调用写接口时也须显式传入允许的 Origin。Origin 校验用于浏览器 CSRF 防护，不能替代会话认证。

不单独依赖 SameSite；未来如需支持不发送 Origin 的客户端，应另行设计认证/CSRF 策略，不直接放宽校验。

### CORS

- 以配置中的明确来源替换现有 `allow_origins=["*"]`。
- 使用 Cookie 跨域时启用 `allow_credentials=True`，前端需 `credentials: 'include'`。
- OPTIONS 预检不能被认证来源依赖误拦截。
- 本地前后端保持相同主机名，避免混用 localhost 与 127.0.0.1 引起 Cookie/SameSite 问题。
- 本阶段不修改前端；后续推荐使用 `/api` 同源代理。

### 基础限流

- 注册：每个来源 IP 每 10 分钟最多 5 次请求。
- 登录：每个来源 IP 每分钟最多 20 次、每个规范化用户名每分钟最多 10 次请求，两项均需满足。
- 限流包括失败请求；返回 429 和 `Retry-After` 秒数。
- 默认使用连接的真实 peer 地址，不盲目信任客户端传入的 X-Forwarded-For。
- 初版可使用线程安全、带过期清理和容量限制的进程内计数器；文档必须明确它只对单进程有效，重启会重置。
- 多 worker/多实例上线前必须改为共享限流存储或网关限流，不宣称进程内实现可覆盖整个集群。

## 9. 配置与资源生命周期

`.env.example` 中添加占位配置，不写真实凭证：

```dotenv
DATABASE_URL=postgresql://recipe_user:replace_me@localhost:5432/recipe_assistant
APP_ENV=development
AUTH_ALLOWED_ORIGINS=http://localhost:5173
AUTH_COOKIE_SECURE=false
AUTH_SESSION_TTL_SECONDS=604800
DB_POOL_MIN_SIZE=1
DB_POOL_MAX_SIZE=5
```

- 来源列表支持逗号分隔，拒绝通配符；用文档说明本地 Swagger 调试需加入实际 Swagger 页面来源。
- 生产配置禁止关闭 Secure 或允许非 HTTPS 前端来源。
- 数据库连接池在应用启动时创建并检查连接，在关闭时释放；不得在模块导入时连接数据库。
- 有限连接/获取超时，不让数据库不可用导致请求无限等待。
- 连接使用后归还池，异常事务回滚。连接池生命周期整合需保留现有启动行为。
- 数据库凭证、密码、会话原文及哈希不写入日志。修改 main.py 时移除已有的直接输出 API 密钥的调试打印。
- 过期会话即使尚未清理也不能通过鉴权。提供可手动调用的过期会话清理方式，不要求引入后台调度平台。

## 10. 自动化验收

使用专用 `TEST_DATABASE_URL`。禁止复用开发/生产数据表进行清空操作；测试配置缺失时明确报告测试未执行，不声称全部通过。不用 SQLite 替代 PostgreSQL 的 JSONB、事务和约束集成验证。

认证集成测试至少覆盖：

1. 注册返回 201，数据库保存 Argon2id 哈希，原始密码未落库。
2. 同时创建完整空 profile；其他用户的 profile 不被复制。
3. 用户名规范化一致，重复注册返回 409，包含并发重复注册情况。
4. 记忆插入失败时用户插入回滚。
5. 错误字段、畸形 JSON、非法用户名、超长/过短密码、非 JSON 请求返回约定错误且不回显密码。
6. 正确密码登录返回 201；错误密码和不存在用户名返回相同 401。
7. Cookie 属性与配置一致，数据库不含原始会话凭证。
8. 携带 Cookie 查询当前用户成功，缺失/伪造/畸形/过期会话返回 401。
9. 不同账户会话返回各自用户，不能通过额外 user_id 字段切换身份。
10. 登录轮换当前 Cookie 会话，旧凭证失效；其他设备会话不受影响。
11. 退出返回无正文的 204，旧凭证失效，重复退出仍返回 204。
12. 非法和缺失 Origin 的写请求返回 403；允许的来源和 OPTIONS 预检正常。
13. 限流触发 429、包含 Retry-After，并在窗口结束后恢复。
14. 数据库不可用时返回服务错误，不返回错误的登录成功或退出成功。
15. 测试不调用 LLM、搜索、向量数据库等与认证无关的服务。

端到端 API 验收链路：注册 → 登录并保存 Cookie → GET 当前用户 → 退出 → 复用旧 Cookie 查询返回 401。

## 11. 完成后的交付说明

AI 实施完成后必须报告：

- 实际修改文件与四个接口是否全部完成。
- 安装依赖、配置环境、启动服务和运行测试的具体命令。
- 使用 Cookie jar 和 Origin 请求头的 curl 调用示例（仅示例账户，不含真实密码）。
- 已运行测试的结果；未执行的测试及真实阻塞原因。
- 本阶段仍未实现前端登录、业务接口用户隔离、旧记忆迁移。
- 进程内限流的单进程限制和生产 HTTPS 配置要求。

不能用固定用户、伪造登录响应、内存用户列表或跳过密码校验代替真实数据库实现；不得静默执行建表或修改现有账号数据。


