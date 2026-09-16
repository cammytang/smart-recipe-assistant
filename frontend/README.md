# 智能菜谱助手前端

实现聊天规划、菜谱步骤、购物抽屉，以及用户名密码登录、注册和个人画像。设计依据为后端目录的 `muti_user_login_spec.md`。

## 本地运行

```sh
npm install
npm run dev -- --host localhost
```

参考 `.env.example` 创建 `.env.local`：

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

后端配置 `AUTH_ALLOWED_ORIGINS=http://localhost:5173`。前后端统一使用 localhost，避免混用 127.0.0.1。生产设置实际 HTTPS API 地址，并在后端启用 Secure Cookie 和允许的 HTTPS Origin。

API 地址不追加 `/api/v1`：认证接口使用 `/api/v1/users`、`/api/v1/sessions`，业务接口仍使用 `/memory`、`/menu/plan` 等原路径。所有请求，包括 SSE fetch，都携带 `credentials: 'include'`。

## 使用流程

1. 游客可以输入需求，首次发送时弹出登录框；不执行匿名规划。
2. 注册成功回到登录；登录成功后，原先待发送的需求只提交一次。
3. 关闭登录框保留草稿，并取消自动恢复。
4. 两页右上角头像打开个人画像，可以查看偏好、清空长期记忆、退出。
5. 会话通过 `/api/v1/users/me` 恢复；服务不可用会提供重试，不当作已退出。
6. 退出停止请求并清理用户数据。跨标签页通过 BroadcastChannel 和窗口焦点重新核实身份。

密码、Cookie、画像和聊天不存入 localStorage 或 sessionStorage。密码只在表单局部状态中保存；HttpOnly Cookie 由服务端设置/清除。

画像不支持标签编辑，暂无匿名试用、云端收藏、头像上传和对话历史恢复。菜单刷新或旧路由状态失效时需重新规划；已启动任务不会自动重放。网络失败的写操作和生成流也不自动重试。

## 检查与测试

```sh
npm run build
npm run lint
npm test
npm run test:e2e
```

单元测试覆盖身份隔离、迟到响应、会话恢复、待执行动作和退出异常。Playwright 使用本机 Google Chrome，自动在独立的 `http://localhost:5187` 启动测试前端，模拟 API 响应，不读写真实账户。需已安装 Chrome；无 Chrome 时可调整 Playwright channel 并安装对应浏览器。

真实联调需要另外启动已配置 PostgreSQL 的后端，并按以下顺序验证：注册 → 登录 → 规划 → 确认 → SSE 生成 → 查看画像 → 清空 → 退出。真实 AI 服务的生成结果与模拟浏览器测试应分开记录，不能用模拟测试宣称真实生成已验证。

主要模块：

- `src/auth/session.js`：会话协调、请求取消和身份版本检查。
- `src/auth/AuthProvider.jsx`：Context、启动恢复和标签页同步。
- `src/auth/AuthDialog.jsx`：登录/注册表单。
- `src/auth/ProfileDrawer.jsx`：画像查看、清空和退出。
- `src/api/client.js`：API 地址、Cookie、HTTP 错误处理。
