# `/api/v1/documents/upload` 规则

最后校对日期: 2026-08-05

## 入口与范围

- 接口: `POST /api/v1/documents/upload`
- 路由实现: [knowledge_base/api_app/routers/documents.py](../../knowledge_base/api_app/routers/documents.py)
- 主服务实现: [knowledge_base/upload_task/application/service.py](../../knowledge_base/upload_task/application/service.py)
- metadata 解析与自动补齐: [knowledge_base/api_app/parsing.py](../../knowledge_base/api_app/parsing.py), [knowledge_base/shared/utils/metadata.py](../../knowledge_base/shared/utils/metadata.py)

这条链路现在只承载品牌场景上传入口. 同一个接口根据文件名模式, 只会走 2 条分支:

1. 品牌附件资产分支
2. 正式品牌 AI 知识库文件分支

注意:

- 现在另有一条独立接口 `POST /api/v1/brands/facts/upload`
- 它不属于 `/documents/upload` 体系
- 那条接口只处理“现成 Markdown -> 抽 facts -> 写入 `brand_knowledge_facts` / Milvus -> 删除该品牌旧 facts”
- 它不会创建 upload task, 也不会走正式知识库文件入库 / `brand_knowledge_json` 回补 / completed 回调

## 请求规则

| 字段 | 必填 | 当前规则 |
| --- | --- | --- |
| `files` | 是 | 支持多文件上传 |
| `metadata` | 是 | 必须是 JSON object 字符串, 且必须包含 `category` / `brand_code` / `brand_name` |
| `chunk_size` | 否 | 保留字段, 当前这条接口的 2 条品牌分支都不使用 |
| `chunk_overlap` | 否 | 保留字段, 当前这条接口的 2 条品牌分支都不使用 |

补充规则:

- `metadata` 不是合法 JSON 时直接返回 `400`.
- `metadata` 是合法 JSON 但不是 object 时也返回 `400`.
- `metadata.category` / `metadata.brand_code` / `metadata.brand_name` 任一缺失时返回 `400`.
- `metadata.category` 与 `metadata.brand_name` 不一致时返回 `400`.
- 这条接口已不再支持普通文档入库.
- 文档示例见 [API.md](../../API.md).

当前推荐 metadata:

```json
{"category":"燕子屋","brand_code":"100064","brand_name":"燕子屋"}
```

## metadata 自动补齐规则

当前标准化仍会处理以下字段:

- `brand_name`
- `category`
- `subcategory`

自动补齐规则:

- 传了 `brand_name` 但没传 `category` 时, 自动补 `category = brand_name`
- 传了 `category` 但没传 `brand_name` 时, 自动补 `brand_name = category`
- 空字符串会被移除

影响:

- 虽然底层仍保留 `brand_name` / `category` 互补能力, 但 `/documents/upload` 入口现在已经要求调用方显式同时传 `category` 和 `brand_name`
- 所以这里不应该再依赖“只传一个字段, 系统自动补另一个字段”这种旧用法

## 文件角色判断

文件角色由 `_resolve_file_role(...)` 决定.

当前规则:

- 文件名符合 `【品牌名】品牌AI知识库_V版本_日期.xxx` 且扩展名为 `.md` 时, 角色为 `brand_ai_knowledge`
- 其他情况默认都是 `attachment`

注意:

- 这里不是靠接口路径决定是否为正式知识库文件, 而是靠文件名模式判断
- 文件名解析规则见 [knowledge_base/brand/ai_knowledge_filename.py](../../knowledge_base/brand/ai_knowledge_filename.py)

## 任务创建阶段规则

任务创建阶段发生在真正后台消费前.

当前行为:

- 先把上传文件落到 staging 目录
- 计算 `file_hash`
- 同一批次内按 `SHA-256` 去重
- 创建 upload task 时 `task_type` 固定写成 `document_upload`
- 只要本批次里包含 `brand_ai_knowledge` 文件, 会自动打开:
  - `brand_callback_enabled = true`
  - `backfill_brand_knowledge_json_empty_only = true`

注意:

- 即使后续某个文件会走品牌附件或正式知识库分支, 入口任务类型仍固定是 `document_upload`
- `/api/v1/documents/upload` 现在这 2 个品牌分支都不再依赖 `document_registry.reserve_document_uploads(...)` 做门禁

## 后台处理分支

### 1. 品牌附件资产分支

触发条件:

- `file_role == "attachment"`
- `metadata.brand_code` 非空
- `attachment_assets` 与 `oss_client` 依赖已初始化

当前行为:

- 文件会走 OSS 原文件和全文 Markdown 资产化流程
- `brand_code` 与 `brand_name` 都必须能解析出来
- 这里的 `brand_name` 取值规则仍然是 `brand_name or category`
- 不做普通文档入库
- 不做 AI 摘要
- 不做旧 facts 抽取入 Milvus
- 主要产物是附件 OSS 文件 + `brand_attachment_assets`

