# 删除语义规则

最后校对日期: 2026-07-21

## 目标

这份文档只说明当前 3 类删除语义:

1. `POST /api/v1/brands/attachments/delete`
2. `POST /api/v1/brands/delete`
3. 内部 `delete_document(...)` 的真实删除范围

重点是澄清:

- 哪些删除只是改品牌知识挂载
- 哪些删除会级联清 Milvus / MySQL / OSS
- `dry_run` 当前到底是什么意思

## 当前公开删除入口

当前对外只有 2 个删除类 HTTP 接口:

- `POST /api/v1/brands/attachments/delete`
- `POST /api/v1/brands/delete`

代码入口:

- [knowledge_base/api_app/routers/documents.py](../../knowledge_base/api_app/routers/documents.py)
- [knowledge_base/api_app/routers/brands.py](../../knowledge_base/api_app/routers/brands.py)

## 一句话区分

- `/brands/attachments/delete`: 只删除 `brand_knowledge_json.attachments` 里的附件挂载关系
- `/brands/delete`: 删除整个品牌及其关联知识数据

当前没有对外公开的 `POST /api/v1/documents/delete`.

## `/api/v1/brands/attachments/delete` 当前规则

### 入口参数

- 必须传 `brand_code`
- 必须传 `attachments`
- 每个附件当前至少要求 `name`
- `url` 可选; 传了会参与匹配

请求模型:

- [knowledge_base/document/schemas/requests.py](../../knowledge_base/document/schemas/requests.py)

### 当前匹配逻辑

系统当前会:

1. 先用 `brand_code` 找品牌
2. 再读取 `brand_knowledge_json` 中 `knowledge_type = attachments` 的当前内容
3. 只在这份当前附件列表里做匹配
4. 匹配成功后, 把匹配到的附件从这份附件列表里移除并回写

也就是说, 这条接口当前删除的是:

- 品牌结构化知识里的附件挂载列表

不是:

- 文档主库里的 `document_registry` 记录
- Milvus 文档向量
- 文档 facts
- OSS 原始文件 / Markdown
- `brand_attachment_assets` 资产表记录

### 当前真实写库行为

匹配到待删附件后, 当前会调用 `_sync_remaining_attachments_after_delete(...)`:

- 重新计算剩余附件列表
- 回写 `brand_knowledge_json`
- `knowledge_type = attachments`

代码锚点:

- [knowledge_base/service.py](../../knowledge_base/service.py)

### 当前不会删除的内容

这条接口当前不会触碰下面这些层:

1. `document_registry`
2. `document_categories`
3. `document_fact_relations`
4. Milvus 文档向量
5. Milvus facts 向量
6. `brand_attachment_assets`
7. OSS 对象

所以这条接口现在要理解成:

- "品牌知识附件挂载删除"
- 不是"附件物理清理"

### 返回状态语义

当前对外接口结果项统一按 `deleted` 返回。

其中:

- `deleted` 表示成功从当前品牌知识附件列表中移除
- 如果当前 `brand_knowledge_json.attachments` 中没有匹配项, 也按幂等删除返回 `deleted`

内部 service summary 仍可能统计 `not_found_count`, 但不会透传为接口响应状态。

当前实现里 `ambiguous_count`、`failed_count` 会出现在 summary 里, 但这条链路现在实际没有完整跑出多状态物理删除分支.

### 回调规则

当至少有一条附件落入 `deleted` 或 `not_found` 语义时, 当前系统还会:

1. 先把剩余附件列表同步回 `brand_knowledge_json`
2. 再构造新的品牌知识快照
3. 如果配置了 `brand_completion_callback_url`, 发送附件删除后的 completed 风格回调
4. 失败时按当前重试规则补发

这意味着:

- 这条接口虽然不删文档实体
- 但会把"删除后的知识快照"回调给上游

## `/api/v1/brands/delete` 当前规则

### 最容易误解的点

`dry_run` 当前语义是反直觉的:

- `dry_run = false`: 只预览删除范围, 不执行真实删除
- `dry_run = true`: 执行真实删除

这是当前代码的真实行为, 不是命名上的理想语义.

请求模型里也专门写了这层兼容说明:

- [knowledge_base/brand/schemas/requests.py](../../knowledge_base/brand/schemas/requests.py)

### 当前预览阶段会统计什么

调用 `/brands/delete` 时, 系统当前会先按品牌名收集整套待删对象, 包括:

1. `brands`
2. `brand_products`
3. `brand_knowledge_json`
4. `brand_attachment_assets`
5. `brand_knowledge_sessions`
6. `brand_knowledge_session_rounds`
7. `brand_knowledge_facts`
8. 品牌分类下的 `documents`
9. `document_registry`
10. `document_categories`
11. `document_fact_relations`
12. `brand_full_knowledge_files`
13. `brand_knowledge_ingestion_jobs`
14. `background_jobs`
15. `upload_tasks`
16. `upload_task_files`
17. `upload_task_callbacks`
18. 品牌 AI 知识库 OSS 对象
19. confirmed knowledge OSS 对象
20. 以及归集后的全部相关 OSS 对象

返回里的 `counts` 现在就是这套预览统计.

### OSS 删除前缀边界

