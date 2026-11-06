# API 文档

本文档聚焦当前常用且已启用的 HTTP 接口、主要字段和返回结构。所有接口均以 `/api/v1` 为前缀。

接口真值优先级建议按下面顺序理解：

1. 代码路由与 Swagger `/docs`
2. [docs/rules/api-truth-matrix.md](./docs/rules/api-truth-matrix.md)
3. [docs/rules/delete-semantics.md](./docs/rules/delete-semantics.md)
4. 本文档

如果本文与代码行为不一致，应以代码与 `docs/rules/` 中的规则文档为准。

当前接口实现对应的新结构如下：

- HTTP 入口位于 `knowledge_base/api_app/`
- 应用装配位于 `knowledge_base/bootstrap.py` 与 `knowledge_base/composition.py`
- 通用技术基础设施位于 `knowledge_base/infrastructure/`
- 文档解析等入库专属基础设施位于 `knowledge_base/ingest/infrastructure/`
- 领域逻辑按 `brand/`、`document/`、`ingest/`、`search/`、`upload_task/` 子域拆分
- `knowledge_base/service.py` 仍作为对外 facade 存在，用于协调子域与运行时能力
- 请求/响应模型位于各子域 `schemas/`，不再通过集中式 `models.py` 出口组织

基础信息：

- Base URL：`http://127.0.0.1:9007`
- Swagger：`/docs`
- ReDoc：`/redoc`
- 默认返回类型：`application/json`

## 接口总览

本表只列本文后续会展开说明的常用公开接口。完整启用列表请看 [docs/rules/api-truth-matrix.md](./docs/rules/api-truth-matrix.md)。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 健康检查 |
| `POST` | `/api/v1/documents/upload` | 上传本地文件，创建后台任务 |
| `POST` | `/api/v1/brands/facts/upload` | 同步上传品牌 Markdown，仅重建 facts |
| `POST` | `/api/v1/documents/upload-tasks` | 查询上传任务状态 |
| `POST` | `/api/v1/brands/upload` | 上传品牌资料，创建后台任务 |
| `POST` | `/api/v1/brands/attachments/preview-parse` | 解析品牌附件生成可编辑初稿 |
| `POST` | `/api/v1/brands/attachments/review-changes` | 结构化附件编辑稿并返回新增/修改字段 |
| `POST` | `/api/v1/brands/attachments/confirm` | 确认品牌附件解析结果并正式入库 |
| `POST` | `/api/v1/brands/delete` | 删除品牌及其关联数据 |
| `POST` | `/api/v1/knowledge/update` | 更新品牌知识与结构化品牌数据 |
| `POST` | `/api/v1/search` | 语义检索 |
| `POST` | `/api/v1/images/search` | 图片资产检索 |
| `POST` | `/api/v1/brands/attachments/delete` | 删除品牌知识里的附件挂载关系 |
| `POST` | `/api/v1/brands/facts` | 按品牌名检索 facts |
| `POST` | `/api/v1/categories/facts` | 分类 facts 语义检索 |

当前未对外启用、但旧文档里可能仍会出现的接口：

- `/api/v1/documents/delete`
- `/api/v1/fulltext`
- `/api/v1/documents/text`

## 通用约定

### Content-Type

- JSON 接口：`application/json`
- 文件上传接口：`multipart/form-data`

### 上传限制

- `/documents/upload` 单文件大小限制为 `50 MB`
- `metadata` 必须是 JSON 对象字符串
- 图片若走 DocMind 文档解析链路，解析前会校验 `20 MB`；超过时会先压缩到可接受范围
- `/brands/upload` 中 `attachments` 的远程文件大小没有单独的前置限制，但会受远程源站、下载超时、解析能力和 OSS / DashScope / DocMind 配额影响

### 重复文件与版本规则

- 系统按 `category + SHA-256` 检查重复文件
- 同内容文件：该文件会在上传任务明细中标记为 `failed`，其他文件继续处理
- 同名不同内容：允许上传，并按该文件名单独递增版本号
- 不同名不同内容：从 `V1` 开始

### OSS 路径规则

- 原始文件：`category/original/<原始文件名>/Vn.<原始后缀>`
- 转换 Markdown：`category/converted/<原始文件名>/Vn.md`

### 摘要与 facts

- 文档主入库完成后，摘要和 facts 会异步后台生成
- 因此上传任务成功，不代表摘要和 facts 一定已经完成

### 并发行为

- 后台 worker 当前按任务队列串行消费上传任务
- 单个上传任务内部，文件处理并发上限当前为 `3`
- `/brands/upload` 返回 `task_id` 后，`attachments` 的远程下载会在后台任务中执行，不阻塞接口首响应
- 文档主流程成功后，摘要和 facts 会再异步触发，因此外部模型实际并发可能高于“文件处理并发数”

## 数据模型

### UploadTaskCreateResponse

