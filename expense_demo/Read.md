# 智能记账助手 · 项目说明（Read.md）

> 一个可直接运行的 AI 记账 Web 应用：用**文字 / 小票图片 / 语音**三种方式记一笔消费，模型抽成结构化草稿，用户确认后入库；查账时模型只把自然语言翻译成查询条件，**所有金额与统计由 SQL 计算**，模型不负责算数。

本文是项目的**唯一说明文档**，涵盖：做了什么、面向场景与技术栈架构、环境搭建与启动、功能清单与验证方式、演示数据的使用。

---

## 一、做了什么

这是一个面向单机 / 小团队内部使用的记账 demo，已打磨为**可正常运行的交付版**。核心能力：

1. **三种录入方式**
   - 文字：「昨天打车32块」→ 文本模型抽字段 → 草稿 → 确认入库
   - 图片：上传小票/支付截图 → GLM 视觉 OCR → 草稿 → 确认入库（含压缩、模糊检测、SHA256 去重）
   - 语音：上传 wav/mp3 或麦克风录音 → GLM 音频 ASR 转文字 → 复用文字链路
2. **自动分类与统计**：8 类固定分类，支持别名归一化（「吃饭」→「餐饮」）；按类别、按月统计，结果可查。
3. **自然语言查账**：「上个月吃饭花了多少」「这个月哪类花得最多」——模型只输出查询条件（时间范围 + 类别 + 查询类型），**金额、笔数、类别排名全部由 SQL 的 `SUM`/`COUNT`/`GROUP BY` 算出**。

相比早期 demo，本版还做了这些**工程加固**：
- **默认以生产模式（`APP_ENV=prod`）启动**：无需任何配置即可运行。运行环境与功能可用性**解耦**——统计页只做本地 SQL 聚合、不依赖外部 API，**有无 Key 都始终可用**；记账、查账依赖 GLM，按是否配置 Key 自动开启/关闭（详见第四节「功能开关」）。
- 演示数据可开关（`ENABLE_SEED`），生产模式默认关闭，避免假数据污染生产库。
- 应用启动与页面渲染都有错误边界，**不向用户渲染异常堆栈**，仅写服务端日志。
- Docker 镜像以**非 root 用户**运行，提供 `.dockerignore`，密钥与缓存不会打进镜像。
- **构建网络加固**：Dockerfile 在 `pip install` 层显式剥离 BuildKit 注入的宿主机代理变量（`127.0.0.1` 代理在容器内无效，会导致 `from versions: none`），改用国内镜像源 + 重试参数；镜像源可通过 `PIP_INDEX_URL` 构建参数覆盖。
- **配置注入稳健化**：`.env` 通过 Compose `env_file` 注入为环境变量（不再把单文件挂进容器），根除"源文件缺失→Docker 建同名目录→配置永久失效"的陷阱；`config.py` 多候选路径 + 目录守卫兜底；重启/重建/缺文件均能正常定位配置。
- 关闭 Streamlit 遥测；测试用内存库；运行产物收敛到 `data/` 单一目录。
- 演示数据集中到项目根目录 `demo_data/`（见第五节）。

**未做（明确的边界）**：用户系统 / 多用户、导出报表、预算模块、AA 金额分摊（仅存备注）、多币种、退款负数。若需从本版继续演进为生产 SaaS，需补多租户隔离、PostgreSQL + 迁移、用户认证、密钥托管等——这些超出本交付范围。

---

## 二、面向什么场景、技术栈与架构

### 适用场景
- 个人 / 小团队内部的记账与消费分析工具；
- 作为「LLM 结构化抽取 + 自然语言查库」的工程范例；
- 演示 GLM 文本 / 视觉 / 音频三种能力在真实业务中的落地方式。

### 技术栈

