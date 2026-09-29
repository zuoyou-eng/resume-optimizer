# 简历优化助手（Resume Optimizer）· 初始可运行版本

> 本仓库是《简历优化助手》项目的**工程骨架 + 第一条垂直链路**：
> 上传简历 → 结构化解析 → 解析结果全量可见（含解析轨迹与未识别内容提示）。
> 对应需求 FR-01 / FR-02 / FR-03，架构遵循《系统设计文档 V1.1》。

**远程仓库**：https://github.com/zuoyou-eng/resume-optimizer （Public，MIT License）
**CI 状态**：GitHub Actions 已配置并在推送时自动运行——两个 job（后端 pytest + 前端 `npm ci && build`），最近一次运行全部通过。
**测试规模**：331 项 pytest 用例（Linux 上 6 项 Windows 专属 OCR 测试按平台自动跳过，即 325 passed + 6 skipped）。

## 目录结构

```
resume-optimizer/
├── 启动项目.bat              # 双击启动：自动建环境、装依赖、选端口、开浏览器
├── docker-compose.yml        # 一键编排：PostgreSQL 14 + FastAPI + Nginx
├── scripts/
│   ├── start.ps1            # 启动逻辑（bat 只负责调用它；UTF-8 with BOM）
│   └── perf_test.py          # 性能压测（对应测试计划 PF-01~PF-11）
├── backend/
│   ├── alembic.ini           # 迁移配置（数据库连接从 app.config 读取）
│   ├── alembic/              # 数据库迁移：表结构版本化（替代 create_all）
│   │   ├── env.py            #   迁移环境（SQLite 自动启用 batch 模式）
│   │   └── versions/         #   迁移脚本（autogenerate 生成）
│   ├── app/
│   │   ├── main.py           # FastAPI 入口：统一响应、trace_id 中间件、全局异常
│   │   ├── config.py         # 环境变量配置（数据库/上传限制/规则版本）
│   │   ├── database.py       # SQLAlchemy 连接（PG 用 JSONB，SQLite 用 JSON 变体）
│   │   ├── models.py         # Resume / ParseResult / Diagnosis / Issue / Draft / Revision 实体
│   │   ├── schemas.py        # Pydantic 契约 + 统一响应 {code,message,data,trace_id}
│   │   ├── errors.py         # 错误码表（1001/1002/1003/2001/2003/6001/6002/6003...）
│   │   ├── api/
│   │   │   ├── resumes.py    # 上传 / 查询结构 / 列表 / 删除
│   │   │   ├── diagnoses.py  # 诊断 / 综合报告
│   │   │   ├── optimize.py   # 改写 / 草稿 / 版本 / 导出 / 对比
│   │   │   └── highlights.py # 亮点挖掘（FR-09：候选/追问/合成/确认）
│   │   ├── services/         # 业务编排 + 文件存储
│   │   ├── diagnosis/        # 诊断引擎（接口化，模块解耦 NFR-07）
│   │   │   ├── base.py       #   DiagnosisModule 协议 + 统一上下文
│   │   │   ├── models.py     #   DiagnosisResult / Issue / Location 数据契约
│   │   │   ├── norm.py       #   FR-04 基础规范体检
│   │   │   ├── content.py    #   FR-05 内容质量诊断
│   │   │   ├── machine.py    #   FR-06 ATS 适配体检（四类字段结论）
│   │   │   ├── match.py      #   FR-08 岗位匹配度分析
│   │   │   ├── structure.py  #   FR-07 结构与篇幅体检
│   │   │   └── runner.py     #   诊断编排 + FR-10 健康分 + FR-11 问题排序
│   │   ├── optimize/         # 优化引擎（接口化：规则引擎 + 用户自带模型 + 测试桩）
│   │   │   ├── facts.py      #   事实抽取与守恒比对（NFR-09）
│   │   │   ├── changes.py    #   difflib 改动点计算与分类
│   │   │   ├── risk.py       #   风险分级器（O-06/07）
│   │   │   ├── engine.py     #   改写引擎基类 + 规则版 + 测试桩
│   │   │   ├── ai_engine.py  #   用户自带模型（OpenAI 兼容端点，Key 不落库）
│   │   │   ├── draft_fields.py # 结构化草稿字段转换（含未识别内容 FR-03）
│   │   │   └── highlight.py  #   FR-09 引导式亮点挖掘（纯逻辑）
│   │   └── parser/           # 解析引擎（接口化，可替换）
│   │       ├── base.py       #   TextExtractor 协议
│   │       ├── pdf_parser.py #   pdfplumber
│   │       ├── docx_parser.py#   python-docx（含表格）
│   │       ├── text_parser.py#   纯文本（utf-8/gbk 探测）
│   │       ├── image_parser.py#   图片 OCR（Windows 内置引擎 + 后处理，后端可替换）
│   │       └── structurer.py #   规则版结构化 + 解析轨迹 + 未识别内容
│   └── tests/                # pytest：单元（纯逻辑）+ 接口（按错误码表），331 项
└── frontend/
    └── src/
        ├── views/UploadPage.vue      # 上传（类型/大小前端预检 + 进度）
        ├── views/ResultPage.vue      # 解析结果（结构 + 轨迹 + 未识别提示）
        ├── views/ResumeListPage.vue  # 列表 + 删除
        ├── views/DiagnosePage.vue    # 三维度诊断报告 + JD 匹配
        ├── views/DraftPage.vue       # 草稿工作台（改写/版本/导出/对比）
        └── views/HighlightPage.vue   # 亮点挖掘（候选→追问→预览→确认）
```

