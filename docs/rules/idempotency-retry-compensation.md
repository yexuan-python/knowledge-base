# 幂等性 / 重试 / 补偿规则

最后校对日期: 2026-07-21

## 这份文档讲什么

这份文档不按单个接口拆, 而是汇总当前实现里几类最容易混淆的共享规则:

1. 同一个动作重复触发时, 是复用、跳过, 还是报错
2. 失败后谁会自动重试, 延迟是多少
3. 进程重启后哪些事情会被补跑
4. 当前所谓"补偿"主要补的是什么

它不是:

- 单个接口完整说明
- 业务字段口径文档

更适合拿来回答:

- 这条链路到底算不算幂等
- 失败之后系统会不会自己再跑一次
- 回调丢了之后有没有补发

## 入口与核心代码

- background jobs: [knowledge_base/background_jobs/application.py](../../knowledge_base/background_jobs/application.py)
- background job store: [knowledge_base/stores/background_job_store.py](../../knowledge_base/stores/background_job_store.py)
- 品牌完成回调协调: [knowledge_base/brand/application/callbacks.py](../../knowledge_base/brand/application/callbacks.py)
- 附件冲突会话回调: [knowledge_base/brand_knowledge/application/service.py](../../knowledge_base/brand_knowledge/application/service.py)
- 附件确认回调: [knowledge_base/brand_knowledge/application/attachment_flow.py](../../knowledge_base/brand_knowledge/application/attachment_flow.py)
- 附件删除回调: [knowledge_base/service.py](../../knowledge_base/service.py)
- 正式知识库入库: [knowledge_base/brand/application/ai_knowledge_ingestion.py](../../knowledge_base/brand/application/ai_knowledge_ingestion.py)
- 上传任务与回调审计: [knowledge_base/stores/upload_task_store.py](../../knowledge_base/stores/upload_task_store.py)

## 一句话总原则

当前实现里的"幂等"不是说所有链路重复调用都完全无副作用.

更准确地说:

- 有些链路通过唯一键复用已有记录
- 有些链路通过内容 hash 跳过重复写入
- 有些链路通过状态机拒绝重复提交
- 出现失败后, 补偿更多是"补跑 job / 补发 callback"
- 不是靠大范围回滚数据库来恢复

## 1. background job 的幂等与重试

### 当前唯一键规则

`background_jobs` 当前最重要的约束是:

- `(job_type, source_id)` 唯一

对应效果是:

- 同一来源的同类 job 再次 enqueue 时, 更倾向于复用原记录
- 不会无限插入重复 job

job_id 当前通常长这样:

- `bg:{job_type}:{source_id}`

### upsert 的真实行为

当前 `upsert_job(...)` 不是"无条件覆盖".

如果旧 job 已经:

- `status = success`

则再次 enqueue 同一 `(job_type, source_id)` 时:

- 会保留 `success`
- 不会重新改回 `waiting`

所以:

- 已成功的同源 job 默认不会被重复跑

### worker 重试规则

当前 background job 统一重试延迟是:

- 60 秒
- 120 秒
- 180 秒
- 300 秒

也就是:

- 第 1 次失败后 60 秒再试
- 第 2 次失败后 120 秒再试
- 第 3 次失败后 180 秒再试
- 第 4 次失败后 300 秒再试

超过 `max_retries` 后:

- job 状态变成 `failed`

### 进程重启后的补偿

应用重启时, `background_jobs` 还有一个关键补偿动作:

- 会把残留在 `processing` 的 job 重置回 `waiting`
- 如果被重置的是 `brand_full_knowledge_refresh`, 会释放它认领但尚未消费的 audit

这样可以补救:

- worker 处理中途崩溃
- job 永远卡在 `processing`
- audit 已 claim 但未 consumed, 后续生成永远扫不到

所以 background job 的补偿主策略是:

- "重置成可再次调度"

不是:

- "回滚已经写过的业务数据"

## 2. 上传任务层的当前重复语义

### `/documents/upload` 不是所有重复都算成功复用

当前上传层面对重复内容的处理分成两类:

1. 上传前重复
2. 入库时重复

### 上传前重复

`document_registry` 预占阶段如果发现同类文件已存在, 当前可能直接报:

- `发现相同文件已存在，不能重复上传`

这类更像:

- 拒绝重复请求

不是:

- 静默复用旧记录

### 正式知识库入库时的内容去重

正式知识库文件进入 `BrandAiKnowledgeIngestionService.ingest_upload_task_file(...)` 后, 还会再做一次内容级幂等:

1. 先把源文件解析成规范化 Markdown
2. 计算 `content_hash`
3. 查 `brand_full_knowledge` 里同品牌是否已有相同 `content_hash`

