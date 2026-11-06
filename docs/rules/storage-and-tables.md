# 存储表职责规则

最后校对日期: 2026-10-09

## 目的

这份文档回答一个最容易混淆的问题:

"某条链路成功后, 到底应该去看哪张表?"

## 核心表分工

| 表 | 当前职责 | 典型来源链路 |
| --- | --- | --- |
| `brands` | 品牌主数据, 包含品牌名、编码、部分结构化字段 | `/brands/upload`, 品牌结构化回填 |
| `brand_products` | 主产品白名单与部分产品结构化字段 | `/brands/upload`, 品牌结构化回填 |
| `brand_knowledge_json` | 品牌结构化知识分区结果, 也保存 `attachment_products` 与 `other_info.附件解析新增产品` 这类附件产品副本 | `/brands/upload`, `/brands/attachments/confirm`, 附件冲突确认完成, 部分结构化更新接口 |
| `brand_full_knowledge_files` | 正式品牌 AI 知识库文档版本 | 正式知识库文件入库, 附件冲突确认后发布正式知识库 |
| `brand_knowledge_facts` | 从正式知识库文档抽取的 facts | 正式知识库入库流程 |
| `upload_tasks` / `upload_task_files` | 上传任务与文件级处理状态 | `/documents/upload`, `/brands/upload` |
| `brand_knowledge_ingestion_jobs` | 正式知识库文件入库进度 | 正式知识库入库流程 |

补充:

- 当前 `/api/v1/brands/{brand_code}/meta` 需要的摘要不依赖先写 `document_summaries`
- 旧 `document_summaries` 摘要链已经下线，不再是当前品牌主链路排查主表

## `brand_knowledge_json`

当前定位:

- 按 `knowledge_type` 拆开的结构化知识分区表
- 每个品牌每个 `knowledge_type` 一条当前记录

当前常见 `knowledge_type`:

- `company_profile`
- `management_team`
- `competitors`
- `attachment_products`

补充说明:

- `/brands/upload` 当前把产品拆成两层:
  - `brand_products`: 请求里的主产品白名单
  - `brand_knowledge_json.attachment_products`: 附件抽到的产品副本
- 同一批附件产品副本还会同步写进 `brand_knowledge_json.other_info` 中的 `附件解析新增产品`
- `/api/v1/knowledge/update` 不直接暴露 `attachment_products` 顶层请求字段
  - 这条接口如果要改附件产品副本, 需要改顶层 `other_info` 里的 `title = 附件解析新增产品`
  - 系统会自动同步 `brand_knowledge_json.attachment_products`
  - 再用最新 `attachment_products` 重建 `brand_knowledge_json.other_info`
- `authority_honors`
- `customers_cases`
- `sensitive_topics`
- `attachments`
- `official_malls`
- `official_media_matrix`
- `other_info`

适合用它排查的问题:

- 品牌结构化知识有没有被 merge / confirm 写进去
- 某个知识分区是否被覆盖或删除
- `attachments` 当前剩余数组是什么

不适合只看它判断的问题:

- 正式 AI 知识库 Markdown 是否入库成功
- 正式知识库 PDF 是否生成成功

## `brand_full_knowledge_files`

当前定位:

- 正式品牌 AI 知识库文档的版本表
- 保存文件版本、日期、revision、OSS 地址、Markdown 正文、入库状态

适合用它排查的问题:

- 正式知识库文件是否创建成功
- 当前品牌最新版本是哪一版
- 对应 Markdown / PDF 的 OSS 地址是什么
- 某次发布是否是 `skipped` 或失败

不适合只看它判断的问题:

- 结构化知识分区是否已经同步到 `brand_knowledge_json`

## `brand_knowledge_facts`

当前定位:

- 正式知识库文档的 facts 结果
- 更偏检索 / 事实层

适合用它排查的问题:

- 正式知识库的 facts 是否抽取成功
- 历史版本 facts 是否已清理

## `brands` 与 `brand_products`

当前定位:

- 仍然是搜索和结构化读取的重要数据源
- 不是完整知识分区总表

`brand_products` 当前表结构口径:

- `product_code` 是有编码主产品的身份字段, 当前用唯一索引 `uk_brand_products_product_code` 约束.
- `product_name` 不是唯一身份字段, 同一个品牌下允许同名但不同 `product_code` 的产品共存.
- 历史迁移里曾有 `uk_brand_product_name (brand_name, product_name)` 和 `uk_brand_id_product_name (brand_id, product_name)`, 当前应通过 `044_alter_brand_products_allow_same_name_different_code.sql` 降级为普通索引.
- 如果线上库没有执行 `044`, 代码层允许的"同名不同 product_code"会被数据库旧唯一约束挡住.

适合用它排查的问题:

- `brand_code` 和 `brand_name` 是否匹配
- 产品列表和基础字段是否已经回填

## 一张表不等于整条链路

当前最重要的认知是:

- `/brands/upload` 成功, 不代表 `brand_full_knowledge_files` 一定有数据
- 正式知识库文件上传成功, 不代表 `brand_knowledge_json` 一定有新数据
- 附件确认成功后, 可能同时影响文档库、`brand_knowledge_json` 和正式知识库
- 附件冲突确认会话完成后, 现在也会同时更新 `brand_knowledge_json`

## 附件冲突确认完成后的产物

当前这条链路完成后, 理论上应该同时能看到 3 类结果:

1. `brand_full_knowledge_files` 里有新的 `【品牌名】品牌AI知识库_Vx_日期.md / pdf`
2. `brands`、`brand_products`、`brand_knowledge_json` 里是本次最终结构化结果
3. completed 回调里的 `knowledge` 应该和第 2 点保持同一口径

所以如果你看到:

- 文件已经生成了
- 但 `brand_knowledge_json` 还是空
- 或 completed 回调里的 `knowledge` 还是旧值

那就说明这条"会话完成后再同步结构化结果"的步骤没有真正跑通

## 排查时的优先顺序

### 看结构化品牌知识

优先查:

1. `brands`
2. `brand_products`
3. `brand_knowledge_json`

### 看正式知识库文件

优先查:

1. `brand_full_knowledge_files`
2. `brand_knowledge_facts`
3. `brand_knowledge_ingestion_jobs`

### 看异步上传状态

优先查:

1. `upload_tasks`
2. `upload_task_files`

### 不建议再当主真相看的旧表

当前这几张表/能力不再是品牌主链路的一手真相:

1. `document_summaries`
2. 旧 `/api/v1/documents/delete`
3. 旧 `/api/v1/fulltext`

## 调整表职责时, 需要同步检查

1. API 文档对成功产物的描述是否变化.
2. 搜索服务主要读取哪些表是否变化.
3. 错误排查文档里的查表顺序是否变化.
4. 同一条链路是否新增了第二份知识产物.
