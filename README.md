# Knowledge Base

一个基于 `FastAPI + Milvus Lite + MySQL + 阿里云 OSS` 的知识库服务，支持多格式文档上传、品牌资料上传、品牌附件预解析与确认入库、语义检索、分类过滤，以及按分类生成 AI 摘要与 facts。

## 文档说明

- 项目说明、部署方式、快速上手：当前文件 [README.md](./README.md)
- 接口字段、请求响应结构： [API.md](./API.md)
  当前公开接口真值优先级建议按 `Swagger /docs -> docs/rules/api-truth-matrix.md -> API.md` 理解
- 规则文档索引： [docs/rules/INDEX.md](./docs/rules/INDEX.md)
- 天眼查联通性单独测试： [TIANYANCHA_TEST.md](./TIANYANCHA_TEST.md)
- 在线调试文档：`http://127.0.0.1:9007/docs`

## 当前能力

- 本地文件上传：返回上传任务，后台异步解析和入库
- 品牌资料上传：品牌附件走后台任务导入，附件解析完成后会抽取品牌知识、回填 MySQL，并按配置回调上游
- 品牌附件两段式入库：支持先预解析生成可编辑 Markdown 初稿，再由前端确认后正式入库
- 文档解析：优先本地解析，失败时可回退到阿里云 DocMind
- 语义检索：支持按 `document_ids`、`source_types`、`category`、`subcategory` 过滤
- 分类聚合：支持获取分类文件详情、分类 facts 检索
- 删除能力：当前公开支持“品牌知识附件挂载删除”和“整品牌级联删除”；内部仍保留文档物理删除链路
- 重复文件拦截：按 `category + SHA-256` 去重
- 同名版本管理：同名不同内容文件按文件名独立递增版本，分别写入 OSS

## 关键行为

### 1. 上传是异步任务，不是立即完成

`POST /api/v1/documents/upload` 返回 `task_id`，表示后台任务已入队，不代表所有文件都已经完成解析、入 Milvus、生成摘要和 facts。

这个接口现在只支持两类文件：

- 品牌附件
- 正式品牌 AI 知识库文件

`metadata` 必须显式传这 3 个字段：

```json
{"category":"品牌名","brand_code":"品牌编码","brand_name":"品牌名"}
```

并且 `category` 必须与 `brand_name` 一致。

这个接口已经不再承载“普通文档入库”分支。

`POST /api/v1/brands/upload` 也是异步任务接口。它会更早返回 `task_id`，品牌附件的远程下载放在后台 task 中执行，不阻塞接口首响应。

如果本次请求没有可处理的附件，接口仍然会保存品牌主数据；此时任务可能以 `file_count=0` 创建。

批量上传时，如果只有部分文件重复：

- 任务仍会正常创建
- 重复项会在任务明细里标记为 `failed`
- `error_message` 会说明重复原因
- 其他非重复文件会继续上传和处理

前端应轮询：

```text
POST /api/v1/documents/upload-tasks
```

### 2. AI 摘要和 facts 也是后台生成

文档主流程成功后，摘要和 facts 会异步生成。

这意味着：

- 文档可能已经能搜到
- 但分类摘要和 facts 还没生成完成

### 2.1 品牌资料里的字段如何落库

