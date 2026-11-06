# 回调规则

最后校对日期: 2026-07-18

## 这份文档讲什么

这里说的"回调", 主要指:

- 系统向上游发送的 HTTP callback
- 以及 `upload_task_callbacks` 表里保存的回调审计记录

当前不是只有一种回调, 也不是只靠一个 `callback_type` 就能完全判断来源.

## 回调配置

当前品牌相关回调统一依赖:

- `BRAND_COMPLETION_CALLBACK_URL`
- `BRAND_COMPLETION_CALLBACK_TIMEOUT_SECONDS`

如果没有配置回调地址, 多数链路会:

- 不发送 HTTP callback
- 但内部流程本身仍可能成功

## 回调审计表

当前主要审计表:

- `upload_task_callbacks`

当前常见字段含义:

| 字段 | 含义 |
| --- | --- |
| `task_id` | 这次回调挂在哪个任务或来源标识上 |
| `callback_type` | 回调类型 |
| `callback_url` | 回调目标地址 |
| `request_payload_json` | 实际发送给上游的 JSON |
| `status` | 回调发送状态 |
| `retry_count` | 已重试次数 |
| `next_retry_at` | 下次重试时间 |
| `last_response_code` | 上次 HTTP 状态码 |
| `last_response_body` | 上次响应体 |
| `last_error_message` | 上次异常或失败原因 |
| `sent_at` | 最终成功发送时间 |

当前 `status` 常见值:

- `waiting`
- `pending`
- `retrying`
- `success`
- `failed`

## 当前主要 callback_type

### 1. `brand_knowledge_status`

当前主要用于:

- 附件冲突扫描会话进入 `waiting_user_input`
- 需要先通知上游"现在等用户确认"

典型来源:

- `BrandKnowledgeApplicationService`
- 附件冲突会话创建后, 如果存在待裁决冲突

### 2. `brand_knowledge_completed`

这是当前最核心、最常见的一类 completed 回调.

当前会被多条链路共用:

1. `/brands/upload`
2. `/knowledge/update` 触发正式知识库重建
3. `/brands/attachments/confirm` 新的 background job pipeline
4. 附件冲突确认会话最终完成
5. 部分旧确认链路兼容逻辑

所以:

- 看到 `brand_knowledge_completed` 只能说明"这是一条品牌知识完成回调"
- 不能只靠 `callback_type` 判断它到底来自哪条入口
- 对附件冲突会话来说, 这条 completed 回调既可能来自"用户确认冲突后继续生成", 也可能来自"扫描无冲突, 自动继续生成"

还要结合:

- `task_id`
- `request_payload_json.brand_code`
- `request_payload_json.knowledge_mete.version`
- 是否有 `knowledge_session_id`
- `task_id` 前缀是否像 `knowledge_update:`、`confirm:`、真实 upload task id 等

### 3. `brand_backfill_completed`

当前用于:

- 手工脚本 `scripts/backfill_brand_from_markdown.py`

特点:

- 不是线上上传接口自动发的
- 只有显式启用 `--callback` 或 `--callback-url` 才会发
- 也会把结果记到 `upload_task_callbacks`

### 4. `attachment_delete_completed`

当前用于:

- 品牌附件删除成功后的回调

特点:

- 回调里的 `knowledge` 会反映删除附件后的当前品牌知识快照
- 这里的"删除"现在是指:
  - 从 `brand_knowledge_json.attachments` 里移除
  - 不代表物理删除 OSS 或附件资产表记录
- 也会有失败重试逻辑

## 各条链路的当前回调口径

## 第一类: `/brands/upload` 主上传回调

核心代码:

- [knowledge_base/brand/application/callbacks.py](../../knowledge_base/brand/application/callbacks.py)

当前特点:

1. 先等 upload task、文件状态、正式知识库或结构化结果进入可判定状态
2. 再决定是否可以发 completed callback
3. 如果正式知识库 Markdown 还没准备好, 会进入 retry

补充:

- `/brands/upload` 这条旧 `document_summaries` 摘要链已经下线
- completed callback 也不再把“摘要是否生成”当成品牌主链路门禁

当前会遇到两种典型回调:

- `brand_knowledge_status`
- `brand_knowledge_completed`

### completed 回调里的 `knowledge`

当前 completed 回调里的 `knowledge` 来源不止一种:

1. 旧附件抽取结果格式化
2. 当前品牌结构化快照
3. 已生成好的最终 snapshot

但对上游来说, 目标口径是同一套消费格式.