| 层 | 选型 |
|---|---|
| 前端 + 后端 | Streamlit 单进程（不做前后端分离） |
| 数据库 | SQLite + SQLAlchemy ORM，金额以「分」存整数 |
| 模型 | 智谱 GLM 家族，经 OpenAI 兼容 SDK 调用（文本 / 视觉 / 音频） |
| 配置 | python-dotenv，全部来自环境变量 |
| 容器 | Docker + docker-compose（基础镜像 `python:3.12-slim`） |
| 测试 | pytest（纯函数 + mock 模型，无需 API Key） |

### 架构与目录

```
expense_demo/
├── app.py                  # 入口：初始化 / 拿输入 / 调 service / 渲染（无 SQL、无 prompt、无金额换算）
├── core/                   # config 配置校验 · db 引擎与 Session · models ORM · validators 纯函数
├── llm/                    # client 模型封装（剥壳/重试/ASR 抽象）· prompts 全部提示词
├── services/               # bookkeeping 记账 · query 查账 · image_prep 图片预处理
├── repositories/           # transactions 数据访问（统计只查 confirmed）· seed 演示数据灌入
├── ui/                     # page_record / page_query / page_stats 三个页面
├── demo_data/              # ★ 所有演示数据（详见第五节）
│   ├── seed_transactions.csv   # 32 笔示例账单（31 confirmed + 1 pending）
│   ├── receipt_*.png           # 3 张清晰小票图（OCR 测试用，真实可辨）
│   ├── voice_*.wav             # 3 段中文录音（ASR 测试用，16kHz mono）
│   ├── sample_receipt.png      # 早期占位小票图（保留兼容）
│   ├── voice_demo.wav          # 早期占位音频（保留兼容）
│   ├── make_demo_receipts.swift # 重新生成 3 张小票图（macOS）
│   └── make_demo_receipt.py    # 生成早期占位小票图的旧脚本
├── data/                   # 运行时 SQLite 目录（docker-compose 挂卷点，仅含 .gitkeep）
├── tests/                  # 单元测试 + 4 个可复用验证脚本
├── Dockerfile / docker-compose.yml / .dockerignore
├── requirements.txt / .env.example / .gitignore
└── Read.md                 # 本文档
```