- `brand_name` 的值会直接作为现有体系里的 `category`
- 因此现有检索、分类详情、facts 检索接口都继续按 `category` 查询，不需要切换字段名
- `brand_alias` 为可选字段；如果传入，会写入 MySQL `brands.brand_alias`
- 品牌主数据会写入 MySQL `brands` 表，当前包含 `brand_code`、`brand_name`、`brand_alias`、`brand_logo`、`website`、`intro`、`email`、`brand_enterprise_entity`、`business_license_image_path` 及品牌知识回填字段
- 产品结构化数据会写入 MySQL `brand_products` 表，当前包含 `product_name`、`product_alias`、`product_description`、`product_website` 及产品知识回填字段
- `/brands/upload` 的 `attachments` 可为空；为空时不会走 OSS / 远程附件处理链路
- 通过 `/brands/upload` 上传的品牌级 `attachments` 不为空时，会沿原 URL 附件链路继续处理：下载远程文件、上传 OSS、主文档入 Milvus、摘要入 MySQL、facts 入 Milvus
- 通过 `/brands/upload` 上传的品牌级 `attachments` 不写 `subcategory`，因此 OSS 路径直接落在 `brand_name/original/...` 和 `brand_name/converted/...`
- 通过 `/brands/upload` 上传的 `products[].attachments` 也会走同样的附件处理链路，并按对应产品名写入 `subcategory`
- 如果 `/brands/upload` 请求里的 `products` 是空数组 `[]`，附件知识抽取阶段不会生成产品内容，最终回调里的 `knowledge.products` 也会是 `[]`
- 如果 `/brands/upload` 请求里的 `products` 有内容，附件知识抽取与最终回调只会覆盖本次请求里出现的产品，不会把未在本次请求中出现的历史产品混入回调
- 如果 `/brands/upload` 请求里的 `competitors` 是空数组 `[]`，附件知识抽取阶段不会生成竞品内容，最终回调里的 `knowledge.competitors` 会是 `{ "competitors": [] }`
- 如果 `/brands/upload` 请求里的 `competitors` 有内容，附件知识抽取与最终回调只会覆盖本次请求里出现的竞品，不会把未在本次请求中出现的其他竞品混入回调
- `/brands/upload` 任务全部附件处理完成后，系统会读取 OSS 中的转换 Markdown，按文件逐个调用 LLM 抽取品牌知识，再做程序化 merge
- `/brands/upload` merge 后的结果会写入 MySQL `brand_knowledge_json`
- 如果走新的 `/brands/attachments/preview-parse + /brands/attachments/review-changes + /brands/attachments/confirm` 三步链路，则原始附件只用于“生成初稿”；前端确认后的内容才是“最终知识源”
- 新的三步链路中，前端确认后的文本会被包装成唯一命名的 confirmed Markdown 并上传 OSS；结构化变更会以 `source_type=attachment_confirm` 写入 `brand_knowledge_update_audits`
- 品牌 AI 知识库 Markdown/PDF 不再由每次 confirm 立即生成，而是通过同品牌 `brand_full_knowledge_refresh` 后台任务按配置延迟窗口统一消费 `knowledge_update` 与 `attachment_confirm` 的未生成变更
- 如果启用了天眼查补全，系统会在品牌知识抽取完成后、回调上游前，按品牌名/企业主体尝试查询企业信息，只补当前仍为空的字段；查询失败不会阻塞主流程
- 天眼查当前按官方 MCP 地址 `https://mcp.tianyancha.com/v1` 通过 HTTPS 直连；服务端会按 MCP 标准流程执行 `initialize -> tools/list -> tools/call`
- 同时会按优先级回填结构化表：
  - `basic_info` 以 `brands` 表为主
  - `products` 以 `brand_products` 表为主；产品知识字段可由附件抽取结果补充
  - `company_profile.subject_info` 对应 `brands.brand_enterprise_entity`
  - `company_profile.business_license_url` 对应 `brands.business_license_image_path`
- 若配置了 `BRAND_COMPLETION_CALLBACK_URL`，任务结束后会向上游发送品牌完成回调；回调中的 `knowledge` 使用独立的上游消费字段规范

### 2.1.1 本地 Markdown 回补脚本

- 提供独立脚本 [`scripts/backfill_brand_from_markdown.py`](./scripts/backfill_brand_from_markdown.py)
- 用途：读取每个品牌目录下的 `.md` 文件，逐个调用现有 LLM 抽取逻辑，按现有 merge / 天眼查补空 / 落库规则回补 `brands`、`brand_products`、`brand_knowledge_json`
- 特点：不走 `/api/v1/brands/upload`，不创建 upload task，不触发上游回调，不影响现有链路
- 建议先使用 `--dry-run --output-dir ...` 核对最终 JSON，再去掉 `--dry-run` 正式写库

单品牌示例：

```bash
python3 scripts/backfill_brand_from_markdown.py \
  --brand-name "demo" \
  --md-dir /path/to/brands/demo \
  --dry-run \
  --output-dir /tmp/brand_backfill_preview
```

直接从 OSS 的 `品牌名/converted/` 读取 Markdown：

```bash
python3 scripts/backfill_brand_from_markdown.py \
  --brand-name "demo" \
  --from-oss-converted \
  --dry-run \
  --output-dir /tmp/brand_backfill_preview
```

