# 规则索引

最后校对日期: 2026-07-21

这组文档的目标不是替代代码, 而是把当前线上链路的规则固定成可检索的说明, 方便后续做两件事:

1. 改规则前, 先确认当前行为到底是什么.
2. 改规则后, 能快速补齐受影响的文档, 避免出现第二套过期真相.

## 使用方式

- 先看本文档, 找到目标链路.
- 再看对应分链路文档, 确认入口、分支条件、落库表、失败点.
- 最后对照代码锚点修改实现与文档.

## 当前推荐结构

当前 `docs/rules/` 建议按 4 层理解:

1. 接口入口规则
2. 功能语义规则
3. 领域口径规则
4. 运行与排查规则

更详细的分层与命名建议见:

- [rules-organization.md](./rules-organization.md)

## 1. 接口入口规则

这类文档主要回答:

- 调哪个接口
- 请求字段怎么传
- 入口分支怎么走
- 首响应和异步行为是什么

当前文档:

- [brand-read-apis.md](./brand-read-apis.md): `/brands`、`/brands/{brand_code}/meta`、`/brands/{brand_code}/paths-load`、`/brands/ai-knowledge/latest` 的读取层级、path 规则与最新知识库文件回退逻辑.
- [documents-upload.md](./documents-upload.md): `/api/v1/documents/upload` 的 metadata 规则、文件角色判断与两类文件处理分支.
- [brands-upload.md](./brands-upload.md): `/api/v1/brands/upload` 的请求字段、后台任务、附件抽取与 merge 规则.
- [knowledge-update.md](./knowledge-update.md): `/api/v1/knowledge/update` 的结构化更新规则, 包括 `attachment_products` 与 `other_info.附件解析新增产品` 的联动.
- [attachment-preview-confirm.md](./attachment-preview-confirm.md): `/brands/attachments/preview-parse` 与 `/brands/attachments/confirm` 两段式链路.

## 2. 功能语义规则

这类文档主要回答:

- 同一能力跨多个接口时, 统一规则是什么
- 底层到底查哪套数据 / 删哪层数据 / 触发哪类回调
- 哪些接口只是不同入口, 但共用同一能力口径

当前文档:

- [api-truth-matrix.md](./api-truth-matrix.md): 当前 FastAPI 实际启用接口、旧文档残留接口与"内部能力但未公开暴露"能力的真相矩阵.
- [delete-semantics.md](./delete-semantics.md): `/brands/attachments/delete`、`/brands/delete` 与内部 `delete_document(...)` 的真实删除范围和边界.
- [search-rules.md](./search-rules.md): `/search`、`/brands/facts`、`/categories/facts` 的检索数据源、过滤口径与最新版本边界.
- [callbacks.md](./callbacks.md): 当前回调类型、来源链路、`upload_task_callbacks` 审计方式与 completed 回调口径.
- [background-jobs.md](./background-jobs.md): 当前 background job 的 job_type、状态流转、轮询方式与和业务会话的边界.
- [brand-ai-knowledge-ingestion.md](./brand-ai-knowledge-ingestion.md): 正式品牌 AI 知识库文件入库规则, 包含文件名校验与落库表.
- [backfill.md](./backfill.md): 当前 3 套回补规则: 附件抽取回补、Markdown 结构化快照回补、手工 backfill 脚本回补.
- [conflict-session-lifecycle.md](./conflict-session-lifecycle.md): 附件冲突会话的创建复用、`round_no` 推进、`no_conflicts` 自动继续与最终生成收口规则.

## 3. 领域口径规则

这类文档主要回答:

- 同一个业务字段在多条链路里的含义
- 哪张表 / 哪个结构是主真相
- 回调、搜索、编辑时应该看哪一层

当前文档:

- [product-rules.md](./product-rules.md): 主产品白名单、附件产品副本、`attachment_products`、`other_info.附件解析新增产品` 与回调产品口径的统一规则.
- [competitors-field-mapping.md](./competitors-field-mapping.md): `competitors` 当前多套字段命名、各链路映射关系与推荐统一方向.
- [storage-and-tables.md](./storage-and-tables.md): `brands`、`brand_products`、`brand_knowledge_json`、`brand_full_knowledge_files`、`brand_knowledge_facts` 等表的职责分工.

## 4. 运行与排查规则

这类文档主要回答:

- 线上状态字段怎么看
- 出错时先查哪里
- 现象与真实根因之间怎么对应

当前文档:

- [status-enums.md](./status-enums.md): 当前 `status` / `knowledge_markdown_status` / `background_jobs.status` / callback 状态的边界和推荐查看方式.
- [error-cases.md](./error-cases.md): 当前高频报错、触发条件、应优先检查的字段.
- [idempotency-retry-compensation.md](./idempotency-retry-compensation.md): 上传、background jobs、callback 与附件冲突会话当前的防重、重试与补偿边界.

## 修改规则时的最小检查单

每次改链路时, 至少同步检查下面 5 件事:

1. 入口接口文档有没有变.
2. metadata 自动补齐规则有没有变.
3. 分支条件有没有变.
4. 落库表有没有变.
5. 常见报错文案和排查路径有没有变.

## 当前代码锚点

- 路由入口:
  - [knowledge_base/api_app/routers/documents.py](../../knowledge_base/api_app/routers/documents.py)
  - [knowledge_base/api_app/routers/brands.py](../../knowledge_base/api_app/routers/brands.py)
  - [knowledge_base/api_app/routers/brand_knowledge.py](../../knowledge_base/api_app/routers/brand_knowledge.py)
- 上传任务分发:
  - [knowledge_base/upload_task/application/service.py](../../knowledge_base/upload_task/application/service.py)
- 正式知识库文件入库:
  - [knowledge_base/brand/application/ai_knowledge_ingestion.py](../../knowledge_base/brand/application/ai_knowledge_ingestion.py)
  - [knowledge_base/brand/ai_knowledge_filename.py](../../knowledge_base/brand/ai_knowledge_filename.py)
- 品牌知识结构化写库:
  - [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py)
  - [knowledge_base/brand_knowledge/application/attachment_flow.py](../../knowledge_base/brand_knowledge/application/attachment_flow.py)
- 存储层:
  - [knowledge_base/stores/brand_knowledge_store.py](../../knowledge_base/stores/brand_knowledge_store.py)
  - [knowledge_base/stores/brand_full_knowledge_store.py](../../knowledge_base/stores/brand_full_knowledge_store.py)
  - [knowledge_base/stores/brand_knowledge_fact_store.py](../../knowledge_base/stores/brand_knowledge_fact_store.py)

## 文档维护约定

- 文档描述的是"当前实现规则", 不是理想状态.
- 当代码行为与旧文档不一致时, 以代码为准, 然后立刻回补本文档.
- 当准备修改规则时, 先在对应文档里把"当前规则"看清楚, 再改代码和文档.
- 当新增一条独立链路时, 优先新增分链路文档, 不要把所有规则继续堆回一个总文档.
