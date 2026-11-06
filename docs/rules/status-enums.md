# 状态枚举规则

最后校对日期: 2026-07-18

## 这份文档讲什么

当前系统里至少有 4 套容易混淆的状态:

1. `upload_tasks.status`
2. `background_jobs.status`
3. `brand_knowledge_sessions.status`
4. 回调 payload 里的
   - `overall_status`
   - `knowledge_markdown_status`
   - `knowledge_extraction_status`

这份文档的目的不是把它们强行说成一回事, 而是把:

- 谁是任务执行态
- 谁是业务会话态
- 谁是对上游暴露的消费态

讲清楚.

## 一句话总览

可以先用这张表抓住大方向:

| 状态字段 | 主要对象 | 当前含义 |
| --- | --- | --- |
| `upload_tasks.status` | 上传任务 | 整个上传任务是否完成 |
| `background_jobs.status` | 异步后台 job | 某个异步执行器现在跑到哪一步 |
| `brand_knowledge_sessions.status` | 附件冲突/知识会话 | 这条需要用户参与的业务流程当前停在哪 |
| `overall_status` | 对上游回调 | 这次品牌知识流程整体状态 |
| `knowledge_markdown_status` | 对上游回调 / session 返回 | 品牌知识 Markdown 这部分当前状态 |
| `knowledge_extraction_status` | 对上游回调 | 结构化抽取当前状态 |

## 第一类: `upload_tasks.status`

### 当前对象

- `/documents/upload`
- `/brands/upload`

### 当前角色

它描述的是:

- 一次上传任务整体跑没跑完
- 文件级处理是否都进入终态

它更偏:

- 上传任务态

而不是:

- 最终知识库业务态

### 当前使用建议

适合用它看:

- 任务有没有创建成功
- 文件是否都进入 `success / failed`

不适合只靠它看:

- 正式知识库是否已经生成
- 附件冲突会话是否等待用户确认

## 第二类: `background_jobs.status`

### 当前常见值

- `waiting`
- `processing`
- `retrying`
- `success`
- `failed`

### 当前角色

它描述的是:

- 某个异步 job 自己的执行态

比如:

- `/knowledge/update` 生成正式知识库的 job
- `/brands/attachments/confirm` 的确认 pipeline job
- `upload_task_process` 的后台消费 job

### 这套状态的正确理解

- `waiting`: 已入队, 还没开始跑
- `processing`: worker 已经接管
- `retrying`: 上次失败, 等下次重试
- `success`: job 本身跑完了
- `failed`: job 最终失败

### 当前使用建议

当接口返回了 `background_job_id` 时, 优先看它.

典型场景:

1. `/api/v1/knowledge/update`
2. `/brands/attachments/confirm`

## 第三类: `brand_knowledge_sessions.status`

### 当前常见值

当前业务代码里最常见的是:

- `running`
- `waiting_user_input`
- `no_conflicts`
- `completed`
- `failed`

SQL 注释里还有:

- `cancelled`

但现在前面 5 个是主流.

### 当前角色

它描述的是:

- 附件冲突扫描 / 冲突确认这类业务会话的流程态

这套状态和 background job 最大的差别是:

- `background_jobs.status` 说的是"某个异步执行器现在怎样"
- `brand_knowledge_sessions.status` 说的是"这条需要用户确认的业务流程现在怎样"

### 当前含义

- `running`: 正在扫描、整理或生成
- `waiting_user_input`: 现在停下来等用户确认冲突
- `no_conflicts`: 没有硬冲突, 可以直接进入后续生成
- `completed`: 会话已经收尾完成
- `failed`: 会话流程失败

## 第四类: 回调里的 `overall_status`

### 当前角色

它是:

- 对上游暴露的总状态

不同链路里, 它不一定来自同一来源, 但目标都是:

- 让上游看到这次品牌知识流程整体是完成、失败, 还是正在等确认

### 当前常见值

最常出现的是:

- `completed`
- `failed`
- `waiting_user_input`
- `no_conflicts`

在附件冲突等待回调里, 当前代码会把 session 状态直接映射给:

- `overall_status`
- `knowledge_session_status`
- `knowledge_markdown_status`

## 第五类: 回调里的 `knowledge_markdown_status`

这是现在最容易混的一类.

### 在不同链路里的当前含义

#### A. `/brands/upload` 主上传 completed 回调

这条线里它更偏:

- 最终品牌知识库 Markdown 生成状态

当前常见值包括:

- `waiting_user_input`
- `success`
- `failed`
- `skipped`

其中:

- 有附件但还没形成最终 Markdown 时, 早期可能是 `waiting_user_input`
- 已经生成正式 Markdown 时, 可能是 `success`