如果 OSS 实际前缀不是 `品牌名/converted/`，也可以显式指定：

```bash
python3 scripts/backfill_brand_from_markdown.py \
  --brand-name "demo" \
  --from-oss-converted \
  --oss-prefix "demo/converted/" \
  --dry-run \
  --output-dir /tmp/brand_backfill_preview
```

批量品牌目录示例：

```bash
python3 scripts/backfill_brand_from_markdown.py \
  --brands-root /path/to/brands \
  --dry-run \
  --output-dir /tmp/brand_backfill_preview
```

正式写库示例：

```bash
python3 scripts/backfill_brand_from_markdown.py \
  --brands-root /path/to/brands \
  --output-dir /tmp/brand_backfill_result
```

可选参数：

- `--skip-tianyancha`：跳过天眼查与网页补空，只做 Markdown 抽取和本地 merge
- `--md-file ...`：单品牌模式下，可重复传多个 Markdown 文件
- `--glob "*.md"`：自定义扫描模式
- `--fail-fast`：任一品牌失败时立即停止

### 2.1.2 品牌知识库 PDF 生成部署检查

完整品牌知识库现在会同时生成两份产物：

- `【品牌名】品牌AI知识库_Vx_日期.md`
- `【品牌名】品牌AI知识库_Vx_日期.pdf`

PDF 生成链路为：

```text
Markdown -> HTML -> Playwright Chromium -> PDF -> 上传 OSS -> 写库/回调
```

服务器上线前，至少确认下面 3 步：

1. 安装 Python 依赖

如果你们用项目虚拟环境：

```bash
./.venv/bin/pip install playwright
```

如果你们用统一依赖同步方式，也可以直接同步项目依赖。

2. 安装 Playwright Chromium 浏览器

```bash
./.venv/bin/python -m playwright install chromium
```

3. 跑自检脚本

```bash
./.venv/bin/python scripts/check_brand_pdf_renderer.py --output /tmp/brand_pdf_check.pdf
```

自检通过时，会输出：

- 当前环境诊断信息
- 生成出的 PDF 字节数
- PDF 头部字节
- 可选的本地 PDF 文件路径

如果这一步失败，优先看报错里有没有下面几类提示：

- `缺少 Playwright 依赖`
  说明 Python 环境里没装 `playwright`
- `Playwright 浏览器未安装`
  说明还没执行 `python -m playwright install chromium`
- `Permission denied` 或 `MachPortRendezvousServer`
  说明当前运行环境限制了 Chromium 子进程启动；这种情况常见于受限沙箱环境，必须在目标服务器环境直接自检
- `PDF 渲染超时`
  可以先调大环境变量 `KB_PDF_RENDER_TIMEOUT_SECONDS`

相关配置：

- `KB_PDF_RENDER_TIMEOUT_SECONDS`
  默认 `45` 秒，用于控制单次 PDF 渲染超时

当前代码在 PDF 渲染失败时，会把以下诊断信息打进日志：

- 操作系统平台
- Python 版本
- `playwright` 是否已安装
- Playwright 缓存目录是否存在
- 本机已下载的 Chromium / headless shell 缓存目录

这能帮助快速区分“缺依赖 / 缺浏览器 / 权限限制 / 超时”。

### 2.2 当前并发行为

- 后台 worker 当前按任务队列串行消费上传任务
- 单个上传任务内部，文件处理并发上限当前为 `3`
- 品牌附件的下载也在这个后台处理阶段执行
- `/api/v1/brands/attachments/preview-parse` 当前也按最多 `3` 个附件并发处理，并保持响应顺序与请求输入顺序一致
- 文档主流程成功后，摘要和 facts 会以额外异步任务触发，因此外部模型的真实并发可能高于“文件处理并发数”

### 3. OSS 使用“原始文件 + 转换文件”双目录

当前 OSS 路径规则：

- 有 `subcategory` 时：
  原始文件：`category/original/<subcategory>/<原始文件名>/Vn.<原始后缀>`
  转换 Markdown：`category/converted/<subcategory>/<原始文件名>/Vn.md`
- 无 `subcategory` 时：
  原始文件：`category/original/<原始文件名>/Vn.<原始后缀>`
  转换 Markdown：`category/converted/<原始文件名>/Vn.md`

