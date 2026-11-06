# `/api/v1/brands/upload` 规则

最后校对日期: 2026-07-23

## 入口与范围

- 接口: `POST /api/v1/brands/upload`
- 路由实现: [knowledge_base/api_app/routers/brands.py](../../knowledge_base/api_app/routers/brands.py)
- 主任务创建: [knowledge_base/upload_task/application/service.py](../../knowledge_base/upload_task/application/service.py)
- 品牌结构化写库: [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py)
- 对外说明: [API.md](../../API.md), [README.md](../../README.md)

这条链路适合"上传品牌主体信息 + 附件 URL + 产品结构 + 竞品种子, 然后交给后台自动抽取和 merge".

## 请求模型核心规则

当前高优先级字段:

- `brand_name`: 必填
- `brand_code`: 可选但强烈建议提供
- `attachments`: 可空数组
- `products`: 可空数组
- `competitors`: 可空数组
- `enterprise_subject`, `business_license_url`, `industry_id`, `industry_code`, `industry_name`: 都属于品牌结构化字段

当前约定:

- `brand_name` 会直接作为历史 `category`
- `attachments` 是品牌级附件
- `products[].attachments` 是产品级附件, 会附带 `subcategory = product_name`
- 品牌相关多值字段统一只按数组输入或换行拆分
  - 不再按 `，`、`,`、`、`、`；`、`;` 自动拆分

## 任务创建阶段

创建任务时当前会做这些事:

1. 先校验并标准化 `brand_name`、`brand_code`、行业字段、产品和竞品结构.
2. 先把 `brands` 主表 upsert 掉.
3. 如果有产品, 同步 upsert `brand_products`.
4. 把品牌级和产品级附件改写成 upload task files.
5. 任务 metadata 中至少会带:
   - `brand_name`
   - `category = brand_name`
   - `brand_callback_enabled = true`
   - 如果有 `brand_code`, 也会一起写入 metadata
6. 每个附件的 `source_url` 与可能的 `subcategory` 会放进 `_task_payload.file_metadata_by_index`

补充:

- 这条链路保留全文 Markdown 解析
- 也保留 facts 抽取
- 旧 `document_summaries` 摘要链已下线

## 附件处理规则

### 品牌级附件

当前行为:

- 进入后台任务后, 会下载远程文件
- 走附件资产处理链路
- 默认不写 `subcategory`
- OSS 路径按品牌根目录组织

### 产品级附件

当前行为:

- 也走后台任务和附件资产处理链路
- 会按产品名写入 `subcategory`
- 后续抽取时可映射到对应产品

## 当前真实执行流程

按 2026-07-23 当前代码, `/api/v1/brands/upload` 的完整主流程应理解成:

1. 入口先 upsert `brands`
2. 如果请求里有主产品白名单, 再 upsert `brand_products`
3. 品牌级附件和产品级附件都登记成 `upload_task_files`
4. 后台逐个附件下载到临时文件, 上传原文件到 OSS, 写 `brand_attachment_assets`
5. 附件解析出 Markdown / full text 后, 先抽一批 `attachment_temp` 临时 facts
   - MySQL: `brand_knowledge_facts`
   - 向量层: Milvus facts
6. 然后按附件内容做结构化抽取与 merge, 写 `brand_knowledge_json`
7. 如果存在附件冲突, 进入 `attachment_conflict` 会话; 没冲突则自动继续
8. 冲突收口后先生成最终正式品牌 AI 知识库 Markdown 文本
9. 再把这份最终正式 Markdown 统一交给正式知识库 ingestion 链
   - 上传 Markdown OSS
   - 渲染并上传 PDF
   - 写 `brand_full_knowledge_files`
   - 切块写正式 document chunks 到 Milvus
   - 抽正式 facts 到 MySQL + Milvus
   - `promote_latest`
   - 清理旧版本
10. 正式 ingestion 成功后, 再删除前面那批 `attachment_temp` 临时 facts
11. 最后回调上游; 回调里的 `knowledge` 口径应基于最终正式 Markdown 重建后的 snapshot

因此这条链路现在不是"只写结构化表", 也不是"只生成 md/pdf". 它已经是:

- 结构化知识抽取
- 临时 facts 过渡层
- 正式品牌 AI 知识库 ingestion
- 最终 completed 回调

这一整条收口链.

## merge 与回填规则

当前自动抽取链路完成后:

1. 系统会读取转换后的 Markdown
2. 逐文件调用知识抽取逻辑
3. 附件里抽到的产品会先额外整理成"附件新增产品副本"
4. 程序化 merge 各知识分区
5. merge 结果写入 `brand_knowledge_json`
6. 同时按优先级回填 `brands`、`brand_products`

## 产品规则

这条链路当前把"主产品白名单"和"附件抽取出的产品副本"分开处理.

### 共同规则

不管请求里的 `products` 是空还是非空, 只要附件抽到了产品, 都会做两件事:

1. 额外写一份到 `brand_knowledge_json`
   - `knowledge_type = attachment_products`
2. 在 `other_info` 里补一条
   - `title = 附件解析新增产品`
   - `content = 产品信息列表`

这份副本是给品牌知识快照和回调展示用的, 不直接等同于主产品表.

### `products = []`

