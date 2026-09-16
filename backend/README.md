# 后端认证接口

按 [AUTH_API_SPEC.md](AUTH_API_SPEC.md) 实现。四个接口采用 PostgreSQL 会话与 HttpOnly Cookie：

| 方法 | 路径 | 成功状态 |
| --- | --- | --- |
| POST | `/api/v1/users` | 201，注册并初始化空记忆 |
| POST | `/api/v1/sessions` | 201，登录并设置 Cookie |
| GET | `/api/v1/users/me` | 200，当前用户 |
| DELETE | `/api/v1/sessions/current` | 204，撤销当前会话并清除 Cookie |

## 安装与配置

在 `Smart_Recipe_Assistant/backend` 目录执行：

```sh
python3 -m venv .venv  # 已有虚拟环境时跳过
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
```

编辑已有 `.env`，参考 `.env.example` 补充 `DATABASE_URL`、`AUTH_ALLOWED_ORIGINS` 等配置；不要覆盖已有 LLM 配置，不要提交真实密码。连接 URL 中的特殊字符需 URL 编码。

数据库必须已有 `database/init.sql` 中的三张表。应用不会自动建表或迁移数据，启动时只读校验字段类型和用户名格式。缺少 `DATABASE_URL` 或表结构不兼容会明确阻止启动。

用户名规范化后为 3～64 位小写英文字母、数字或下划线。密码遵循当前规范的 8～128 位规则，允许可打印 ASCII 字母、数字、符号和空格，不要求每类都出现，不裁剪空格；不接受控制字符或中文密码。使用 Argon2id，不保存明文。

## 启动

只启动认证服务，不加载 LLM、搜索和向量数据库：

```sh
.venv/bin/python -m uvicorn auth.app:create_auth_app --factory --app-dir src --host 127.0.0.1 --port 8000 --no-proxy-headers
```

启动整个菜谱后端：

```sh
.venv/bin/python -m uvicorn main:app --app-dir src --host 127.0.0.1 --port 8000 --no-proxy-headers
```

直接 peer 地址用于限流。生产反向代理环境需要单独配置可信代理或网关限流，不可盲信外部转发头。

Swagger 地址为 `http://localhost:8000/docs`。若从此页面测试写请求，将 `http://localhost:8000` 加入 `AUTH_ALLOWED_ORIGINS`，例如：

```dotenv
AUTH_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:8000
```

Origin 必须精确匹配，不允许通配符。注册、登录和退出缺少/非法 Origin 返回 403。开发时统一使用 localhost；不要混用 localhost 与 127.0.0.1。跨端口前端请求需 `credentials: 'include'`，后续推荐统一 `/api` 代理。

生产配置必须为 `APP_ENV=production`、`AUTH_COOKIE_SECURE=true`，前端来源使用 HTTPS。默认会话固定有效 7 天，无自动续期。登录只轮换当前 Cookie 会话，其他设备会话保持有效。

## curl 验证

以下仅为演示账户。写接口必须发送 Origin。Cookie jar 中包含登录凭证，请妥善处理，不要提交仓库或共享。

```sh
curl -i http://localhost:8000/api/v1/users \
  -H 'Origin: http://localhost:5173' \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_user","password":"Example-password-123!"}'

curl -i -c /tmp/recipe-auth-cookies.txt http://localhost:8000/api/v1/sessions \
  -H 'Origin: http://localhost:5173' \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_user","password":"Example-password-123!"}'

curl -i -b /tmp/recipe-auth-cookies.txt http://localhost:8000/api/v1/users/me

curl -i -X DELETE -b /tmp/recipe-auth-cookies.txt \
  -H 'Origin: http://localhost:5173' \
  http://localhost:8000/api/v1/sessions/current

# jar 保留旧凭证；服务端已撤销，因此此请求应返回 401。
curl -i -b /tmp/recipe-auth-cookies.txt http://localhost:8000/api/v1/users/me
```

响应统一包含 `Cache-Control: no-store`。错误为 `{"error":{"code":"...","message":"..."}}`。错误响应不回显密码、哈希、SQL 或堆栈。数据库故障返回 503，其他未预期错误返回 500。

## 测试

使用独立、可丢弃的 PostgreSQL 测试数据库，数据库名需包含 `test`。测试通过 shell 环境读取 `TEST_DATABASE_URL`，不会自动读取真实 `.env`。

```sh
# 用自己的专用测试连接替换示例，不要指向业务数据库。
export TEST_DATABASE_URL='postgresql://localhost/recipe_auth_test'
.venv/bin/python -m pytest tests -q
```

测试为每项集成测试创建随机 schema 并加载 `database/init.sql`，结束时只删除自己创建的 schema。该数据库用户需要创建 schema 的权限；测试不清空或重建原有业务表。未配置 TEST_DATABASE_URL 时，数据库集成测试会明确 skip，其余校验测试仍执行。全量验收必须有真实 PostgreSQL，不使用 SQLite 替代。

测试包含注册事务回滚、重复注册并发、会话摘要与属性、错误密码、用户隔离、轮换/过期/退出、异常输入、Origin、CORS、限流和连接池不可用。

## 过期会话清理

```sh
.venv/bin/python scripts/cleanup_sessions.py
```

只删除已过期会话，不修改用户或偏好。即使没有运行清理，过期会话也无法通过鉴权。

## 当前范围与部署限制

- 未增加前端登录页，也未迁移 `user_memory.json`。记忆和菜单接口现已要求有效会话，记忆按用户存储于 PostgreSQL。
- 业务接口通过 `Depends(get_current_user)` 获取可信用户 ID，MemoryService 绑定该用户；不能信任请求体中的 user_id。
- 限流为线程安全的进程内固定窗口，具有容量限制和过期清理。注册每 IP 5 次/10 分钟，登录每 IP 20 次/分钟且每用户名 10 次/分钟。只对单进程有效，重启会重置。
- 多 worker/多实例部署前必须采用共享限流存储或网关限流；本阶段未引入 Redis。

## 用户记忆与菜单鉴权

现已为 `/memory`、`/memory/confirm`、`/memory/clear`、`/menu/plan`、`/menu/stream` 和 `/research` 接入会话鉴权。详见 [业务接口文档](docs/MEMORY_API.md)。

记忆按用户存入 PostgreSQL；确认和清空使用短事务，Agent 使用当前请求的记忆快照。旧 JSON 不再自动读取，未迁移旧数据。前端登录与 Cookie 请求接入仍未包含在本次修改中。