例如：

```text
溪谷留香/original/品牌手册0316.pdf/V1.pdf
溪谷留香/converted/品牌手册0316.pdf/V1.md
金牌家居/original/产品图/主卧.jpg/V1.jpg
金牌家居/converted/课程资料/全国各省竞品(1)(3).xls/V1.md
```

版本规则：

- 同内容命中 `SHA-256`：该文件会在任务明细中标记为 `failed`，其他文件继续处理
- 同名不同内容：版本号递增
- 不同名不同内容：从 `V1` 开始

### 4. Milvus 与 AI 用的文本不完全一样

- OSS 保存：`markdown_text`
- AI 摘要、facts、品牌知识抽取：使用 `markdown_text`
- Milvus 向量检索：使用清洗后的 `parsed.text`

这样可以同时兼顾：

- 人可读、可回溯的 Markdown 存档
- 更稳定的向量检索文本

## 技术栈

- Web：`FastAPI`
- 向量存储：`Milvus Lite`
- 关系数据：`MySQL`
- 文档解析：本地解析 + `DocMind` 兜底
- 向量生成：`DashScope`
- 摘要与 facts：`DashScope`
- 对象存储：`阿里云 OSS`

## 支持的文件类型

文档类：

- `pdf`
- `docx`
- `xlsx`
- `xls`
- `csv`
- `txt`
- `md`
- `json`

图片类：

- `jpg`
- `jpeg`
- `png`
- `gif`
- `bmp`
- `webp`

说明：

- 图片会优先判断是否走“文档解析链路”
- DocMind 支持的图片类型会优先按文档方式解析
- 本地上传图片和 URL 下载图片，都会在进入 DocMind、图片标签识别、图片 embedding 前按各自模型限制自动压缩
- 对图片分支，系统会额外生成图片描述和标签，并写入 Milvus 文本与 metadata，用于增强图片搜索命中
- 解析失败或不适合走文档链路的图片，会走图片向量入库分支

## 项目结构

```text
.
├── knowledge_base/
│   ├── api_app/              # FastAPI 应用、依赖注入、路由拆分
│   ├── bootstrap.py          # 应用启动入口
│   ├── composition.py        # 基础设施、runtime、子域应用装配
│   ├── service.py            # 对外 facade / 运行时协调层
│   ├── infrastructure/       # 通用技术基础设施
│   │   ├── settings.py       # 配置定义
│   │   ├── logging_setup.py  # 日志初始化
│   │   ├── db_migrate.py     # 数据库 migration 入口
│   │   ├── embedding.py      # 文本/图片向量生成
│   │   ├── milvus_store.py   # Milvus Lite 封装
│   │   ├── ai_processing.py  # 摘要 / facts / 品牌知识抽取
│   │   └── oss_client.py     # OSS 封装
│   ├── brand/                # 品牌子域
│   ├── document/             # 文档子域
│   ├── ingest/               # 入库流程子域
│   │   └── infrastructure/   # 解析、DocMind、chunking、水印检测
│   ├── search/               # 检索子域
│   ├── upload_task/          # 上传任务子域
│   ├── alerts/               # 告警子域
│   ├── stores/               # MySQL / registry / relation store
│   └── shared/               # 跨子域共享工具
├── data/
│   └── upload_staging/       # 上传暂存目录
├── logs/
├── API.md
├── README.md
├── main.py
├── pyproject.toml
└── uv.lock
```

## 模块边界

- `api_app/` 负责 HTTP 层：路由、请求参数、依赖注入。
- `brand/`、`document/`、`ingest/`、`search/`、`upload_task/`、`alerts/` 按业务子域承接应用逻辑。
- `ingest/infrastructure/` 负责入库子域专属基础设施，例如文档解析、DocMind 适配、chunking、水印检测。
- `infrastructure/` 负责通用技术基础设施，例如配置、日志、迁移入口、Milvus、OSS、Embedding、AI 调用。
- `service.py` 保留为对外 facade，负责协调子域能力与运行期状态。
- `bootstrap.py` 与 `composition.py` 负责配置、store、runtime、应用服务的统一装配。
- 请求/响应模型已经分别下沉到各子域 `schemas/`，领域实体位于对应 `domain/`。

## 环境要求