## 第二类: `/knowledge/update` 触发的 completed 回调

核心代码:

- [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py)
- [knowledge_base/background_jobs/application.py](../../knowledge_base/background_jobs/application.py)

当前行为:

1. `/knowledge/update` 先更新结构化表
2. 如果本次有实质变更, 创建 `brand_knowledge_update_full_generation` background job
3. background job 生成下一版正式知识库
4. 完成后发送 `brand_knowledge_completed`

这里的关键规则是:

- completed 回调里的 `knowledge` 优先使用这次已经更新后的最新 snapshot
- 不是再回旧快照

## 第三类: `/brands/attachments/confirm` 回调

核心代码:

- [knowledge_base/brand_knowledge/application/attachment_flow.py](../../knowledge_base/brand_knowledge/application/attachment_flow.py)
- [knowledge_base/background_jobs/application.py](../../knowledge_base/background_jobs/application.py)

当前这条线会走新的 confirm background pipeline.

行为是:

1. confirm 接口先返回 `background_job_id`
2. background job 异步做正式知识库生成与结构化同步
3. 成功后发送 `brand_knowledge_completed`

注意:

- 这里 completed 回调的 `callback_type` 和 `/knowledge/update` 一样
- 所以必须结合 `task_id = confirm:...` 或 job 来源一起看

## 第四类: 附件冲突会话回调

核心代码:

- [knowledge_base/brand_knowledge/application/service.py](../../knowledge_base/brand_knowledge/application/service.py)

当前这条线分两步:

1. 有待裁决冲突时发 `brand_knowledge_status`
2. 全部确认并生成最终知识库后发 `brand_knowledge_completed`

也就是说:

- `brand_knowledge_status` 不只是"上传处理中"
- 现在它更明确地承载"等待用户确认冲突"这类状态通知

## 第五类: 手工 backfill 脚本回调

核心代码:

- [scripts/backfill_brand_from_markdown.py](../../scripts/backfill_brand_from_markdown.py)

当前行为:

- 成功时 `overall_status = completed`
- 失败时 `overall_status = failed`
- 回调类型固定是 `brand_backfill_completed`

当前这套脚本回调没有做复杂持久化重试调度:

- 会记录一次 pending / result
- 但不像主流程 background job 那样有完整的持久化重试队列

## 第六类: 附件删除回调

核心代码:

- [knowledge_base/service.py](../../knowledge_base/service.py)

当前行为:

- 从品牌知识附件列表移除成功后会重建当前品牌知识快照
- 再发送 `attachment_delete_completed`

## 为什么只看 `callback_type` 不够

因为现在确实有多条链路共用:

- `brand_knowledge_completed`
- `brand_knowledge_status`

所以要判断"这条回调是哪个接口发的", 当前更稳的方式是一起看:

1. `callback_type`
2. `task_id`
3. `request_payload_json`
4. 必要时再看关联的 `background_jobs` / `upload_tasks` / `brand_knowledge_sessions`

## 如何判断一条回调大概率来自哪条链路

### 看 `task_id`

常见模式:

- 普通 upload task id: 多半来自 `/brands/upload` 或 `/documents/upload`
- `knowledge_update:...`: 多半来自 `/knowledge/update`
- `confirm:...`: 多半来自 `/brands/attachments/confirm`
- `attachment_conflict:...`: 多半来自附件冲突会话
- `manual_brand_backfill...`: 多半来自手工 backfill 脚本

### 看 payload

几个特别有辨识度的字段:

- `knowledge_session_id`
- `knowledge_session_status`
- `knowledge_mete.version`
- `knowledge.attachment_products` 是否通过 `other_info` 镜像体现
- `overall_status`

## 回调里的 `knowledge` 当前统一目标

虽然不同链路的内部构造方式不同, 但当前对上游的统一目标是:

- 返回同一套品牌知识消费格式

其中:

- `knowledge.products` 看主产品白名单
- 附件新增产品副本通过 `other_info -> 附件解析新增产品` 体现
- `knowledge_mete` 反映当前正式知识库版本与 OSS 地址

## 调整回调规则时, 至少同步检查

1. 回调是哪条链路发的.
2. `callback_type` 有没有被多条链路共用.
3. completed 回调里的 `knowledge` 来自旧抽取结果, 还是最新 snapshot.
4. 失败后是否仍然需要重试, 重试是内存态还是持久化.
5. `upload_task_callbacks` 的审计记录是否还能唯一追到来源.
