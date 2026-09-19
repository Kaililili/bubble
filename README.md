# Bubble — 会记事、有情绪、能点单的个人 AI 助手

![持续更新中](https://img.shields.io/badge/status-%E6%8C%81%E7%BB%AD%E6%9B%B4%E6%96%B0%E4%B8%AD-blue)

> 一个把「长期记忆 + 知识图谱 + 工具调用」真正跑通的个人 Agent 应用:
> 聊天里随口提到的兴趣会被异步抽取成**实体关系图**,情绪会被量化成曲线,
> 需要时还能通过 MCP 帮你**点一杯瑞幸**(门店 → 比价 → 选规格 → 确认下单)——全部在自己搭的栈上跑。

**项目亮点**

- **对话驱动的兴趣知识图谱**:抽取 → 原句接地校验 → 四层实体消解 → Neo4j 幂等写 → 社区摘要,
  支持 Local(多跳)与 Global(主线)两种检索;原句证据提升为 `Statement` 溯源节点。
- **工程化的记忆系统**:背景常驻 / 长尾按需检索(向量 + 重要度 + 新鲜度融合)、滚动摘要、洞察层、
  事实时效(旧版本失效可追溯)、滑动窗口指代解析。
- **Agent 工具调用 + MCP**:function calling 与 ReAct 双路径;MCP 动态接入,敏感工具**只生成审批单**,
  用户在前端确认后由后端执行——LLM 永远无法自主下单。
- **情绪感知**:13 类受控情绪 + valence/arousal 二维量化,负面信号时自动带上相关记忆。

---

## 目录

- [核心功能](#核心功能)
- [技术栈](#技术栈)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [能做什么](#能做什么)
- [常见问题](#常见问题)
- [关键设计](#关键设计)
- [目录结构](#目录结构)

## 核心功能

| 模块 | 能力 |
|---|---|
| 模型配置 + 聊天 | 多 provider 模型配置中心(chat/embedding/websearch),API Key Fernet 加密落库;SSE 流式输出、多会话、历史持久化 |
| Agent 工具调用 | 工具注册中心 + function calling / ReAct 双路径;工具可开关;对话内工具卡片可下钻 |
| 记忆系统 | 用户背景(常驻,带 token 护栏)+ 长尾记忆(`remember`/`recall`/`forget`);凭证类加密存储、脱敏展示、查看需二次确认 |
| 兴趣图谱(GraphRAG) | 聊天异步抽取兴趣与实体关系,兴趣页展示时间线 + 实体关系图 + 多跳检索 + 兴趣主线 |
| 情绪助手 | 后台异步识别情绪(受控 13 类 + 效价/唤醒度),情绪页展示曲线、分布、气泡词云、触发事件 |
| MCP 工具接入 | 设置页可接入外部 MCP 服务(URL + token → 测试连接 → 自动同步工具清单),每个工具单独控制**是否暴露给 AI**、**是否需用户确认**,敏感工具只生成审批单;以瑞幸咖啡为例,接入后聊天里可查附近门店与比价,下单走页面按钮,底层下单工具**不暴露给模型** |

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.13 · FastAPI · SQLAlchemy 2(async) · LangChain/LangGraph · Pydantic v2 |
| 存储 | PostgreSQL + pgvector(业务与向量)· Neo4j(实体关系图)· Redis(缓存/队列) |
| 前端 | React 18 · TypeScript · Vite · Ant Design · ECharts · AntV X6 |
| 模型接入 | 兼容 OpenAI 协议的多 provider(chat / embedding / rerank),按用户配置动态构建客户端 |
| 工具扩展 | MCP(Model Context Protocol):外部服务工具动态接入,与内置工具统一注册、统一编排 |
| 异步 | Celery(Redis 队列)+ beat 定时任务:兴趣抽取 / 情绪分析 / 会话摘要 / 洞察刷新 |

## 环境要求

- Docker + Docker Compose(推荐用于存储与一键部署)
- 本机开发:[uv](https://docs.astral.sh/uv/) + Node.js 20+

## 快速开始

### 方式 A:Docker 一键启动(推荐)

```bash
git clone https://github.com/Kaililili/bubble.git
cd bubble

cp .env.example .env           
python api/gen_keys.py --write 
docker compose up -d --build    
```

> 没有 `python` 命令时用 `py api/gen_keys.py --write`(Windows)或
> `uv run --no-project python api/gen_keys.py --write`;去掉 `--write` 只打印结果。
> 首次启动会自动建表、补列、建向量索引,不需要手动初始化。

> 国内网络:Docker Hub / ghcr.io 拉不动时,在 `.env` 里取消对应行的注释换镜像源
> (`api` / `worker` / `beat` 三个镜像都基于 `UV_IMAGE`):
>
> ```dotenv
> NODE_IMAGE=docker.m.daocloud.io/library/node:20-alpine
> NGINX_IMAGE=docker.m.daocloud.io/library/nginx:alpine
> UV_IMAGE=ghcr.nju.edu.cn/astral-sh/uv:python3.13-bookworm-slim
> ```

打开 http://localhost:5173 ,注册账号后在「设置 → 模型配置」里填 chat 与 embedding 模型即可开始对话。

### 方式 B:本机开发

```bash
# 1) 只起存储
docker compose up -d postgres neo4j redis

# 2) 后端(首次先建 .env 和密钥)
cp .env.example .env
python api/gen_keys.py --write
uv sync
cd api
uv run python run.py            # http://localhost:8000

# 3) 前端
cd ../web
npm install
npm run dev                     # http://localhost:5173

# 4) 后台任务 worker(另开一个终端):兴趣/情绪/摘要/洞察靠它消费队列
cd ../api
uv run celery -A app.celery_app worker --pool=solo -l info
```

> Windows 也可以直接跑 `.venv\Scripts\python.exe run.py`(中文控制台先设 `$env:PYTHONIOENCODING='utf-8'`)。
> 需要定时任务(每天 04:00 社区重聚类、04:30 洞察刷新)再开一个终端跑
> `uv run celery -A app.celery_app beat -l info`,只跑一个实例。

## 能做什么

注册后在「设置 → 模型配置」里加一个 chat 模型(建议再配 embedding)即可开始,以下都是跑通的效果:

| 你说的话 / 操作 | 会发生什么 |
|---|---|
| 「我最近在学 Rust,主要在看 async 和所有权」 | 消息进队列,攒够 5 条或静默 60 秒后合并抽取一次,之后**兴趣页**出现实体与关系(参数见 `.env.example`) |
| 「我以前是不是关注过篮球?」 | 触发图谱检索,回答带**时间区间**与**多跳路径**(篮球 → CBA/勇士队 → 库里);查不到就说不知道,不编造 |
| 「记住我的 Steam 密码是 xxx」 | 加密落库,列表只显示脱敏值,查看真实值需二次确认 |
| 「今天组会又被导师说了,好烦」 | **情绪页**记录 `愤怒 / 效价 -0.55` 与触发事件;后续对话会先共情再给建议 |
| 「附近哪家瑞幸近?生椰拿铁多少钱?」 | 按距离和价格列出门店(需先在「设置 → MCP」接入瑞幸服务) |
| 瑞幸页:选门店 → 选饮品 → 选规格 → 确认下单 | 走后端接口真实下单;**下单工具不暴露给模型**,对话里只会引导你去页面操作 |
| 在兴趣页点节点 | 展示该实体的时间线、关联实体与**原句出处**(Statement 溯源) |

## 常见问题

**配置在哪里改?**

- **部署类**(端口、数据库连接、Redis/Neo4j 地址):仓库根的 `.env`,模板见 `.env.example`,
  改完 `docker compose up -d` 重启生效。
- **应用类**(模型 API Key、MCP 服务、工具开关):界面里的「设置」页,按用户保存、Key 加密落库,不用改代码。

**没配置模型能用吗?**

能。没配 embedding 时,记忆与兴趣检索降级为关键词匹配;没配 websearch 时搜索工具会提示先去配置。
都不影响聊天主链路。

**支持哪些模型?**

任何兼容 OpenAI 协议的 chat / embedding(可选 rerank),在「设置 → 模型配置」里按用户添加。

**敏感信息怎么存?**

凭证类真实值用 Fernet 加密,只对脱敏描述做向量化;面板默认脱敏展示,查看真实值需二次确认。

## 关键设计

几条硬约束:

- **幻觉治理**:实体/关系必须给出原句 evidence 并通过子串接地校验,否则直接丢弃;实体类型与关系类型都走白名单。
- **兴趣不是节点**:图里只有 `(:User)` 与 `(:Entity)`,「兴趣」是 `(User)-[:INTERESTED_IN {since,until,status}]->(Entity)` 这条边;
  实体之间用 `:RELATED {type,weight}` 表达上下位/成员/组成/共现。
- **降级优先**:Neo4j 不可用时检索降级为 PostgreSQL 向量/关键词;未配置 embedding 时降级关键词;后台任务失败不影响聊天。
- **凭证安全**:真实值 Fernet 加密、只对脱敏描述向量化、面板查看需二次确认、对话历史落库前先脱敏。
- **检索融合**:记忆召回打分 = **0.7 × 向量相似度 + 0.15 × 重要度 + 0.15 × 时间新鲜度**,命中回写访问次数,
  非向量信号只用于破平局。
- **上下文预算**:长会话保留最近 40 条原文 + 滚动摘要;抽取时带最近 4 条消息做指代解析(仅上下文,不作证据)。
- **MCP 与写操作隔离**:外部 MCP 服务动态加载(工具名清洗、单服务超时降级、进程内缓存);
  下单/取消这类敏感工具**不进模型工具集**,只生成审批单,用户确认后由后端按原始参数执行。

## 目录结构

```
bubble/
├── api/
│   ├── app/
│   │   ├── core/agent/          # Agent 编排、工具注册、内置工具
│   │   │   ├── interest/        # 兴趣抽取/消解/社区/检索/Statement 溯源
│   │   │   ├── emotion/         # 情绪词表、分析、聚合
│   │   │   └── memory/          # 融合排序、滚动摘要、洞察层、事实时效
│   │   ├── models/              # SQLAlchemy 模型
│   │   ├── repositories/        # 数据访问层
│   │   ├── prompts/             # 提示词集中管理(带版本号与 registry)
│   │   ├── tasks/               # Celery 任务(抽取/情绪/摘要/洞察/定时维护)
│   │   ├── celery_app.py        # Celery 应用与 beat 计划
│   │   ├── services/            # chat / memory / interest / emotion / mcp
│   │   ├── controllers/         # FastAPI 路由
│   │   └── db/                  # PostgreSQL / Neo4j / Redis 连接与启动建表
│   ├── tests/                   # 纯函数单测(兴趣/情绪/记忆/提示词)
│   ├── init_db.py               # 幂等建表/补列/建向量索引
│   └── run.py                   # 本地启动入口
├── web/                         # React + Vite 前端
├── docker-compose.yml           # 存储 + api + web + worker + beat
└── .env.example
```

## License

[MIT](LICENSE)