- Python `>= 3.12`
- 推荐使用 `uv`
- 可访问 DashScope
- 如果启用全文和对象存储，需要可访问阿里云 OSS
- 如果启用 DocMind 兜底解析，需要可访问阿里云 DocMind
- 如果启用天眼查补空字段，需要能够访问官方 MCP 地址 `https://mcp.tianyancha.com/v1`，并提供有效 API Key
- 需要可访问 MySQL

安装依赖：

```bash
uv sync
```

初始化数据库 schema：

```bash
uv run knowledge-base-db-migrate
```

从现在开始，数据库表结构升级通过显式 migration 命令完成；服务启动时不会再自动建表或改表。

启动服务：

```bash
uv run knowledge-base-api
```

## 配置

项目启动时会自动加载根目录 `.env`。

可以从示例开始：

```bash
cp .env.example .env
```

### 必配

```bash
DASHSCOPE_API_KEY="你的 DashScope Key"
MYSQL_HOST="127.0.0.1"
MYSQL_PORT="3306"
MYSQL_USER="root"
MYSQL_PASSWORD="你的 MySQL 密码"
MYSQL_DATABASE="knowledge_base"
```

### 常用配置

```bash
KB_MILVUS_URI="/Users/yourname/knowledge_base/data/milvus.db"
KB_COLLECTION_NAME="documents"
KB_VECTOR_STORE="milvus"
KB_QDRANT_URL="http://127.0.0.1:6333"
KB_QDRANT_API_KEY=""
KB_QDRANT_COLLECTION_NAME="documents"
KB_QDRANT_FACTS_COLLECTION_NAME="documents_facts"
KB_QDRANT_ON_DISK_VECTORS="true"
KB_QDRANT_TIMEOUT_SECONDS="10"
KB_CHUNK_SIZE="1200"
KB_CHUNK_OVERLAP="150"
KB_DEFAULT_TOP_K="5"
KB_MILVUS_FILTER_BATCH_SIZE="200"
KB_MILVUS_ITERATOR_BATCH_SIZE="100"
KB_MILVUS_WRITE_BATCH_SIZE="100"
KB_VECTOR_SEARCH_MAX_CONCURRENCY="1"
KB_MILVUS_SEARCH_MAX_CONCURRENCY="1"
KB_LOG_LEVEL="INFO"
KB_LOG_DIR="./logs"
KB_UPLOAD_STAGING_DIR="./data/upload_staging"
KB_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS="300"
OSS_ENDPOINT="oss-cn-beijing.aliyuncs.com"
OSS_BUCKET_NAME="你的 bucket"
OSS_REGION="cn-beijing"
OSS_ACCESS_KEY_ID="你的 access key id"
OSS_ACCESS_KEY_SECRET="你的 access key secret"
KB_DOCMIND_ENABLED="true"
KB_DOCMIND_ENDPOINT="docmind-api.cn-hangzhou.aliyuncs.com"
DOCMIND_ACCESS_KEY_ID="你的 DocMind AK"
DOCMIND_ACCESS_KEY_SECRET="你的 DocMind SK"
KB_DOCMIND_TIMEOUT_SECONDS="300"
KB_DOCMIND_POLL_INTERVAL_SECONDS="3"
KB_DOCMIND_DOWNLOAD_TIMEOUT_SECONDS="60"
KB_DOCMIND_LLM_ENHANCEMENT="true"
KB_DOCMIND_ENHANCEMENT_MODE="VLM"
BRAND_COMPLETION_CALLBACK_URL="http://你的回调服务地址"
BRAND_COMPLETION_CALLBACK_TIMEOUT_SECONDS="5"
KB_IMAGE_TAGGING_ENABLED="true"
KB_IMAGE_TAGGING_MODEL="qwen-vl-max-latest"
KB_IMAGE_TAGGING_MAX_TAGS="8"
KB_CORS_ALLOW_ORIGINS="http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,http://192.168.1.68:3000"
KB_CORS_ALLOW_CREDENTIALS="true"
```

说明：