```json
{
  "task_id": "0a5df66a-861e-4627-8529-cac12e8dd2a1",
  "status": "queued",
  "file_count": 2,
  "message": "文件已上传成功，后台任务正在排队处理"
}
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | `string` | 上传任务 ID |
| `status` | `string` | 初始通常为 `queued` |
| `file_count` | `integer` | 本次上传的文件数 |
| `message` | `string` | 提示信息 |

### UploadTaskStatusResponse

```json
{
  "task_id": "0a5df66a-861e-4627-8529-cac12e8dd2a1",
  "status": "processing",
  "file_count": 2,
  "success_count": 1,
  "failed_count": 0,
  "pending_count": 0,
  "processing_count": 1,
  "error_message": null,
  "created_at": "2026-04-28 10:00:00",
  "updated_at": "2026-04-28 10:00:10",
  "files": [
    {
      "file_id": 12,
      "file_index": 0,
      "file_name": "demo.pdf",
      "status": "success",
      "file_size": 12345,
      "document_id": "6cbd4ed2-3438-4d9f-9f24-44e7c2e65c21",
      "source_type": "pdf",
      "chunk_count": 8,
      "error_message": null,
      "created_at": "2026-04-28 10:00:00",
      "updated_at": "2026-04-28 10:00:09"
    }
  ]
}
```

任务状态常见取值：

- `queued`
- `processing`
- `completed`
- `completed_with_errors`
- `failed`

文件状态常见取值：

- `pending`
- `processing`
- `success`
- `failed`

说明：

- 对 `/brands/upload` 的远程附件，在尚未实际下载前，`file_size` 可能为 `null`
- `document_id` 只有在该文件主入库成功后才会出现
- 命中重复的文件会直接标记为 `failed`，`error_message` 会说明原因，不再继续后续处理

### IngestedDocument

```json
{
  "document_id": "6cbd4ed2-3438-4d9f-9f24-44e7c2e65c21",
  "source_name": "demo.pdf",
  "source_type": "pdf",
  "chunk_count": 8,
  "metadata": {
    "category": "demo",
    "subcategory": "quickstart",
    "original_file_key": "demo/original/demo.pdf/V1.pdf",
    "fulltext_key": "demo/converted/demo.pdf/V1.md",
    "converted_version": 1
  }
}
```

### SearchRequest

```json
{
  "query": "品牌手册讲了什么",
  "top_k": 5,
  "document_ids": ["doc-1"],
  "source_types": ["pdf", "docx"],
  "category": "溪谷留香",
  "subcategory": "品牌资料"
}
```

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `query` | `string` | 是 | 最少 1 个字符 | 查询文本 |
| `top_k` | `integer` | 否 | `1-50` | 返回文档数，默认 `5` |
| `document_ids` | `string[] \| null` | 否 | 无 | 限制文档范围 |
| `source_types` | `string[] \| null` | 否 | 无 | 限制文档类型 |
| `category` | `string \| null` | 否 | 无 | 一级分类过滤 |
| `subcategory` | `string \| null` | 否 | 无 | 二级分类过滤 |

### SearchResponse

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "chunk_id": "6cbd4ed2-3438-4d9f-9f24-44e7c2e65c21:0",
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

说明：

- `data[].content` 为命中的原文 chunk 文本
- `data[].metadata.source_url` 对文本类优先返回 OSS 中的 Markdown 全文地址
- 如果 OSS 未配置，`data[].metadata.source_url` 会回退为原始 `source_url` 或为空

### BrandUploadRequest

```json
{
  "brand_code": "BRAND-001",
  "brand_name": "品牌名称",
  "brand_alias": "品牌别名",
  "industry_id": 12,
  "industry_code": "STONE",
  "industry_name": "石材",
  "brand_logo": "https://example.com/logo.png",
  "website": "https://example.com",
  "intro": "品牌介绍",
  "email": "brand@example.com",
  "products": [
    {
      "name": "产品A",
      "product_alias": "别名1,别名2",
      "product_images": ["https://example.com/a.png"],
      "product_description": "产品介绍",
      "product_link": "https://example.com/product-a",
      "attachments": [
        {
          "name": "产品资料.docx",
          "url": "https://example.com/product-a.docx"
        }
      ],
      "competitors": "竞品1,竞品2"
    }
  ],
  "competitors": [
    {
      "name": "竞品1",
      "website": "https://example.com/competitor-1"
    }
  ],
  "attachments": [
    {
      "name": "品牌手册.pdf",
      "url": "https://example.com/brand-book.pdf"
    }
  ]
}
```

说明：

- `brand_name` 必填
- `brand_alias` 可选
- `industry_id` 可选；存在时会写入 `brands.industry_id`
- `industry_code`、`industry_name` 可选；当与 `industry_id` 一起提供时，会同步更新 MySQL `industries` 表
- `attachments` 可为空数组
- `brand_name` 的值会直接作为历史 `category`
- 品牌主数据会写入 MySQL `brands` 表，包含 `brand_code`、`brand_name`、`brand_alias`、`brand_logo`、`website`、`intro`、`email`、`brand_enterprise_entity`、`business_license_image_path`、`industry_id` 及品牌知识回填字段
- 行业字典会写入 MySQL `industries` 表，更新字段包括 `id`、`code`、`name`
- 产品结构化数据会写入 MySQL `brand_products` 表，包含 `product_name`、`product_alias`、`product_description`、`product_website` 及产品知识回填字段
- 品牌级 `attachments` 不为空时，会作为远程附件进入后台任务：下载远程文件、上传原文件和 Markdown 到 OSS、主文档入 Milvus、生成摘要、提取 facts
- `products[].attachments` 也会走同样的处理链路，并按对应产品名写入 `subcategory`
- `intro` 与 `products[].product_description` 会保留在结构化数据中，但不会单独生成“品牌介绍文本”或“产品介绍文本”写入 Milvus
- 附件主流程全部完成后，系统会读取 OSS 中的转换 Markdown，按文件调用 LLM 抽取品牌知识，并进行程序化 merge
- merge 结果会写入 MySQL `brand_knowledge_json`
- merge 结果还会按优先级回填结构化表：
  - `basic_info` 以 `brands` 表为主
  - `products` 以 `brand_products` 表为主；产品知识字段可由附件抽取结果补充
  - `basic_info.industry_id` 对应 `brands.industry_id`
  - `company_profile.subject_info` 对应 `brands.brand_enterprise_entity`
  - `company_profile.business_license_url` 对应 `brands.business_license_image_path`
- 若配置了 `BRAND_COMPLETION_CALLBACK_URL`，任务完成后会向上游发送回调；回调中 `knowledge` 使用上游约定字段名和层级

### DocumentIdRequest

```json
{
  "document_id": "6cbd4ed2-3438-4d9f-9f24-44e7c2e65c21"
}
```

### CategorySearchRequest

```json
{
  "category": "demo",
  "query": "报名条件",
  "top_k": 5
}
```

说明：

- 模型里 `query` 允许为 `null`
- 但当前实现会实际调用向量检索，因此请始终传入非空 `query`

## 详细接口

### 1. 健康检查

- Method：`GET`
- Path：`/api/v1/health`

请求：

```bash
curl http://127.0.0.1:9007/api/v1/health
```

响应：

```json
{
  "status": "ok",
  "collection_name": "documents"
}
```

### 2. 上传本地文件

- Method：`POST`
- Path：`/api/v1/documents/upload`
- Content-Type：`multipart/form-data`
- Status Code：`202 Accepted`

表单字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `files` | `file[]` | 是 | 可一次上传多个文件 |
| `metadata` | `string` | 是 | JSON 对象字符串，且必须包含 `category`、`brand_code`、`brand_name`，其中 `category` 必须与 `brand_name` 一致 |
| `chunk_size` | `integer` | 否 | 保留字段，品牌附件 / 正式品牌 AI 知识库文件分支当前不会使用 |
| `chunk_overlap` | `integer` | 否 | 保留字段，品牌附件 / 正式品牌 AI 知识库文件分支当前不会使用 |

请求示例：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/documents/upload \
  -F "files=@./品牌手册.pdf" \
  -F 'metadata={"category":"燕子屋","brand_code":"100064","brand_name":"燕子屋"}'
```

