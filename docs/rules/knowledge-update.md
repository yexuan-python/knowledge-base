# `/api/v1/knowledge/update` 规则

最后校对日期: 2026-10-08

## 目标

这份文档只说明一件事:

- `/api/v1/knowledge/update` 现在怎么更新品牌结构化知识
- 特别是 `attachment_products` 和 `other_info -> 附件解析新增产品` 现在怎么联动

## 入口定位

- 接口: `POST /api/v1/knowledge/update`
- 代码入口:
  - [knowledge_base/api_app/routers/knowledge.py](../../knowledge_base/api_app/routers/knowledge.py)
  - [knowledge_base/service.py](../../knowledge_base/service.py)
  - [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py)

## 当前更新范围

这条接口当前会更新 3 类存储:

1. `brands`
2. `brand_products`
3. `brand_knowledge_json`

如果本次内容发生实质变化, 还会继续触发:

4. 正式品牌 AI 知识库 Markdown / PDF 重建任务
5. 完成后的 completed 回调

## 内部控制开关

`KnowledgeUpdateRequest` 里现在还有 2 个内部流程开关:

1. `skip_attachment_document_sync`
2. `skip_full_ai_knowledge_sync`

它们不是给普通外部调用方当业务字段长期维护的, 主要用于内部链路临时改写流程:

- `skip_attachment_document_sync = True`
  - 表示本次 `update_knowledge` 不再额外执行附件到文档的同步链路
  - 典型场景是附件确认 / 合并流程, 先更新结构化数据, 不重复跑附件同步
- `skip_full_ai_knowledge_sync = True`
  - 表示本次 `update_knowledge` 只改结构化数据, 不要自己再触发整套正式品牌 AI 知识库重建
  - 典型场景也是内部确认流水线, 由外层 job 统一接管后续重建步骤

如果是正常外部调用 `POST /api/v1/knowledge/update`, 一般不用主动传这两个字段.
只有内部编排流程在需要“跳过某一步”时才会显式设置它们.

## Markdown 生成与重试

`/knowledge/update` 接收结构化字段更新，不接收 Markdown 正文。正常更新优先进入品牌级合并刷新任务 `brand_full_knowledge_refresh`，将结构化变更整理为摘要后生成新版知识库：

1. 有上一版 Markdown 时，优先调用 `generate_brand_ai_knowledge_patch_from_structured_update` 生成局部补丁，由代码合并到上一版，保留未修改内容。
2. 补丁生成最多尝试 3 次（含首次），失败后分别等待 10 秒、20 秒再试；空白生成结果也视为失败。任意一次成功即结束生成。
3. 补丁连续 3 次失败后，才回退到完整 Markdown 生成；完整生成沿用最多 3 次的重试机制，不再重新尝试补丁。
4. 没有上一版 Markdown 时，直接完整生成。完整生成最终仍失败时，抛出异常，交由现有后台任务失败及重试流程处理。

直接生成及旧后台更新任务中的补丁分支也遵循先尝试 3 次补丁、再回退完整生成的顺序。

## 返回结果与状态流

`/api/v1/knowledge/update` 的首响应, 不只是告诉你 "成功" 还是 "失败", 还会把这次更新的范围和后续处理状态一起返回.

当前最重要的几个返回字段是:

1. `status`
   - 当前更新结果
   - 正常成功时通常是 `success`
   - 如果品牌不存在, 会返回 "没有这个品牌，无法修改"
2. `updated_sections`
   - 这次实际被应用的知识分区
   - 例如 `brands`、`products`、`attachments`、`other_info`、`sensitive_topics`
   - 这里表示"本次处理到了哪些 section", 不一定等于每个 section 都发生了内容变化
3. `deleted_sections`
   - 这次被明确清空或收缩的分区
   - 例如某个可清空分区从有内容变成空内容时, 会出现在这里
4. `knowledge_revision`
   - 本次更新后对应的品牌知识版本号
   - 如果这次没有触发版本提升, 通常会沿用旧版本号
5. `background_job_id`
   - 只有本次更新真的触发了后续异步重建, 并且没有被 `skip_full_ai_knowledge_sync` 跳过时, 才会出现在返回里
   - 前端或调用方可以拿它继续轮询后台任务
6. `background_job_status`
   - 与 `background_job_id` 配套返回
   - 常见值通常是 `waiting` 或 `processing`

可以把它理解成两层信息:

- 第一层: 这次结构化数据改了什么
- 第二层: 后续正式品牌 AI 知识库有没有继续排队生成

### 什么时候会有后台任务信息

只有当本次 `update_knowledge` 触发了版本提升, 并且没有显式跳过正式知识库同步时, 才会继续创建异步 job.

也就是说:

- 没有实质变更, 通常不会有新的 `background_job_id`
- `skip_full_ai_knowledge_sync = True` 时, 也不会把异步重建任务挂到首响应里
- 但 `updated_sections`、`deleted_sections`、`knowledge_revision` 仍然会按这次更新本身返回

### `industry_id` 的特殊规则

`basic_info.industry_id` 属于品牌元数据, 不再作为正式品牌 AI 知识库正文变更处理.

也就是说:

- 只改 `industry_id` 时, 仍会更新 `brands.industry_id`
- 只改 `industry_id` 时, 仍会写入 `brand_knowledge_update_audits`, 但 `source_type = knowledge_metadata_update`
- `knowledge_metadata_update` 不在品牌级正式知识库 refresh 默认消费范围内, 不会触发 Markdown / PDF 重建
- 只改 `industry_id` 时, 不提升 `knowledge_revision`, 首响应也不会返回新的 `background_job_id`

## `attachments` 当前规则

`/api/v1/knowledge/update` 里的顶层 `attachments` 现在按"轻挂载附件"处理, 不再按"文档入库"处理.

当前语义:

1. 传了 `attachments`
   - 会同步写 `brand_knowledge_json.knowledge_type = attachments`
2. 新增附件
   - 会下载远程文件
   - 上传原文件到 OSS
   - 写一条 `brand_attachment_assets`
   - 但不会解析 Markdown
   - 不会抽 facts
   - 不会入 Milvus
3. 删除附件
   - 只会通过新的附件列表把 `brand_knowledge_json.attachments` 改掉
   - 不会删 OSS
   - 不会删 `brand_attachment_assets`
   - 不会删任何 document / Milvus / facts 数据

所以现在要把这块理解成:

- `attachments` 控制的是"品牌知识里挂哪些附件"
- 不是"把这些附件当知识文档全文入库"

### 附件身份判断

当前 `attachments` 的身份只看 `url`.

- 同一个 `url` 视为同一个附件
- 同一个 `url` 改 `name`, 只更新展示名, 不重新下载 / 上传附件资产
- 同一批请求里同一个 `url` 出现多次, 保留最后一条
- 新出现的 `url` 才会进入附件资产同步流程
- 下载后仍然会计算文件 SHA256, 用 `brand_code + file_hash` 对 `brand_attachment_assets` 做内容级去重

## 产品相关的统一规则

现在产品分成两层:

1. `brand_products`
   - 这是主产品白名单
   - `/knowledge/update` 请求里的顶层 `products` 会按下面的主产品规则尝试更新这一层
2. `brand_knowledge_json.attachment_products`
   - 这是附件抽取产品副本
   - 主要给知识快照、知识库正文和 completed 回调展示使用

同时, 附件产品副本还会镜像到:

- `brand_knowledge_json.other_info`
  - 其中一条固定为:
    - `title = 附件解析新增产品`
    - `content = attachment_products 当前值`

## 顶层 `products` 的主产品规则

`/api/v1/knowledge/update` 的顶层 `products` 按完整产品列表同步；未传字段与空数组含义相同。

当前规则是:

- 请求里没传 `products`：按空列表处理，清空该品牌的 `brand_products`。
- 显式传 `products = []`：清空该品牌的 `brand_products`。
- 原来有 A / B / C，只传 A / B：更新或保留 A / B，删除 C；其他品牌不受影响。
- 产品优先按 `product_code` 匹配，保留项不删除重建；产品顺序变化不会被识别为删除。
- 移除产品会写入 `products` 分区的删除审计，记录变更前后的完整列表，提升知识库版本并触发 Markdown 补丁更新。
- 部分删除时仅移除缺失产品，保留其余产品；清空时移除旧产品内容。补丁仍按最多 3 次尝试、等待 10 秒和 20 秒、失败后回退完整生成的流程执行。
- 产品同步的更新和删除在同一数据库事务中执行，失败时一起回滚。

HTTP 入口会将缺失的 `products` 标记为显式空列表；附件确认等内部直接调用保留局部更新语义，省略 `products` 时不修改产品。