- 强烈建议把 `KB_MILVUS_URI` 配成绝对路径，避免相对路径导致 Milvus Lite 把数据库写到意外目录
- `KB_VECTOR_SEARCH_MAX_CONCURRENCY=1` 会限制向量检索进入 Milvus/Qdrant 的并发量，小内存机器建议先保持 `1`
- `KB_MILVUS_ITERATOR_BATCH_SIZE` 控制 Milvus 批量读取大小，品牌改名等后台任务会按这个大小流式读取，避免一次性读完整品牌向量
- `KB_MILVUS_WRITE_BATCH_SIZE` 控制 Milvus 写入/upsert 批大小，大文档和 facts 写入会分批提交，降低单次落盘峰值
- `KB_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS` 控制同品牌正式知识库合并刷新任务的 debounce 延迟，默认 `300` 秒；`/knowledge/update` 和 `/brands/attachments/confirm` 都读取这个配置
- 未配置 `OSS_*` 时，OSS 功能关闭，全文外链、图片外链等能力不可用；旧文档里提到的 `/api/v1/fulltext` 当前没有公开 HTTP 路由
- `KB_DOCMIND_ENABLED=true` 时，本地解析失败或提取不到正文的文档会自动走 DocMind 兜底
- `KB_UPLOAD_STAGING_DIR` 用于上传任务暂存文件，任务完成后会自动清理
- `KB_IMAGE_TAGGING_ENABLED=true` 时，图片会额外生成图片描述和标签，用于增强向量检索；关闭后图片仍可上传，但检索主要依赖图片向量和文件名
- `KB_CORS_ALLOW_ORIGINS` 用逗号分隔允许访问后端的前端地址；如果你的前端运行在 `http://localhost:3000` 并请求 `http://192.168.1.68:9007`，这里必须包含 `http://localhost:3000`
- 如果使用仓库内 `webapp` 的 Vite 开发服务，默认通过 `/api -> http://127.0.0.1:9007` 代理转发，前端应优先请求相对路径 `/api/...`，不需要额外设置 `VITE_API_BASE_URL`

### 使用 Qdrant 向量库

Qdrant 可作为 Milvus Lite 的轻量替代。单机 Docker 启动示例：

```bash
sudo mkdir -p /data/qdrant
sudo docker run -d \
  --name qdrant \
  --restart unless-stopped \
  -p 127.0.0.1:6333:6333 \
  -p 127.0.0.1:6334:6334 \
  -v /data/qdrant:/qdrant/storage \
  qdrant/qdrant
```

切换后端：

```bash
KB_VECTOR_STORE="qdrant"
KB_QDRANT_URL="http://127.0.0.1:6333"
KB_QDRANT_COLLECTION_NAME="documents"
KB_QDRANT_FACTS_COLLECTION_NAME="documents_facts"
KB_QDRANT_ON_DISK_VECTORS="true"
KB_VECTOR_SEARCH_MAX_CONCURRENCY="1"
```

如果 Qdrant 部署在独立机器上，只向 API 服务所在内网地址开放 `6333/6334`。Milvus Lite 的 `milvus.db` 数据不会自动进入 Qdrant；切换后需要重新导入知识库或编写一次性迁移脚本。

## 启动服务

```bash
uv run python main.py
```

或：

```bash
uv run knowledge-base-api
```

默认地址：

- 服务：`http://127.0.0.1:9007`
- Swagger：`http://127.0.0.1:9007/docs`
- ReDoc：`http://127.0.0.1:9007/redoc`

## 快速开始

### 1. 健康检查

```bash
curl http://127.0.0.1:9007/api/v1/health
```

### 2. 上传文件

```bash
curl -X POST http://127.0.0.1:9007/api/v1/documents/upload \
  -F "files=@./demo.txt" \
  -F 'metadata={"category":"demo","subcategory":"quickstart"}'
```

返回示例：

```json
{
  "task_id": "0a5df66a-861e-4627-8529-cac12e8dd2a1",
  "status": "queued",
  "file_count": 1,
  "message": "文件已上传成功，后台任务正在排队处理"
}
```

### 3. 轮询任务状态

```bash
curl -X POST http://127.0.0.1:9007/api/v1/documents/upload-tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "119c1eab-767e-45b5-84b4-d62a058143e9"
  }'
```

当文件项出现 `document_id` 且 `status=success` 时，说明该文件主入库流程已经完成。

对于品牌资料上传：