## 本地开发（无需 Docker）

后端：

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# 若 pip 配了不可用的代理：HTTPS_PROXY= HTTP_PROXY= .venv/Scripts/python.exe -m pip install ...
.venv/Scripts/python.exe -m pytest tests -v                   # 跑测试
.venv/Scripts/python.exe -m uvicorn app.main:app --reload      # 启动 http://127.0.0.1:8000
```

前端：

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 ，/api 已代理到 8000
```

若本机 8000 被其他进程占用，可换端口启动后端并用环境变量指过去（默认值不变）：

```bash
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --port 8010
cd frontend && API_TARGET=http://127.0.0.1:8010 npm run dev
```

本地默认使用 SQLite（`backend/data/resume.db`），零外部依赖；
模型代码通过 `with_variant` 在 PostgreSQL 上自动切换为 JSONB，无需改动。

> **不需要装 `requirements-pg.txt`**：PostgreSQL 驱动 `psycopg2-binary` 在 Python 3.14 上
> 没有预编译 wheel，安装会退化为源码编译、要求机器上有 C 编译工具。本地 SQLite 用不到它，
> 因此单独拆成一个文件，只有 docker compose / 生产部署才装（Dockerfile 已处理好）。
>
> **表结构怎么来**：启动时 `init_db()` 会 `create_all` 建表，首次运行即可用；
> 若要走 Alembic 版本化管理（推荐，便于后续升级），先执行
> `alembic upgrade head`，对早期 `create_all` 建的库用 `alembic stamp head` 纳入管理。

## 分发给他人运行

### 方式一：双击启动（推荐）

项目根目录有 **`启动项目.bat`**，双击即可。它会自动完成：

1. 检测 Python（找不到就提示去哪下载）
2. 首次运行创建虚拟环境并安装后端依赖（约 1-2 分钟）
3. 自动挑选可用端口（8000 被占就用 8001，前端同理）——不会因为端口冲突起不来
4. 启动后端并等待 `/api/v1/health` 真正就绪
5. 检测 Node.js，没有就只起后端并提示接口文档地址
6. 首次运行安装前端依赖，启动后自动打开浏览器

**装依赖失败时会自动重试一次**：先按你当前环境装，失败则清空 `HTTP_PROXY`/`HTTPS_PROXY`
再试——国内用户常配了指向本地代理（如 Clash 的 7897）但代理没开，此时 pip / npm 只会报一堆
超时，很难自己定位。这一条是实测踩出来的。

> 停止服务：直接关掉弹出的「后端」「前端」两个窗口即可，关启动窗口不停服务。
> 逻辑在 `scripts/start.ps1`（bat 只负责调它）；该脚本是 UTF-8 with BOM 编码，
> 用文本编辑器改动后请保持这个编码，否则中文会变乱码。

### 方式二：手动启动

见上方「本地开发」一节，分两步起后端与前端。

### 对方机器需要满足的条件