如果找到相同内容且:

- `force_reingest = false`

则当前不会报错, 而是直接:

- 把 ingestion job 标成 `skipped`
- 返回已有 `document_id`
- 返回已有 `full_knowledge_file_id`
- 返回已有 Markdown OSS 地址

因此真实语义是:

- 同内容的正式知识库上传默认是"跳过并复用旧结果"
- 不是重复再写一版

### 正式知识库入库的半成功重试

正式知识库入库如果在写入 `brand_full_knowledge_files` 后、写 Milvus / facts / promote latest 前失败, 后台 job 重试时会按:

- `brand_code`
- `source_task_id`
- `file_name`

查找已有的正式知识库文件记录.

如果找到同来源同文件记录:

- 复用已有 `full_knowledge_file_id`
- 复用已有 `revision_no`
- 复用已有 `document_id`
- 继续执行后续 OSS / Milvus / facts / promote latest 步骤

如果已有记录带 `content_hash`, 且本次解析出的 `content_hash` 不一致:

- 直接报错
- 不静默覆盖旧记录

所以这类重试不是生成新修订号, 而是恢复同一个来源任务未完成的入库流水线.

### 版本过旧的处理

如果文件名里的版本号小于当前品牌最新版本, 且:

- `force_reingest = false`

当前直接报:

- `知识库版本过旧`

所以:

- "同内容"是跳过
- "旧版本"是拒绝

这是两套不同规则.

### `force_reingest` 的当前作用

`force_reingest = true` 时, 当前主要会放开两类限制:

1. 允许旧版本继续入库
2. 遇到相同内容时不再默认 `skipped`

但它不等于:

- 自动删除旧版本
- 自动清理旧 facts
- 自动重置所有上下游任务

## 3. 附件冲突会话的幂等规则

这条线当前有两层幂等:

### 第一层: 会话创建幂等

同一个 `source_task_id` 创建附件冲突会话时:

- 若已有最新会话且 `status != failed`
- 直接返回旧会话

所以:

- 重复点开始扫描, 通常拿到的是同一个 `session_id`

### 第二层: 最终生成 job 幂等

附件冲突最终生成 job:

- `job_type = attachment_conflict_resolution`
- `source_id = session_id`

因此:

- 同一会话重复 enqueue, 会复用同一 background job 记录

### 重复提交裁决为什么通常会失败

提交裁决成功后, session 会立刻变成:

- `status = running`
- `current_round = round_no + 1`

所以下一次再拿同样的 `session_id + round_no` 提交时, 通常会被挡在:

- 状态不再是 `waiting_user_input` / `no_conflicts`
- 或 `round_no` 已不匹配

因此它的幂等不是"第二次提交返回同样成功结果", 而是:

- 状态机阻止重复提交

## 4. completed callback 的幂等与防重

### 品牌主上传 completed callback

`BrandCallbackCoordinator.maybe_finalize_task_callback(task_id)` 当前有两层防重:

1. 如果该 `task_id` 的 `brand_knowledge_completed` 已经 `success`
   - 直接返回成功
2. 如果同一个 `task_id` 已在 `runtime.inflight_brand_callbacks`
   - 当前调用直接返回 `False`

所以:

- 它既防已完成重复发送
- 也防同一时刻并发生成两次 payload

这也是当前 `/brands/upload` completed 回调最关键的并发防抖点之一.

### callback 审计表当前怎么复用

`upload_task_callbacks` 当前 `(task_id, callback_type)` 是唯一维度.

因此:

- 同一个任务、同一种回调类型, 不会无限新增审计行
- 主要是持续更新同一行的状态、重试次数和最近响应

## 5. 各类 callback 的当前重试规则

当前系统里不止一套 callback 重试延迟.

### `/brands/upload` 主完成回调

重试延迟:

- 60 秒
- 120 秒
- 180 秒

触发条件包括:

- HTTP 非 2xx
- 生成正式知识库还没准备好

这条线的特别之处是:

- `FullMarkdownNotReadyError` 也会把 callback 行改成 `retrying`
- 说明"业务还没就绪"同样用 callback 重试机制来补

### 附件冲突会话 callback

包括:

- `brand_knowledge_status`
- `brand_knowledge_completed`

当前重试延迟:

- 60 秒
- 120 秒
- 180 秒

callback task_id 当前分别长这样:

- `attachment_conflict:waiting:{session_id}`
- `attachment_conflict:completed:{session_id}`

### 附件删除 callback

`callback_type`:

- `attachment_delete_completed`

当前重试延迟:

- 60 秒
- 120 秒
- 180 秒