如果 `/api/v1/brands/upload` 请求里 `products` 为空数组, 当前语义是:

- 本次没有主产品白名单
- 附件里抽到的产品 **不会** 写入 `brand_products`
- completed 回调里的 `knowledge.products` 也保持 `[]`
- 但抽到的产品仍然会:
  - 落 `attachment_products`
  - 落 `other_info -> 附件解析新增产品`

### `products != []`

如果请求里 `products` 非空, 当前语义是:

- 请求中的产品就是主产品白名单
- `brand_products` 只围绕这批白名单产品做 merge / 回填
- completed 回调里的 `knowledge.products` 也只返回这批白名单产品
- 与此同时, 附件里抽到的产品仍然会额外保留一份:
  - 落 `attachment_products`
  - 落 `other_info -> 附件解析新增产品`

也就是说:

- `brand_products` / `knowledge.products` 看的是白名单主产品
- `attachment_products` / `other_info.附件解析新增产品` 看的是附件抽取产品副本

当前资料中已经明确的知识分区包括:

- `company_profile`
- `management_team`
- `competitors`
- `attachment_products`
- `authority_honors`
- `customers_cases`
- `sensitive_topics`
- `attachments`
- `official_malls`
- `official_media_matrix`
- `other_info`

## 当前落库重点

| 表 | 当前职责 |
| --- | --- |
| `brands` | 品牌主数据与部分结构化字段 |
| `brand_products` | 主产品白名单及其结构化字段 |
| `brand_knowledge_json` | merge 后的结构化知识分区, 同时保存 `attachment_products` 与 `other_info` 中的附件产品副本 |
| `upload_tasks` / `upload_task_files` | 异步任务与文件级状态 |
| `brand_attachment_assets` | 附件原文件、解析全文与来源 URL 资产记录 |
| `brand_knowledge_facts` | 附件临时 facts 与正式知识库 facts |
| `brand_full_knowledge_files` | 正式品牌 AI 知识库 Markdown / PDF 与最新版本状态 |

注意:

- 这条链路最先产出的结构化主结果仍然是 `brand_knowledge_json`
- 但当前最终收口已经会继续生成并正式入库品牌 AI 知识库
- 所以现在不能再把它理解成"只写 `brand_knowledge_json`、不碰正式知识库"

## 与两段式附件确认链路的区别

`/brands/upload` 当前特点:

- 原始附件就是知识抽取输入
- 自动抽取和自动 merge 是主流程
- `brand_knowledge_json` 是主要结构化产物

`/brands/attachments/preview-parse + /confirm` 当前特点:

- 原始附件先只生成可编辑初稿
- 前端确认后的文本才是最终知识源
- 确认后既会写 `brand_knowledge_json`, 也可以继续生成正式 AI 知识库

## 当前最容易混淆的地方

### `brand_name` 与 `category`

- 在这条链路里, `brand_name` 会直接作为 metadata 的 `category`
- 所以后续很多读取逻辑按 `category` 看时, 实际指向的是品牌名

### 为什么这里不再谈摘要

- `/brands/upload` 的品牌知识抽取依赖附件全文 Markdown
- 以及后续的结构化 merge / facts
- 旧 `document_summaries` 摘要链已经下线
- 所以这里不再存在“是否跳过摘要”这一步

### `attachments` 为空

- `attachments` 可以为空
- 为空时不会走远程附件链路
- 但品牌主数据和产品主数据仍然可能已被 upsert

### `brand_knowledge_json` 与 `brand_full_knowledge_files`

- `/brands/upload` 的第一层主知识产物仍然是 `brand_knowledge_json`
- 但当前最终收口已经会继续走正式品牌 AI 知识库 ingestion
- 所以实际最终还会落:
  - `brand_full_knowledge_files`
  - 正式 document chunks
  - 正式 facts

### 临时 facts 与正式 facts

当前明确分两层:

1. 附件解析后先生成 `attachment_temp` 临时 facts
2. 最终正式 Markdown ingestion 成功后, 再写正式 facts
3. 只有正式 ingestion 成功后, 才删除 `attachment_temp` 临时 facts

所以排查时不要把这两层混成同一层看.

## 调整本链路规则时, 需要同步检查

1. metadata 是否仍然固定写 `category = brand_name`.
2. 品牌级附件和产品级附件的 `subcategory` 规则是否变化.
3. merge 后是否仍然写 `brand_knowledge_json`.
4. 是否仍然先写 `attachment_temp` facts, 再写正式 facts, 再删临时 facts.
5. 最终正式 Markdown 是否仍然统一走正式知识库 ingestion, 而不是只停在 md/pdf 持久化.
6. completed 回调里的 `knowledge` 是否仍然来自最终正式 Markdown 重建后的 snapshot.
7. 品牌结构化字段回填优先级是否变化.
8. `/brands/upload` 与两段式确认链路的边界是否变化.

## 变更约定

这篇文档记录的是 `/api/v1/brands/upload` 当前真实实现规则.

后续如果准备修改代码, 且修改后的行为会与本文档任一规则不一致, 必须先做两件事:

1. 先明确提示这是"改规则", 不能当成普通重构直接改
2. 再同步更新本文档, 避免代码和规则出现两套真相
