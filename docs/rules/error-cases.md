# 常见报错与排查规则

最后校对日期: 2026-07-17

## 用法

遇到报错时, 先按"报错文案 -> 触发位置 -> 优先检查字段"排查.

这份文档只记录当前已经稳定存在、且容易误判的规则错误.

## `/documents/upload` 入口层

### `metadata must be a valid JSON object`

触发位置:

- `metadata` JSON 反序列化失败

优先检查:

1. 表单里的 `metadata` 是否是合法 JSON
2. 是否把单引号、转义或引号写坏了

### `metadata must be a JSON object`

触发位置:

- `metadata` 虽然能反序列化, 但结果不是 object

优先检查:

1. 是否误传了数组
2. 是否误传了字符串字面量

## 正式品牌 AI 知识库入库层

### `正式知识库文件名不符合规范`

触发位置:

- 文件名没匹配 `【品牌名】品牌AI知识库_V版本_日期.xxx`

优先检查:

1. 中括号和固定中文文案是否完整
2. `V` 版本号格式是否正确
3. 日期是否是 8 位

### `文件名中的品牌名与请求中的 brand_name 不一致`

触发位置:

- 文件名解析出的品牌名和请求里的 `brand_name` 严格不相等

优先检查:

1. 文件名里的品牌名
2. metadata 里的 `brand_name`
3. metadata 里的 `category`

注意:

- 当前调用会优先取 `brand_name`, 否则回退 `category`
- 所以即使没显式传 `brand_name`, 也可能是 `category` 在参与比较

### `请求中的 brand_code / brand_name 不匹配`

触发位置:

- `brand_code` 查到的品牌主数据名称, 与请求 `brand_name` 严格不一致

优先检查:

1. `brands` 表里该 `brand_code` 对应的正式 `brand_name`
2. 请求中的 `brand_name`
3. 文件名中的品牌名

### `知识库版本过旧`

触发位置:

- 上传版本号小于当前品牌已有的最新版本号, 且没有开启 `force_reingest`

优先检查:

1. 当前品牌最新正式知识库版本
2. 本次文件名中的 `Vx`
3. 是否本来就希望强制重入库

## 品牌附件资产层

### `brand_code 不能为空`

触发位置:

- 已经命中品牌附件资产分支, 但 metadata 里拿不到 `brand_code`

优先检查:

1. metadata 是否带了 `brand_code`
2. 调用方是否本来就不该走品牌附件分支

### `brand_name 不能为空`

触发位置:

- 已经命中品牌附件资产分支, 但 `brand_name or category` 都解析不到值

优先检查:

1. metadata.brand_name
2. metadata.category

### `附件缺少 source_url`

触发位置:

- 需要按 URL 下载或处理附件, 但找不到 `source_url`

优先检查:

1. `_task_payload.file_metadata_by_index`
2. 调用方是否只给了文件名没有给 URL

## 附件冲突确认链路

### `当前会话不处于可生成正式知识库的状态`

触发位置:

- 冲突确认会话状态不是 `waiting_user_input` 或 `no_conflicts`

优先检查:

1. session 当前状态
2. round 是否已经变化

### `未生成有效的最终品牌知识库 Markdown`

触发位置:

- 冲突确认后没有产出有效最终 Markdown

优先检查:

1. 本轮 resolution 是否完整
2. 源 Markdown 是否能正确读取

## 查表建议

### 结构化知识异常

优先查:

1. `brands`
2. `brand_products`
3. `brand_knowledge_json`

### 正式知识库异常

优先查:

1. `brand_full_knowledge_files`
2. `brand_knowledge_facts`
3. `brand_knowledge_ingestion_jobs`

### 上传异步状态异常

优先查:

1. `upload_tasks`
2. `upload_task_files`