成功响应：

```json
{
  "task_id": "0a5df66a-861e-4627-8529-cac12e8dd2a1",
  "status": "queued",
  "file_count": 1,
  "message": "文件已上传成功，后台任务正在排队处理"
}
```

常见错误：

- `400`：`metadata` 不是合法 JSON 对象
- `400`：缺少 `category` / `brand_code` / `brand_name`
- `400`：`metadata.category` 与 `metadata.brand_name` 不一致
- `400`：`/api/v1/documents/upload` 已不再支持普通文档入库；当前仅支持品牌附件和正式品牌 AI 知识库文件
- 重复文件不会再让整个请求直接返回 `400`；它们会在任务文件明细里以 `failed` 呈现

### 3. 查询上传任务状态

- Method：`POST`
- Path：`/api/v1/documents/upload-tasks`
- Content-Type：`application/json`

请求：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/documents/upload-tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "119c1eab-767e-45b5-84b4-d62a058143e9"
  }'
```

成功响应：见 `UploadTaskStatusResponse`

说明：

- 请求中的 `task_id` 直接指定要查询的上传任务
- `task.status=completed` 表示本批文件主流程已处理完成
- `task.status=completed_with_errors` 表示有部分文件失败，但其他文件已经正常处理完成
- 这不等于摘要和 facts 一定全部完成

### 3.1 同步重建品牌 Facts

- Method：`POST`
- Path：`/api/v1/brands/facts/upload`
- Content-Type：`multipart/form-data`
- Status Code：`200 OK`

这是一条轻量同步接口，只处理“现成 Markdown -> 抽 facts -> 写入 `brand_knowledge_facts` / Milvus -> 删除该品牌旧 facts`”。

它和 `/api/v1/documents/upload` 的区别是：

- 不创建 upload task
- 不走后台异步任务
- 不解析 PDF / Office 文件
- 不生成正式品牌 AI 知识库文件
- 不回写 `brand_knowledge_json`
- 不发送品牌完成回调

表单字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `files` | `file[]` | 是 | 当前仅支持 1 个 Markdown 文件 |
| `metadata` | `string` | 是 | JSON 对象字符串，且必须包含 `category`、`brand_code`、`brand_name`，其中 `category` 必须与 `brand_name` 一致 |

请求示例：

```bash
curl -X POST 'http://127.0.0.1:9007/api/v1/brands/facts/upload' \
  -F 'files=@/absolute/path/to/【燕子屋】品牌AI知识库_V1_20260805.md;type=text/markdown' \
  --form-string 'metadata={"category":"燕子屋","brand_code":"100064","brand_name":"燕子屋"}'
```

成功响应示例：

```json
{
  "status": "success",
  "brand_code": "100064",
  "brand_name": "燕子屋",
  "document_id": "brandfacts:100064:2d8d9f7f1f5fd7b11cb6e3b87e5a0c91",
  "fact_count": 265,
  "deleted_fact_count": 508,
  "content_hash": "2d8d9f7f1f5fd7b11cb6e3b87e5a0c91f96c0f1d65f09cc1e6dcb6ad4b6fa2f1",
  "content_type": "text/markdown",
  "file_hash": "835d109390520dd2097fd393517ba421a8ccfddaaf1ac27bb86c1f46d60af3ce",
  "file_size": 97095,
  "file_name": "【燕子屋】品牌AI知识库_V1_20260805.md"
}
```

响应字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `status` | `string` | 当前成功时返回 `success` |
| `brand_code` | `string` | 品牌编码 |
| `brand_name` | `string` | 品牌名 |
| `document_id` | `string` | 本次 facts 版本对应的 source document id |
| `fact_count` | `integer` | 本次写入的 facts 数量 |
| `deleted_fact_count` | `integer` | 本次清理掉的旧 facts 数量 |
| `content_hash` | `string` | Markdown 规范化正文哈希 |
| `content_type` | `string \| null` | 上传内容类型 |
| `file_hash` | `string \| null` | 原始文件 SHA-256 |
| `file_size` | `integer \| null` | 原始文件大小 |
| `file_name` | `string \| null` | 原始文件名 |

