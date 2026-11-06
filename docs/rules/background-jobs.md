# Background Job 规则

最后校对日期: 2026-10-09

## 这份文档讲什么

这里说的 background job, 指的是:

- MySQL `background_jobs` 表里的异步任务
- 以及 `BackgroundJobService` 驱动的 worker 队列

它和下面几类东西不是一回事:

- `upload_tasks`
- `brand_knowledge_sessions`
- `upload_task_callbacks`

但这些东西之间会互相引用和串联.

## 入口与核心代码

- 路由: [knowledge_base/api_app/routers/background_jobs.py](../../knowledge_base/api_app/routers/background_jobs.py)
- 服务: [knowledge_base/background_jobs/application.py](../../knowledge_base/background_jobs/application.py)
- 存储: [knowledge_base/stores/background_job_store.py](../../knowledge_base/stores/background_job_store.py)

查询接口:

- `GET /api/v1/background-jobs/{job_id}`

## 当前主要 job_type

| job_type | 当前用途 | 典型创建方 |
| --- | --- | --- |
| `upload_task_process` | 异步消费 upload task | `/documents/upload`、`/brands/upload` 任务入队后 |
| `brand_knowledge_update_full_generation` | `/knowledge/update` 后生成下一版正式知识库并回调 | `/api/v1/knowledge/update` |
| `brand_full_knowledge_refresh` | 按品牌合并消费 `knowledge_update` / `attachment_confirm` 审计变更, debounce 后生成正式知识库并回调 | `/knowledge/update`、`/brands/attachments/confirm` |
| `attachment_confirm_pipeline` | 新版附件确认全流程 | `/brands/attachments/confirm` |
| `attachment_confirm_full_generation` | 旧的附件确认正式知识库生成兼容任务 | 兼容路径 / 旧逻辑 |
| `attachment_conflict_resolution` | 附件冲突会话在冲突扫描后继续生成最终结果 | 附件冲突确认流 |

## 每种 job_type 现在在做什么

### 1. `upload_task_process`

当前作用:

- 真正执行 upload task 的后台消费

典型流程:

1. 接口创建 upload task
2. 创建 background job
3. worker 拉起处理
4. 最后更新 `upload_tasks` / `upload_task_files`

特点:

- `max_retries = 0`
- 更像一个单次后台执行器

### 2. `brand_knowledge_update_full_generation`

当前作用:

- `/knowledge/update` 已经改完结构化表后
- 异步生成下一版正式品牌 AI 知识库 Markdown / PDF
- 然后发 completed callback

特点:

- payload 会带 `structured_knowledge_markdown`
- payload 会带这次更新后的 `knowledge_snapshot`
- completed callback 优先回这次最新 snapshot

### 3. `brand_full_knowledge_refresh`

当前作用:

- 按品牌维度合并消费 `brand_knowledge_update_audits`
- 默认消费 `source_type in ('knowledge_update', 'attachment_confirm')` 的未生成变更
- 等同品牌一段时间内没有新增变更后, 再统一生成正式品牌 AI 知识库 Markdown / PDF
- 生成完成后发送带 `knowledge_mete` 的 `brand_knowledge_completed` 回调

延迟配置:

- `/knowledge/update` 和 `/brands/attachments/confirm` 都会读取 `brand_full_knowledge_refresh_delay_seconds`
- 环境变量是 `KB_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS`
- 默认值是 `300` 秒
- 配成 `0` 时表示不等待 debounce 窗口, 任务可以尽快进入可执行状态
- 配成非法值时, shared helper 会回退到默认 `300` 秒

这条任务的 `job_id` 固定按品牌复用:

- `bg:brand_full_knowledge_refresh:{brand_code}`

因此同品牌短时间内连续发生 `knowledge_update` 或 `attachment_confirm` 时, 不会创建多条 full refresh job, 而是更新同一条 job 的 `next_retry_at` 达到顺延效果.

### 4. `attachment_confirm_pipeline`

当前作用:

- 新版 `/brands/attachments/confirm` 异步执行整条确认流水线

典型内容:

- 读取 review 结果
- 回写结构化表
- 上传 confirmed Markdown 到 OSS
- 写 `brand_knowledge_update_audits`
- 顺延同品牌 `brand_full_knowledge_refresh`
- 发送一次轻量 completed callback

