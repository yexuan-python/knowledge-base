# 附件预解析与确认链路规则

最后校对日期: 2026-10-09

## 入口与范围

这是一条独立于 `/api/v1/brands/upload` 的两段式链路.

接口入口:

- `POST /api/v1/brands/attachments/preview-parse`
- `POST /api/v1/brands/attachments/confirm`
- `GET /api/v1/brands/attachments/confirm/result/{job_id}`
- `POST /api/v1/brands/attachments/review-changes`

主实现:

- [knowledge_base/api_app/routers/brand_knowledge.py](../../knowledge_base/api_app/routers/brand_knowledge.py)
- [knowledge_base/brand_knowledge/application/attachment_flow.py](../../knowledge_base/brand_knowledge/application/attachment_flow.py)
- [knowledge_base/brand_knowledge/application/service.py](../../knowledge_base/brand_knowledge/application/service.py)

## 这条链路解决的问题

目标不是"原始附件直接自动入最终库", 而是:

1. 先把附件解析成可编辑初稿
2. 允许前端或人工修改
3. 确认后再作为最终知识源正式入库

## preview-parse 阶段规则

当前行为:

- 输入品牌信息和附件列表
- 先解析附件, 生成草稿内容
- 草稿结果不是最终知识真相
- 当前更接近"候选内容"
- `candidate_snapshot` 只允许包含本次从附件内容中实际解析/抽取出来的字段
- 请求入参里的 `brand_name`、`attachments` 只是上下文和待解析文件列表, 不能当作附件解析结果回填到 `candidate_snapshot`
- 如果所有有效附件均下载失败或解析失败, `/brands/attachments/preview-parse` 仍返回 `200`, 但 `candidate_snapshot` 和 `field_labels` 都为空, 前端不得进入 `review-changes`
- 如果附件下载失败、解析失败, 或解析后没有抽出任何有效内容, 响应里的 `candidate_snapshot` 必须是 `{}`, `field_labels` 也必须是 `{}`

当前特点:

- 适合需要人工审稿的品牌附件场景
- 不要求原始附件抽取结果直接成为最终结构化结果

## confirm 阶段规则

当前确认后会做几类事情:

1. 读取 `review-changes` 阶段缓存的结构化确认结果
2. 调用 `update_knowledge` 把确认后的结构化内容写回 `brands`、`brand_products`、`brand_knowledge_json`
3. 将确认后的附件 Markdown 以 `{brand_name}-{draft_id}-{review_id}-confirmed-knowledge.md` 上传到 OSS
4. 在 `brand_knowledge_update_audits` 记录 `source_type=attachment_confirm`、`source_task_id=confirm:{draft_id}:{review_id}` 和 `source_oss_key`
5. 按配置顺延同品牌 `brand_full_knowledge_refresh` 后台任务
6. 立即发送一次 `brand_knowledge_completed` 回调, `knowledge` 只包含本次 confirm 有变化的字段, 不带 `knowledge_mete`
7. `brand_full_knowledge_refresh` 真正生成正式 AI 知识库后, 再发送带 `knowledge_mete` 的完成回调

`confirm` 不再直接生成下一版正式 AI 知识库. 正式 `【品牌名】品牌AI知识库_Vx_日期.md/.pdf` 由品牌级 `brand_full_knowledge_refresh` 统一生成; 它默认消费同品牌未生成的 `source_type in ('knowledge_update', 'attachment_confirm')` 审计变更. 如果延迟窗口内又有新的 `knowledge_update` 或 `attachment_confirm`, refresh job 会被重新顺延.

延迟窗口由统一配置控制:

- 配置字段: `brand_full_knowledge_refresh_delay_seconds`
- 环境变量: `KB_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS`
- 默认值: `300` 秒
- 共同使用方: `/api/v1/knowledge/update` 和 `/api/v1/brands/attachments/confirm`

第一次 confirm 回调复用 `brand_knowledge_completed` 类型是为了兼容上游已有协议, 但语义是“附件确认变更已经写回结构化知识库”. 它不能带完整品牌快照, 也不能带正式 AI 知识库 MD/PDF 地址. 未变化的 section 不应出现在 `knowledge` 中, 避免上游把空对象或空数组误当成清空指令.

## `brand_knowledge_json` 写入规则

当前这条链路会直接写 `brand_knowledge_json`, 包括但不限于:

- 结构化知识分区
- `attachment_products`
- `attachments`

因此:

- 这条链路是 `brand_knowledge_json` 的重要写入来源之一
- 它和 `/brands/upload` 一样, 都会直接影响结构化知识分区

## 附件处理规则

`preview-parse` 阶段:

- 只做预解析和草稿生成
- 不写 MySQL 正式结构化表
- 不写 Milvus
- 不发 completed 回调

`confirm` 阶段:

- 会把确认后的 `attachments` 作为正式附件列表写回 `brand_knowledge_json.attachments`
- 新增附件会按普通附件处理:
  - 下载远程文件
  - 上传原文件到 OSS
  - 写入 `brand_attachment_assets`
- 但不会解析成附件全文 Markdown 再入文档库
- 不会抽 facts
- 不会入 Milvus

## 状态查看建议

如果你是在看单个确认任务的执行结果:

- 用 `GET /api/v1/brands/attachments/confirm/result/{job_id}`
- 这个接口仍然是 `attachment_confirm_pipeline` / `attachment_confirm_full_generation` 的正式结果查询入口

如果你是在看品牌页统一展示“这个品牌的品牌 AI 知识库是否在生成”:

- 可以直接看 `POST /api/v1/brands/knowledge-base/conflict-session/latest`
- 当前实现会把 `attachment_confirm_pipeline`、`attachment_conflict_resolution`、`brand_knowledge_update_full_generation`、`brand_full_knowledge_refresh` 的状态对齐到展示态

注意:

- `confirm/result` 没有废弃, 只是更适合按 job 粒度跟踪
- 品牌页如果只关心统一展示态, 优先看 `conflict-session/latest`

所以现在这条链路里的附件语义也是:

- 只挂载
- 只存档
- 不作为普通知识文档入检索库

## 与正式 AI 知识库的关系

如果 `build_next_brand_full_knowledge(...)` 与 `brand_ai_knowledge_ingestion` 依赖存在, 当前链路还能继续做一件事:

- 用确认后的最终 Markdown 生成并发布下一版正式品牌 AI 知识库

当前正式知识库生成输入规则:

- 主输入永远是确认后的附件 Markdown
- 天眼查回补内容与 LLM 联网回补内容会被单独整理成补充 Markdown
- 不会把一整份最终结构化 JSON 快照直接当成正式知识库主输入
- 如果附件冲突扫描结果是 `no_conflicts`, 也会直接沿这条 full-markdown 生成路径继续, 不需要额外的人为确认步骤

这样做的目的:

- 保留附件原文对最终 Markdown 生成结果的主导权
- 只把外部补齐信息作为补充, 避免把最终生成结果带偏

这意味着:

- 两段式确认链路既会写结构化知识, 也可能产出正式知识库文档
- 结构化知识产物和正式知识库产物仍然是两套表

## 与 `/brands/upload` 的边界

`/brands/upload` 当前更偏:

- 自动抽取
- 自动 merge
- 原始附件直接进入知识生产

两段式确认链路当前更偏:

- 先生成草稿
- 人工确认后再入库
- 确认文本才是最终知识源

## 当前最容易混淆的地方

### 冲突确认完成后为什么现在还能看到 `brand_knowledge_json`

- 因为会话完成后, 系统现在会把最终结构化结果再次同步写回
- 所以附件冲突确认不再只是生成 `【品牌名】品牌AI知识库_Vx_日期.md`
- 也会把最终确定版知识同步落回结构化表

### completed 回调里的 `knowledge` 现在来自哪里

- 现在优先取本次会话刚生成并刚落库的最终结构化结果
- 不是再去拿旧的、可能还是空的历史快照

### 确认后是不是只写 `brand_knowledge_json`

- 不是
- 它会写 `brand_knowledge_json`
- 也可能继续生成正式 AI 知识库
- 但附件本身不会再走一遍文档入库 / Milvus / facts

## 调整本链路规则时, 需要同步检查

1. 草稿和最终稿的边界是否变化.
2. 是否仍然保持"附件 Markdown 为主输入, 外部回补 Markdown 为补充输入".
3. 确认后是否仍然写 `brand_knowledge_json`.
4. completed 回调是否仍然返回本次最终 `knowledge`.
5. 是否仍然允许继续生成正式 AI 知识库.
6. `/brands/upload` 与本链路的职责边界是否变化.