#### B. 附件冲突会话返回值

现在这条线已经做了统一:

- `knowledge_markdown_status = session.status`

也就是它会直接返回:

- `running`
- `waiting_user_input`
- `no_conflicts`
- `completed`
- `failed`

这是为了让前端和调用方不需要维护两套状态字典.

#### C. 附件冲突等待/完成回调

当前也按同样思路处理:

- 等待用户确认时:
  - `knowledge_markdown_status = waiting_user_input`
- 完成时:
  - `knowledge_markdown_status = completed`

#### D. `/knowledge/update` 这条线

这条线不是直接把 background job 状态原样塞进 completed 回调.

它的 completed 回调通常在最终生成完成后才发出, 所以最终 completed payload 里:

- `knowledge_markdown_status` 更像完成结果态

如果只是接口首响应:

- 应该看返回里的 `background_job_status`
- 而不是去猜最终 completed 回调里的字段

## 第六类: 回调里的 `knowledge_extraction_status`

### 当前角色

它描述的是:

- 结构化抽取这部分成功没成功

### 当前常见值

- `success`
- `failed`
- `skipped`

### 当前理解方式

- `success`: 当前结构化抽取已成功
- `failed`: 当前结构化抽取出错
- `skipped`: 这条链路这一步没有做, 或这次不需要做

## 当前推荐的状态判断顺序

### 场景 1: `/knowledge/update` 调完之后, 想知道正式知识库生成完没

优先看:

1. 接口首响应里的 `background_job_id`
2. `background_job_status`
3. `GET /api/v1/background-jobs/{job_id}`

不要优先去看:

- `brand_knowledge_sessions`

因为这条线核心是 background job, 不是会话.

### 场景 2: `/brands/attachments/confirm` 调完之后, 想知道确认任务完成没

优先看:

1. `background_job_id`
2. `GET /api/v1/brands/attachments/confirm/result/{job_id}`
3. 必要时再看 `GET /api/v1/background-jobs/{job_id}`

### 场景 3: 想知道附件冲突现在是不是在等用户确认

优先看:

1. `/brands/knowledge-base/conflict-session/latest`
2. `status`
3. `knowledge_markdown_status`

当前这条接口里:

- `knowledge_markdown_status` 已经和 `status` 使用同一套业务枚举
- 如果当前品牌没有冲突会话, 接口仍然返回 `200`, 只是返回一个空态对象:
  - `brand_code`
  - `brand_name`
  - `status = no_conflicts`
- 如果当前品牌存在最新冲突会话, 接口仍然返回完整会话对象, `status` 还是原来的业务态字典

### 场景 4: 想知道上游 callback 表达的最终业务状态

优先看:

1. `overall_status`
2. `knowledge_markdown_status`
3. `knowledge_extraction_status`

然后再结合:

- `task_id`
- `callback_type`
- `knowledge_session_status`

判断来源链路.

### 场景 5: 想看 `/api/v1/documents/upload-tasks` 里的文件级进度

优先看:

1. `status`
2. `file_role`
3. `facts_status`
4. `knowledge_markdown_oss_url` / `knowledge_pdf_oss_url`

当前规则:

- 品牌主链路的 upload task 文件状态已经不再返回 `summary_status` / `summary_error`
- 旧摘要链已经下线；如果数据库里还残留旧 summary 字段，那也不再属于当前品牌主流程推荐口径

## 当前最重要的统一认知

### 1. 不要把所有 status 混成一个字段

当前系统里:

- `background_jobs.status` 是执行态
- `brand_knowledge_sessions.status` 是业务会话态
- callback 里的状态是对上游暴露的消费态

### 2. 附件冲突会话这条线, `knowledge_markdown_status` 已经对齐 `status`

这意味着前端如果查:

- `/brands/knowledge-base/conflict-session/latest`

当前就可以按同一套字典理解:

- `running`
- `waiting_user_input`
- `no_conflicts`
- `completed`
- `failed`

### 3. `/knowledge/update` 首响应不要只盯 `knowledge_markdown_status`

这条线在接口首响应里更应该看:

- `background_job_id`
- `background_job_status`

因为它本质上是先创建异步生成任务.

## 调整状态规则时, 至少同步检查

1. 新状态属于执行态、业务态, 还是回调消费态.
2. 是否会让前端维护两套状态字典.
3. 返回同一接口时, 是否能把 `knowledge_markdown_status` 与主 `status` 对齐.
4. background job 和 session 是否被错误混用.
5. callback 的 `overall_status` 是否还能让上游直接理解.
