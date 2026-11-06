# 品牌读接口规则

最后校对日期: 2026-07-21

## 目标

这份文档只说明当前 4 个品牌读接口的真实行为:

1. `GET /api/v1/brands`
2. `GET /api/v1/brands/{brand_code}/meta`
3. `POST /api/v1/brands/{brand_code}/paths-load`
4. `POST /api/v1/brands/ai-knowledge/latest`

重点是澄清:

- 这些接口分别查哪层数据
- 哪些返回值是原表字段, 哪些是派生拼装结果
- `meta`、`path_index`、`paths-load` 和最新 AI 知识库之间的边界

主代码锚点:

- [knowledge_base/api_app/routers/brands.py](../../knowledge_base/api_app/routers/brands.py)
- [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py)
- [knowledge_base/service.py](../../knowledge_base/service.py)

## 总体范围

这 4 条接口当前都属于:

- 读接口
- 不改写业务数据
- 主要从品牌快照、结构化知识和正式知识库产物里拼出返回结果

但它们的返回层级并不一样:

- `/brands` 更像品牌列表视图
- `/brands/{brand_code}/meta` 更像品牌知识导航入口
- `/brands/{brand_code}/paths-load` 更像按知识 path 加载正文
- `/brands/ai-knowledge/latest` 更像读正式知识库文件下载信息

## `GET /api/v1/brands`

### 目标

返回品牌列表, 支持按关键字筛选.

### 当前筛选规则

`keyword` 可选.

传了 `keyword` 时, 当前会按下面 3 个字段做 `LIKE`:

1. `brand_name`
2. `brand_alias`
3. `brand_code`

不传时, 返回全部品牌.

### 当前排序规则

当前按:

1. `updated_at DESC`
2. `id DESC`

### 当前返回字段规则

当前返回里最需要注意的是 `website`.

虽然底层 `brands.website` 可能是字符串、JSON 字符串或其他旧格式, 但在列表返回前会统一做一次网站归一化:

- 只保留 `http://` 或 `https://` 开头的值
- 最终返回成 `list[str]`

所以当前 `/brands` 返回的是:

- 面向展示的归一化品牌列表
- 不是对 `brands` 原始存储字段的原样透传

## `GET /api/v1/brands/{brand_code}/meta`

### 目标

返回一个品牌的导航型 meta 信息, 并可选带上 `path_index`.

### 参数规则

- `brand_code` 必填
- `include_path_index` 可选, 默认 `true`

当前错误边界:

- `brand_code` 为空: `400`
- `brand_code` 不存在: `404`

### 当前数据来源

这条接口不是只查 `brands`.

它会一起读取:

1. `brands`
2. `brand_products`
3. `brand_knowledge_json`

其中 `brand_knowledge_json` 当前会参与读取的主要 section 包括:

- `company_profile` / `company_info`
- `management_team`
- `competitors`
- `authority_honors` / `honors`
- `customers_cases` / `cases`
- `sensitive_topics`
- `attachments`
- `official_malls`
- `official_media_matrix`
- `attachment_products`

### `meta.products` 当前规则

`meta.products` 当前不是单纯的 `brand_products` 原样返回.

系统会先构造一份展示用产品列表:

1. 先放 `brand_products`
2. 再追加 `attachment_products`
3. 按产品名大小写无关去重
4. 如果同名产品已在主产品里出现, 附件产品副本不会重复加入

也就是说:

### `meta` 当前字段边界

`meta` 当前只返回导航型基础信息:

- `brand_code`
- `brand_name`
- `brand_aliases`
- `brand_english_name`
- `industry`
- `official_websites`
- `knowledge_revision`
- `company_subject_name`
- `products`
- `competitors`

`official_malls` 与 `official_media_matrix` 虽然仍会参与 `path_index` 生成和 `/paths-load` 内容渲染, 但当前不再直接出现在 `meta` 返回体里.

- `meta.products` 是"主产品 + 附件产品副本"的展示合并结果
- 不等于只看 `brand_products`

### `meta.competitors` 当前规则

当前优先从 `brand_knowledge_json.competitors` 构造竞品实体.

如果结构化竞品内容为空, 才会回退到 `brands.competitors_json` 里的名称列表, 并生成最小竞品节点.

### `meta` 里的 path 字段当前语义

`meta.products[].path` 当前固定按:

- `产品信息/{产品名}`

`meta.competitors[].path` 当前固定按:

- `竞品信息/{竞品名}`

这些 path 不是数据库字段, 而是后续 `/paths-load` 的读取入口.

### `path_index` 当前规则

当 `include_path_index = true` 时, 当前会动态生成 path index.

只会为当前品牌"确实有内容"的节点创建 path, 例如:

1. `品牌介绍`
2. `管理团队`
3. 每个产品节点
4. 每个竞品节点
5. `权威荣誉`
6. `客户案例`
7. `敏感话题`
8. `附件资料`
9. `官方商城`
10. `官方媒体与矩阵`

如果某一类数据当前为空:

- 对应 path 不会出现在 `path_index` 里

### `path_index.summary` 当前规则

每个 path 的摘要当前是这样生成的:

1. 先用本地 fallback summary
2. 再尝试对 path 正文内容调用 `summarize_text(...)`
3. 如果模型总结成功, 用模型总结
4. 如果失败, 回退到 fallback summary
5. 最终截断到 120 字

所以:

- `path_index.summary` 不是稳定的原表字段
- 它是派生摘要

### `include_path_index = false` 当前行为

当前如果显式传 `false`:

- 仍会返回 `meta`
- 但响应里会移除 `path_index`

这意味着:

- 当前这条接口既能当导航入口
- 也能当纯 meta 读取接口

## `POST /api/v1/brands/{brand_code}/paths-load`

### 目标

