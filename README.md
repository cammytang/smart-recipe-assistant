# 智能菜谱助手（Smart Recipe Assistant）

> 根据用餐人数、饮食偏好、过敏原、现有食材和时间要求，规划菜单并生成菜谱、购物清单与来源信息。

## 📝 项目简介

智能菜谱助手是一个前后端分离的菜单规划应用。用户用自然语言描述用餐需求后，系统先生成可修改、可确认的菜品规划，再逐道检索和整理菜谱，最终输出完整菜单与去重后的购物清单。

项目将本地菜谱 RAG 与网络搜索结合：仓库中的 `backend/original_data/data/dishes.json` 包含 356 条结构化菜谱，并已配套本地 Qdrant `recipes` 集合。系统也可以通过 DuckDuckGo 或 Tavily 补充检索结果。适用于家庭菜单规划、现有食材利用、减脂或忌口菜单生成等场景。

## ✨ 核心功能

- [x] 自然语言菜单规划：解析人数、餐别、时间、已有食材、饮食偏好与忌口等约束。
- [x] 菜单确认与二次调整：先返回菜品规划，用户确认后再执行完整生成流程。
- [x] 混合菜谱检索：优先检索本地 Qdrant 菜谱库，并支持 DuckDuckGo、Tavily 等搜索后端。
- [x] 流式任务进度：通过 SSE 实时返回菜品状态、信息来源、摘要、最终报告和购物清单。
- [x] 长期偏好记忆：保存已确认菜单形成的饮食偏好、过敏原、不喜欢或常用食材等信息。（可手动清空偏好记忆）
- [x] 购物清单生成：从确认菜谱中提取每份食材并合并去重。
- [x] 固定用例评测：提供规划模式和完整流程模式，支持传统 Agent 与 LangGraph 实现。

## 🛠️ 技术栈

- 后端：Python、FastAPI、Uvicorn、Pydantic
- 智能体：HelloAgents `ToolAwareSimpleAgent`，按“规划 → 检索 → 总结 → 报告”流程协作
- 工作流：传统编排实现与 LangGraph 图工作流
- 检索：Qdrant 本地向量库、OpenAI 兼容 Embedding API、DuckDuckGo、Tavily
- 工具与存储：HelloAgents NoteTool、JSON 长期记忆、Loguru
- 前端：React 19、React Router、Vite 8、Tailwind CSS

## 🚀 快速开始

### 环境要求

- Python 3.10+（项目当前本地虚拟环境使用 Python 3.14）
- Node.js 20.19+ 或 22.12+
- 可用的 OpenAI 兼容大模型接口
- 可用的 Embedding 接口；项目运行时会查询本地 Qdrant 菜谱库
- 如使用 Tavily 搜索，需要 Tavily API Key；默认搜索后端为 DuckDuckGo

### 安装依赖

后端：

```bash
cd Smart_Recipe_Assistant/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

前端：

```bash
cd Smart_Recipe_Assistant/frontend
npm install
```

### 配置 API 密钥

后端会读取 `backend/.env`。仓库没有提供 `.env.example`，请自行创建该文件，并按实际服务填写：

```dotenv
# 大模型配置
LLM_PROVIDER=qwen
LLM_MODEL_ID=你的模型名称
LLM_API_KEY=你的 API Key
LLM_BASE_URL=你的 OpenAI 兼容接口地址

# Embedding 配置；未填写时会依次复用 OPENAI_* 或 LLM_* 配置
EMBEDDING_MODEL=你的 Embedding 模型名称
EMBEDDING_API_KEY=你的 Embedding API Key
EMBEDDING_BASE_URL=你的 OpenAI 兼容接口地址

# 搜索配置
SEARCH_API=duckduckgo
# 使用 Tavily 时再填写
TAVILY_API_KEY=你的 Tavily API Key
```

`LLM_PROVIDER` 也支持代码中已适配的 `ollama` 和 `lmstudio`。对应地址可通过 `OLLAMA_BASE_URL`、`LMSTUDIO_BASE_URL` 配置。

项目已经包含 `backend/qdrant_data`。如果更换了 Embedding 模型，或需要从 `dishes.json` 重新构建索引，请在后端目录运行：

```bash
python scripts/index_recipes.py --recreate
```

该命令会删除并重建本地 `recipes` 集合，请勿在仍有进程使用该 Qdrant 数据目录时执行。

### 运行项目

启动后端（默认监听 `http://127.0.0.1:8000`）：