`/brands/delete` 删除 OSS 对象时, 所有 OSS 删除候选都必须匹配当前 `OSS_OBJECT_KEY_PREFIX`.

这个约束覆盖所有 OSS 来源, 包括:

- `document_registry` / 文档 metadata 中记录的原始文件、全文 Markdown 等对象
- `brand_full_knowledge_files.oss_key`
- `brand_full_knowledge_files.pdf_oss_key`
- `brand_attachment_assets.oss_key`
- `brand_attachment_assets.fulltext_key`
- 目录扫描发现的品牌 AI 知识库对象
- 目录扫描发现的 confirmed knowledge 对象

前缀规则和上传 key 生成规则保持一致:

- `OSS_OBJECT_KEY_PREFIX` 为空时, 只扫描 `{safe_brand_name}/{artifact_dir}/`
- `OSS_OBJECT_KEY_PREFIX = test` 时, 只扫描 `test/{safe_brand_name}/{artifact_dir}/`
- `OSS_OBJECT_KEY_PREFIX = prod` 时, 只扫描 `prod/{safe_brand_name}/{artifact_dir}/`

执行删除时也只允许删除匹配当前前缀的 OSS key:

- `OSS_OBJECT_KEY_PREFIX` 为空时, 只允许删除无环境前缀的 key
- `OSS_OBJECT_KEY_PREFIX = test` 时, 只允许删除 `test/` 开头的 key
- `OSS_OBJECT_KEY_PREFIX = prod` 时, 只允许删除 `prod/` 开头的 key

不会再默认同时扫描或删除无前缀目录和固定 `test/` 目录.

### 执行真实删除时的顺序

当 `dry_run = true` 时, 当前会执行真实删除.

当前主顺序是:

1. 先对收集到的每个 `document_id` 调内部 `delete_document(...)`
2. 再删额外 OSS 对象
3. 删品牌知识会话
4. 删附件资产
5. 删正式知识库入库任务
6. 删 background jobs
7. 删 upload tasks / files / callbacks
8. 删 `brand_knowledge_facts`
9. 删 Milvus facts 集合里该 `brand_code` 的 facts
10. 删 `brand_full_knowledge_files`
11. 删 `brand_knowledge_json`
12. 删 `brand_products`
13. 最后删 `brands`
14. 失效该品牌的最新文档缓存

### 当前会删掉哪些存储层

这条接口现在属于"整品牌级联删除", 会覆盖:

- MySQL 业务表
- Milvus 文档向量
- Milvus facts 向量
- OSS 原始文件 / Markdown / 品牌知识库文档 / confirmed 文档

因此它当前是:

- 强删除
- 广范围删除

不是简单的逻辑下线或状态变更.

### 当前定位品牌的方式

这条接口当前只按 `brand_name` 找品牌.

也就是说:

- 不是按 `brand_code` 作为入口
- `brand_name` 找不到就直接报不存在

## 内部 `delete_document(...)` 当前规则

虽然现在没有公开 `POST /api/v1/documents/delete`, 但内部删除文档逻辑仍被品牌全量删除复用.

当前内部删除范围:

1. 从 facts 关系里移除该文档
2. 如果某条 fact 只关联这一个文档, 则直接删掉该 fact
3. 如果某条 fact 还关联其他文档, 则改写其 `document_ids`
4. 删除 `document_registry` 注册记录
5. 删除 OSS 原始文件 / 全文 Markdown / 图片对象
6. 删除 Milvus 文档 chunk 向量
7. 删除 `document_categories`

所以内部 `delete_document(...)` 是真正的文档物理删除链路.

## 当前三条删除语义的边界

### 1. 删除附件挂载

接口:

- `/brands/attachments/delete`

效果:

- 只影响 `brand_knowledge_json.attachments`
- 不删文档实体

### 2. 删除单个文档实体

当前状态:

- 只有内部能力
- 没有公开 API

效果:

- 删文档向量、文档 facts 关系、注册表、分类映射、OSS 对象

### 3. 删除整个品牌

接口:

- `/brands/delete`

效果:

- 级联清理品牌下的结构化知识、正式知识库、文档、facts、任务记录、OSS 对象

## 当前最容易误判的地方

### 为什么 `/brands/attachments/delete` 返回 deleted, 但文档还能搜到

因为当前删的是品牌知识里的附件挂载列表, 不是文档主库.

### 为什么 `dry_run = false` 没有执行真实删除

因为当前实现把 `false` 当成"仅预览", `true` 才当成"执行删除".

### 为什么品牌删除会删到正式知识库 PDF / Markdown

因为当前会把品牌 AI 知识库 OSS 对象和 confirmed knowledge 对象一起归集到删除范围.

## 调整删除规则时, 需要同步检查

1. `/brands/attachments/delete` 是否仍然只改 `brand_knowledge_json.attachments`.
2. 品牌删除时 `dry_run` 的真实语义是否变化.
3. 品牌删除是否仍然复用内部 `delete_document(...)`.
4. 是否仍然删除 `brand_knowledge_facts` 与 Milvus facts.
5. 是否仍然删除品牌 AI 知识库与 confirmed knowledge OSS 对象.
6. [API.md](../../API.md) 与 [README.md](../../README.md) 中旧的 `/documents/delete` 描述是否需要同步修正.