前端或调用方当前通常要拿:

- `background_job_id`
- 再去轮询 job 状态或 confirm result 接口

补充说明:

- 如果只想看这个确认任务本身的执行结果, 继续查 `GET /api/v1/brands/attachments/confirm/result/{job_id}`
- 如果想按品牌统一看“品牌 AI 知识库是否在生成”, 当前也可以查 `/api/v1/brands/knowledge-base/conflict-session/latest`
- 后者是展示态聚合接口, 不替代单个 job 的结果查询

### 5. `attachment_confirm_full_generation`

当前作用:

- 旧的附件确认正式知识库生成任务

当前主要意义:

- 保留兼容
- `get_attachment_confirm_result(...)` 现在仍然接受这类 job

### 6. `attachment_conflict_resolution`

当前作用:

- 附件冲突会话在冲突扫描之后
- 异步继续生成最终正式知识库与最终结构化结果

当前统一收口是:

- `status=waiting_user_input` 时, 用户提交裁决后进入这个 job
- `status=no_conflicts` 时, 系统自动以空裁决进入这个 job

因此它现在不只是"冲突确认后再生成", 也承担"无冲突时直接生成最终正式知识库"这条异步收口

这条线和 `brand_knowledge_sessions` 关系最紧:

- session 管当前会话状态
- background job 管真正的异步生成动作

## 当前状态流转

`background_jobs.status` 当前常见值:

- `waiting`
- `processing`
- `retrying`
- `success`
- `failed`

SQL 注释里还有 `canceled`, 但当前主逻辑里最常用的是前面 5 个.

### 当前含义

- `waiting`: 已入队, 等 worker 处理
- `processing`: worker 已锁住并开始执行
- `retrying`: 上次失败, 等 `next_retry_at` 到时再跑
- `success`: 任务成功完成
- `failed`: 达到最大重试次数后失败

## 当前重试规则

`BackgroundJobService` 当前统一使用这组延迟:

- 60 秒
- 120 秒
- 180 秒
- 300 秒

也就是:

- 第一次失败后 60 秒再试
- 再失败就继续按上面的延迟滚动

不是每类 job 都会无限重试.

## 去重与幂等

当前 `background_jobs` 有一个重要约束:

- `(job_type, source_id)` 唯一

效果是:

- 同一来源的同类 job 重复 enqueue 时, 更倾向于复用已有记录
- 不会无脑生成一堆重复任务

job_id 当前通常长这样:

- `bg:{job_type}:{source_id}`

### 已成功完成的 job 是否能被重新拉起

`upsert_job(...)` 里的两个参数语义要分开:

- `restart_completed`: 是否允许已经 `success` 的同源 job 重新置为 `waiting`
- `reopen_terminal`: 是否需要界面侧重新打开终端/面板

例如 `brand_full_knowledge_refresh` 是按品牌维度 debounce 的合并任务, 同一个 `brand_code` 后续可能不断产生新的 `knowledge_update` / `attachment_confirm` audit. 因此它需要:

- `restart_completed = true`
- `reopen_terminal = false`

这样新 audit 进入后, 旧的成功 refresh job 可以重新排队执行, 但不会因为后台合并生成主动打扰终端.

`brand_full_knowledge_refresh` 成功后仍会发送 `brand_knowledge_completed` 回调, callback 记录的 `task_id` 使用完整 job id:

- `bg:brand_full_knowledge_refresh:{brand_code}`

注意: 这个固定 job id 只用于按品牌 debounce、认领 audit、记录回调和让前端按品牌查询状态. 真正生成出来的品牌 AI 知识库文件写入 `brand_full_knowledge_files` 时, 会使用按批次派生的 `source_task_id`:

- `bg:brand_full_knowledge_refresh:{brand_code}:{knowledge_revision}:{batch_hash}`

其中 `batch_hash` 来自本轮消费的 audit 列表. 这样同一品牌后续再次触发合并生成时, background job 仍然复用同一条任务记录, 但生成文件不会因为复用固定 `source_task_id` 而命中"同一来源任务已存在不同内容"的保护.

生成正式品牌 AI 知识库时, `brand_full_knowledge_refresh` 会走专门的合并来源 prompt:

- `generate_brand_ai_knowledge_from_merged_sources`