写入 `brand_products` 时还有一条更具体的规则:

- 只有带非空 `product_code` 的产品才会写入 `brand_products`
- 没有 `product_code` 的产品会被跳过, 不报错
- 无编码产品若与已有产品同名，会保留该已有产品；不会新增无编码记录。每个产品必须有名称，避免无效条目被当成空列表删除旧产品。
- 没有 `product_code` 的产品仍然可以作为本次结构化变更参与审计和正式知识库重建, 但不会进入主产品白名单表

主产品身份判断以 `product_code` 为准:

- `product_code` 相同: 更新同一个产品
- `product_code` 不同: 视为不同产品, 即使 `product_name` 相同也允许同时保存
- 历史上如果存在同品牌同名但没有 `product_code` 的旧产品, 新请求带 `product_code` 时会优先回填 / 更新这条旧产品

## `attachment_products` 不能显式直传

`/api/v1/knowledge/update` 当前不允许单独增加一个顶层字段去直接传:

```json
{
  "attachment_products": [...]
}
```

这不是当前接口的公开写法.

也就是说, 调用方不能把 `attachment_products` 当成独立请求字段直接维护.

## 正确更新方式

如果要改附件产品副本, 当前唯一对外写法是改顶层 `other_info` 里的这条:

```json
{
  "other_info": [
    {
      "title": "附件解析新增产品",
      "content": [
        {
          "name": "附件新品A",
          "product_description": "示例描述"
        }
      ]
    }
  ]
}
```

系统收到后会自动做 3 件事:

1. 解析这条 `content`，标准化成 `attachment_products`
2. 同步写回 `brand_knowledge_json.attachment_products`
3. 用最新的 `attachment_products` 重新构建整份 `other_info`

所以现在的真实规则是:

- `other_info.附件解析新增产品` 是对外可编辑入口
- `attachment_products` 是系统内部同步产物

## `other_info` 的重建规则

只要这次请求显式传了顶层 `other_info`, 系统就会重建最终的 `other_info` 分区.

重建时遵循下面的规则:

1. 先合并普通 `other_info` 条目
2. 再把 `附件解析新增产品` 这一条按最新的 `attachment_products` 重写进去

效果上等于:

- 你改普通 `other_info`, 系统会保留当前附件产品镜像
- 你改 `附件解析新增产品`, 系统会同步更新附件产品镜像

## 清空规则

如果调用方在 `other_info` 里显式把 `title = 附件解析新增产品` 的内容清空, 当前语义是:

- 清空 `brand_knowledge_json.attachment_products`
- 同步从 `other_info` 镜像里移除这批附件产品内容

## completed 回调里的表现

`/knowledge/update` 这条线在触发正式知识库重建后, 回调返回的 `knowledge` 会使用重建后的最新快照.

这意味着:

- 回调里的 `knowledge.other_info` 会带最新的 `附件解析新增产品`
- 回调里的 `knowledge.products` 仍然看 `brand_products` 白名单
- 回调不会额外暴露一个新的顶层 `attachment_products` 字段给上游

所以这条链路现在已经形成闭环:

1. 调用方改 `other_info.附件解析新增产品`
2. 系统同步更新 `attachment_products`
3. 系统重建 `other_info`
4. 正式知识库重建
5. completed 回调返回新的 `other_info`

## 和 `products` 的区别

这两个字段不要混:

- 顶层 `products`
  - 更新主产品白名单
  - 只有带 `product_code` 的产品会写 `brand_products`
  - 全量同步，少传会删除缺失旧产品；空数组或未传字段均清空
  - 回调 `knowledge.products` 也看它
- `other_info -> 附件解析新增产品`
  - 更新附件抽取产品副本
  - 会写 `brand_knowledge_json.attachment_products`
  - 回调里通过 `knowledge.other_info` 返回

## 适合怎么排查

如果你怀疑这条规则没有跑通, 优先查:

1. `brand_knowledge_json`
   - `knowledge_type = other_info`
   - `knowledge_type = attachment_products`
2. `brand_products`
   - 看主产品白名单是不是你预期的内容
3. 对应 `/knowledge/update` 触发出的知识库重建任务 / 回调记录

## 当前代码锚点

- `BrandApplicationService.update_knowledge`
- `_extract_attachment_products_override_from_other_info`
- `_rebuild_other_info_with_attachment_products`
- `_build_attachment_product_callback_snapshot`
