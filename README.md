# Bubble — 会记事、有情绪、能点单的个人 AI Agent

![持续更新中](https://img.shields.io/badge/status-%E6%8C%81%E7%BB%AD%E6%9B%B4%E6%96%B0%E4%B8%AD-blue)

> 自建 **Agent 运行时**的个人 AI 应用:对话里随口提到的信息被异步沉淀成长期记忆与兴趣知识图谱,
> 情绪被量化成趋势曲线,需要时还能通过外部 MCP 服务点一杯瑞幸。
> 记忆、图谱、情绪是**能力域**,按"能否让模型自主"分成不同的暴露方式。

## 架构总览

```
任务层   个人周报 / 记忆问答 / 兴趣多跳问答 / 瑞幸点单(用户可见的交付物)
入口层   对话(SSE 流式) / REST 接口 / 定时任务
编排层   ① Agent 运行时:ReAct + Function Calling 双路径循环
         ② 多步任务工作流:Plan-Execute(plan → execute → replan → finish)
工具层   11 个内置工具 + 外部 MCP 工具(动态接入、清单自动同步)
         治理:工具开关 / 读写分级 / 写操作审批 / 超时降级 / 结果缓存
能力域   长期记忆 · 兴趣知识图谱 · 情绪感知(各自拥有数据与生命周期)
执行层   Celery worker + beat:抽取、分析、长任务异步执行
存储     PostgreSQL + pgvector / Neo4j / Redis
```

**两种编排范式,按任务形态选**

| | ReAct 循环 | Plan-Execute 工作流 |
|---|---|---|
| 用在哪 | 对话问答、临时调工具 | 多步任务(如生成个人回顾) |
| 谁定下一步 | 模型每步现决定 | 规划器运行时产出显式步骤计划 |
| 结果校验 | 工具结果回灌给模型 | 每步声明期望结果,未达成自动重规划(三重上限封顶) |

**能力域:按"能否让模型自主"分三种暴露方式**

| 能力域 | 暴露给模型的形式 | 触发路径 |
|---|---|---|
| 记忆 | 工具 `recall` / `remember` / `forget` / `save_profile`;背景与洞察常驻注入 | 对话 + 回复结束后台 |
| 兴趣图谱 | 工具 `interest_recall`(多跳) / `interest_overview`(主线);抽取消解入图不暴露 | 对话 + 后台 + 定时重聚类 |
| 情绪 | **无工具**:后台分析写库 + 情绪档案注入 | 回复结束后台 |
| 外部服务 | 瑞幸门店查询与比价走工具;**下单不暴露**,走界面按钮 | 对话 + 人工确认 |

原则:**能自主的做成工具;有副作用的收窄成审批或界面按钮;不需要模型参与的重活交给事件与定时任务。**

## 快速开始

需要 Docker;本机开发另需 [uv](https://docs.astral.sh/uv/) 与 Node.js 20+。

### 方式 A:Docker 一键启动(推荐)

```bash
git clone https://github.com/Kaililili/bubble.git
cd bubble
cp .env.example .env
python api/gen_keys.py --write
docker compose up -d --build
```

> 没有 `python` 命令时用 `py api/gen_keys.py --write`(Windows)或
> `uv run --no-project python api/gen_keys.py --write`。
> 首次启动自动建表、补列、建向量索引;国内网络拉不动镜像时在 `.env` 里换镜像源
> (`NODE_IMAGE` / `NGINX_IMAGE` / `UV_IMAGE`)。

打开 http://localhost:5173 ,注册后在「设置 → 模型配置」填 chat 与 embedding 模型即可对话。

### 方式 B:本机开发

```bash
docker compose up -d postgres neo4j redis    # 只起存储
cp .env.example .env
python api/gen_keys.py --write
uv sync
cd api
uv run python run.py                         # http://localhost:8000
cd ../web
npm install
npm run dev                                  # http://localhost:5173
uv run celery -A app.celery_app worker --pool=solo -l info    # 另开终端:后台任务
```

> Windows 也可直接跑 `.venv\Scripts\python.exe run.py`(中文控制台先设 `$env:PYTHONIOENCODING='utf-8'`)。
> 需要定时任务(04:00 社区重聚类 / 04:30 洞察刷新 / 周日 21:00 个人回顾)再开一个终端跑 `celery beat`,只跑一个实例。

## 能做什么

注册后加一个 chat 模型即可开始,以下是跑通的效果:

| 你说的话 / 操作 | 会发生什么 |
|---|---|
| 「我最近在学 Rust,主要在看 async 和所有权」 | 攒够 5 条或静默 60 秒合并抽取一次,之后**兴趣页**出现实体与关系 |
| 「我以前是不是关注过篮球?」 | 图谱检索,回答带**时间区间**与**多跳路径**(篮球 → CBA/勇士队 → 库里);查不到就说不知道 |
| 「记住我的 Steam 密码是 xxx」 | 加密落库,列表只显示脱敏值,查看真实值需二次确认 |
| 「今天组会又被导师说了,好烦」 | **情绪页**记录 `愤怒 / 效价 -0.55` 与触发事件;后续对话先共情再给建议 |
| 「帮我看看我最近过得怎么样」 | 触发**多步任务**:收集情绪/兴趣/记忆 → 交叉分析 → 成文,报告约半分钟后发到本对话 |
| 「附近哪家瑞幸近?生椰拿铁多少钱?」 | 按距离和价格列出门店(需在「设置 → MCP」接入瑞幸服务) |
| 瑞幸页:选门店 → 选饮品 → 选规格 → 确认下单 | 走后端接口真实下单;**下单工具不暴露给模型** |

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.13 · FastAPI · SQLAlchemy 2(async) · LangChain / LangGraph · Pydantic v2 |
| 存储 | PostgreSQL + pgvector(业务与向量)· Neo4j(实体关系图)· Redis(缓存/队列) |
| 前端 | React 18 · TypeScript · Vite · Ant Design · ECharts · AntV X6 |
| 模型接入 | 兼容 OpenAI 协议的多 provider(chat / embedding / rerank),按用户配置动态构建客户端 |
| 工具扩展 | MCP(Model Context Protocol):外部服务工具动态接入,与内置工具统一注册、统一编排 |
| 异步 | Celery(Redis 队列)+ beat:兴趣抽取 / 情绪分析 / 会话摘要 / 洞察刷新 / 个人回顾 |

## 边界与限制

- **MCP 支持范围**:**SSE / Streamable HTTP** 传输 + **Bearer(或无)鉴权**的服务;
  不支持 stdio(本地进程)与 OAuth 类鉴权;内网地址会被 SSRF 校验拒绝。
- **定位是个人应用**,不是多租户 SaaS:队列与缓存按单用户设计(MCP 工具缓存为进程内缓存)。
- **未做公开评测**:验证方式是纯函数单测 + 真实账号端到端,没有对外声称的准确率指标。
- **不自动执行有副作用的操作**:下单、写库类操作一律需要用户确认,LLM 无法自主触发。

## 常见问题

**配置在哪里改?** 部署类(端口、数据库、Redis/Neo4j 地址)在仓库根的 `.env`;
应用类(模型 Key、MCP 服务、工具开关)在界面「设置」页,按用户保存、Key 加密落库。

**没配置模型能用吗?** 能。没配 embedding 时记忆与兴趣检索降级为关键词匹配;没配 websearch 时搜索工具会提示先去配置。

**支持哪些模型?** 任何兼容 OpenAI 协议的 chat / embedding(可选 rerank)。

**敏感信息怎么存?** 凭证真实值用 Fernet 加密,只对脱敏描述做向量化;面板默认脱敏,查看真实值需二次确认。

## 关键设计

- **幻觉治理**:实体/关系必须给出原句 evidence 并通过子串接地校验,否则直接丢弃;类型走白名单。
- **检索融合**:记忆召回 = **0.7 × 向量 + 0.15 × 重要度 + 0.15 × 时间新鲜度(30 天半衰期)**,
  非向量信号只用于破平局。
- **上下文预算**:长会话保留最近 40 条原文 + 滚动摘要;抽取时带最近 4 条消息做指代解析(不作证据)。
- **兴趣不是节点**:图里只有 `(:User)` 与 `(:Entity)`,「兴趣」是 `(User)-[:INTERESTED_IN {since,until,status}]->(Entity)`。
- **MCP 与写操作隔离**:敏感工具不进模型工具集,只生成审批单,用户确认后由后端按原始参数执行。

## 目录结构

```
bubble/
├── api/
│   ├── app/
│   │   ├── core/agent/          # Agent 运行时、工具注册、内置工具
│   │   │   ├── interest/        # 兴趣抽取/消解/社区/检索/Statement 溯源
│   │   │   ├── emotion/         # 情绪词表、分析、聚合
│   │   │   ├── memory/          # 融合排序、滚动摘要、洞察层、事实时效
│   │   │   └── plan/            # 多步任务编排(Plan-Execute 图 + 步骤执行器)
│   │   ├── models/              # SQLAlchemy 模型
│   │   ├── repositories/        # 数据访问层
│   │   ├── prompts/             # 提示词集中管理(带版本号与 registry)
│   │   ├── tasks/               # Celery 任务(抽取/情绪/摘要/洞察/回顾/维护)
│   │   ├── celery_app.py        # Celery 应用与 beat 计划
│   │   ├── services/            # chat / memory / interest / emotion / mcp / review
│   │   ├── controllers/         # FastAPI 路由
│   │   └── db/                  # PostgreSQL / Neo4j / Redis 连接与启动建表
│   ├── tests/                   # 纯函数单测(兴趣/情绪/记忆/提示词)
│   └── run.py                   # 本地启动入口
├── web/                         # React + Vite 前端(12 个页面,移动端适配)
├── docker-compose.yml           # 存储 + api + web + worker + beat
└── .env.example
```

## License

[MIT](LICENSE)