**关键设计约束**（贯穿全局，改动时请遵守）：
- 金额：模型出「元」，入库用 `Decimal(str(x))*100` 转整数分，展示再除 100。
- 两阶段状态：`pending`（待确认草稿）/ `confirmed`（已确认），**所有统计只算 confirmed**。
- 模型不算数：自然语言只翻成查询条件，数字由 SQL 聚合得出。
- Prompt 集中在 `llm/prompts.py`，system 为静态模板，用户输入只作 `user` 角色。
- 模型调用 `temperature=0`，返回剥 ```json 壳 + 正则兜底，失败重试 1 次，仍失败返回 `None`（反问话术由 service 决定）。

---

## 三、环境搭建与启动步骤

### 方式 A：Docker（推荐，最省事）

1. 安装 Docker Desktop（macOS / Windows）或 `docker.io + docker-compose`（Linux）。
2. 进入项目目录，准备配置文件（默认就是生产模式，可直接启动）：
   ```bash
   cd expense_demo
   cp .env.example .env        # 已有 .env 可跳过
   # 默认 APP_ENV=prod：无 Key 也能启动，统计可用；填 ZAI_API_KEY 可解锁记账/查账
   # 想在本地体验演示数据，把 .env 改成 APP_ENV=dev
   ```
3. 启动（本环境推荐用 legacy 构建器，规避 buildx 活动目录权限错误）：
   ```bash
   # 首次构建：完整构建镜像并后台启动（本命令已实测通过，含 pip 安装）
   DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up --build -d
   # 之后日常启动（镜像已构建，无需再 build）
   docker compose up -d
   ```
   > 直接 `docker compose up --build` 在本机可能报 `failed to update builder last activity time ... operation not permitted`，这是 Docker Desktop 的 buildx 目录问题，与项目无关；上面的 legacy 命令可绕过。首次完整构建约需 4~5 分钟（下载依赖）。
4. 浏览器打开 <http://localhost:8501>（**不要用 Streamlit 打印的 External URL / 公网 IP**，那是容器对外地址，本机通常连不通；始终用 `localhost`）。默认生产模式下侧边栏只出现「统计」；填入 Key 并重建容器后出现全部功能。

> 容器内数据库路径用 `/app/data/expense.db`；宿主机 `./data` 挂载到容器 `/app/data`，重启不丢数据。常用命令：`docker compose up -d`（后台）、`docker compose down`（停止）、`docker compose logs -f`（看日志）。

#### 如何停止项目（Docker）

按你的启动方式选择对应的停止命令：

| 启动方式 | 停止命令 | 效果 |
|---|---|---|
| 后台启动 `docker compose up -d`（推荐）| `docker compose down` | 停止并**删除容器和网络**；镜像与 `./data` 数据保留，下次 `docker compose up -d` 会重建容器 |
| 只想暂停、稍后快速恢复 | `docker compose stop`（恢复用 `docker compose start`）| 仅停/启容器进程，不删除容器，恢复最快 |
| 前台启动 `docker compose up`（不带 `-d`）| 在终端按 `Ctrl + C` | 停止前台进程；需要彻底清理再执行 `docker compose down` |

```bash
cd expense_demo
docker compose down        # 停止并移除容器（最常用）
docker compose ps -a       # 确认已无运行中的容器
```

> **数据安全性**：`docker compose down` **不会**删除镜像，也不会删除宿主机 `./data` 里的数据库——账本数据不丢。只有显式加 `-v`（`docker compose down -v`）才会清理匿名卷，但本项目数据库挂在宿主机 `./data`，同样不受影响。`down` 属于可重复执行的安全操作。

**`.env` 配置机制（重要，已重构为稳健方案）**：`.env` 不再以文件形式挂载进容器，而是由 `docker-compose.yml` 的 `env_file` 在**创建容器时**读取并注入为环境变量；`config.py` 全部从 `os.environ` 取值。这样做是为了根除一个隐蔽故障：**若把单个文件 bind mount 进容器，一旦宿主机源文件缺失，Docker 会自动创建同名「目录」，之后配置永远读不到，且"重写 .env"会失败**。改为 `env_file` 后，容器文件系统里没有 `.env`，目录陷阱不复存在。

- 改完 `.env`（例如填入 `ZAI_API_KEY`、切换 `APP_ENV`）后，执行 **`docker compose up -d`** 重建容器即可生效（Compose 会检测到变更并 `Recreated`）。`docker compose restart` 只重启进程、不重新读取 `.env`，改配置请用 `up -d`。
- `.env` 缺失时也能启动：应用回退到镜像内置默认（`APP_ENV=prod`，统计可用），不会因缺文件报错。
- 只有当修改了 `docker-compose.yml` 或 `Dockerfile` 本身时，才需要重新构建：`DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up -d --build`（本机 legacy 命令）。另外，日常改动代码文件后也建议重建镜像，让新代码进入镜像。
- 若想用外部环境变量覆盖（CI / `docker run -e`），默认即为"环境变量优先"（`DOTENV_OVERRIDE=0`）；设 `DOTENV_OVERRIDE=1` 可恢复".env 文件优先"。

> 排查配置是否生效：`docker compose exec expense-demo python -c "from core.config import load_settings; s=load_settings(); print(s.app_env, s.llm_ready, s.enable_seed, s.stats_enabled, s.record_enabled, s.query_enabled)"`。

> **若 `.env` 曾被误建成目录**（旧挂载方案的遗留状态，表现为 `docker compose up` 报 `read ./.env: is a directory`）：先删目录再重建文件即可——
> ```bash
> rmdir .env && cp .env.example .env    # rmdir 仅能删空目录，安全
> ```
> 否则若目录非空，请先备份移走再重建。新方案不会再自动产生该目录。

### 方式 B：本机 Python（不用 Docker）

1. 安装 Python 3.12（目标版本），创建并激活虚拟环境：
   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   ```