这个 prompt 用于同时处理 `knowledge_update`、`attachment_confirm`、删除/收缩等多来源合并场景. 普通单次结构化更新仍走原来的 `generate_brand_ai_knowledge_from_structured_update` / `change` / `deletion` 分流.

## worker 当前怎么跑

当前 worker 模式大致是:

1. 从内存 queue 取 `job_id`
2. 把 DB 里的 job 标记成 `processing`
3. 按 `job_type` 找 handler
4. 成功则 `mark_success`
5. 失败则按重试规则 `mark_retrying` 或 `mark_failed`

应用重启时还会做一件事:

- 把 DB 里残留的 `processing` job 重置回 `waiting`
- 如果被重置的是 `brand_full_knowledge_refresh`, 同步释放它认领但尚未消费的 audit

这样能避免:

- 上次进程挂掉后任务永远卡死在 `processing`
- audit 已经被 claim 但因为进程中断而永远不再参与全量知识库生成

## 现在有哪些查询方式

### 通用查法

- `GET /api/v1/background-jobs/{job_id}`

返回内容包括:

- `job_id`
- `job_type`
- `source_type`
- `source_id`
- `status`
- `retry_count`
- `max_retries`
- `next_retry_at`
- `payload`
- `result`

### 附件确认专用查法

除了通用 job 查询, 当前还有一个更轻量的结果查法:

- `GET /api/v1/brands/attachments/confirm/result/{job_id}`

这条接口只接受:

- `attachment_confirm_pipeline`
- `attachment_confirm_full_generation`

如果 job 还没成功, 返回消息通常会落在:

- `waiting`
- `processing`
- `retrying`
- `failed`

## 当前谁该查 background job, 谁不该查

### 应该直接查 background job 的

1. `/knowledge/update`
   - 返回了 `background_job_id`
2. `/brands/attachments/confirm`
   - 返回了 `background_job_id`
3. 需要看异步正式知识库生成细节的时候

### 不应该只靠 background job 的

1. 附件冲突扫描会话当前状态
   - 重点应该查 `brand_knowledge_sessions`
   - 或 `/brands/knowledge-base/conflict-session/latest`
2. upload task 文件级处理进度
   - 重点应该查 `upload_tasks` / `upload_task_files`
   - 当前品牌主链路的 upload task 文件状态重点看 `status`、`file_role`、`facts_status`、正式知识库相关字段
   - 不再指望旧 `summary_status` / `summary_error`

也就是说:

- background job 更像"异步执行器状态"
- session / upload task 更像"业务流程状态"

## 与 `knowledge_markdown_status` / `status` 的关系

当前前端或调用方最容易混的是:

- background job 的 `status`
- conflict session 的 `status`
- `knowledge_markdown_status`

现在的推荐理解是:

- background job 的 `status` 是任务执行态
- conflict session 的 `status` 是业务会话态
- 如果某接口已经把二者映射成统一枚举, 前端优先看该接口自身定义的业务状态
- 对品牌页而言, `POST /api/v1/brands/knowledge-base/conflict-session/latest` 现在就是这样的统一展示态接口之一

## 常见排查路径

### `/knowledge/update` 之后迟迟没出正式知识库

先查:

1. `background_job_id`
2. `GET /api/v1/background-jobs/{job_id}`
3. 看 `job_type` 是否是 `brand_knowledge_update_full_generation`
4. 再看 `result.callback_result` 和 `last_error_message`

### `/brands/attachments/confirm` 一直没完成

先查:

1. confirm 返回的 `background_job_id`
2. `GET /api/v1/brands/attachments/confirm/result/{job_id}`
3. 必要时再查通用 background job 明细

### 附件冲突会话卡住

先看:

1. `brand_knowledge_sessions.status`
2. `/brands/knowledge-base/conflict-session/latest`
3. 如果状态已经进入最终生成阶段, 再看对应 `attachment_conflict_resolution` job

## 调整 background job 规则时, 至少同步检查

1. 新链路是否真的需要 `background_jobs`, 还是已有 `upload_tasks` / `session` 就够了.
2. `job_type` 是否会与旧逻辑重名.
3. 是否需要持久化重试.
4. 前端 / 调用方应该轮询哪个接口, 不能让一条业务线维护两套状态口径.
5. completed callback 的审计记录是不是也要跟着补.