```bash
cd Smart_Recipe_Assistant/backend
source .venv/bin/activate
python src/main.py
```

另开一个终端启动前端：

```bash
cd Smart_Recipe_Assistant/frontend
npm run dev
```

访问 Vite 在终端中显示的地址。当前前端将后端地址固定为 `http://127.0.0.1:8000`，如需使用其他主机或端口，需要同步修改前端页面中的请求地址。

可通过健康检查确认后端是否启动成功：

```bash
curl http://127.0.0.1:8000/healthz
```

## 📖 使用示例

在首页输入：

```text
两人减脂晚餐，冰箱有鸡蛋和西兰花，不吃辣，30 分钟内完成
```

典型使用流程：

1. 选择沿用后端搜索配置、DuckDuckGo 或 Tavily。
2. 点击“先规划菜单”，查看系统给出的菜品列表及其规划理由。
3. 如不满意，填写修改意见并重新规划；满意后确认菜单。
4. 在进度页查看各菜品的检索来源与摘要流式生成过程。
5. 生成完成后查看完整菜单和购物清单。


后端还提供以下接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/healthz` | 健康检查 |
| `POST` | `/menu/plan` | 只生成待确认的菜单规划 |
| `POST` | `/menu/stream` | 按确认后的菜品列表流式生成完整结果 |
| `POST` | `/research` | 同步执行完整研究流程 |
| `GET` | `/memory` | 读取长期记忆 |
| `POST` | `/memory/confirm` | 根据确认结果更新长期记忆 |
| `POST` | `/memory/clear` | 清空长期记忆 |

## 🎯 项目亮点

- 两阶段交互：将菜单规划和耗时的菜谱检索拆开，允许用户先修改、确认，再生成详细内容。
- 本地知识与网络搜索结合：本地结构化菜谱提供基础信息，网络检索用于补充来源与内容。
- 可观察的流式执行：前端按菜品展示进行中、完成、跳过或失败状态，并实时接收来源和摘要。
- 约束与记忆：本次明确输入优先于历史偏好，并记录记忆使用项和冲突项供评测。
- 可重复评测：评测器不依赖额外评审模型，使用确定性规则检查菜品数量、禁用食材、报告章节和购物清单去重等要求。

## 📊 性能评估

仓库提供 20 条固定评测用例，覆盖规划约束、安全约束、食材利用、饮食偏好、用餐规模、时间限制、长期记忆、报告质量和购物清单等类别。

已保存的最近一轮完整结果如下：

| 评测模式 | Agent | 用例数 | 通过数 | 平均得分 | 执行错误 |
| --- | --- | ---: | ---: | ---: | ---: |
| 仅规划 | legacy | 20 | 16 | 90.42% | 0 |
| 完整流程 | graph | 20 | 16 | 91.91% | 0 |

以上数据来自 `backend/evals/reports/eval_plan_20260731_105908.json` 和 `backend/evals/reports/eval_graph_full_20260731_115630.json`。这是基于仓库规则评测器的结果，不等同于真实用户满意度或线上性能指标。

运行仅规划评测：

```bash
cd Smart_Recipe_Assistant/backend
python evals/run_eval.py --mode plan
```

运行 LangGraph 完整流程评测（会调用模型、Embedding 和搜索服务）：

```bash
python evals/run_eval.py --mode full --agent graph
```

## 🔮 未来计划

仓库当前没有独立路线图。根据现有代码中可确认的限制，后续可优先处理：

- [ ] 将前端固定的后端地址改为环境变量配置。
- [ ] 为 `.env` 增加不含密钥的示例文件。
- [ ] 补充自动化测试，并针对现有评测中未通过的安全约束、负向偏好和报告质量用例继续优化。
- [ ] 为评测中的 LangGraph 规划模式补齐支持；当前 `--agent graph` 只支持 `--mode full`。


## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源协议，可自由使用、修改和分发。

## 👤 作者

- GitHub: [@cammytang](https://github.com/cammytang)

## 🙏 致谢

项目使用了 Datawhale 社区的 HelloAgents 框架，并基于 FastAPI、React、LangGraph、Qdrant 等开源项目构建。