常见错误：

- `400`：`metadata` 不是合法 JSON 对象
- `400`：缺少 `category` / `brand_code` / `brand_name`
- `400`：`metadata.category` 与 `metadata.brand_name` 不一致
- `400`：当前上传了 0 个或多个文件；这条接口只支持单文件
- `400`：上传文件不是 `.md`
- `400`：`brand_code` / `brand_name` 与品牌主数据不匹配
- `400`：LLM 返回内容无法修复成合法 facts JSON

### 4. 上传品牌资料

- Method：`POST`
- Path：`/api/v1/brands/upload`
- Content-Type：`application/json`
- Status Code：`202 Accepted`

请求：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/brands/upload \
  -H "Content-Type: application/json" \
  -d '{
    "brand_name": "demo",
    "brand_alias": "demo,示例品牌",
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

响应：

```json
{
  "task_id": "0a5df66a-861e-4627-8529-cac12e8dd2a1",
  "status": "queued",
  "file_count": 2,
  "message": "品牌资料已提交成功，后台任务正在排队处理"
}
```

说明：

- 这是异步任务接口，返回 `task_id`
- `/brands/upload` 请求 JSON 中，品牌主体字段使用 `enterprise_subject`，营业执照字段使用 `business_license_url`
- `/brands/upload` 也支持 `industry_id`
- `/brands/upload` 也支持 `industry_code`、`industry_name`
- `attachments` 可为空；为空时不会走附件下载 / OSS 处理链路
- 品牌级 `attachments` 不为空时，会在后台任务中下载，然后按原 URL 附件链路继续处理：
  上传原文件和转换 Markdown 到 OSS、主文档入 Milvus、生成摘要写 MySQL、提取 facts 写 Milvus
- `products[].attachments` 也会进入同一个后台任务，并走同样的处理链路
- 如果请求里的 `products` 是空数组 `[]`，附件知识抽取阶段不会生成产品内容，回调里的 `knowledge.products` 也会返回空数组
- 如果请求里的 `products` 有内容，附件知识抽取与回调返回都会只针对本次请求中出现的产品；请求里未出现的历史产品不会混入本次回调
- 请求里的 `competitors` 会作为竞品种子；附件内容中明确抽取出的新竞品也允许进入品牌知识与回调
- 天眼查 / LLM 联网检索只对当前竞品列表补字段，不会额外凭空新增竞品
- 远程附件下载本身不阻塞这个接口返回
- 任务 `file_count` 只统计实际进入后台处理链路的附件条目，不再额外生成品牌介绍文本或产品文本条目
- 若本次请求只有品牌主数据、没有任何可处理附件，仍会创建任务，此时 `file_count` 可能为 `0`
- 当前单个品牌任务内部的文件处理并发上限为 `3`
- 现有查询接口仍然按 `category` 查询；品牌上传场景中请把品牌名作为 `category` 使用

品牌完成回调示例：

```json
{
  "brand_code": "BRAND-001",
  "overall_status": "completed",
  "completed_at": "2026-06-16 10:00:00",
  "knowledge_extraction_status": "success",
  "knowledge": {
    "basic_info": {
      "industry_id": "12",
      "brand_name": "示例品牌",
      "brand_alias": "示例别名",
      "brand_logo": "https://example.com/logo.png",
      "website": ["https://example.com"],
      "intro": "品牌介绍",
      "extra_info": {
        "brand_english_name": "Example Brand",
        "official_wechat": "example_wechat",
        "brand_positioning": "高端智能服务品牌",
        "brand_advantage": "渠道广、交付快、服务稳定",
        "brand_mission": "让企业服务更高效",
        "brand_vision": "成为行业领先品牌",
        "target_region": ["中国", "新加坡"],
        "other_info": ""
      }
    },
    "company_profile": {
      "subject_info": "示例品牌主体名称",
      "business_license_url": "https://example.com/license.png",
      "stock_info": "",
      "company_addresses": ["上海市徐汇区示例路 1 号"],
      "company_intro": "公司简介",
      "founded_at": "2020-01-01",
      "store_distribution": [],
      "recent_news": [],
      "development_philosophy": [],
      "company_values": [],
      "company_mission": [],
      "development_history": [],
      "other_info": []
    },
    "management_team": {
      "members": []
    },
    "competitors": {
      "competitors": []
    },
    "authority_honors": {
      "honors": []
    },
    "customers_cases": {
      "cases": []
    },
    "products": [],
    "sensitive_topics": {
      "sensitive_contents": [],
      "controversial_events": [],
      "forbidden_words": [],
      "negative_clarifications": [],
      "other_info": []
    },
    "attachments": {
      "files": [
        {
          "name": "品牌手册.pdf",
          "url": "https://example.com/brand-book.pdf",
          "type": "pdf",
          "description": ""
        }
      ]
    },
    "official_malls": [],
    "official_media_matrix": [],
    "other_info": [
      {
        "title": "补充说明",
        "content": "品牌知识库其他信息"
      }
    ]
  }
}
```

说明：

