# GitHub Actions 持续部署

## 发布行为

- 推送到 `main`：构建并发布两份 `linux/amd64` 镜像；两者成功后才部署该提交的
  `sha-<完整提交 SHA>` 版本。这里“最新版本”指本次成功构建的提交，不使用浮动 `latest`。
- Actions → **Publish container images**：手动构建，可取消勾选 `deploy` 只发布镜像。
- Actions → **Deploy application**：选择默认分支，填写已经发布过的完整镜像版本，
  例如 `sha-763679ecc2a4b13baaccf0405c002083df1cb5d4`。用于部署指定版本或回退。
- 非默认分支不能执行生产部署。工作流不会调用模型或重新构建菜谱索引。
- 当前发布流程执行镜像构建，不包含完整应用测试；业务测试工作流可后续单独接入。

## 服务器前提

本项目已在腾讯云香港服务器部署，默认目录 `/home/ubuntu/apps/smart-recipe`，保留：

```text
backend.env                    # 真实运行密钥，仅在服务器
postgres.env                   # 数据库配置，仅在服务器
runtime/qdrant_data/            # 已初始化菜谱索引
runtime/notes/
runtime/logs/
caddy/Caddyfile
```

外部 Docker 网络 `smart-recipe`、数据库 `smart-recipe-db`、HTTPS 网关
`smart-recipe-gateway` 必须已经正常运行，域名为 `https://chef-ai.club`。
CD 不管理这两个容器、不初始化数据库、不删除卷或重建索引。
部署使用的 UID/GID、索引模型应与已有后端保持一致。

部署用户须能上传文件，且 `sudo -n docker info` 无需交互密码即可执行。
有 Docker 管理权限的部署密钥具有很高的服务器权限，只供受信任的生产工作流使用。
私有镜像请事先在服务器的 root Docker 配置中配置只读拉取凭据
（脚本使用 `sudo docker`）；公开镜像无需登录。

发布前检查（服务器执行，不会显示密钥）：

```sh
cd ~/apps/smart-recipe
test -s backend.env
test -d runtime/qdrant_data
sudo -n docker info >/dev/null
sudo docker compose version
curl --fail --show-error https://chef-ai.club/api/healthz
```

## 为 Actions 配置专用 SSH 密钥

在 Mac 创建密钥；如果目标文件已存在，勿覆盖，换一个新文件名：

```sh
ssh-keygen -t ed25519 -f ~/.ssh/chef-ai-deploy -C github-actions-chef-ai
```

自动部署需要无交互密钥，专用密钥不设置口令。将 `.pub` 公钥的一整行添加到服务器部署
用户（当前 `ubuntu`）的 `~/.ssh/authorized_keys`，保留已有公钥。
服务器上 `~/.ssh` 权限应为 `700`，`authorized_keys` 为 `600`。
私钥不上传服务器、不提交仓库，只保存到 GitHub Secret。

如果 Mac 已能 SSH 登录该服务器，可追加公钥并验证新密钥：

```sh
cat ~/.ssh/chef-ai-deploy.pub | ssh ubuntu@43.129.171.222 \
  'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys'
ssh -i ~/.ssh/chef-ai-deploy -o IdentitiesOnly=yes ubuntu@43.129.171.222 'sudo -n docker info >/dev/null && echo ready'
```

Mac 可用 `pbcopy < ~/.ssh/chef-ai-deploy` 将私钥复制到剪贴板，再粘贴到
GitHub Secret；不要贴到终端日志或聊天。保存后清空剪贴板。

验证 SSH 后，先在可信的服务器终端查看主机指纹：

```sh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Mac 上扫描并对照指纹（扫描本身不证明服务器身份）：

```sh
ssh-keyscan -t ed25519 43.129.171.222 > /tmp/chef-ai-known-hosts
ssh-keygen -lf /tmp/chef-ai-known-hosts
```

确认指纹一致后，将 `/tmp/chef-ai-known-hosts` 的内容保存到下面的 Secret。
自定义 SSH 端口时扫描也要加对应的 `-p` 参数。

## GitHub 设置

仓库 Settings → Environments 创建 `production`，按需要限制部署分支为 `main`。
在仓库 Settings → Secrets and variables → Actions 配置 Repository secrets：

| Secret | 值 |
| --- | --- |
| `DEPLOY_HOST` | `43.129.171.222`（以控制台实际公网 IP 为准） |
| `DEPLOY_USER` | `ubuntu` |
| `DEPLOY_SSH_KEY` | 专用 SSH 私钥完整内容，包括 BEGIN/END 行 |
| `DEPLOY_KNOWN_HOSTS` | 核验后的 known_hosts 记录 |

可选 Repository variables：

| Variable | 默认值 |
| --- | --- |
| `DEPLOY_PORT` | `22` |
| `DEPLOY_PATH` | `/home/ubuntu/apps/smart-recipe` |

密钥只在 GitHub 设置页粘贴，不发到聊天里。服务器防火墙须允许 Runner 的 SSH 连接；
如果仅允许个人固定 IP，需要另行配置 Runner 网络接入。

## 首次启用

先完成上述配置，再提交并推送工作流和 `deploy/`，因为推送 `main` 会触发构建与部署。
也可以先手动运行 **Deploy application**，部署已存在的 SHA 镜像，验证 SSH 和服务接管。
首次接管会在两份镜像均拉取成功后，停止并移除旧前后端容器（不删除卷），再用
`smart-recipe-app` Compose 项目创建同名容器，保持网关转发和网络别名。
这是单实例部署，会有短暂停机，进行中的生成请求可能中断。

发布包保存到服务器 `releases/<版本>-<运行编号>-<尝试编号>/`。后端环境文件及运行数据
不通过 Actions 上传或覆盖。运行摘要记录成功版本；服务器 `.deployed-version` 和
`.previous-version` 记录最近成功发布信息。

健康检查覆盖容器、前端 `/api/healthz` 转发和公网 HTTPS。它不验证外部模型、搜索接口
及真实生成质量，发布后仍需业务验收。

失败时工作流保持红色，并尝试使用本次开始前记录的前后端镜像重新创建服务。
回退仅覆盖应用镜像，不回退 `backend.env`、数据库结构或数据。数据库迁移需要另行设计
兼容性和恢复方案。首次不存在完整旧版本或回退失败时，需要人工处理。

不要再交替使用旧 `compose.backend.yaml` 更新同名容器，以免旧配置覆盖 CD 管理的版本。
可以用当前成功发布包查看状态：

```sh
sudo docker ps --filter name=smart-recipe
sudo docker logs --tail 60 smart-recipe-backend
```

旧镜像不会自动清理，以便回退；2 GB / 40 GB 服务器需要定期检查磁盘，确认回退版本后
再清理不需要的镜像，勿执行删除数据卷的清理命令。

## 本地检查

```sh
bash -n deploy/deploy.sh
python3 -m unittest discover -s deploy -p 'test_*.py' -v
```

测试使用模拟 Docker/网络命令，覆盖先拉取后停机、拉取失败保留服务、健康失败恢复旧镜像
以及拒绝非法版本；不会连接服务器或读取生产密钥。
