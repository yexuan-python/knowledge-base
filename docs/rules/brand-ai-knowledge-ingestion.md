# 正式品牌 AI 知识库文件入库规则

最后校对日期: 2026-08-05

## 入口与范围

这条链路描述的是"正式品牌 AI 知识库 Markdown 或 PDF"的入库规则.

当前会从以下入口进入:

1. `/api/v1/documents/upload` 上传符合命名规范的知识库文件
2. 附件冲突确认会话完成后, 系统生成最终 Markdown, 再发布为正式知识库文件

不包含的入口:

- `POST /api/v1/brands/facts/upload`

原因:

- 那条接口虽然也会读取 Markdown 并抽取 facts
- 但它不是“正式品牌 AI 知识库文件入库”
- 它不会创建/更新 `brand_full_knowledge_files`
- 不会回写 `brand_knowledge_json`
- 也不会走正式知识库完成回调

核心实现:

- [knowledge_base/brand/application/ai_knowledge_ingestion.py](../../knowledge_base/brand/application/ai_knowledge_ingestion.py)
- [knowledge_base/brand/ai_knowledge_filename.py](../../knowledge_base/brand/ai_knowledge_filename.py)
- [knowledge_base/upload_task/application/service.py](../../knowledge_base/upload_task/application/service.py)
- [knowledge_base/brand_knowledge/application/service.py](../../knowledge_base/brand_knowledge/application/service.py)

## 文件名规则

当前文件名正则:

`^[【「](?P<brand_name>.+?)[】」]品牌AI知识库_V(?P<version_no>\d+)_(?P<knowledge_date>\d{8})\.(?P<ext>[^.]+)$`

当前含义:

- `brand_name`: 中括号或引号内的品牌名
- `version_no`: 版本号, 如 `V4`
- `knowledge_date`: 知识日期, 格式 `YYYYMMDD`
- `ext`: 扩展名

当前在 `/documents/upload` 入口里, 只有命中这个模式且扩展名为 `.md` 的文件会被识别成 `brand_ai_knowledge` 角色.

## 进入本链路的前置条件

在真正写库前, 当前会严格校验下面几项:

1. `brand_code` 非空
2. `brand_name` 非空
3. 文件名非空
4. 文件名符合正式知识库命名规范
5. 文件名解析出的 `brand_name` 必须与请求中的 `brand_name` 完全一致
6. `brand_code` 必须能查到品牌
7. 品牌表里的正式 `brand_name` 必须与请求中的 `brand_name` 完全一致

注意:

- 这里是严格全等比较, 不是别名匹配
- `燕之屋` 和 `燕子屋` 在这里会被视为不同品牌名

## 版本规则

当前会读取该品牌最新正式知识库版本:

- 如果上传版本号小于当前最新版本号, 且 `force_reingest = false`, 会直接报"知识库版本过旧"
- 如果内容哈希与已存在版本完全相同, 且 `force_reingest = false`, 会走 `skipped`

## 成功路径

当前成功路径大致如下:

1. 读取源文件字节
2. 如果是 Markdown, 直接规范化文本
3. 如果是非 Markdown, 先解析成 Markdown
4. 计算 `content_hash`
5. 如果内容哈希与已存在版本完全相同, 且 `force_reingest = false`, 直接标记 `skipped`
6. 在 `brand_full_knowledge_files` 创建 `processing` 记录, 先占用版本/修订号唯一键
7. 上传 Markdown 到 OSS
8. 渲染 PDF 并上传到 OSS
9. 回填 `brand_full_knowledge_files` 的 Markdown/PDF OSS 地址
10. 后续更新入库状态、Milvus 状态、facts 状态
11. 提取并写入 `brand_knowledge_facts`
12. 将当前版本提升为最新版本

## 当前主要落库表

| 表 | 当前职责 |
| --- | --- |
| `brand_full_knowledge_files` | 正式知识库文件版本、OSS 地址、Markdown 正文、状态 |
| `brand_knowledge_facts` | 从正式知识库抽取出的 facts |
| `brand_knowledge_ingestion_jobs` | 正式知识库入库任务进度 |

重要结论:

- 这条链路成功后主要写 `brand_full_knowledge_files`
- 不是以 `brand_knowledge_json` 为主产物

## 与 `brand_knowledge_json` 的关系

当前关系是:

- `brand_knowledge_json` 更像结构化知识分区的结果表
- `brand_full_knowledge_files` 更像最终正式知识库文档的版本表
- 二者可以来自相关链路, 但不是同一张表的不同视图