| 条件 | 要求 | 不满足会怎样 |
|------|------|-------------|
| Python | **3.13+**（实测 3.13.2 与 3.14.6 两个版本） | 依赖版本固定，过旧的解释器可能装不上 |
| 网络 | `pip install` 与 `npm install` 需要访问 PyPI / npm 源 | 装依赖阶段失败；可用国内镜像源 |
| 系统 | **Windows**（图片 OCR 走系统内置引擎） | PDF/Word/TXT 全部正常；**仅图片上传不可用**（返回 2001 并提示改格式） |
| Node.js | 18+（只跑后端 API 则不需要） | 前端起不来，但 `/docs` 接口文档仍可用 |

> **关于 Python 版本的一个真实教训**：项目原先只在 3.14 上验证过，README 因此写了"3.11+"。
> 实际用 3.13 一跑就崩——`def diagnose(...) -> DiagnosisResult:` 这类注解引用了未导入的名字，
> 靠 **PEP 649（3.14 默认启用的延迟注解求值）** 才没报错。已在 5 个诊断模块补齐导入，
> 并把 `build_engine()` 移到类定义之后，现在 3.13 / 3.14 均实测通过。

> **`requirements.txt` 必须保持纯 ASCII**：pip 按系统区域编码（中文 Windows 是 GBK）读取
> 依赖文件，里面任何一条 UTF-8 中文注释都会让 `pip install -r` 在解析阶段就崩
> （`UnicodeDecodeError`），一个包都装不上。因此该文件与 `requirements-pg.txt`
> 的注释全是英文，改动时请勿加中文。

### 已验证 / 未验证的路径（汇报时需如实说明）

**已验证**（排除 `.venv` / `node_modules` / `data/` 后从零实测，非推断）：

| 项 | 结果 |
|---|---|
| 干净环境 `pip install -r requirements.txt` | 纯 wheel 安装，零源码编译 |
| `pytest` 全量 | **331 项通过**，且在 **Python 3.13.2 与 3.14.6 两个版本上分别通过** |
| `uvicorn` 启动 + 上传真实简历 + 解析 + 诊断 | 全链路 200，`data/` 首次运行自动创建 |
| 一键启动脚本（含首次装依赖） | 完整跑通，退出码 0，浏览器自动打开 |

**未验证**：

| 项 | 状态 |
|---|---|
| `docker compose up --build` 一键拉起 | ⚠️ **未实跑**（本机无 Docker/PostgreSQL），编排文件仅静态校验 |
| macOS / Linux 上的图片 OCR | ⚠️ 依赖 Windows 内置 WinRT 引擎，这两个平台上图片上传不可用 |
| Python 3.11 / 3.12 | ⚠️ 未实测（3.13 已通过，更早版本大概率可行但无证据） |
| 首次 `npm install` 在无缓存的全新网络环境下 | ⚠️ 本次验证走的是已配置的 npm 源 |

### 数据库迁移（Alembic）

表结构由 Alembic 版本化管理，不再依赖启动时 `create_all`：

```bash
cd backend
.venv/Scripts/python.exe -m alembic upgrade head    # 升级到最新结构
.venv/Scripts/python.exe -m alembic downgrade base  # 回滚（迁移可逆）
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "说明"   # 模型变更后生成迁移
```

- `tests/test_migrations.py` 会比对"迁移后的 schema"与"ORM 元数据"，**差异必须为空**——
  防止"改了模型但忘了生成迁移"导致测试全绿而生产库缺列。
- SQLite 上自动启用 `render_as_batch`（SQLite 无法直接 ALTER TABLE）。
- 测试仍走 `create_all`（隔离、快速），由上面的比对测试保证两条路径不分叉。
- **存量库接入**：本项目早期用 `create_all` 建的库没有版本记录，直接 `upgrade` 会因
  "表已存在"失败。因已实测两种建表方式逐列一致，用 `stamp` 打版本标记即可安全纳入管理
  （不动表结构、不丢数据）：
  ```bash
  .venv/Scripts/python.exe -m alembic stamp head
  ```

### 性能压测

```bash
# 先启动后端，再执行（对应《测试计划》4.7 PF-01~PF-11）
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app &
python ../scripts/perf_test.py        # 结果写入 .perf/perf-result.json
```

