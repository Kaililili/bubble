# Bubble — 会记事、有情绪、能点单的个人 AI 助手

> 一个把「长期记忆 + 知识图谱 + 工具调用」真正跑通的个人 Agent 应用:
> 聊天里随口提到的兴趣会被异步抽取成**实体关系图**,情绪会被量化成曲线,
> 需要时还能通过 MCP 帮你**比价下单**——全部在自己搭的栈上跑。

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
- [首次使用流程](#首次使用流程)
- [常见问题](#常见问题)
- [关键设计](#关键设计)
- [目录结构](#目录结构)
- [开发约定](#开发约定)
- [Roadmap](#roadmap)

## 核心功能

| 模块 | 能力 |
|---|---|
| 模型配置 + 聊天 | 多 provider 模型配置中心(chat/embedding/websearch),API Key Fernet 加密落库;SSE 流式输出、多会话、历史持久化 |
| Agent 工具调用 | 工具注册中心 + function calling / ReAct 双路径;工具可开关;对话内工具卡片可下钻 |
| 记忆系统 | 用户背景(常驻,带 token 护栏)+ 长尾记忆(`remember`/`recall`/`forget`);凭证类加密存储、脱敏展示、查看需二次确认 |
| 兴趣图谱(GraphRAG) | 聊天异步抽取兴趣与实体关系,兴趣页展示时间线 + 实体关系图 + 多跳检索 + 兴趣主线 |
| 情绪助手 | 后台异步识别情绪(受控 13 类 + 效价/唤醒度),情绪页展示曲线、分布、气泡词云、触发事件 |
| MCP 接入 | 设置页配置 MCP 服务(自动同步工具清单);内置瑞幸比价/下单:门店 → 比价 → 选规格 → 确认下单 |
| 日志与追踪 | 统一异常处理、请求上下文、结构化日志(按请求串联关键步骤) |

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.13 · FastAPI · SQLAlchemy 2(async) · LangChain/LangGraph · Pydantic v2 |
| 存储 | PostgreSQL + pgvector(业务与向量)· Neo4j(实体关系图)· Redis(缓存/队列) |
| 前端 | React 18 · TypeScript · Vite · Ant Design · ECharts · AntV X6 |
| 模型接入 | 兼容 OpenAI 协议的多 provider(chat / embedding / rerank),按用户配置动态构建客户端 |
| 异步 | Celery(Redis 队列)+ 定时任务:兴趣抽取 / 情绪分析 / 会话摘要 / 洞察刷新;本地开发可切回进程内 inline 模式 |

**异步设计**:聊天主链路只做「读上下文 → 调模型 → 流式返回」;兴趣、情绪、摘要、洞察都在**回复结束后**由后台任务完成(队列模式可重试、进程重启不丢,见 FAQ),

## 环境要求

- Docker + Docker Compose(推荐用于存储与一键部署)
- 本机开发:[uv](https://docs.astral.sh/uv/)(会自动装 Python 3.13,不用自己装)+ Node.js 20+
- 只需要一个能跑 `python` 的解释器来生成密钥(脚本只用标准库);没装也可以让 uv 代跑

## 快速开始

### 方式 A:Docker 一键启动(推荐)

```bash
git clone https://github.com/Kaililili/bubble.git
cd bubble

# 1) 建 .env(Windows PowerShell 用:Copy-Item .env.example .env)
cp .env.example .env

# 2) 生成 JWT_SECRET / FERNET_KEY 并写入 .env
#    脚本只用标准库,任何 Python 3 都能跑;没装 Python 就用 uv 代跑(见下)
python api/gen_keys.py --write

# 3) 起 7 个容器:postgres / neo4j / redis / api / web / worker / beat
docker compose up -d --build
docker compose ps                # 7 个服务都是 Up 就绪
# 建表/补列/向量索引在服务启动时自动完成,无需手动初始化
```

没装 Python 时的两种替代(任选一种):

```bash
py api/gen_keys.py --write                              # Windows 自带 py 启动器
uv run --no-project python api/gen_keys.py --write      # 用 uv 临时拉一个 Python,不装依赖
python3 api/gen_keys.py --write                         # macOS / Linux
```

去掉 `--write` 只打印结果,自己贴进 `.env` 也可以。

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
# 1) 只起存储(Docker Desktop 要先启动)
docker compose up -d postgres neo4j redis

# 2) 后端:第一次先建 .env 与密钥(仓库根的 .env 提供配置)
cp .env.example .env            # Windows PowerShell:Copy-Item .env.example .env
python api/gen_keys.py --write

uv sync
cd api
uv run python run.py            # http://localhost:8000(启动时自动建表/补列/建索引)
# Windows 也可以直接:.venv\Scripts\python.exe run.py
# (中文控制台先执行 $env:PYTHONIOENCODING='utf-8')

# 3) 前端
cd ../web
npm install
npm run dev                     # http://localhost:5173,/api 代理到 8000

# 4) 后台任务(可选):默认进程内 inline,不需要 worker;
#    想让兴趣/情绪/摘要/洞察进队列,另开一个终端在 api/ 下:
# uv run celery -A app.celery_app worker --pool=solo -l info   # Windows 必须 --pool=solo
# uv run celery -A app.celery_app beat -l info                 # 定时任务
```

> 依赖声明在**仓库根目录**的 `pyproject.toml`,`.venv` 也建在根目录;在 `api/` 下执行 `uv sync`/`uv run` 也可以(uv 会向上找到项目)。
> 跑 `uv run <命令>` 就不用管虚拟环境路径了;直接调用解释器则是 `.venv\Scripts\python.exe`(Windows)。

## 首次使用流程

1. 注册账号 → 「设置 → 模型配置」添加 chat 与 embedding(可选 websearch/rerank)。
2. 在聊天里说一句陈述,例如「我最近在学 Rust,顺便在看 async 和所有权」。
3. 约十几秒后,**兴趣页**会出现对应实体与关系(后台抽取);聊天里也会提示「已加入兴趣档案」。
4. 问「我以前是不是关注过篮球?」「跟 NBA 相关的我还关注过什么?」——会触发 `interest_recall` 工具,
   回答里带**时间区间**与**多跳路径**;查不到时明确说不知道,不编造。
5. 说一句带情绪的话(「今天组会又被导师说了,好烦」),情绪页会出现记录与触发事件。

## 常见问题

**没配置 embedding 模型能用吗?**

能。记忆与兴趣的检索会自动降级为关键词匹配,不阻断对话;配置后恢复向量检索。

**`JWT_SECRET` 和 `FERNET_KEY` 是干什么的?怎么生成?**

一条命令生成并写入 `.env`:

```bash
python api/gen_keys.py --write      # 也可以不带参数,先打印出来自己复制
```

| 变量 | 作用 | 更换后果 |
|---|---|---|
| `JWT_SECRET` | 登录 token 的签名密钥 | 已登录用户需要重新登录,**数据无影响** |
| `FERNET_KEY` | 加密数据库里的敏感值(模型 API Key、MCP token) | **旧密文解不开**:模型配置的 Key、MCP 里的 token 都需要在界面上重填一遍 |

两个值都写在仓库根的 `.env`(由 `.env.example` 复制而来,**不会提交到仓库**)。没配置或格式不对时,
服务启动会直接报错并提示生成命令;因为 Fernet 是对称加密,**`FERNET_KEY` 一旦用于加密就不要再换**,
换之前请先确认界面上的密钥都还能重填,并记得备份 `.env`。

**后台任务是怎么跑的?**

两种模式,由 `.env` 的 `BACKGROUND_MODE` 控制:

- `inline`(默认,本地开发):兴趣抽取 / 情绪分析 / 会话摘要 / 洞察刷新在回复结束后以进程内异步任务执行,
  不需要额外组件,但进程重启会丢任务。
- `celery`(Docker 部署默认):任务投递到 Redis 队列,由 worker 消费 —— 进程重启任务不丢、失败自动重试(指数退避),
  并由 beat 每天定时跑「社区全量重聚类」(04:00)与「洞察刷新」(04:30)。

Docker 一键启动会自动带上 `worker` / `beat` 两个容器;本机想用队列模式,另开终端跑
`celery -A app.celery_app worker --pool=solo -l info` 即可。

队列模式下,兴趣抽取会**先缓冲再合并**:攒够 `INTEREST_BATCH_SIZE`(默认 5)条或静默
`INTEREST_BATCH_WAIT_SECONDS`(默认 60)秒,把这几条消息合并成**一次**抽取(省调用,也能抽到跨消息的关系);
每条消息的时间与出处都会被保留,面板上的「出现在哪句话里」仍指向具体那条。想恢复逐条抽取,把 `INTEREST_BATCH_SIZE=1`。

**Neo4j 挂了会怎样?**

兴趣检索降级为 PostgreSQL 的向量/关键词召回,后台抽取任务只记 warning,聊天主链路不受影响。

**支持哪些模型?**

任何兼容 OpenAI 协议的 chat / embedding(可选 rerank)。在「设置 → 模型配置」里按用户添加,API Key 加密后落库。

**敏感信息怎么存?**

凭证类真实值用 Fernet 加密进 `content_encrypted`,只对脱敏描述做向量化;面板默认脱敏展示,
查看真实值需二次确认;对话历史落库前会先脱敏。

**为什么"兴趣"要放进图数据库,而不是一张表?**

因为要回答「我以前是不是关注过篮球」「跟 NBA 相关的我还关注过什么」这类问题——需要时间区间(何时开始/结束)、
实体之间的多跳关系(NBA → 勇士队 → 库里)以及社区级的主线归纳,单表做不到。

## 关键设计

几条硬约束(实现细节都在代码里):

- **幻觉治理**:实体/关系必须给出原句 evidence 并通过子串接地校验,否则直接丢弃;实体类型与关系类型都走白名单。
- **兴趣不是节点**:图里只有 `(:User)` 与 `(:Entity)`,「兴趣」是 `(User)-[:INTERESTED_IN {since,until,status}]->(Entity)` 这条边;
  实体之间用 `:RELATED {type,weight}` 表达上下位/成员/组成/共现。
- **降级优先**:Neo4j 不可用时检索降级为 PostgreSQL 向量/关键词;未配置 embedding 时降级关键词;后台任务失败不影响聊天。
- **凭证安全**:真实值 Fernet 加密、只对脱敏描述向量化、面板查看需二次确认、对话历史落库前先脱敏。
- **检索融合**:记忆召回打分 = **0.7 × 向量相似度 + 0.15 × 重要度 + 0.15 × 时间新鲜度**,命中回写访问次数,
  非向量信号只用于破平局。
- **上下文预算**:长会话保留最近 40 条原文 + 滚动摘要;抽取时带最近 4 条消息做指代解析(仅上下文,不作证据)。

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

## 开发约定

- 前端改动必须考虑移动端适配,并在提交前跑 `npm.cmd run build`。
- 后端 `app/core/agent/tools/builtin/` 内使用相对导入(到 app 层是 5 个点)。
- 控制台输出避免 emoji/中文在 GBK 下崩溃;Windows 下先设 `PYTHONIOENCODING=utf-8`。
- 改表结构后跑 `api/init_db.py`(幂等补表补列),再验证启动。

## Roadmap

- [x] 阶段一 模型配置 + 基础聊天
- [x] 阶段二 Agent 工具调用
- [x] 阶段三 记忆系统(分层 / 凭证安全 / 融合检索 / 滚动摘要 / 洞察层 / 事实时效)
- [x] 阶段四 兴趣追踪 + GraphRAG(Local/Global、社区摘要、Statement 溯源)
- [x] 阶段五 情绪助手
- [x] 阶段六 瑞幸比价 + MCP(含敏感工具审批)

## License

[MIT](LICENSE)