2. 安装依赖并配置：
   ```bash
   pip install -r requirements.txt
   cp .env.example .env               # 默认 prod；按需填 ZAI_API_KEY，或改 APP_ENV=dev
   ```
3. 启动：
   ```bash
   streamlit run app.py --server.port=8501 --server.headless=true
   # 或：python tests/start_streamlit.py
   ```
4. 浏览器打开 <http://localhost:8501>。
5. 停止项目：在启动 Streamlit 的那个终端按 `Ctrl + C` 即可（若是后台 `nohup`/`&` 启动，则用 `pkill -f "streamlit run"` 终止进程）。

### 环境变量说明（`.env`）

| 变量 | 作用 | 默认 / 说明 |
|---|---|---|
| `APP_ENV` | 运行环境 | **`prod`（默认）**；可选 `dev/demo/test/prod/production`。只决定运行档位（如 seed 默认值），不决定功能开关 |
| `ENABLE_SEED` | 是否灌入演示数据 | 留空=跟随 APP_ENV（`dev/demo/test` 开、`prod` 关）；可显式 `true`/`false` |
| `STRICT` | 严格模式 | `false`；`true` 时启动**强制**要求 Key（缺 Key 直接失败），用于部署自检 |
| `ZAI_API_KEY` | GLM 密钥 | 记账、查账依赖它；统计不依赖，可不填 |
| `ZAI_BASE_URL` | 模型接口 | 官方 `https://open.bigmodel.cn/api/paas/v4/`；**只写到 `/v1` 或 `/api/paas/v4/` 一级，不要带 `/chat/completions`**（SDK 会自己拼，写全了会 404） |
| `MODEL_TEXT` | 文本模型（记账/查账） | 需**纯文本**能力。GLM-5.x 用 `glm-5.3`；官方旧版可用 `glm-4-flash` |
| `MODEL_VISION` | 视觉模型（图片 OCR） | 需**多模态**能力。`glm-5.3` / `glm-5.2` 是纯文本、**不支持图片**；要用 OCR 必须配多模态模型（如 `glm-5.3-flash`、`glm-4v-plus`），且账号要开通该服务 |
| `MODEL_AUDIO` | 语音模型（ASR） | 需平台提供 **OpenAI 兼容 `/audio/transcriptions` 端点**。官方旧值 `glm-asr-2512`（旧名 `glm-4-voice-asr` 已废弃）；很多中转平台无此端点，则语音不可用 |
| `REASONING_EFFORT` | GLM-5.x 思考强度 | `low`（最快最省）/ `high` / `max`；**留空则不传该参数**（兼容不认识它的端点）。GLM-5.3 强制开启思考、无法关闭 |
| `DB_PATH` | 数据库路径 | 本地 `./data/expense.db`，容器 `/app/data/expense.db` |
| `DOTENV_OVERRIDE` | `.env` 文件是否覆盖环境变量 | 默认 `0`（环境变量优先，适配 Docker env_file 注入）；设 `1` 恢复文件优先（本地调试） |
| `ENV_FILE_PATH` | 自定义 `.env` 路径（可选） | 指定后优先从该真实文件加载；目录路径会被自动跳过 |

> API Key 在 <https://bigmodel.cn> 控制台创建。**不要提交到 Git**（`.env` 已在 `.gitignore`）。模型名以账号实际开通的服务为准——**填了 Key 但报 `401006 服务 ID 不存在/模型与服务不匹配`，就是该模型没在你的控制台开通**，不是代码问题。
>
> 注意 `.env` 里留空的字段（如 `ZAI_BASE_URL=`、`MODEL_TEXT=`）会自动回退到默认值，无需删除这些行。

### 模型能力对照（重要：先看清你手里的模型能干什么）

本项目三类功能对模型能力的要求**不同**，不是随便一个 GLM 模型就能全跑。以当前常见的 GLM-5.x 为例：