完整数据与瓶颈分析见工作区《简历优化助手-性能测试报告.md》。
要点：NFR-01（单份 ≤15s）实测 0.052s 大幅达标；NFR-02（10 并发增幅 ≤50%）
在 SQLite 单 worker 下未达标（+491%），根因为 Python GIL + SQLite 写锁，
建议部署形态采用 PostgreSQL + uvicorn 多 worker。

## Docker 部署

```bash
cp .env.example .env
docker compose up --build
# 访问 http://localhost
```

- 后端容器启动时**先执行 `alembic upgrade head` 再起服务**；迁移失败则容器退出，不会带病启动。
- 容器内额外安装 `requirements-pg.txt`（psycopg2 驱动，编译所需系统库已在镜像里装好）；
  本地开发用 SQLite，**不需要**装这个文件——见下方「分发给他人运行」。
- 三服务按 `db → backend → frontend` 健康检查链式等待，`frontend` 只在后端真正就绪后启动。
- `backend/` 与 `frontend/` 各有 `.dockerignore`：排除 `.venv`、`node_modules`，
  以及含真实简历原文的 `data/*.db`——避免开发数据被打进镜像。
- 上传体积上限在后端（`MAX_FILE_SIZE_MB`，默认 10）与 Nginx（`client_max_body_size 10m`）
  两处保持一致；若只改一处，用户会收到与体积无关的误导性报错。
- ⚠️ 图片 OCR 依赖 Windows 内置 WinRT 引擎（PowerShell 调用），**Linux 容器内不可用**，
  上传图片会返回 2001 并提示改用 PDF/Word。需要容器内支持时在
  `app/parser/image_parser.py` 的 `_BACKENDS` 注册一个跨平台后端即可，上层代码无需改动。

## 接口速览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/resumes` | 上传简历并同步解析（multipart: file） |
| GET | `/api/v1/resumes` | 简历列表 |
| GET | `/api/v1/resumes/{id}/structure` | 结构化结果 + 解析轨迹 + 未识别内容 |
| DELETE | `/api/v1/resumes/{id}` | 删除（软删除 + 级联清除衍生数据，NFR-05） |
| POST | `/api/v1/job-descriptions` | 提交岗位描述，服务端提取关键要求（FR-08） |
| POST | `/api/v1/diagnoses` | 发起诊断，可指定维度（FR-04/05/06/07/08） |
| GET | `/api/v1/diagnoses/{id}` | 查询单维度诊断结果（含问题项与判定依据） |
| GET | `/api/v1/reports/{resume_id}` | 综合报告：健康分 + 按优先级排序的问题清单（FR-10/11） |
| GET | `/api/v1/reports/{resume_id}/export` | 导出诊断报告为自包含 HTML（FR-13，可直接打印为 PDF） |
| POST | `/api/v1/rewrites` | 基于问题项发起改写，返回改动点与事实比对（O-01/02、FR-12 只读建议同源） |
| POST | `/api/v1/rewrites/{id}/apply` | 应用单条改写到草稿（O-03） |
| GET | `/api/v1/resumes/{id}/draft` | 草稿内容（O-04） |
| PATCH | `/api/v1/drafts/{id}/fields` | 手工编辑字段，同样产生新版本（NFR-10） |
| GET | `/api/v1/drafts/{id}/revisions` | 版本历史（全量快照） |
| POST | `/api/v1/drafts/{id}/rollback` | 回滚到任意历史版本（撤销逐字一致） |
| POST | `/api/v1/drafts/{id}/batch-apply` | 批量应用（服务端仅接受 auto_safe，6003） |
| POST | `/api/v1/drafts/{id}/export` | 导出 txt/docx 并自动复检（O-05） |
| GET | `/api/v1/drafts/{id}/comparison` | 三类差异对比：分数/内容/机器读取（O-09） |
| POST | `/api/v1/tailors` | 依据岗位匹配结果生成定制草稿版本（O-08，只重排不新增事实） |
| GET | `/api/v1/resumes/{id}/highlight-candidates` | 可挖掘亮点的平淡经历清单（FR-09） |
| POST | `/api/v1/highlights/questions` | 生成分层追问序列（动作→量化→结果→佐证） |
| POST | `/api/v1/highlights/compose` | 合成候选描述预览（**不落库**） |
| POST | `/api/v1/highlights/confirm` | 用户确认后写入草稿并产生新版本 |
| POST | `/api/v1/model-settings/test` | 测试用户自带模型的连通性与鉴权（不发简历内容，不产生业务数据） |