落库重点:

- 资产记录主写 `brand_attachment_assets`
- 不会因为这条上传直接新增旧 `document_summaries` 主链路数据
- 这条链路主要服务品牌附件管理、冲突处理和后续结构化知识生成

### 2. 正式品牌 AI 知识库文件分支

触发条件:

- `file_role == "brand_ai_knowledge"`
- `metadata.brand_code` 非空
- `metadata.brand_name` 或 `metadata.category` 能解析出品牌名
- `brand_ai_knowledge_ingestion` 依赖已初始化

当前行为:

- 进入 [brand-ai-knowledge-ingestion.md](./brand-ai-knowledge-ingestion.md) 描述的正式知识库文件入库流程
- 成功后写 `brand_full_knowledge_files` 与 `brand_knowledge_facts`
- 成功后新增一段“正式 Markdown 结构化回补”:
  - 直接使用这份 `【品牌名】品牌AI知识库_Vx_日期.md`
  - 结构化解析为 snapshot
  - 按“保留当前线上 merge 规则”回写 `brand_knowledge_json`
    - `competitors`: 只补已有竞品的空字段, 不新增, 不整表替换
    - `attachment_products`: 不改 `brand_products`, 只按本次 Markdown 重建附件产品副本
    - `brands.intro`: 保留旧值优先, 只有旧值为空时才用 incoming
    - 其他大部分 `brand_knowledge_json` 分区: 新值非空时优先覆盖, 新值为空时保留旧值
- 完成后走主知识库 completed 回调, 直接返回当前最新 knowledge snapshot

## 当前最容易混淆的地方

### `category` 和 `brand_name`

- 这两个字段在底层仍会互补
- 但这条接口现在已经把它们提升成显式必填, 并要求二者一致
- 所以对调用方来说, 不要再把 `category` 当成可选别名字段

### `brand_code`

- 现在是整条 `/documents/upload` 入口的必填字段
- 它同时决定品牌附件分支和正式知识库分支的品牌定位

### `brand_knowledge_json`

- 上传品牌附件时, 这里不会直接写 `brand_knowledge_json`
- 上传正式品牌 AI 知识库文件时, 现在会在正式入库完成后, 再做一次基于最终 Markdown 的结构化回补
- 这一步不是“全量替换”
- 也不是“所有字段都只补空值”
- 当前保留的实际规则是:
  - `competitors`: 只补已有竞品的空字段, 不新增新竞品, 不整表替换
  - `brand_products`: 这条回补不直接改
  - `attachment_products`: 用 Markdown 抽出的产品, 扣掉 `brand_products` 里已有产品后, 重建副本并写回
  - `brands`: `brand_code`、`brand_name`、`brand_alias`、`brand_logo`、`website`、`industry_id`、`knowledge_revision`、`competitors_json`、`intro` 保留旧值优先; 其中 `intro` 只有旧值为空时才用 incoming
  - `company_profile`、`management_team`、`authority_honors`、`customers_cases`、`sensitive_topics`、`attachments`、`official_malls`、`official_media_matrix`、`other_info`: 新值非空时优先覆盖, 新值为空时保留旧值

### `/brands/facts/upload` 不是 `/documents/upload` 的第三分支

- `/documents/upload` 当前仍然只有 2 条品牌分支:
  - 品牌附件资产
  - 正式品牌 AI 知识库文件
- `/brands/facts/upload` 是独立同步接口
- 它要求上传内容本身就是 Markdown
- 它不依赖文件名命中 `brand_ai_knowledge` 角色
- 它不产出 `upload_task_id`
- 它的主要产物只有:
  - `brand_knowledge_facts`
  - Milvus facts 向量
- 它会在新 facts 成功写入后, 删除当前品牌旧 facts

## 已废弃的旧对外能力

这条接口已经切到品牌场景专用后, 下面两类旧对外能力不再作为当前规则的一部分:

- 旧 `/api/v1/documents/delete`
- 旧 `/api/v1/fulltext`

内部仍可能保留少量 `document_id` / `get_full_text(...)` helper 给品牌知识库流程复用, 但那已经不是当前对外文档协议.

## 调整本链路规则时, 需要同步检查

1. 这条接口是否仍然只允许 A. 品牌附件 和 B. 正式品牌 AI 知识库文件.
2. `metadata` 是否仍然强制要求 `category` / `brand_code` / `brand_name`.
3. `category` 与 `brand_name` 是否仍然要求完全一致.
4. `/documents/upload` 这 2 条品牌分支是否仍然不依赖 `document_registry` 预占门禁.
5. 正式知识库文件成功后, 是否仍然执行当前这套“竞品保守补空 + 附件产品重建 + 其他分区新值优先”的 `brand_knowledge_json` 回补.
6. 正式知识库文件完成后, 是否仍然走主知识库 completed 回调.
7. `/brands/facts/upload` 是否仍然保持为独立同步接口, 而不是重新混入 `/documents/upload` 分支判断.