- 仅在配置了 `BRAND_COMPLETION_CALLBACK_URL` 时发送
- `knowledge_extraction_status` 常见值为 `success`、`failed`、`skipped`
- 回调里的 `knowledge` 采用独立的上游消费字段规范，不再与 `/api/v1/knowledge/update` 的请求 JSON 一一同名
- 其中 `knowledge.products` 仍然是数组，但 `management_team` / `competitors` / `authority_honors` / `customers_cases` / `attachments` 都是对象包装结构
- `knowledge.sensitive_topics` 为单个对象；没有敏感话题时可返回空对象 `{}`，有内容时按 `sensitive_contents`、`controversial_events`、`forbidden_words`、`negative_clarifications`、`other_info` 这 5 个字段展开；`/knowledge/update` 请求体里的 `sensitive_topics` 也使用同一对象结构
- `knowledge.products` 只反映本次 `/brands/upload` 请求里的产品范围：请求里没有产品则返回 `[]`；请求里有 1 个产品则只返回这 1 个产品对应的信息
- `knowledge.competitors` 会包含本次 `/brands/upload` 请求里的竞品种子，以及附件内容明确抽取出的新增竞品；联网检索只补字段，不额外凭空新增竞品
- `company_profile`、`management_team`、`competitors`、`customers_cases`、`sensitive_topics` 里的多值文本字段统一返回数组；没有内容时返回 `[]`
- 顶层 `attachments` 来自 `/brands/upload` 的品牌级 `attachments`
- `products[].attachments` 不在回调 `knowledge.attachments` 中返回
- 回调里的 `knowledge.other_info` 使用数组结构：`[{ "title": string, "content": any }]`

### 5. 更新品牌知识

- Method：`POST`
- Path：`/api/v1/knowledge/update`
- Content-Type：`application/json`

请求示例：

```json
{
  "basic_info": {
    "brand_code": "BRAND-001",
    "brand_name": "示例品牌",
    "brand_alias": "示例别名",
    "brand_logo": "https://example.com/logo.png",
    "website": ["https://example.com"],
    "intro": "品牌介绍",
    "brand_enterprise_entity": "示例品牌主体名称",
    "business_license_image_path": "https://example.com/license.png",
    "english_name": "Example Brand",
    "official_wechat_account": "example_wechat",
    "positioning": "高端智能服务品牌",
    "advantages": "渠道广、交付快、服务稳定",
    "mission": "让企业服务更高效",
    "vision": "成为行业领先品牌",
    "target_regions": ["中国", "新加坡"],
    "other_info": ""
  },
  "products": [
    {
      "name": "产品A",
      "product_alias": "A产品",
      "product_description": "产品A介绍",
      "product_website": "https://example.com/product-a",
      "product_images": ["https://example.com/product-a-1.png"],
      "price_info": "99元/月",
      "coverage_regions": ["中国"],
      "product_advantages": "上手快，成本低",
      "target_scenarios": "客服、运营、销售",
      "service_standard": "7x24小时支持",
      "service_process": "咨询-开通-培训-运营",
      "cases_and_reputation": "服务过多家头部企业",
      "certification_info": "ISO认证",
      "core_technology": "自研智能引擎",
      "other_info": ""
    }
  ],
  "company_profile": {
    "brand_subject_name": "示例品牌主体名称",
    "business_license_image_path": "https://example.com/license.png"
  },
  "management_team": [],
  "competitors": [],
  "authority_honors": [],
  "customers_cases": [],
  "official_media_matrix": [
    {
      "platform": "微信",
      "account_name": "示例品牌服务号",
      "account_id": "example_service",
      "url": "https://example.com/wechat",
      "description": "官方服务号",
      "related_products": ["产品A"],
      "other_info": ["新品发布"]
    }
  ],
  "official_malls": [
    {
      "platform": "天猫",
      "store_name": "示例品牌旗舰店",
      "url": "https://example.com/tmall",
      "description": "官方旗舰店",
      "related_products": ["产品A"],
      "other_info": ["支持售后咨询"]
    }
  ],
  "other_info": [
    {
      "title": "停车场信息",
      "content": "有地下停车场，节假日建议提前预约"
    },
    {
      "title": "夜游说明",
      "content": "每晚 19:30 开始"
    }
  ],
  "sensitive_topics": {
    "sensitive_contents": ["价格争议", "售后投诉"],
    "controversial_events": ["某次社媒舆情事件"],
    "forbidden_words": ["保本", "稳赚"],
    "negative_clarifications": ["统一回应口径示例"],
    "other_info": ["客服转述时避免绝对化表述"]
  },
  "attachments": [
    {
      "name": "品牌手册.pdf",
      "url": "https://example.com/brand-book.pdf"
    }
  ]
}
```

说明：

- 当前品牌完成回调里的 `knowledge` 使用独立字段规范；`/knowledge/update` 请求体继续使用内部更新结构
- `official_media_matrix` 会写入 `brand_knowledge_json.knowledge_type = official_media_matrix`，用于官方媒体与账号矩阵
- `official_malls` 会写入 `brand_knowledge_json.knowledge_type = official_malls`，用于官方商城/官方店铺
- 顶层 `other_info` 是独立的“其他信息”知识分区，会写入 `brand_knowledge_json.knowledge_type = other_info`；它不同于 `basic_info.other_info` 或产品/竞品对象内部的 `other_info`
- 顶层 `other_info` 使用数组结构：`[{ "title": string, "content": any }]`；同 `title` 更新时覆盖 `content`，不同 `title` 会新增
- `/api/v1/knowledge/update` 当前不对外暴露顶层 `attachment_products` 请求字段；如果要修改附件抽取产品副本，需通过顶层 `other_info` 中 `title = 附件解析新增产品` 的那一条来传
- 当顶层 `other_info` 中出现 `title = 附件解析新增产品` 时，系统会自动把这条 `content` 标准化后同步写入 `brand_knowledge_json.knowledge_type = attachment_products`
- 同一次更新里，系统还会基于最新的 `attachment_products` 自动重建 `other_info` 分区；所以 completed 回调里的 `knowledge.other_info` 会返回这次重建后的最新内容
- 如果本次显式清空 `title = 附件解析新增产品` 的 `content`，系统会同步清空 `brand_knowledge_json.attachment_products`，并从最终 `other_info` 镜像中移除这批附件产品内容
- `sensitive_topics` 使用对象结构，固定字段为：
  - `sensitive_contents: string[]`
  - `controversial_events: string[]`
  - `forbidden_words: string[]`
  - `negative_clarifications: string[]`
  - `other_info: string[]`