按 path 列表批量加载品牌知识节点正文.

### 参数规则

- `brand_code` 必填
- `paths` 必填
- `knowledge_revision` 可选

当前会先把 `paths` 做 trim, 空字符串会被丢弃.

如果 trim 后没有有效 path:

- 返回 `400`

### `knowledge_revision` 当前规则

如果请求带了 `knowledge_revision`, 且当前品牌存在 `knowledge_revision`, 当前要求两者完全相等.

不相等时:

- 返回 `409`

当前语义是:

- 调用方可以用它做"读取版本校验"
- 不是触发切换版本

### 当前读取逻辑

这条接口和 `/meta` 共用同一套品牌快照与 path 渲染逻辑.

当前支持的 path 类型主要就是 `path_index` 里那批:

- `品牌介绍`
- `管理团队`
- `产品信息/{产品名}`
- `竞品信息/{竞品名}`
- `权威荣誉`
- `客户案例`
- `敏感话题`
- `附件资料`
- `官方商城`
- `官方媒体与矩阵`

### `paths-load` 当前实现说明

当前实现里, `paths-load` 做了两层只影响性能、不改变响应语义的优化:

1. 同一次请求里, 如果命中了完整品牌知识库 Markdown, 会先构建一次 Markdown 索引, 供多个 path 复用
2. 同一进程内, 会按 `brand_code + knowledge_revision + path` 做短 TTL 的内存缓存

当前缓存规则:

- 默认 TTL 为 `600` 秒
- 可通过环境变量 `KB_BRAND_PATHS_LOAD_CACHE_TTL_SECONDS` 调整
- `knowledge_revision` 变化后会自然切换到新 cache key, 不会复用旧 revision 的 path 正文
- 后续 `paths-load` 访问会周期性顺手清理当前进程内已过期的旧 cache key

因此:

- 这层缓存不改变接口返回结构
- 它只用于减少重复正文渲染与 Markdown 解析开销

### 返回结构规则

当前返回:

- `assets`
- `missing_paths`

对于每个请求 path:

1. 能渲染出正文, 就进入 `assets`
2. 渲染不出来, 就进入 `missing_paths`

当前 `missing_paths[].reason` 固定写:

- `not_found`

### `assets` 当前字段语义

每个 asset 当前包含:

- `title`
- `path`
- `content`
- `knowledge_revision`
- `updated_at`

其中:

- `content` 是接口现场渲染出的 Markdown 正文
- `knowledge_revision` 取的是当前品牌 revision
- `updated_at` 取该节点可获得的更新时间, 常见是品牌更新时间或产品更新时间

所以这条接口当前更像:

- path -> Markdown asset 渲染器

而不是:

- 直接从某张单表里读现成正文

## `POST /api/v1/brands/ai-knowledge/latest`

### 目标

返回当前品牌最新正式 AI 知识库 Markdown 的下载信息.

### 参数规则

- `brand_code` 必填

当前错误边界:

- `brand_code` 为空: `400`
- 品牌不存在: `404`
- 找不到可下载 Markdown: `404`
- 生成 OSS 下载链接失败: `500`

### 当前双来源规则

这条接口当前不是单一路径取数, 而是两段回退:

#### 第一优先级

优先查:

- `brand_full_knowledge_files`

具体条件是:

1. 能拿到最新记录
2. 该记录有 `oss_key`
3. 该记录有 `file_name`
4. 能成功生成 `oss_url`

只有这 4 个条件都满足, 才会直接返回:

- `source = brand_full_knowledge_files`

#### 第二优先级

如果第一优先级没成功, 当前会回退到 OSS 目录扫描.

当前会扫描的前缀是:

1. `{safe_brand_name}/ai_knowledge/`
2. `test/{safe_brand_name}/ai_knowledge/`

只取后缀为 `.md` 的对象, 再按文件名里的版本号和日期排序, 选最新一个.

命中后返回:

- `source = oss`

### 当前找不到文件时的表现

如果两段回退都找不到:

- service 层会返回空 `oss_key` / 空 `oss_url`
- router 层会进一步把它转成 `404`
- 错误信息是"品牌 AI 知识库 Markdown 不存在"

所以:

- 这条接口不会稳定返回一个"空成功"
- 对调用方来说, 缺文件当前就是 `404`

### 当前只保证 Markdown 下载信息

虽然正式知识库表里也有 PDF 字段, 但这条接口当前返回模型只保证 Markdown 主文件:

- `file_name`
- `oss_key`
- `oss_url`

它不是"最新品牌知识库全部产物详情接口".

## 当前最容易混淆的地方

### 为什么 `/brands/{brand_code}/meta` 的产品数可能比 `brand_products` 多

因为它会把 `attachment_products` 也合并进展示层.

### 为什么某些 path 在 `/meta` 的 `path_index` 里没有

因为当前 `path_index` 只为"当前有内容"的节点生成.

### 为什么 `/paths-load` 里有 `missing_paths`

因为它按 path 逐个渲染, 不是先校验所有 path 都存在再统一失败.

### 为什么 `/brands/ai-knowledge/latest` 会 `404`, 但品牌明明存在

因为这条接口不只是校验品牌存在, 还要求当前能拿到可下载的最新 Markdown.

## 调整这组接口规则时, 需要同步检查

1. `/brands` 的 `website` 是否仍然做 URL 归一化.
2. `/meta.products` 是否仍然合并 `brand_products` 与 `attachment_products`.
3. `path_index` 是否仍然只为有内容的节点生成.
4. `/paths-load` 的 `knowledge_revision` 是否仍然只是版本校验.
5. `/brands/ai-knowledge/latest` 是否仍然走 `brand_full_knowledge_files -> OSS` 的双来源回退.
6. 找不到最新 Markdown 时是否仍然返回 `404`.