统一响应格式：`{code, message, data, trace_id}`；`code` 见 `backend/app/errors.py`。
接口文档：启动后访问 `/docs`（FastAPI 自动生成，直接支撑接口测试）。

### 诊断维度与计分

| dimension | 模块 | 对应需求 | 计分方式 | 计入健康分 |
|-----------|------|---------|---------|-----------|
| `norm` | 基础规范体检 | FR-04 | 按严重程度扣分（critical 15 / major 8 / minor 3） | 是（权重 0.3） |
| `content` | 内容质量诊断 | FR-05 | 同上 | 是（权重 0.4） |
| `machine` | ATS 适配体检 | FR-06 | 同上 | 是（权重 0.3） |
| `match` | 岗位匹配度分析 | FR-08 | **要求覆盖率**：已覆盖 1 / 部分覆盖 0.5，按 kind 加权 | **否** |
| `structure` | 结构与篇幅体检 | FR-07 | 同上 | **否**（弹性项，单独展示） |

> **健康分 ≠ 匹配分**：健康分只衡量简历本身的质量；匹配分取决于目标岗位，
> 两者分开呈现，避免用"岗位不合适"误判"简历写得差"。

所有诊断模块输出**统一的 `DiagnosisResult`**（设计文档 4.2）：每条问题项必带
`location`（定位到字段与原文片段）、`problem`、`suggestion`、`evidence`（判定依据）、
`confidence`。模块之间互不依赖、不访问数据库，可脱离服务单独测试（NFR-07/NFR-08）。

### 诊断用法

```bash
# 1. 提交岗位描述（可选，不提交则只跑三个质量维度）
curl -X POST localhost:8000/api/v1/job-descriptions \
  -H 'Content-Type: application/json' \
  -d '{"title":"后端开发工程师","raw_text":"任职要求：本科及以上学历；熟练掌握 Python…"}'

# 2. 发起诊断（带 jd_id 才会执行岗位匹配维度）
curl -X POST localhost:8000/api/v1/diagnoses \
  -H 'Content-Type: application/json' \
  -d '{"resume_id":"<id>","jd_id":"<jd_id>"}'

# 3. 查看综合报告
curl localhost:8000/api/v1/reports/<resume_id>
```

前端入口：简历列表页操作列「诊断」，或解析结果页右上角「三维度诊断 →」。

### 优化闭环（V1.1 · O-01~O-09）

```bash
# 1. 基于某条问题项发起改写（issue_id 取自综合报告 issues[].issue_id）
curl -X POST localhost:8000/api/v1/rewrites \
  -H 'Content-Type: application/json' \
  -d '{"resume_id":"<id>","issue_id":"<issue_id>"}'

# 2. 应用该改写到草稿（首次应用时草稿自动从解析结果初始化）
curl -X POST localhost:8000/api/v1/rewrites/<rewrite_id>/apply

# 3. 手工编辑字段 / 版本历史 / 回滚 / 导出复检 / 三类差异对比
curl -X PATCH localhost:8000/api/v1/drafts/<draft_id>/fields \
  -H 'Content-Type: application/json' -d '{"field_name":"skills[0]","value":"Python、Go"}'
curl localhost:8000/api/v1/drafts/<draft_id>/revisions
curl -X POST localhost:8000/api/v1/drafts/<draft_id>/rollback \
  -H 'Content-Type: application/json' -d '{"revision_no":1}'
curl -X POST localhost:8000/api/v1/drafts/<draft_id>/export
curl localhost:8000/api/v1/drafts/<draft_id>/comparison
```

前端入口：简历列表页操作列「草稿」、解析结果页右上角「草稿工作台 →」，
或侧边栏「04 草稿工作台」。

**改写为何可信（设计文档 4.5.7 可测试性四措施）**