- `sensitive_topics` 显式传 `{}` 时，会把当前品牌已有的敏感话题清空，并在 `brand_knowledge_json` 中写为 `{}` 
- `attachments` 使用品牌级附件数组；单个元素格式为 `{ "name": string, "url": string }`
- `attachments` 不传时：不修改已有附件
- `attachments` 传非空数组时：会先按 `name + url` 与当前附件做差异比对
  - 新增项会走远程附件入库链路：下载远程文件、上传 OSS、文档入 Milvus、摘要入 MySQL、facts 入 Milvus
  - 删除项当前只会把对应附件从 `brand_knowledge_json.attachments` 挂载列表中移除，不会物理删除 `document_registry`、Milvus 文档向量、facts、`brand_attachment_assets` 或 OSS 对象
  - 最后再把 `brand_knowledge_json.attachments` 覆盖成本次请求里的最终数组
- `attachments` 显式传空数组 `[]` 时：表示清空当前品牌知识里的附件挂载列表；当前不会逐个物理删除底层文档实体
- 该接口会同时更新：
  - `brands` 表中的品牌主数据字段
  - `brand_products` 表中的产品结构化字段
  - `brand_knowledge_json` 中的各知识分区内容
- 当前结构化搜索仍主要读取 `brands`、`brand_products` 和 `brand_knowledge_json`

### 5.1 预解析品牌附件

- Method：`POST`
- Path：`/api/v1/brands/attachments/preview-parse`
- Content-Type：`application/json`

说明：

- 该接口只负责“生成编辑初稿”，不会在此阶段写 MySQL、Milvus 或 OSS
- 远程附件会先下载到本地临时草稿目录，再逐个解析为 Markdown
- 如果请求里有多个附件，后端会按前端传入顺序把多个附件正文用空行合并，供本次结构化抽取和后续归档使用
- 附件明细、解析正文和当前库快照会保留在 draft 内部，当前响应不返回 `attachments`、`combined_markdown_text` 或 `current_snapshot`
- 接口返回 `draft_id`，供后续 `review-changes` 和 `confirm` 继续使用

请求示例：

```json
{
  "brand_name": "Jollybaby",
  "brand_code": "100063",
  "attachments": [
    {
      "name": "品牌手册-1.pdf",
      "url": "https://example.com/a.pdf"
    },
    {
      "name": "品牌手册-2.pdf",
      "url": "https://example.com/b.pdf"
    }
  ]
}
```

响应示例：

```json
{
  "draft_id": "bad_xxx",
  "brand_name": "Jollybaby",
  "candidate_snapshot": {
    "basic_info": {
      "brand_name": "Jollybaby",
      "extra_info": {
        "brand_positioning": ["专注婴童早教玩具"]
      }
    },
    "other_info": [
      {
        "title": "停车场信息",
        "content": "有地下停车场，节假日建议提前预约"
      }
    ]
  },
  "field_labels": {
    "basic_info": "基础信息",
    "basic_info.extra_info.brand_positioning": "品牌定位",
    "products[].base_info.name": "产品名称",
    "competitors.competitors[].name": "竞品名称",
    "company_profile.founded_at": "成立时间"
  },
  "knowledge_revision": "LXKG-JLBY-V1.0.0-20260630120000"
}
```

字段说明：

- `draft_id`：本次附件预解析草稿 ID
- `candidate_snapshot`：附件本次抽取出的候选结构化快照；字段格式与品牌完成回调里的 `knowledge` 一致，前端直接编辑这个对象后传给 `review-changes`
- `candidate_snapshot` 响应会自动移除 `null`、空字符串、空数组、空对象；只返回本次真正抽到的字段
- `candidate_snapshot` 不会把请求入参里的 `brand_name`、`attachments` 当作解析结果返回；如果附件下载失败、解析失败，或没有抽取出任何有效字段，则接口仍返回 `200`，但 `candidate_snapshot` 返回 `{}`，同时 `field_labels` 返回 `{}`
- `candidate_snapshot.other_info`：顶层“其他信息”数组，元素格式为 `{ "title": string, "content": any }`，承载无法归入标准字段但有价值的附件信息；`title` 会返回中文标题，已归入标准字段且内容重复的信息不会再次出现在这里；当 `title` 为 `附件解析新增产品` 时，`content[]` 内仍使用稳定英文 key，中文展示名通过 `field_labels` 的 `other_info[].content[].xxx` 返回；未预定义的英文 key 会尽量映射常见中文名，无法识别时返回中文兜底名 `补充信息`
- `field_labels`：本次 `candidate_snapshot` 实际返回字段的中文名映射，供前端展示字段名使用；数组元素用 `[]` 表示，例如 `products[].base_info.name`；`other_info` 不返回字段中文名
- `knowledge_revision`：预解析时读取到的当前知识版本；后续 `review-changes` / `confirm` 可用于并发校验

### 5.2 审核附件候选快照差异

- Method：`POST`
- Path：`/api/v1/brands/attachments/review-changes`
- Content-Type：`application/json`

说明：

- 这是三步流里的“审核”接口
- 前端把用户编辑后的 `candidate_snapshot` 传回
- 后端不会再调用 LLM 做二次结构化，只把 `candidate_snapshot` 与 MySQL 当前品牌知识做字段级 diff
- 响应里返回 `review_id`、新增字段数、修改字段数、字段明细；前端确认无误后再调用 `confirm`
- 若请求里带了 `knowledge_revision`，且数据库当前版本已变化，接口返回 `409`

