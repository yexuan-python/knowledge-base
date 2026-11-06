# 附件冲突会话生命周期规则

最后校对日期: 2026-07-21

## 这份文档讲什么

这里说的"附件冲突会话", 指的是:

- `brand_knowledge_sessions` / `brand_knowledge_session_rounds` 里的 `session_kind = attachment_conflict`
- 以及下面 3 条接口共享的一套状态机:
  - `POST /api/v1/brands/knowledge-base/conflict-sessions`
  - `POST /api/v1/brands/knowledge-base/conflict-session/latest`
  - `POST /api/v1/brands/knowledge-base/conflict-sessions/resolutions`

它不是:

- `attachment preview / confirm` 草稿链路
- `background_jobs` 本身
- `/knowledge/update`

但它会和这些能力联动.

## 入口与核心代码

- 路由: [knowledge_base/api_app/routers/brand_knowledge.py](../../knowledge_base/api_app/routers/brand_knowledge.py)
- 会话服务: [knowledge_base/brand_knowledge/application/service.py](../../knowledge_base/brand_knowledge/application/service.py)
- 会话存储: [knowledge_base/stores/brand_knowledge_session_store.py](../../knowledge_base/stores/brand_knowledge_session_store.py)
- background job: [knowledge_base/background_jobs/application.py](../../knowledge_base/background_jobs/application.py)
- 顶层状态补全: [knowledge_base/service.py](../../knowledge_base/service.py)

## 这条链路的当前目标

当前实现里, 这条链路专门处理:

1. 从普通附件上传任务里读取可用附件
2. 扫描是否存在需要人工裁决的硬冲突
3. 有冲突时暂停在 `waiting_user_input`
4. 无冲突时直接异步继续生成最终正式知识库
5. 有裁决后异步生成最终正式知识库并回写结构化结果

所以它不是一个"多轮聊天机器人", 而是一条:

- 扫描
- 等裁决或自动跳过
- 最终生成

的定向工作流.

## 1. 创建会话规则

入口:

- `POST /api/v1/brands/knowledge-base/conflict-sessions`

请求核心字段:

- `task_id`: 必填, 指向一条普通附件上传任务
- `initial_message`: 可选; 不传时使用默认提示语

### 会先做的校验

当前会先验证:

1. 依赖是否初始化完成
2. `task_id` 非空
3. 对应 `upload_task` 存在
4. `task_type` 不能是 `brand_ai_knowledge_upload`
5. 任务 metadata 里能拿到 `brand_code` 和 `brand_name`
6. `brand_code` 对应品牌存在
7. 任务里的 `brand_name` 必须和品牌主数据一致
8. 任务下必须存在 `file_role = attachment` 且 `status = success` 的文件
9. 附件资产里必须能读出 Markdown 源

所以:

- 这条接口只接受"普通附件上传任务"
- 正式知识库文件上传任务不能起冲突会话

### 源文档当前怎么装载

当前会优先从 `brand_attachment_assets` 取:

- 已缓存的 `parsed_markdown`
- 或 `fulltext_key` 对应的 converted Markdown
- 再不行才回退到 OSS 原文件并现场解析

最终每个源文档会收敛成:

- `document_id`
- `asset_id`
- `original_filename`
- `source_url`
- `oss_url`
- `subcategory`
- `source_role = attachment_asset`
- `markdown_text`

### 临时 facts 当前会怎么处理

如果当前任务能解析出 `brand_code`, 会先把附件内容同步成:

- `brand_knowledge_facts.fact_scope = attachment_temp`
- 向量库里的临时 facts

这批临时 facts 的用途是:

- 让附件扫描阶段的检索或补充信息更完整

它不是最终正式知识库 facts.

## 2. 创建时的幂等规则

这条接口当前有一个很重要的复用规则:

- 会先查 `get_latest_by_source_task_id(source_task_id=task_id, session_kind="attachment_conflict")`

如果查到的最新会话:

- `status != failed`