| 措施 | 作用 | 可断言的结论 |
|------|------|-------------|
| 事实清单结构化 | 改写前抽取学校/单位/时间/数字/技术名词，改写后重新抽取比对 | `violated` 与 `added` 必须为空，否则**拒绝输出**（6002） |
| 改动点结构化 | difflib 逐点差异 + 分类（标点/错别字/格式/措辞/结构） | 非目标语句改动率、误判为 auto_safe 的用例数必须为 0 |
| 风险等级带依据 | `auto_safe` 仅限标点/错别字/格式三类，措辞与结构一律 `needs_review` | 批量应用只接受 `auto_safe`，且**判定只在服务端做**（O-07） |
| 全量快照版本 | 每次操作存完整字段快照 + 版本指针 | 撤销后逐字一致，结构性成立（NFR-10） |

> **宁可改写失败，也不返回可能编造的内容**：事实不守恒时直接拒绝并给出依据，
> 违规内容绝不落库。只能由人补充信息的问题降级为「仅建议」（FR-12），系统不代写。

**草稿包含未识别内容**：解析时无法归类的原文会以 `unrecognized[N]` 字段进入草稿
（FR-03：严禁静默丢失），可编辑、可导出；导出时以「未归类内容（原样保留）」成块输出，
复检重新解析后仍判为未识别，ATS 对比结论不失真。

### 用户自带模型接入（O-01 的 AI 引擎）

改写引擎是接口化的（`app/optimize/engine.py` 的 `RewriteEngine`），
规则引擎与 AI 引擎实现同一个 `_generate()` 钩子，因此**前置抽事实、后置事实比对、
改动点计算、风险分级全部由基类统一执行**——换引擎不可能绕过事实守恒。

**两种用法**

| 方式 | 做法 | 产物特征 |
|------|------|---------|
| 规则引擎（默认） | 不传 `model_settings` | 只做标点/错别字/日期/装饰字符等确定性修正，恒为 `auto_safe`，可批量应用 |
| 用户自带模型 | 前端「草稿工作台 → [ AI ] 模型接入」填 base_url / API Key / model | 做措辞与结构优化，通常为 `needs_review`，**必须逐条人工确认** |

```bash
# 用用户模型改写某条问题项
curl -X POST localhost:8000/api/v1/rewrites \
  -H 'Content-Type: application/json' \
  -d '{
    "resume_id":"<id>","issue_id":"<issue_id>",
    "model_settings":{"base_url":"https://api.deepseek.com","api_key":"sk-...","model":"deepseek-chat"}
  }'
```

任何 OpenAI 兼容端点都可接入（DeepSeek / 通义 / 本地 Ollama 等）；
`base_url` 填到根地址或 `/v1` 均可，服务端会自动归一到 `/chat/completions`。

**安全与降级契约**（`app/optimize/ai_engine.py`）

1. **API Key 不落库、不记日志**：配置随请求一次性传入，仅用于构建本次请求的引擎实例，
   用完即弃；Key 只走 `Authorization` 头，不进请求体、不进 `reason`、不进 `model_version`。
2. **调用失败一律降级为「仅建议」**：超时 / 网络错误 / 401 / 404 / 429 / 5xx /
   返回不可解析 / 空内容，全部走既有 FR-12 路径（`suggestion_only`），
   **不新增错误码**，也不把半成品当成功透出。
3. **编造内容一律拒绝**：模型若改变或新增原文没有的事实（含数字、时间、学校、
   单位、技术名词，以及"获得一致好评"这类评价性主张），基类判 `rejected` → 6002，
   违规文本绝不透出、绝不落库。
4. **如实标注可复现性**：AI 引擎的 `reproducible` 为 `false`
   （NFR-08 约束的是确定性引擎），不会假装"相同输入相同结论"。
5. **前端知情同意**：面板明确告知"该字段的简历原文会发送到所填接口地址"，
   Key 只存用户自己的浏览器（可选记住，localStorage）。

> 由于事实守恒会拦下一切新增内容，AI 的真实增益集中在**措辞与结构**；
> 「补充量化结果」这类需要真实信息的问题仍然只能由用户自己填，系统不代写。

## 已实现 / 未实现