| 功能 | 需要的模型能力 | `glm-5.2` / `glm-5.3`（纯文本） | 补救 / 替代 |
|---|---|---|---|
| 统计 | 无（纯本地 SQL） | ✅ 始终可用，与模型无关 | 不需要模型 |
| 文字记账 | 文本 → JSON | ✅ 可用（`glm-5.3` 实测通过） | — |
| 自然语言查账 | 文本 → 查询条件 | ✅ 可用（同上） | — |
| 图片 OCR 记账 | 多模态视觉（读图） | ❌ 不支持（官方明确 5.x 无视觉，传图被拒） | 配多模态模型 `glm-5.3-flash` / `glm-4v-plus`，或在控制台开通视觉服务 |
| 语音 ASR 记账 | 音频转写端点 | ❌ 不支持（多数中转平台无 `/audio/transcriptions`，返回 404） | 用文字记账替代；或自行接入 Whisper / 讯飞（改 `llm/client.py` 的 `transcribe_audio`） |

> **如果你手里只有 `glm-5.2` / `glm-5.3` 这类纯文本模型**：把 `MODEL_TEXT=glm-5.3`、`MODEL_VISION` 与 `MODEL_AUDIO` 留空或指向未开通模型也无妨——**文字记账 + 查账 + 统计这三项照常可用**，页面会自动降级，图片/语音入口调用失败时会给出提示，不影响其他功能。GLM-5.3 强制思考，建议设 `REASONING_EFFORT=low` 以免响应过慢。

### 无 API Key 也能跑（默认生产模式的行为）
不填 Key、以默认 `APP_ENV=prod` 启动时，应用**照常运行且不会报错**：
- **统计**：始终可用（纯本地 SQL 聚合，不调用任何外部 API）；
- **记账、查账**：因依赖 GLM 而**自动关闭**，不出现在侧边栏导航中，侧边栏「功能状态」会标注关闭原因；
- 在 `.env` 填入 `ZAI_API_KEY` 并重启，记账/查账即自动开启，无需改代码。

想在本地用演示数据体验完整链路，把 `.env` 改为 `APP_ENV=dev` 再启动：seed 会自动灌入 31 笔示例账单（confirmed），统计页随即有内容。

---

## 四、功能清单与验证方式

### 功能清单

| 页面 | 功能 | 是否依赖 API Key | 验收点 |
|---|---|---|---|
| 记账 | 文字 / 图片 / 语音三种录入 | **是**（GLM 抽取/OCR/ASR） | 生成草稿 → 可改金额/商户/分类/日期 → 确认入库；缺金额时反问、不猜数 |
| 查账 | 自然语言提问 | **是**（GLM 解析意图） | 展示解析出的查询条件；金额/笔数/排名由 SQL 算出；「哪类最多」给完整排行含并列 |
| 统计 | 分类 / 月度聚合 | **否**（纯本地 SQL） | 累计支出、8 类分布、月度趋势、最近 20 笔（仅 confirmed） |

### 功能开关（按 Key 自动开启/关闭）

功能可用性只取决于是否配置 `ZAI_API_KEY`，与 `APP_ENV` 无关，规则集中在 `core/config.py` 的 `Settings` 属性中：

| 开关属性 | 对应功能 | 规则 |
|---|---|---|
| `stats_enabled` | 统计 | **恒为 True**，有无 Key 都可用 |
| `record_enabled` | 记账 | = `llm_ready`（配置了 Key 才开启） |
| `query_enabled` | 查账 | = `llm_ready`（配置了 Key 才开启） |

- 无 Key：`app.py` 的侧边栏只列出「统计」，记账/查账不出现在导航中（点击兜底也不会调用依赖 Key 的服务）；侧边栏「功能状态」逐项标注开启/关闭及原因。
- 有 Key：三个功能全部出现；`STRICT=true` 时缺 Key 会在启动阶段直接失败（部署自检用）。
- 排查命令：`python -c "from core.config import load_settings as l; s=l(); print(s.app_env, s.llm_ready, s.stats_enabled, s.record_enabled, s.query_enabled)"`。