### 附件确认 callback

附件确认链路当前是单独一套更短的延迟:

- 6 秒
- 12 秒
- 18 秒

callback task_id 当前长这样:

- `confirm:{draft_id}:{review_id}`

所以不要把它和品牌主上传回调的 60/120/180 秒规则混为一谈.

## 6. callback 失败后的当前补偿方式

这几条 callback 的共同点是:

1. 失败后先把 `upload_task_callbacks.status` 改成 `retrying`
2. 写入:
   - `retry_count`
   - `next_retry_at`
   - `last_response_code`
   - `last_response_body`
   - `last_error_message`
3. 运行时在内存里调度一次重试协程
4. 如果进程重启, 再从数据库把到期的 `retrying` callback 捞起来补跑

所以 callback 的补偿当前主要分两层:

1. 进程还活着时的内存调度
2. 进程重启后的持久化重试恢复

### 什么时候会真正变成 `failed`

当重试次数超过当前这条 callback 的最大重试轮次后:

- 状态才会落成 `failed`
- `next_retry_at` 清空

## 7. 运行时防重复调度规则

除了 DB 持久化状态, 几条 callback 还都会配一个运行时 `set` 防止同一个来源被重复 schedule:

- `scheduled_brand_callback_retries`
- `scheduled_attachment_conflict_callback_retries`
- `scheduled_attachment_confirm_callback_retries`
- `scheduled_attachment_delete_callback_retries`

作用是:

- 同一个 callback task_id 如果已经挂了一个重试协程
- 当前进程内不会再多挂一份

因此:

- DB 负责跨进程恢复
- runtime `set` 负责单进程内防重

## 8. 当前的"补偿"主要不是回滚

这套系统当前说的补偿, 更多是下面几类:

1. background job 重置 `processing -> waiting`
2. callback 失败后的补发
3. 进程重启后重新 schedule 到期重试
4. 正式知识库未准备好时延后重试 callback

而不是:

1. 自动撤销已经落库的品牌结构化更新
2. 自动删除已经成功写入的 OSS 文件
3. 自动回滚已经成功写入的 facts / 向量

所以排障时不要默认存在"全链路事务回滚".

## 9. 附件临时 facts 的当前补偿边界

附件冲突扫描会先写:

- `fact_scope = attachment_temp`

这批临时 facts 的清理当前是:

- 最终正式知识库成功生成后, best effort 清理

也就是说:

- 它不是一个严格事务内清理
- 清理失败当前也不会把主流程整体回滚

因此如果看到:

- session 已完成
- 但临时 facts 还残留

更像是清理补偿没跑完, 不是主流程必然失败.

## 10. 哪些行为算"复用旧结果", 哪些算"拒绝重复"

### 当前更偏复用旧结果的

1. 同 `(job_type, source_id)` 的 background job enqueue
2. 同品牌相同 `content_hash` 的正式知识库入库
3. 同 `task_id` 的有效附件冲突会话创建
4. 已成功发送过的品牌 completed callback

### 当前更偏拒绝重复的

1. 版本过旧且未 `force_reingest` 的正式知识库上传
2. 冲突会话在错误轮次重复提交裁决
3. 状态已离开 `waiting_user_input` / `no_conflicts` 后再次提交裁决
4. 上传前被 `document_registry` 判成重复的文件

## 11. 当前排查建议

如果你怀疑"系统是不是重复跑了 / 为什么没重试 / 为什么没补发", 优先查:

1. `background_jobs`
   - 看 `job_type`
   - 看 `source_id`
   - 看 `status`
   - 看 `retry_count`
   - 看 `next_retry_at`
2. `upload_task_callbacks`
   - 看 `(task_id, callback_type)` 是否只有一行
   - 看 `status`
   - 看 `retry_count`
   - 看 `last_error_message`
3. `brand_knowledge_sessions`
   - 看 `source_task_id`
   - 看 `status`
   - 看 `current_round`
4. `brand_full_knowledge`
   - 看是否已存在相同 `content_hash`
   - 看版本号是否比上传文件更新

## 调整这组规则时, 至少同步检查

1. [background-jobs.md](./background-jobs.md) 里的重试与幂等描述有没有变.
2. [callbacks.md](./callbacks.md) 里的各类 callback 状态与来源有没有变.
3. [conflict-session-lifecycle.md](./conflict-session-lifecycle.md) 里的会话复用和提交边界有没有变.
4. [brand-ai-knowledge-ingestion.md](./brand-ai-knowledge-ingestion.md) 里的版本与重复内容处理有没有变.
5. [error-cases.md](./error-cases.md) 里是否需要补新的重试失败 / 幂等误判案例.