**已实现**：文件上传（扩展名 + 魔术字节双重校验、大小限制、空内容拦截）；
PDF/DOCX/TXT 文本提取；**图片 OCR**（FR-01 图片格式：PNG/JPG/BMP/WebP，
走 Windows 内置 WinRT OCR 引擎，零第三方依赖；后端按 `OcrBackend` 协议可替换）；
规则版结构化（基本信息/教育/经历/项目/技能/荣誉）；
解析轨迹；未识别内容显式提示（FR-03）；**三维度诊断 + 岗位匹配**
（FR-04/05/06/08，含统一诊断结果模型、ATS 四类字段结论、缺口清单）；
**结构与篇幅体检**（FR-07：模块完整性/页数身份匹配/篇幅占比/关键信息位置，
身份推断不使用当前日期，NFR-08 可复现）；**综合健康分与按优先级排序的问题清单**
（FR-10/11）；**优化闭环**（改写引擎 + 事实守恒校验 + 风险分级 + 草稿与全量快照版本
+ 回滚 + 导出复检 + 三类差异对比，O-01~O-09）；**引导式亮点挖掘**（FR-09：
候选清单→分层追问→合成预览→确认写入，只用原文+用户答案中的事实，未经确认不写入）；
**报告层修改建议**（FR-12：每条问题可看 before/after 对照、改动点与理由，
降级时明确提示缺什么信息，不替用户编造内容）；**报告导出**（FR-13：自包含 HTML，
含健康分/维度分/问题清单/ATS 结论/匹配明细/免责声明，可离线打开或打印为 PDF）；
**定制版本生成**（O-08：按岗位匹配结果重排经历与技能，只调顺序不新增事实，
可回滚，无移动不产生空版本）；**用户自带模型接入**（`AIRewriteEngine`：
OpenAI 兼容端点，Key 不落库不记日志，调用失败一律降级为「仅建议」，
编造内容一律 6002 拒绝，`reproducible` 如实标为 false）；
软删除 + 衍生数据级联清除（NFR-05）；
统一响应与 trace_id；确定性输出（NFR-08，同输入同结论）；
**数据库迁移版本化**（Alembic：`upgrade`/`downgrade`/`autogenerate` 全链路可用，
SQLite 自动 batch 模式，`test_migrations.py` 保证迁移与 ORM 元数据不分叉）；
**性能压测**（`scripts/perf_test.py`，覆盖测试计划 PF-01~PF-11，报告见工作区
《简历优化助手-性能测试报告.md》）；
pytest 单元 + 接口测试 **331 项**；Docker Compose 部署编排。

> **图片 OCR 的两个后处理**（`app/parser/image_parser.py`，只作用于 OCR 路径，
> 不影响 PDF/Word 的精确文本）：① **字间空白规整**——OCR 常把「姓 名 ： 张 三」
> 按字切开，不处理则章节关键词永远匹配不上；② **阅读顺序还原**——按坐标重排，
> 两栏简历必须「左栏读完再读右栏」，否则会读成左右交错的乱序文本。
> 已知限制：字母形近误识（如 `FastAPI` → `FastAPl`）无法通用修复，
> 会被「中英文标点混用」等规范检查如实报出。

**未实现（按设计文档的路线图排期）**：
登录与权限体系（当前任何能访问服务的人都能读全部简历，多用户部署前必须补，
NFR-05 的"未授权访问"这半句因此尚未达标）；
异步任务队列、MinIO 对象存储为后续工程化项。

**已验证 / 未验证的边界**（汇报时需如实说明）：

| 项 | 状态 |
|---|---|
| pytest 全量 | ✅ 331 项通过（Python **3.13.2 与 3.14.6** 双版本实测，SQLite） |
| 用户自带模型接入 | ✅ 21 项端到端断言全部通过（本机假 OpenAI 兼容服务，含降级/拒绝/保密性路径） |
| 全链路端到端 | ✅ 上传 → 解析 → 诊断 → 改写 → 草稿 → 导出，四种格式均实测通过 |
| Alembic 迁移 | ✅ `upgrade`/`downgrade`/重复执行均验证；并在"仅 app + alembic、无 data/"的等效容器结构下验证通过 |
| NFR-01（≤15s） | ✅ 实测 0.052s，余量约 259 倍 |
| NFR-02（并发增幅 ≤50%） | ❌ SQLite 单 worker 下 +491%，根因 GIL + 写锁；建议 PostgreSQL + 多 worker |
| Docker Compose 一键拉起 | ⚠️ **未实跑**（本机无 Docker/PostgreSQL）；编排文件、Dockerfile、.dockerignore、健康检查链已做静态校验 |
| NFR-03（3 分钟首次使用） | ⚠️ 需真实用户验收，未测 |