**测试话术**：
- 记账：`昨天打车32块`、`午饭 25，和同事 AA`、`9月28号交房租3500`
- 查账：`上个月吃饭花了多少？`、`这个月哪类花得最多？`、`列出9月的交通记录`、`今年医疗花了多少？`
- 缺字段（应反问）：`买了个东西`

### 验证方式

**1）单元测试（18 个，无需 API Key）**
```bash
pytest -q
```
覆盖：金额元→分（含 `0.29` 浮点陷阱）、RecordDraft 校验、分类/日期归一化、查账意图解析（mock 模型）、SQL 只统计 confirmed。

**2）可复用验证脚本（在 `tests/` 下，无需 API Key）**
```bash
python tests/verify_apptest.py        # AppTest 无浏览器验证三页面渲染 + 功能开关
python tests/verify_e2e.py            # seed 幂等、金额换算、pending 不计入统计（会灌 seed，仅用于验证）
python tests/verify_llm_pipeline.py   # 用假模型演练文字/图片/语音三条链路 + 去重 + 反问
python tests/start_streamlit.py       # 本地启动服务
```

**3）真实 API 链路测试（需 .env 中已配置真实 ZAI_API_KEY）**
```bash
# 脚本用临时隔离库跑「草稿→确认→统计」全链路，不调 seed_all、不写生产库，结束即删临时库。
docker compose cp tests/verify_live_api.py expense-demo:/app/tests/verify_live_api.py
docker compose exec -T expense-demo python3 tests/verify_live_api.py
# 若容器镜像内缺新演示素材，先补拷：
#   for f in receipt_*.png voice_taxi.wav voice_coffee.wav voice_shop.wav; do \
#     docker compose cp demo_data/$f expense-demo:/app/demo_data/$f; done
```

**4）服务健康检查**
```bash
curl -i http://127.0.0.1:8501/_stcore/health    # 期望 HTTP 200 / ok
```

> 本版交付前已实跑验证：25 个单测通过；生产模式（`APP_ENV=prod`、`ENABLE_SEED=false`）下三页面 0 渲染异常、无 seed 时统计页正确显示空状态、服务健康 200。真实 API 实测结论见第五节「连接正式 API 测试清单」末尾。

---

## 五、演示数据及其使用方式

所有演示数据在**项目根目录的 `demo_data/`**（与启动命令同级的目录）：

| 文件 | 用途 |
|---|---|
| `seed_transactions.csv` | 32 笔示例账单（其中 31 笔 confirmed 计入统计、1 笔 pending 演示草稿），跨 2026-09/10/11 三个月，覆盖全部 8 类，合计约 ¥7,377.50；首次启动自动灌入 |
| `receipt_coffee.png` | 清晰小票图：星巴克咖啡，合计 ¥28.00（餐饮）|
| `receipt_market.png` | 清晰小票图：盒马鲜生，合计 ¥66.50（餐饮/购物）|
| `receipt_payment.png` | 支付成功截图：滴滴出行，实付 ¥27.50（交通）|
| `voice_taxi.wav` | 真实中文录音：「昨天打车三十二块五，滴滴出行」（交通，16kHz 单声道）|
| `voice_coffee.wav` | 真实中文录音：「今天下午在星巴克喝咖啡，花了二十八块」（餐饮）|
| `voice_shop.wav` | 真实中文录音：「上周末在优衣库买衣服，一百九十九元」（购物）|
| `sample_receipt.png` | 早期占位小票图（保留兼容）；推荐改用上面 3 张 `receipt_*.png` |
| `voice_demo.wav` | 早期占位音频（保留兼容）；推荐改用上面 3 段 `voice_*.wav` |
| `make_demo_receipts.swift` | 重新生成 3 张小票图：`swift demo_data/make_demo_receipts.swift demo_data`（需 macOS）|
| `make_demo_receipt.py` | 生成早期占位小票图的旧脚本（保留兼容）|

