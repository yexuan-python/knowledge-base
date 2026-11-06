# AGENTS.md

## 项目概览

这是一个 Python/FastAPI 知识库服务，核心业务包括：

- 品牌 AI 知识库入库、版本校验、事实抽取和全文发布
- 上传任务创建、排队、状态流转、文件处理和失败落库
- 品牌附件上传、图片附件向量化、附件确认、附件冲突处理和附件删除
- 后台任务、回调发送、回调审计和重试
- 文档入库、事实搜索、语义搜索和图片搜索

优先保持现有 API 行为、回调 payload、路由响应结构和历史兼容方法不变。除非用户明确要求，不要删除看似“只做代理”的方法；很多路由、测试、后台任务或旧调用会依赖这些入口。

## 工作规则

- 搜索文件和文本优先用 `rg` / `rg --files`。
- 手工改代码用 `apply_patch`。
- 不要回滚用户已有改动；如果工作区已有无关改动，忽略它们。
- 不要做无关重构。优先解决当前请求，并把改动控制在相关模块内。
- 不要使用 `git reset --hard`、`git checkout --` 等破坏性命令，除非用户明确要求。
- 结构化数据优先用已有 schema、store、application service 或 helper 处理，不要用脆弱的字符串拼接绕过现有抽象。

## 架构约定

`KnowledgeBaseService` 应尽量作为兼容门面。新增业务逻辑优先放到对应的 application service、workflow、processor 或 shared helper 中，不要继续把业务流程塞回主 service。

已经拆出的重要模块包括：

- `knowledge_base/brand/application/facts_only_upload.py`
- `knowledge_base/brand_knowledge/application/attachment_delete.py`
- `knowledge_base/brand_knowledge/application/attachment_preview_entry.py`
- `knowledge_base/brand_knowledge/application/status_queries.py`
- `knowledge_base/search/facade.py`
- `knowledge_base/shared/callback_delivery.py`
- `knowledge_base/shared/image_preparation.py`

文档删除能力优先放在 `knowledge_base/document/application/service.py`。主 service 里同名方法通常只是兼容代理。

## 上传任务约定

上传任务逻辑已经拆到：

- `knowledge_base/upload_task/application/service.py`
- `knowledge_base/upload_task/application/upload_enqueuer.py`
- `knowledge_base/upload_task/application/brand_upload_enqueuer.py`
- `knowledge_base/upload_task/application/task_processor.py`
- `knowledge_base/upload_task/application/file_processor.py`
- `knowledge_base/upload_task/application/lifecycle.py`
- `knowledge_base/upload_task/application/queue_coordinator.py`
- `knowledge_base/upload_task/application/status.py`
- `knowledge_base/upload_task/application/attachment_assets.py`
- `knowledge_base/upload_task/application/document_attachment_assets.py`
- `knowledge_base/upload_task/application/image_attachment_assets.py`
- `knowledge_base/upload_task/application/helpers.py`

不要把这些逻辑重新塞回 `UploadTaskApplicationService`。

上传任务状态流转、成功/失败汇总、后台任务失败后的任务状态落库，优先放在 `UploadTaskLifecycle`。

上传任务入队、worker 循环、后台 job delegation、worker 异常处理，优先放在 `UploadTaskQueueCoordinator`。

单文件处理分流、附件流和正式品牌 AI 知识库流，优先放在 `UploadTaskFileProcessor`。

附件资产处理不要混在一个大 processor 里。普通附件逻辑放在 `DocumentAttachmentAssetProcessor`，图片附件逻辑放在 `ImageAttachmentAssetProcessor`。

## 品牌 AI 知识库规则

品牌 AI 知识库版本检查在：

- `knowledge_base/brand/application/brand_ai_knowledge_ingestion_context.py`

注意：

- `force_reingest=True` 是显式强制重建/绕过保护的开关。
- 修改版本号、`knowledge_date`、旧版本拒绝规则时，必须补针对性测试。
- 不要把旧版本文件默认覆盖新版本文件，除非业务明确要求。
- 当前规则允许“版本号更低但 `knowledge_date` 更新”的正式知识库入库；如果 `knowledge_date` 也更旧，则默认拒绝。
- 同内容跳过、强制重建、旧数据清理、正式 markdown/pdf 资产更新都属于高风险路径。

相关测试优先看：

- `tests/test_brand_ai_knowledge_ingestion.py`
- `tests/test_brand_upload_task_behavior.py`
- `tests/test_attachment_preview_official_upload.py`

## 回调和重试

回调和重试逻辑优先走统一抽象，不要复制粘贴新的重试循环。

重点关注：

- 附件删除回调
- 附件确认回调
- 附件冲突回调
- 品牌完成回调
- 后台任务 callback audit

新增或修改回调时，优先复用 `knowledge_base/shared/callback_delivery.py`，并补充后台任务或 callback audit 测试。

## 高风险区域

改下面这些地方要特别小心，并补有针对性的测试：

- 上传任务状态流转
- `force_reingest` 传递
- 品牌 AI 知识库版本校验
- 附件删除后的回调 payload
- 附件确认 / 冲突处理回调
- 后台任务重试和审计
- 路由响应结构
- OSS key、document_id、full_knowledge_file_id、asset_id 的生成和落库
- Milvus/Qdrant 写入失败后的清理逻辑

如果一个改动会影响这些路径，先找对应测试，再实现；没有覆盖时补一个小而直接的测试。

## 常用验证命令

语法检查：

```bash
PYTHONPATH=. .venv/bin/python -m compileall -q knowledge_base tests
```

上传任务相关小回归：

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_upload_task_queue_coordinator.py \
  tests/test_upload_task_lifecycle.py \
  tests/test_brand_upload_task_behavior.py \
  tests/test_brand_facts_only_upload.py \
  -k "not slow"
```

核心回归：

```bash
PYTHONPATH=. .venv/bin/pytest \
  tests/test_upload_task_queue_coordinator.py \
  tests/test_knowledge_search_facade.py \
  tests/test_document_delete_behavior.py \
  tests/test_brand_facts_only_upload.py \
  tests/test_upload_task_lifecycle.py \
  tests/test_brand_upload_task_behavior.py \
  tests/test_attachment_preview_official_upload.py \
  tests/test_attachment_delete_behavior.py \
  tests/test_background_job_callback_audit.py \
  tests/test_brand_attachment_conflict_sessions.py \
  tests/test_brand_knowledge_request_defaults.py \
  tests/test_brand_knowledge_patch_apply.py \
  tests/test_brand_full_markdown_update.py \
  tests/test_brand_knowledge_routes.py \
  tests/test_knowledge_routes.py \
  tests/test_brand_routes.py \
  tests/test_brand_search_flow.py \
  tests/test_search_route.py \
  tests/test_search_application_service.py \
  -k "not search_facts_preserves"
```

提交或汇报前检查：

```bash
git diff --check
```

## 汇报要求

完成代码修改后，说明：

- 改了什么
- 主要文件
- 跑了哪些测试
- 是否还有风险或后续建议

如果没有运行测试，要明确说明原因。
