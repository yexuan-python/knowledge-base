# 检索口径规则

最后校对日期: 2026-08-20

## 目标

这份文档只说明当前 3 组检索入口的真实口径:

1. `POST /api/v1/search`
2. `POST /api/v1/brands/facts`
3. `POST /api/v1/categories/facts`

重点是澄清:

- `/search` 查的是哪套数据
- facts 检索查的是哪套数据
- `brand_name` / `category` / `subcategory` 现在怎么解释
- "最新版本" 约束在哪些分支生效

主代码锚点:

- [knowledge_base/api_app/routers/documents.py](../../knowledge_base/api_app/routers/documents.py)
- [knowledge_base/search/application/service.py](../../knowledge_base/search/application/service.py)
- [knowledge_base/document/application/service.py](../../knowledge_base/document/application/service.py)
- [knowledge_base/infrastructure/milvus_store.py](../../knowledge_base/infrastructure/milvus_store.py)

## 当前检索入口分工

### `/api/v1/search`

当前返回的是:

- 文档 chunk 命中结果

底层主来源:

- Milvus 文档向量集合
- 或品牌结构化快照程序化命中后, 再补语义检索

### `/api/v1/brands/facts` 与 `/api/v1/categories/facts`

当前返回的是:

- facts 命中结果

底层主来源:

- Milvus facts 集合

因此:

- `/search` 与 `/brands/facts` 不是同一套索引
- `/search` 查 chunk
- facts 接口查 fact

### `/api/v1/images/search`

当前返回的是:

- 图片资产命中结果

底层主来源:

- 图片向量检索
- 附件资产索引

因此:

- `/images/search` 不是文本 chunk 检索
- 它返回的是图片级结果, 不是文本段落

当前规则:

1. 先按 `brand_name` / `category` / `subcategory` 解析并收敛到可搜索文档范围
2. 再把 `source_types` 固定为 `["image"]`
3. 如果请求里带了 `document_ids`, 还会与收敛后的文档范围取交集
4. 最终返回图片资产信息, 包括 `asset_id`、`document_id`、`oss_url`、`image_summary`、`image_tags`

所以当前 `/images/search` 更像:

- "按品牌 / 分类限制范围的图片资产检索"
- 不是图片 OCR 后的文本检索

当前也会遵守和 `/search` 一样的品牌解析习惯:

- `brand_name` 优先
- `category` 兼容旧字段名
- `subcategory` 只在分类范围收敛时生效

## `brand_name` 与 `category` 当前统一口径

当前检索层把:

- `brand_name`
- `category`

视为同一层主过滤入口.

具体规则:

1. `/search` 中, 优先取 `brand_name`, 其次取 `category`
2. facts 接口中, 也是优先取 `brand_name`, 其次取 `category`
3. 返回结果里, `category` 当前会跟随解析后的主名称输出

也就是说:

- `category` 现在更多是兼容旧字段名
- 但如果它没有被识别成品牌, 仍会按普通分类名参与过滤

## `/api/v1/search` 当前规则

### 1. 查询模式判断

当前 `/search` 会先根据 `query` 文本分类:

- `structured`
- `hybrid`
- `semantic`

当前规则:

- 命中结构化关键词, 走 `structured`
- 命中混合关键词, 走 `hybrid`
- 都不命中时, 走 `semantic`

### 2. `structured` / `hybrid` 当前怎么查

这两类查询当前都会先查品牌结构化快照, 不是直接先查 Milvus.

结构化快照来源主要是:

- `brands`
- `brand_products`
- `brand_knowledge_json`

如果结构化命中不够 `top_k`, 才会继续补一轮语义检索.

所以当前真实行为是:

- `structured` = 先结构化, 不够再补语义
- `hybrid` = 先结构化, 不够再补语义

### 3. `semantic` 当前怎么限制范围

如果请求里没有 `brand_name` / `category`:

- 当前会先用 `document_categories.get_searchable_document_ids(...)`
- 只保留"可搜索文档"
- 实际约束是:
  - `document_registry` 不存在的文档也允许
  - 或 `document_registry.is_latest = 1 AND status = success`

所以当前无品牌过滤时, `/search` 默认只查最新成功版本文档.

### 4. 带品牌过滤时的当前规则

如果请求里传了 `brand_name` 或 `category`, 当前先尝试把它解析成品牌.

#### 情况 A: 解析到品牌, 且品牌存在最新正式知识库文档

当前会直接把语义检索范围收敛到:

- `brand_full_knowledge_files` 里该品牌最新一版对应的 `document_id`

这意味着:

- `/search` 对已建成正式知识库的品牌, 当前优先只搜"最新正式品牌知识库文档"
- 不会再自动把该品牌普通附件文档一起纳入搜索范围

#### 情况 B: 解析到品牌, 但没有最新正式知识库文档

当前实现会直接得到空的文档范围, 最终返回空结果.

当前不会自动回退到:

- 该品牌普通 `category` 文档集合

这是当前代码行为里一个很重要的边界.

#### 情况 C: 请求里的 `brand_name` / `category` 没能解析成品牌

这时当前会把它当成普通分类:

- 有 `subcategory` 时, 取该 `category + subcategory` 下最新成功文档
- 没有 `subcategory` 时, 取该 `category` 下最新成功文档

### 5. `subcategory` 当前只影响语义检索分支

当前 `subcategory` 的作用是:

- 在普通分类搜索时收敛文档集合

它当前不会改变:

- 结构化快照搜索范围
- 已解析成正式品牌知识库文档时的单文档优先逻辑

### 6. `document_ids` 与 `source_types` 当前怎么生效

当前语义检索最终会把过滤条件传给 Milvus:

- `document_ids`
- `source_types`

如果同时还带了品牌 / 分类过滤, 当前行为是:

- 先算品牌 / 分类可搜索文档范围
- 再与请求传入的 `document_ids` 取交集
- 交集为空则直接返回空

### 7. `/search` 返回结果当前如何组装

当前返回结果会做这些处理:

1. 按 `document_id` 聚合 chunk 命中
2. 为文本类结果尽量拼出 OSS `source_url`
3. 对重复 `chunk_id` / 文本做去重
4. 最终 `brand_name` 与 `category` 都会跟随解析后的主名称输出
5. `metadata` 中优先补 `brand_id`、`brand_code`、`brand_name`、`kb_version`

## `/api/v1/brands/facts` 与 `/api/v1/categories/facts` 当前规则

### 1. 两个路径当前是同一套实现

这两个接口共用同一个 handler.

当前只是参数命名兼容不同:

- `/brands/facts` 更偏当前品牌名口径
- `/categories/facts` 更偏旧分类名口径

### 2. `query` 在 schema 可空, 但当前实现应视为必传

请求模型里 `query` 当前声明为可空.

但当前实际流程会直接拿它做 embedding.

因此真实规则应理解成:

- `query` 现在应视为必传
- 传空值不属于稳定受支持用法

### 3. facts 当前查的是哪套数据

facts 接口当前走的是 Milvus facts 集合, 不是 chunk 集合.

Milvus facts 当前过滤条件是:

- `category == 解析后的 brand_name / category`
- 如果能解析出 `brand_code`, 还会加 `brand_code == 对应品牌编码`
- 不再依赖最新正式知识库 `document_id` 过滤品牌 facts

### 4. brand facts 当前的文档范围规则

如果品牌存在 `brand_code`:

- 当前 facts 检索会按 `category + brand_code` 收敛到该品牌 facts
- 不再要求命中最新版正式知识库的单个 `document_id`

这也是 facts 接口与普通 category facts 的主要品牌化收敛逻辑.

### 5. 没有最新正式知识库文档时的 facts 行为

如果品牌存在, 但没有最新正式知识库 `document_id`:

- 仍然按 `category + brand_code` 在 facts 集合里检索
- 因为品牌 facts 已不依赖 `document_id` 过滤, 所以不会因为缺少最新版文档记录而被额外清空

所以 facts 接口和 `/search` 不一样:

- `/search` 在这种情况下可能直接空结果
- facts 接口则可能还能返回该品牌现存 facts

### 6. 返回里的 `document_count` 现在怎么来

`/brands/facts` 和 `/categories/facts` 当前会对每条 fact 统计:

- 该 fact 在当前有效文档范围内命中的 `document_ids` 数量

如果该 fact 被多个文档合并复用:

- `document_count` 可能大于 1

### 7. facts 检索当前的 embedding 限流保护规则

`/brands/facts` 与 `/categories/facts` 在真正查 Milvus facts 之前, 会先把 `query` 做一次 embedding.

因此这两个接口当前不仅受 Milvus 查询影响, 也受外部 embedding 服务配额与限流影响.

当前代码在 embedding 层增加了统一的冷却与快速失败规则:

1. 正常状态下, 外部 embedding 调用最大并发默认是 `10`
2. 一旦外部 embedding 返回 `rate limit` / `too many requests` 类错误, 立即进入全局冷却
3. 冷却期默认持续 `60` 秒; 这段时间内新请求不会继续打外部 embedding, 也不会在服务端排队等待
4. 冷却期内再次请求时, 服务端会直接返回 `503`
5. 响应里会带 `Retry-After` 提示上游稍后重试
6. 冷却期结束后, 下一次请求才会重新尝试外部 embedding

所以当前真实行为不是:

- "被限流后继续在服务端排队"
- 也不是 "服务端自动恢复慢放行"

而是:

- "被限流后先全局冷却"
- "冷却期间直接返回 503"
- "冷却结束后下一次请求再尝试"

当前相关配置项是:

- `KB_EMBEDDING_MAX_CONCURRENCY`
- `KB_EMBEDDING_RATE_LIMIT_COOLDOWN_SECONDS`

## 当前最容易混淆的地方

### 为什么 `/search` 和 `/brands/facts` 对同一个品牌返回范围不一样

因为二者查的不是同一套集合:

- `/search` 查 chunk
- facts 接口查 facts

并且它们在"品牌存在但无最新正式知识库文档"时的回退行为也不一样.

### 为什么传了品牌名后, `/search` 结果反而变少

因为当前一旦识别成品牌, `/search` 会优先把范围缩到该品牌最新正式知识库文档.

### 为什么 `category` 返回值看起来像 `brand_name`

因为当前响应层会把 `category` 回填为解析后的主名称; 在品牌检索场景下, 这个主名称通常就是品牌名.

## 当前代码锚点

- 查询模式判断:
  - `SearchApplicationService._classify_search_query`
- 品牌过滤解析:
  - `SearchApplicationService._resolve_request_brand_name`
  - `SearchApplicationService._resolve_latest_brand_document_ids`
- 语义检索批量过滤:
  - `SearchApplicationService._search_with_document_filter_batches`
- facts 检索上下文:
  - `DocumentApplicationService._resolve_brand_fact_search_context`
- facts 集合检索:
  - `MilvusVectorStore.search_facts`

## 调整检索规则时, 需要同步检查

1. `/search` 是否仍然优先识别 `structured` / `hybrid` / `semantic`.
2. 识别成品牌后, 是否仍然优先只查最新正式知识库文档.
3. 品牌缺少最新正式知识库文档时, `/search` 是否仍然直接返回空.
4. facts 接口是否仍然把 `query` 视为实际必传.
5. `brand_name` 与 `category` 的统一口径是否变化.
6. `subcategory` 是否仍然只影响普通分类语义检索范围.