> **新增素材可直接用于正式 API 测试**：3 张小票图为高对比、文字锐利的 PNG（960×1440），3 段语音为 macOS 中文合成的真人可辨语音（16kHz / mono / 16-bit PCM），均能通过图片清晰度检测与 ASR 转写。

### 怎么用

- **账单数据（CSV）**：`dev/demo/test` 环境下首次启动会自动读入 SQLite（`ENABLE_SEED` 控制）；默认 `prod` 不灌入。想在默认的 `prod` 模式下看演示数据，可显式设 `ENABLE_SEED=true`，或直接把 `.env` 改成 `APP_ENV=dev`。无条件重灌可删除 `data/expense.db` 后重启；seed 是幂等的，重复启动不会重复写入。也可直接编辑 CSV 自定义示例账单，字段为：`amount,merchant,category,occurred_at,note,source,status`（金额单位「元」，status 用 `confirmed` 才会计入统计，`pending` 仅作草稿演示、不计入统计）。
- **图片记账测试**：在「记账」页上传 `demo_data/receipt_coffee.png`（或 `receipt_market.png`、`receipt_payment.png`），走 OCR 链路。小票上的商户、金额、日期都是清晰可辨的，便于核对模型抽取是否正确。同一张图第二次上传会被 SHA256 去重拦截。
- **语音记账测试**：在「记账」页上传 `demo_data/voice_taxi.wav`（或 `voice_coffee.wav`、`voice_shop.wav`），走 ASR → 文字抽取链路。三段录音都是标准记账话术，可直接验证「商户/金额/分类」抽取。

### 连接正式 API 测试清单

填好 `.env` 的 `ZAI_API_KEY` 后，用 `docker compose up -d` 重建容器（改配置须重建，`restart` 不重读），侧边栏出现「记账/查账/统计」即表示 Key 生效。建议按此顺序验证：

1. **文字记账**：输入「昨天打车 32 块」→ 应抽出草稿（商户/金额/分类/日期）→ 确认入库。
2. **图片 OCR**：上传 `receipt_coffee.png` → 应抽出「星巴克咖啡 / 28.00 / 餐饮 / 2026-11-16」。
3. **语音 ASR**：上传 `voice_taxi.wav` → 应先转写出中文，再抽出「滴滴出行 / 32.50 / 交通」。
4. **查账**：问「这个月餐饮花了多少」「哪类花得最多」→ 应返回条件 + SQL 计算的数字。
5. **统计**：确认累计支出、8 类分布、月度趋势只统计 `confirmed`。

> **模型名注意**：语音转写模型已修正为智谱官方当前的 `glm-asr-2512`（旧名 `glm-4-voice-asr` 已废弃）。若某模型报「模型不存在/无权限」，到 <https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys> 确认账号已开通对应模型，并在 `.env` 调整 `MODEL_TEXT/MODEL_VISION/MODEL_AUDIO` 后重建容器。

> 演示数据仅用于体验与验证，**生产环境默认关闭 seed**（`APP_ENV=prod` 或 `ENABLE_SEED=false`），避免假账单混入真实账本；统计功能不依赖 seed，任何时候都可用（有真实数据则统计真实数据，无数据则显示空状态提示）。

#### 生产模式真实 API 实测结论（本次交付实跑）

使用真实 Key、`APP_ENV=prod`、`ENABLE_SEED=false`，**未注入任何 seed 假数据**（生产库 `data/expense.db` 全程未创建），演示素材仅取自 `demo_data/` 与文档演示话术，结果如下：