请求示例：

```json
{
  "draft_id": "bad_xxx",
  "candidate_snapshot": {
    "basic_info": {
      "brand_name": "Jollybaby",
      "extra_info": {
        "brand_positioning": ["专注婴童早教玩具"]
      }
    },
    "other_info": [
      {
        "title": "停车场信息",
        "content": "有地下停车场，节假日建议提前预约"
      }
    ]
  },
  "brand_name": "Jollybaby",
  "brand_code": "100063",
  "knowledge_revision": "LXKG-JLBY-V1.0.0-20260630120000"
}
```

响应示例：

```json
{
  "review_id": "bar_xxx",
  "draft_id": "bad_xxx",
  "brand_code": "100063",
  "brand_name": "Jollybaby",
  "knowledge_revision": "LXKG-JLBY-V1.0.0-20260630120000",
  "summary": {
    "added_field_count": 3,
    "modified_field_count": 2,
    "deleted_field_count": 0
  },
  "changes": [
    {
      "field_path": "basic_info.positioning",
      "field_label": "基础信息 / positioning",
      "change_type": "added",
      "old_value": null,
      "new_value": "专注婴童早教玩具"
    }
  ],
  "warnings": [
    "请务必核对修改的信息，确保内容与品牌官方一致，避免错误或过时信息。",
    "系统仅提供信息聚合服务，最终内容以您确认的为准。"
  ],
  "can_confirm": true
}
```

字段说明：

- `review_id`：本次审核结果 ID；正式保存时需要回传给 `confirm`
- `summary.added_field_count`：新增字段数
- `summary.modified_field_count`：修改字段数
- `summary.deleted_field_count`：当前保留字段，现阶段固定为 `0`
- `changes[]`：字段级差异明细
- `can_confirm`：当前是否允许进入确认保存

### 5.3 确认品牌附件解析结果并入库

- Method：`POST`
- Path：`/api/v1/brands/attachments/confirm`
- Content-Type：`application/json`

说明：

- 这是三步流里的“最终保存”接口
- 前端必须把 `review_id` 回传给该接口；不再支持不传 `review_id` 的旧链路
- `confirm` 不再重新调用 LLM 做结构化，也不会重新下载原始附件
- 接口只做轻量校验并创建后台任务，然后立即返回 `background_job_id`
- 后台 `attachment_confirm_pipeline` 会：
  - 校验 `knowledge_revision`
  - 读取审核阶段缓存的结构化结果
  - 调用现有 `update_knowledge` 更新 MySQL 品牌知识
  - 用审核阶段缓存的编辑稿作为最终 Markdown 内容
  - 将最终 Markdown 以 `{brand_name}-{draft_id}-{review_id}-confirmed-knowledge.md` 命名上传到 OSS，避免同品牌多次确认互相覆盖
  - 在 `brand_knowledge_update_audits` 记录 `source_type=attachment_confirm`、`source_task_id=confirm:{draft_id}:{review_id}` 与 `source_oss_key`
  - 顺延同品牌的 `brand_full_knowledge_refresh` 后台任务 2 分钟
  - 执行业务回调
- `brand_full_knowledge_refresh` 会在同品牌 2 分钟内没有新的 `knowledge_update` 或 `attachment_confirm` 变更后执行，统一消费未生成的审计变更，并生成完整 `【品牌名】品牌AI知识库_Vx_日期.md/.pdf`
- 前端拿到 `background_job_id` 后，轮询 `/api/v1/brands/attachments/confirm/result/{job_id}`；当响应 `code=0` 时表示后台处理完成
- 如果页面需要按品牌统一展示“品牌 AI 知识库是否在生成”，当前也可以轮询 `/api/v1/brands/knowledge-base/conflict-session/latest`，它会把 `attachment_confirm_pipeline` 与 `brand_full_knowledge_refresh` 的状态对齐到最终展示态；但 `confirm/result` 仍然是按单个确认 job 查询结果的正式入口

请求示例：

```json
{
  "draft_id": "bad_xxx",
  "review_id": "bar_xxx",
  "brand_name": "Jollybaby",
  "knowledge_revision": "LXKG-JLBY-V1.0.0-20260630120000"
}
```

响应示例：

```json
{
  "draft_id": "bad_xxx",
  "brand_id": 123,
  "brand_name": "Jollybaby",
  "status": "waiting",
  "updated_sections": [],
  "knowledge_revision": "LXKG-JLBY-V1.0.0-20260630120000",
  "final_markdown_oss_key": null,
  "final_markdown_oss_url": null,
  "final_document_id": null,
  "original_attachments": [],
  "attachment_documents": [],
  "background_job_id": "bg:attachment_confirm_pipeline:confirm:bad_xxx:bar_xxx",
  "background_job_status": "waiting",
  "confirm_callback_status": "waiting"
}
```

字段说明：

- `status`：`waiting` 表示已创建后台确认任务；如果同一任务之前已完成，可能直接返回 `success`
- `background_job_id`：前端轮询确认结果时使用
- `updated_sections` / `final_markdown_oss_key` / `final_markdown_oss_url` / `final_document_id` / `original_attachments`：确认接口快速返回时为空，后台完成后可从结果接口读取

### 6. 语义检索

- Method：`POST`
- Path：`/api/v1/search`
- 默认行为：
  只检索最新版文件内容；同一 `category` 下同名文件如果存在 `V1`、`V2`，默认只命中最新成功版本。
  品牌介绍、产品介绍这类不走文件注册表的纯文本内容不受该规则影响，仍可正常检索。

请求：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "品牌手册讲了什么",
    "top_k": 5,
    "category": "demo"
  }'