则不会新建会话, 直接返回现有会话.

因此当前真实语义是:

- 同一个 `task_id` 正常情况下只有一条"有效中的"附件冲突会话
- 只有旧会话已经 `failed` 时, 才允许重新创建一条新会话

这意味着:

- 重复点"开始扫描"通常拿到的是同一条会话
- 不是每次都会新生成一个 `session_id`

## 3. 首轮扫描规则

创建新会话后, 系统会立即:

1. 先落一条 `status = running`、`current_round = 1` 的 session
2. 调 `scan_brand_knowledge_conflicts(...)`
3. 把返回值规范化后写入 round 1

当前 round 1 的 `stage` 固定是:

- `attachment_initial`

### 扫描结果如何归一化

当前归一化规则是:

1. 只要 `conflicts` 里还有有效冲突, 最终状态强制是 `waiting_user_input`
2. 没有冲突且模型显式返回 `status = no_conflicts`, 最终状态才是 `no_conflicts`
3. 其他情况回落到 `running`
4. `auto_merged` 会被单独保留
5. `conflict_markdown` 会按冲突列表重新生成

所以:

- `status = waiting_user_input` 的判断优先级最高
- 不是完全信任模型原始 `status`

### external enrichment 的当前角色

如果品牌产品依赖已初始化, 扫描前还会尝试基于附件内容构造补充 Markdown 源.

当前补充源:

- 只作为 `external_enrichment`
- 用于辅助扫描和自动消解
- 不能改变附件本身是主来源这一点

## 4. 当前状态机

`brand_knowledge_sessions.status` 在这条链路里当前常见值是:

- `running`
- `waiting_user_input`
- `no_conflicts`
- `completed`
- `failed`

SQL 迁移里还写过:

- `cancelled`

但这条附件冲突链路当前主逻辑基本没有走它.

### 每个状态当前代表什么

- `running`: 会话已创建, 正在扫描或正在异步生成最终正式知识库
- `waiting_user_input`: 扫描发现硬冲突, 等用户提交裁决
- `no_conflicts`: 扫描确认没有待人工裁决冲突, 准备自动继续
- `completed`: 最终正式知识库已生成并完成落库
- `failed`: 扫描或最终生成阶段失败

## 5. `round_no` 的当前规则

当前不是任意多轮对话, 而是相对固定的两段式轮次:

1. `round_no = 1`
   - 扫描附件
   - 产出 `conflicts` / `auto_merged` / `scan_summary`
2. 用户提交裁决后
   - session 先被推进到 `current_round = 2`
   - 然后异步执行最终生成 job
3. 生成成功后
   - 会写一条 `round_no = 2` 的 `attachment_finalize`

因此当前实现里:

- 提交裁决时, 请求体里的 `round_no` 必须等于会话当前 `current_round`
- 一旦提交成功, `current_round` 会立即递增
- 同一轮不能反复提交

## 6. 无冲突时的自动继续规则

如果首轮扫描结果是:

- `status = no_conflicts`

当前不会停在这里等用户确认, 而是立刻内部调用:

- `submit_attachment_conflict_resolutions(session_id, round_no=1, resolutions=[], force_reingest=False)`

效果是:

1. 会话状态从 `no_conflicts` 立刻改成 `running`
2. `current_round` 从 `1` 变成 `2`
3. 创建 `attachment_conflict_resolution` background job
4. 最终正式知识库改为异步生成

所以:

- `no_conflicts` 更像一个瞬时中间状态
- 对外常常更快看到的是 `running`

## 7. 提交裁决规则

入口:

- `POST /api/v1/brands/knowledge-base/conflict-sessions/resolutions`

请求核心字段:

- `session_id`
- `round_no`
- `resolutions`
- `force_reingest`

### 当前允许提交的前提

只有同时满足下面条件才允许提交:

1. 会话存在
2. `session_kind = attachment_conflict`
3. 当前 `status` 属于 `waiting_user_input` 或 `no_conflicts`
4. 请求 `round_no` 等于会话当前 `current_round`
5. 会话源文档还在
6. 还能重新装载出 Markdown 源