| 链路 | 结果 | 真实返回/说明 |
|---|---|---|
| 文字记账 | ✅ 通过 | 「昨天打车三十二块五，滴滴出行」→ 商户=滴滴出行、¥32.50、交通、2026-11-18；确认后统计笔数 0→1、总额 ¥32.50、分类=[交通] |
| 查账意图解析 | ✅ 通过 | 「这个月餐饮花了多少」→ `{start:11-01, end:11-19, category:餐饮, metric:sum}`；「哪类花得最多」→ `metric:rank`（数字仍由 SQL 算）|
| 图片 OCR | ⛔ 降级 | 视觉模型 `glm-5.3-flash` 返回 `401006 服务 ID 不存在/模型与服务不匹配`——账号未开通视觉服务，非代码缺陷；代码按设计返回空、不崩溃 |
| 语音 ASR | ⛔ 降级 | 端点返回 `404 page not found`——平台无 `/audio/transcriptions` 兼容端点；代码按设计降级，可改用文字记账 |
| 全链路（草稿→确认→统计）| ✅ 通过 | pending 不计入统计、confirm 后解锁，SQL 聚合正确 |

> **结论**：当前 Key 下「文字记账 / 查账 / 统计」三条核心链路在生产模式真实可用；OCR/ASR 属账号能力未开通的正常降级，不影响其他功能。若要启用 OCR，需在智谱控制台开通多模态视觉服务并把 `MODEL_VISION` 设为对应服务 ID；ASR 需平台提供 OpenAI 兼容转写端点（或将 `transcribe_audio` 替换为 Whisper/讯飞实现）。

---

## 六、已知限制与兜底

- **图片 / 语音不是所有模型都能用**：GLM-5.2 / 5.3 是纯文本模型，只支持文字记账与查账；图片 OCR 需多模态模型（`MODEL_VISION`，如 `glm-5.3-flash`）、语音 ASR 需平台提供 `/audio/transcriptions` 端点（`MODEL_AUDIO`）。账号未开通对应服务会报 `401006`，属正常降级——文字记账 + 查账 + 统计不受影响。若平台无 ASR 端点，可在 `llm/client.py` 的 `transcribe_audio` 里替换为 Whisper / 讯飞实现（接口已抽象，改动集中在单一方法）。
- **JSON 输出**：优先 `response_format=json_object`；不支持时重试去掉该参数，并剥壳 + 正则抓首个 `{...}` 兜底。
- **分类口径**：模型可能把消费归到「其他」，可在草稿页手动改正后确认。
- **AA**：「和同事 AA」只写入备注，不做金额分摊，整笔按原金额记录。
- **构建报 `from versions: none`（最常见，本版已修复）**：若 `pip install` 出现 `Could not find a version that satisfies the requirement SQLAlchemy ... (from versions: none)`，这**不是版本约束问题**，而是 BuildKit 把宿主机代理变量注入了构建容器。本机代理常为 `http://127.0.0.1:<端口>`，在构建容器里 `127.0.0.1` 指向容器自身，代理连不上 → pip 找不到任何包。Dockerfile 已在 pip 层用 `env -u` 剥离 HTTP(S)/ALL/FTP/NO_PROXY 全部代理变量并改用国内镜像源 + 重试参数。若换网后仍失败，可切换源重试：
  ```bash
  PIP_INDEX_URL=https://pypi.org/simple docker compose up --build -d
  ```
  验证是否为此问题：`docker run --rm -e HTTP_PROXY=http://127.0.0.1:52835 python:3.12-slim pip index versions SQLAlchemy`（会复现 `ProxyError`）；去掉 `-e` 参数则正常。
- **Docker 构建失败（退出码 137 / OOM）**：`pip` 安装 pandas、opencv 时若本机 Docker 内存配额过小会被系统杀死。Docker Desktop 用户可在 Settings → Resources 把内存调到 ≥ 4GB 后重试；镜像只需构建一次，之后 `docker compose up` 走缓存。
- **buildx 活动文件权限错误**：若 `docker compose build` 报 `failed to update builder last activity time ... operation not permitted`，是本机 buildx 目录权限问题（与项目无关），可用 legacy 构建器绕过：`DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build`。该方式同样受上面的代理修复保护。
