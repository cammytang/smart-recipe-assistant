# 认证接口调用文档

本文件描述 `src/auth/router.py` 已实现的四个接口。实施约束见 [AUTH_API_SPEC.md](../AUTH_API_SPEC.md)，安装配置见 [README.md](../README.md)。

## 服务地址和通用规则

- 本地基地址：`http://localhost:8000`。
- API 前缀：`/api/v1`。
- Swagger：`http://localhost:8000/docs`。
- OpenAPI JSON：`http://localhost:8000/openapi.json`。
- 注册和登录要求 `Content-Type: application/json`。
- 所有 POST/DELETE 要求 `Origin` 精确匹配 `AUTH_ALLOWED_ORIGINS`。curl/Postman 也必须设置，例如 `Origin: http://localhost:5173`。
- 浏览器跨端口调用必须 `credentials: 'include'`。不要在 localStorage 保存密码或会话凭证。
- 认证响应均设置 `Cache-Control: no-store`。

## 1. 注册用户

`POST /api/v1/users`

无需登录。创建用户和独立空记忆，注册成功不会自动登录。

| 请求字段 | 类型 | 必填 | 校验 |
| --- | --- | --- | --- |
| username | string | 是 | trim 并转小写后，3～64 位字母、数字、下划线 |
| password | string | 是 | 8～128 个可打印 ASCII 字符，允许空格，不裁剪 |

不接受额外字段。密码无需强制每种字符均出现，不接受中文或控制字符。

```json
{"username":"demo_user","password":"Example-password-123!"}
```

成功 `201 Created`：

```json
{
  "id": "b652d664-0d55-4ad6-a31f-1e6607d77eab",
  "username": "demo_user",
  "created_at": "2026-09-14T08:00:00Z"
}
```

常见失败：409 用户名已占用；422 输入不合法；429 注册过频。

## 2. 登录

`POST /api/v1/sessions`

请求字段与注册相同。

成功 `201 Created`：

```json
{
  "user": {
    "id": "b652d664-0d55-4ad6-a31f-1e6607d77eab",
    "username": "demo_user"
  },
  "expires_at": "2026-09-21T08:00:00Z"
}
```

响应同时设置 `recipe_session` Cookie，属性为 HttpOnly、SameSite=Lax、Path=/、默认 Max-Age=604800。生产环境开启 Secure。会话凭证不会出现在 JSON 响应里。

每次成功登录轮换当前 Cookie 对应的会话，不影响其他设备；失败登录不撤销已有会话。用户名不存在和密码错误统一返回 401。

## 3. 获取当前用户

`GET /api/v1/users/me`

无请求体，不接受指定用户身份。浏览器自动附带 Cookie。

成功 `200 OK`：

```json
{
  "id": "b652d664-0d55-4ad6-a31f-1e6607d77eab",
  "username": "demo_user"
}
```

没有有效会话或会话过期时返回 401；数据库不可用返回 503。前端启动时调用此接口恢复登录状态，网络/服务错误应提供重试，不应一律当作未登录。

## 4. 退出当前会话

`DELETE /api/v1/sessions/current`

无请求体，需要允许的 Origin。删除当前会话并清除 Cookie，不退出其他设备。

成功 `204 No Content`，无响应体。无 Cookie、会话不存在或重复退出均返回 204。数据库撤销失败返回服务错误，不返回成功。

## 错误格式与状态码

```json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "用户名或密码错误"
  }
}
```

| 状态码 | code | 含义 |
| --- | --- | --- |
| 401 | INVALID_CREDENTIALS | 用户名或密码错误 |
| 401 | UNAUTHENTICATED | 缺失、无效或过期会话 |
| 403 | ORIGIN_NOT_ALLOWED | 写请求缺少或使用不允许的 Origin |
| 409 | USERNAME_TAKEN | 用户名已被使用 |
| 415 | UNSUPPORTED_MEDIA_TYPE | 注册/登录未使用 JSON |
| 422 | VALIDATION_ERROR | JSON 或字段校验失败 |
| 429 | RATE_LIMITED | 超出限流，参考 Retry-After 秒数 |
| 500 | INTERNAL_ERROR | 内部异常 |
| 503 | SERVICE_UNAVAILABLE | 数据库连接不可用 |

注册每 IP 5 次/10 分钟；登录每 IP 20 次/分钟且每用户名 10 次/分钟。限流是单进程内存实现，多进程部署需共享限流或网关支持。

## 浏览器调用示例

以下代码应运行在允许来源的前端页面中：

```javascript
const base = 'http://localhost:8000/api/v1'

async function request(path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    ...options,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (response.status === 204) return null
  const data = await response.json()
  if (!response.ok) throw new Error(data.error?.message || '请求失败')
  return data
}

await request('/users', {
  method: 'POST',
  body: JSON.stringify({ username: 'demo_user', password: 'Example-password-123!' }),
})
await request('/sessions', {
  method: 'POST',
  body: JSON.stringify({ username: 'demo_user', password: 'Example-password-123!' }),
})
const user = await request('/users/me')
await request('/sessions/current', { method: 'DELETE' })
```

浏览器自动设置 Origin，不在 JavaScript 中手动伪造。确保前后端统一使用 localhost，或都使用 127.0.0.1。

## 调试顺序

1. 配置数据库连接和允许来源，启动服务。
2. 注册新测试用户，检查返回 201。
3. 登录，确认收到 Set-Cookie。
4. 携带 Cookie 查询当前用户，确认 200 且用户匹配。
5. 退出，确认 204。
6. 再携带原 Cookie 查询用户，确认 401。

完整 curl Cookie jar 示例见 [README.md](../README.md#curl-验证)。不要把 Swagger 的“注册成功”当作已登录，记忆和菜单接口也已接入用户鉴权，参见 [业务接口文档](MEMORY_API.md)。前端仍需携带登录 Cookie。