- 远程附件在尚未实际下载前，`file_size` 可能为 `null`
- 任务状态出现 `completed_with_errors` 时，表示有部分文件失败，但其他文件可能已经成功入库
- 与历史已存在内容重复的文件，不会继续走解析、Milvus、OSS、摘要或 facts 处理；会直接标记为 `failed`

### 4. 上传品牌资料

```bash
curl -X POST http://127.0.0.1:9007/api/v1/brands/upload \
  -H "Content-Type: application/json" \
  -d '{
    "brand_name": "demo",
    "industry_id": 12,
    "industry_code": "STONE",
    "industry_name": "石材",
    "enterprise_subject": "示例品牌主体名称",
    "business_license_url": "https://example.com/license.png",
    "intro": "demo 品牌介绍",
    "products": [
      {
        "name": "产品A",
        "product_description": "产品 A 主打轻烘焙咖啡豆",
        "competitors": "竞品1,竞品2",
        "attachments": [
          {
            "name": "product-a.docx",
            "url": "https://example.com/product-a.docx"
          }
        ]
      }
    ],
    "attachments": [
      {
        "name": "demo.pdf",
        "url": "https://example.com/demo.pdf"
      }
    ]
  }'
```

返回示例：

```json
{
  "task_id": "0a5df66a-861e-4627-8529-cac12e8dd2a1",
  "status": "queued",
  "file_count": 2,
  "message": "品牌资料已提交成功，后台任务正在排队处理"
}
```

补充说明：

- `/brands/upload` 请求 JSON 中，品牌主体字段使用 `enterprise_subject`，营业执照字段使用 `business_license_url`
- `/brands/upload` 也支持 `industry_id`
- `/brands/upload` 也支持 `industry_code`、`industry_name`
- `attachments` 可传空数组 `[]`
- `intro` 可选；存在时会保存到品牌主数据，但不会写入 Milvus
- `products[].product_description` 与 `products[].competitors` 都是可选；会保存到产品结构化数据，但不会生成品牌产品文本
- `products[].attachments` 可选；存在时会像品牌级附件一样走 OSS、Milvus、摘要、facts 链路
- 如果 `products=[]`，回调 `knowledge.products` 固定返回空数组
- 如果 `products` 中有产品，回调 `knowledge.products` 只返回本次请求里这些产品对应的内容
- 如果 `competitors=[]`，回调 `knowledge.competitors` 固定返回 `{ "competitors": [] }`
- 如果 `competitors` 中有竞品，回调 `knowledge.competitors` 只返回本次请求里这些竞品对应的内容
- 如果品牌附件与历史内容重复，该条目会直接标记为 `failed`，不会继续后续处理
- `file_count` 表示“本次后台任务待处理条目数”，不是单纯的附件数量
  例如：`1` 个品牌附件 + `1` 个产品附件，则 `file_count=2`

### 4.1 预解析品牌附件并生成可编辑初稿

这是一条独立于 `/api/v1/brands/upload` 的两段式链路，适合“先解析附件生成初稿，前端允许人工修改，确认后再正式入库”的场景。

第一步调用：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/brands/attachments/preview-parse \
  -H "Content-Type: application/json" \
  -d '{
    "brand_name": "demo",
    "brand_code": "BRAND-001",
    "attachments": [
      {
        "name": "demo.pdf",
        "url": "https://example.com/demo.pdf"
      }
    ]
  }'
```

当前执行流程：

- 下载附件到本地草稿目录
- 解析为 `parsed_text + markdown_text`
- 按输入顺序合并多个附件的 `markdown_text`
- 返回 `combined_markdown_text`

关键行为：

- 当前最大并发数为 `3`
- 返回顺序保持与请求 `attachments` 输入顺序一致
- 这一阶段不会上传 OSS
- 这一阶段不会写入最终知识源
- LLM prompt 明确限制只能依据当前 Markdown 原文输出，严禁调用模型内置静态知识、外部知识、杜撰或主观臆测

### 4.2 确认初稿并正式入库

第二步调用：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/brands/attachments/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "draft_id": "bad_xxx",
    "review_id": "bar_xxx",
    "brand_name": "demo",
    "knowledge_revision": "LXKG-DEMO-V1.0.0-20260630120000"
  }'
```

关键行为：