### `resolutions` 当前允许为空

空裁决是合法的, 典型场景就是:

- 扫描没有硬冲突
- 系统自动继续生成

所以:

- `resolutions = []` 不代表异常
- 需要结合当前会话状态一起理解

### 提交后会发生什么

提交成功时当前会立即:

1. 把 `resolution_history_json` 追加一条 `{round_no, resolutions}`
2. 把 session 改成:
   - `status = running`
   - `current_round = round_no + 1`
3. 清空当前 `conflicts`
4. 写入"正在生成最终正式知识库"的 assistant message
5. enqueue 一个 `attachment_conflict_resolution` background job

返回给调用方时:

- `knowledge_markdown_status` 会直接被标成 `running`

## 8. `force_reingest` 的当前真实语义

`force_reingest` 不影响:

- 首轮冲突扫描
- 会话是否复用
- 冲突裁决本身

它只会一路透传到最终正式知识库入库阶段.

当前主要影响两类判断:

1. 如果生成出来的最终 Markdown 和历史正式知识库内容完全相同
   - 默认会 `skipped`
   - 传 `force_reingest = true` 才强制重建
2. 如果最终写入版本号比当前最新版本更旧
   - 默认报版本过旧
   - 传 `force_reingest = true` 才允许继续

所以:

- `force_reingest` 是最终入库层的覆盖开关
- 不是会话层的"强制重试"

## 9. 最终生成 job 的当前规则

真正生成最终正式知识库的是:

- `job_type = attachment_conflict_resolution`

它的 `source_id` 当前固定取:

- `session_id`

所以这类 job 当前按 session 幂等.

### job 执行时会做什么

当前大致顺序是:

1. 重新取 session 和源文档
2. 读取:
   - `history_resolutions`
   - `current_resolutions`
   - `auto_merged`
3. 调 `generate_brand_knowledge_full_markdown(...)`
4. 要求必须产出 `final_markdown`
5. 基于最终 Markdown 构造结构化 snapshot
6. 生成并入库正式知识库 Markdown / PDF
7. 回写结构化快照
8. 清理 `attachment_temp` facts
9. 更新 session 为 `completed`
10. 发送 completed callback

### 最终 round 当前怎么记

最终生成成功后, 当前会写一条:

- `round_no = generation_round_no`
- `stage = attachment_finalize`

也就是:

- 首轮扫描是 `attachment_initial`
- 最终落库是 `attachment_finalize`

## 10. 失败时的当前行为

### 扫描阶段失败

创建会话后的首轮扫描如果报错:

- session 会被更新成 `failed`
- `current_round` 保持在 `1`
- assistant message 会写成"附件冲突扫描会话创建失败"

### 最终生成阶段失败

`attachment_conflict_resolution` job 里如果报错:

- session 会被更新成 `failed`
- `current_round` 保持在生成轮次
- assistant message 会写入具体失败原因
- background job 自身再按 background job 统一重试规则处理

注意:

- 会话一旦 `failed`, 旧 session 不会重新回到 `waiting_user_input`
- 想重新从原任务发起扫描, 当前做法是重新创建一条新 session

## 11. latest 查询规则

入口:

- `POST /api/v1/brands/knowledge-base/conflict-session/latest`

请求核心字段:

- `brand_code`: 必填
- `brand_name`: 可选; 传了就会校验和 `brand_code` 是否一致

### 当前查找方式

当前会先校验:

1. `brand_code` 非空
2. 品牌存在
3. 如果传了 `brand_name`, 必须和品牌主数据一致

然后查:

- `get_latest_by_brand_code(brand_code, session_kind="attachment_conflict", preferred_statuses=[...])`

当前 `preferred_statuses` 是:

- `waiting_user_input`
- `running`
- `no_conflicts`
- `failed`
- `completed`

但注意:

- 这不是按这个顺序做业务优先级排序
- 只是先用这组状态过滤
- 真正返回的还是 `updated_at DESC, id DESC` 的最新一条

因此真实规则更准确地说是:

- "从附件冲突会话里取最近更新的一条, 状态限定在这组常见状态里"

### 查不到时的当前行为

查不到会话时:

- service 返回 `None`
- 路由层返回 `200`
- payload 当前为:

```json
{
  "brand_code": "100111",
  "brand_name": "校园及第",
  "status": "no_conflicts"
}
```

### 正常返回示例

当品牌存在最新冲突会话时, 当前仍然返回完整会话对象, 例如:

```json
{
  "session_id": "bks_20260721_001",
  "brand_code": "100111",
  "brand_name": "校园及第",
  "status": "waiting_user_input",
  "knowledge_markdown_status": "waiting_user_input",
  "round_no": 1,
  "session_kind": "attachment_conflict",
  "source_task_id": "4611ad61-1039-480d-afbc-eb907dba588b",
  "assistant_message": "检测到 2 处冲突，请先确认。",
  "source_documents": [],
  "conflicts": [],
  "conflict_markdown": null,
  "scan_summary": "共发现 2 处硬冲突",
  "auto_merged": [],
  "final_markdown": null,
  "final_oss_key": null,
  "final_filename": null,
  "final_full_knowledge_file_id": null,
  "final_document_id": null,
  "knowledge_oss_url_md": null,
  "knowledge_oss_url_pdf": null
}
```

## 12. `knowledge_markdown_status` 的当前解释

这条链路里最容易误读的字段就是:

- `status`
- `knowledge_markdown_status`

在 `BrandKnowledgeApplicationService.get_knowledge_session(...)` 里:

- 默认 `knowledge_markdown_status = session.status`

但在顶层 `KnowledgeBaseService.get_latest_brand_attachment_conflict_session(...)` 里:

- 会再额外查最新 background job
- 并用 job 状态覆盖 `knowledge_markdown_status`

当前覆盖逻辑是:

1. 先查 `attachment_conflict_resolution`
2. 再查 `brand_knowledge_update_full_generation`
3. 如果 job 状态是 `waiting` / `processing` / `retrying`
   - 返回 `knowledge_markdown_status = running`
4. 如果 job 状态是 `success`
   - 返回 `completed`
5. 如果 job 状态是 `failed`
   - 返回 `failed`
6. 否则回退到 session 自身 `status`

所以:

- `status` 更偏会话状态
- `knowledge_markdown_status` 更偏"最新正式知识库生成动作现在怎么样了"

## 13. 回调规则

这条链路当前会发两类回调:

1. 扫描发现待裁决冲突时
   - `callback_type = brand_knowledge_status`
   - `overall_status = waiting_user_input`
2. 最终正式知识库完成时
   - `callback_type = brand_knowledge_completed`
   - `overall_status = completed`

并且:

- "无冲突自动继续生成"这条线最后也会发 `brand_knowledge_completed`
- 所以 completed 回调不等于"用户一定手工裁决过"

## 14. 当前排查建议

如果你怀疑会话生命周期没按预期跑通, 优先看:

1. `brand_knowledge_sessions.status`
2. `brand_knowledge_sessions.current_round`
3. `brand_knowledge_sessions.resolution_history_json`
4. `brand_knowledge_session_rounds.stage`
5. `background_jobs` 里 `attachment_conflict_resolution` 的状态
6. `upload_task_callbacks` 里:
   - `brand_knowledge_status`
   - `brand_knowledge_completed`

## 调整这条规则时, 需要同步检查

1. [background-jobs.md](./background-jobs.md) 里 `attachment_conflict_resolution` 的描述有没有变.
2. [callbacks.md](./callbacks.md) 里附件冲突会话回调口径有没有变.
3. [status-enums.md](./status-enums.md) 里 session / background job 状态说明有没有变.
4. [error-cases.md](./error-cases.md) 里相关报错文案和排查路径要不要补.