所以:

- 看 `/documents/upload` 的正式知识库文件是否成功, 优先查 `brand_full_knowledge_files`
- 不要只看 `brand_knowledge_json`

## 与 `/brands/facts/upload` 的区别

`POST /api/v1/brands/facts/upload` 当前是一条更轻的 facts-only 链路.

它和本文这条正式知识库入库链路的差别是:

- 输入只接受现成 `.md` 文件
- 不做 PDF / Office -> Markdown 解析
- 不要求文件名命中正式知识库命名规则
- 不写 `brand_full_knowledge_files`
- 不写 `brand_knowledge_ingestion_jobs`
- 不回写 `brand_knowledge_json`
- 不发送正式知识库完成回调
- 只会:
  - 从 Markdown 抽取 facts
  - 写入 `brand_knowledge_facts`
  - 写入 Milvus facts 向量
  - 删除该品牌旧 facts

## 附件冲突会话如何生成正式知识库

当前这条线会先做一次 `scan_brand_knowledge_conflicts(...)` 冲突扫描, 拿到:

- `status`
- `conflicts`
- `auto_merged`
- `scan_summary`

然后统一走 `generate_brand_knowledge_full_markdown(...)` 产出最终 Markdown:

1. 如果 `status=waiting_user_input`, 先等待用户确认 `conflicts`, 再把 `history_resolutions` / `current_resolutions` / `auto_merged` 传给 full-markdown 生成器
2. 如果 `status=no_conflicts`, 则直接以空的 `history_resolutions=[]`、`current_resolutions=[]` 和扫描得到的 `auto_merged` 调 full-markdown 生成器

最终 Markdown 的主输入仍然是扫描阶段读取到的附件 Markdown, 然后再生成 `【品牌名】品牌AI知识库_Vx_日期.md`.

当前发布方式有三种:

- 优先: 直接走 `build_full_brand_knowledge_markdown_from_confirmed_markdown(...)` 这条正式知识库生成路径
- 附件 confirm / 普通知识更新合并路径: 先写 `brand_knowledge_update_audits`, 再由同品牌 `brand_full_knowledge_refresh` 后台任务在配置的延迟窗口内无新变更后统一生成正式知识库
- 回退: 依赖不完整时, 再用临时 `.md` 文件调用 `ingest_upload_task_file(...)`

其中 `brand_full_knowledge_refresh` 使用 `generate_brand_ai_knowledge_from_merged_sources(...)`, 专门处理 `knowledge_update`、`attachment_confirm`、删除/收缩等多来源合并输入. 普通单次结构化更新才继续走 `generate_brand_ai_knowledge_from_structured_update(...)` / `change` / `deletion` 的原有分流.

`brand_full_knowledge_refresh` 的延迟窗口由 `KB_BRAND_FULL_KNOWLEDGE_REFRESH_DELAY_SECONDS` 控制, 默认 `300` 秒. `/knowledge/update` 和 `/brands/attachments/confirm` 都使用这同一份配置.

因此:

- 附件冲突确认生成的最终知识库, 仍然会落到 `brand_full_knowledge_files`
- 附件 confirm 生成的 `{brand_name}-{draft_id}-{review_id}-confirmed-knowledge.md` 只作为本轮 refresh 的 confirmed Markdown 来源, 不再每次 confirm 立即生成一版完整品牌 AI 知识库
- 但实现上不再总是经过 `/documents/upload` 风格的文件再入库动作

## 当前最容易混淆的地方

### metadata 里的品牌名来源

调用本链路时, 上传任务层实际传的是:

- `brand_name` 优先取 `metadata.brand_name`
- 否则回退到 `metadata.category`

这意味着:

- 即使调用方只传了 `category`, 也会被当成正式品牌名参与严格比较

### 报错发生顺序

- "文件名中的品牌名与请求中的 brand_name 不一致" 发生得很早
- 这时往往连正式知识库记录都还没开始创建

## 调整本链路规则时, 需要同步检查

1. 文件名正则是否变化.
2. `/documents/upload` 对 `brand_ai_knowledge` 的识别条件是否变化.
3. 品牌名匹配是否仍然是严格全等.
4. 成功产物是否仍然以 `brand_full_knowledge_files` 为主.
5. 附件冲突确认会话是否仍然优先走正式知识库生成器, 还是回退到文件入库.