```

响应：见 `SearchResponse`

### 7. 删除品牌知识附件挂载

- Method：`POST`
- Path：`/api/v1/brands/attachments/delete`
- 默认行为：
  先按 `brand_code` 找品牌，再在当前 `brand_knowledge_json.attachments` 里匹配附件挂载项。
  传入 `url` 时，会优先按 `name + url` 精确匹配；未传 `url` 时，按附件名匹配。
  当前只删除“品牌知识里的附件挂载关系”，不会物理删除底层文档、facts、Milvus 向量或 OSS 对象。

请求：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/brands/attachments/delete \
  -H "Content-Type: application/json" \
  -d '{
    "brand_code": "BRAND-001",
    "attachments": [
      {
        "name": "品牌手册.pdf",
        "url": "https://example.com/brand-book.pdf"
      }
    ]
  }'
```

请求字段：

- `brand_code`：必填，品牌编码
- `attachments`：必填，待删除附件数组
- `attachments[].name`：必填，附件原始文件名
- `attachments[].url`：选填；传入后优先按 `name + url` 精确删除，兼容远程附件同名场景

成功响应：

```json
{
  "code": "200",
  "message": "成功",
  "data": {
    "brand_code": "BRAND-001",
    "brand_name": "示例品牌",
    "name": "品牌手册.pdf",
    "url": "https://example.com/brand-book.pdf",
    "status": "deleted",
    "document_id": null,
    "matched_document_ids": [],
    "detail": "已从品牌知识附件列表移除"
  }
}
```

说明：

- 对外接口统一返回 `status=deleted`
- 如果附件原本已不在当前 `brand_knowledge_json.attachments` 中，也按幂等删除返回 `deleted`
- 只要本次请求落入“已删除/幂等删除”语义，当前都会发送附件删除回调，供上游同步自身附件记录
- 这条接口当前不会删除：
  - `document_registry`
  - `document_categories`
  - Milvus 文档向量
  - Milvus facts
  - `brand_attachment_assets`
  - OSS 对象

删除成功回调：

- 仅当本次请求至少有一个附件 `status=deleted` 时触发
- 删除成功后会先更新 `brand_knowledge_json.attachments` 为剩余附件列表
- 回调 JSON 结构沿用当前品牌完成回调；其中 `knowledge.attachments.files` 表示删除后的剩余附件
- `knowledge_mete` 读取当前品牌已有的 `knowledge_revision` 和最新完整知识库文件地址，不重新生成 Markdown / PDF
- 回调失败不影响删除接口响应；失败会记录到 `upload_task_callbacks`，并按重试策略补偿发送

常见错误：

- `404`：没有找到对应附件
- `400`：参数错误，或命中多个同名附件需要人工确认

### 8. 分类 facts 语义检索

- Method：`POST`
- Path：`/api/v1/categories/facts`
- 默认行为：
  直接检索 Milvus facts 集合。对于品牌 facts，使用 `category` 作为品牌名过滤，并在可解析品牌时额外使用 `brand_code` 过滤；不再依赖最新版知识库 `document_id`。
- embedding 限流保护：
  调用前会先做 `query` embedding。正常情况下外部 embedding 最大并发默认 `10`；如果命中外部限流, 服务端会先全局冷却默认 `60` 秒, 冷却期间不会排队等待, 而是直接返回 `503` 并带上 `Retry-After`。

请求：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/categories/facts \
  -H "Content-Type: application/json" \
  -d '{
    "category": "demo",
    "query": "报名条件",
    "top_k": 5
  }'
```

成功响应：

```json
{
  "category": "demo",
  "query": "报名条件",
  "facts": [
    {
      "fact": "demo 的报名时间为 2025 年 3 月 1 日至 3 月 10 日",
      "score": 0.92,
      "document_count": 2
    }
  ]
}
```

### 9. 品牌 facts 语义检索

- Method：`POST`
- Path：`/api/v1/brands/facts`
- 默认行为：
  `brand_name` 是主字段；`category` 只是兼容旧字段名。
- embedding 限流保护：
  与 `/api/v1/categories/facts` 共用同一套 embedding 冷却规则。也就是说, query 会先做 embedding; 发生外部限流时, 会先冷却, 冷却期间直接返回 `503` 和 `Retry-After`。

请求：

```bash
curl -X POST http://127.0.0.1:9007/api/v1/brands/facts \
  -H "Content-Type: application/json" \
  -d '{
    "brand_name": "demo",
    "query": "这个品牌的核心优势有哪些",
    "top_k": 5
  }'
```

成功响应：

```json
{
  "brand_name": "demo",
  "category": "demo",
  "query": "这个品牌的核心优势有哪些",
  "facts": [
    {
      "fact": "demo 的核心优势包括 ...",
      "score": 0.92,
      "document_count": 2
    }
  ]
}
```

## 常见联调说明

### 1. 怎么判断文件真的入库成功了

看上传任务状态接口里每个文件项：

- `status=success`
- 存在 `document_id`

满足这两个条件，说明该文件主入库流程已经完成。

补充：

- `POST /api/v1/documents/upload-tasks` 是“查询上传任务状态”的接口
- 它用于查看任务是否还在排队、处理中、已成功或失败，以及每个文件条目的处理结果

### 2. 为什么上传成功了，但分类 facts 还是空

常见原因：

- facts 后台任务还没跑完
- AI 认为该文档没有足够强的分类相关事实
- DashScope 或 Milvus 在 facts 链路上报错

### 3. 为什么 Swagger 里看不到 `/documents/delete` 或 `/fulltext`

常见原因：

- 这两个接口当前没有公开路由入口
- 旧版 `API.md` / `README.md` 曾保留过历史描述
- 当前应以 Swagger `/docs` 和 `docs/rules/api-truth-matrix.md` 为准