- `confirm` 只做轻量校验，必须传 `review_id`
- 它会创建 `attachment_confirm_pipeline` 后台任务，并立即返回 `background_job_id`
- 后台任务消费 `preview-parse` / `review-changes` 的草稿与审核结果，完成结构化更新、confirmed Markdown 上传 OSS、写入 `brand_knowledge_update_audits`、发送轻量完成回调，并顺延同品牌 `brand_full_knowledge_refresh`
- 正式品牌 AI 知识库 Markdown/PDF 由 `brand_full_knowledge_refresh` 在 `KB_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS` 延迟窗口后统一生成，默认 `300` 秒
- 前端轮询 `/api/v1/brands/attachments/confirm/result/{job_id}` 看单个任务结果
- 如果只想看品牌页统一展示态，可以轮询 `/api/v1/brands/knowledge-base/conflict-session/latest`

### 5. 搜索

默认只检索最新版文件内容。同一分类下如果同名文件存在多个版本，搜索默认只命中最新成功版本。

图片资产检索走 `/api/v1/images/search`，返回的是图片级结果，不是文本 chunk。

```bash
curl -X POST http://127.0.0.1:9007/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "demo 文档讲了什么",
    "top_k": 5,
    "category": "demo"
  }'
```

返回示例：

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "chunk_id": "doc-1:0",
      "content": "这里是命中的文本片段",
      "score": 0.91,
      "category": "demo",
      "metadata": {
        "brand_id": 100003,
        "brand_name": "demo",
        "kb_version": "LXKG-DEMO-V1.0.0-20260629000000",
        "section_title": "demo.pdf",
        "source_url": "https://bucket.oss-cn-beijing.aliyuncs.com/demo/converted/demo.pdf/V1.md",
        "content_hash": "sha256:..."
      }
    }
  ]
}
```

### 6. 全文读取说明

系统内部仍有全文读取能力，但当前没有公开的 `/api/v1/fulltext` HTTP 路由。

如果你在旧文档里看到这个接口：

- 不要把它当成当前公开能力
- 以 Swagger `/docs` 和 [docs/rules/api-truth-matrix.md](./docs/rules/api-truth-matrix.md) 为准
- 如果后续需要重新公开，建议先同步修正 `API.md` 与删除/全文相关规则文档

### 7. 检索分类 facts

默认直接检索 Milvus facts。品牌类请求会按 `category=品牌名` 检索，并在可解析品牌时附带 `brand_code` 过滤；不再依赖最新版知识库 `document_id`。

```bash
curl -X POST http://127.0.0.1:9007/api/v1/categories/facts \
  -H "Content-Type: application/json" \
  -d '{
    "category": "demo",
    "query": "这个分类里关于报名条件的事实",
    "top_k": 5
  }'
```

### 7.1 检索更贴合问题的 facts

这个接口不会修改原有 `/api/v1/categories/facts` 的行为。
它会在 facts 检索前做一层问题意图匹配和多路召回，更适合：

- `核心优势有哪些`
- `和竞品相比有什么差异`
- `用户常见质疑有哪些`

请求参数和返回结构与 `/api/v1/categories/facts` 保持一致：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/categories/facts/matched \
  -H "Content-Type: application/json" \
  -d '{
    "category": "demo",
    "query": "这个分类的核心优势有哪些",
    "top_k": 5
  }'
```

## 当前限制

- 品牌资料里的产品竞品文本会走内部文本入库链路，但 `/api/v1/documents/text` 仍未对外启用
- 品牌附件的远程下载、文档解析、向量化、摘要和 facts 都依赖外部服务，因此总体吞吐会受 OSS、DashScope、DocMind 和源站速度影响
- `POST /api/v1/categories/facts` 的请求模型里 `query` 是可空字段，但当前实现里应视为必传
- `upload_tasks` 成功表示上传主任务完成，不等于摘要和 facts 一定已经全部生成完毕
- `POST /api/v1/documents/upload-tasks` 是上传任务查询接口，用于查看任务整体状态和文件级处理结果
- 当前没有对外公开的 `POST /api/v1/documents/delete`；旧文档若出现它，应按“内部能力 / 历史描述”理解

## 建议阅读顺序

第一次接项目时建议这样看：

1. 先看本文件，完成环境配置和本地启动
2. 跑一遍“快速开始”
3. 再看 [API.md](./API.md) 对字段和返回结构做联调
