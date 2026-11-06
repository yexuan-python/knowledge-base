# 接口真相矩阵 / 废弃接口规则

最后校对日期: 2026-08-20

## 目标

这份文档只说明 3 件事:

1. 当前 FastAPI 实际注册了哪些对外接口
2. 哪些接口只存在于旧文档, 但当前代码没有对外暴露
3. 哪些能力虽然还有内部实现, 但现在不是公开 API

这里的"真相来源"只看当前应用启动时实际 `include_router(...)` 进去的路由.

主代码锚点:

- [knowledge_base/api_app/app.py](../../knowledge_base/api_app/app.py)
- [knowledge_base/api_app/routers/__init__.py](../../knowledge_base/api_app/routers/__init__.py)

## 当前已注册路由

应用启动时当前只注册了 6 组 router:

- `health_router`
- `documents_router`
- `brands_router`
- `brand_knowledge_router`
- `knowledge_router`
- `background_jobs_router`

对应代码:

- [knowledge_base/api_app/app.py](../../knowledge_base/api_app/app.py)
- [knowledge_base/api_app/routers/__init__.py](../../knowledge_base/api_app/routers/__init__.py)

因此, 当前真正对外启用的接口只有下面这些.

## 当前启用接口矩阵

| 方法 | 路径 | 当前状态 | 代码入口 | 说明 |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/health` | 启用 | `routers/health.py` | 健康检查 |
| `POST` | `/api/v1/documents/upload` | 启用 | `routers/documents.py` | 上传文件并创建后台任务 |
| `POST` | `/api/v1/brands/facts/upload` | 启用 | `routers/documents.py` | 同步上传品牌 Markdown，仅重建 facts |
| `POST` | `/api/v1/documents/upload-tasks` | 启用 | `routers/documents.py` | 查询上传任务状态 |
| `POST` | `/api/v1/search` | 启用 | `routers/documents.py` | 检索文本 chunk |
| `POST` | `/api/v1/images/search` | 启用 | `routers/documents.py` | 检索图片资产 |
| `POST` | `/api/v1/brands/attachments/delete` | 启用 | `routers/documents.py` | 删除品牌知识里的附件挂载 |
| `POST` | `/api/v1/brands/facts` | 启用 | `routers/documents.py` | 按品牌名检索 facts |
| `POST` | `/api/v1/categories/facts` | 启用 | `routers/documents.py` | 兼容旧字段名的 facts 检索入口 |
| `GET` | `/api/v1/brands` | 启用 | `routers/brands.py` | 品牌列表 |
| `GET` | `/api/v1/brands/{brand_code}/meta` | 启用 | `routers/brands.py` | 品牌 meta 与 path index |
| `POST` | `/api/v1/brands/{brand_code}/paths-load` | 启用 | `routers/brands.py` | 按路径加载品牌知识片段 |
| `POST` | `/api/v1/brands/ai-knowledge/latest` | 启用 | `routers/brands.py` | 读取品牌最新正式 AI 知识库文件 |
| `POST` | `/api/v1/brands/upload` | 启用 | `routers/brands.py` | 品牌上传主链路 |
| `POST` | `/api/v1/brands/delete` | 启用 | `routers/brands.py` | 品牌删除预览 / 执行删除 |
| `POST` | `/api/v1/brands/attachments/preview-parse` | 启用 | `routers/brand_knowledge.py` | 附件预解析草稿 |
| `POST` | `/api/v1/brands/attachments/confirm` | 启用 | `routers/brand_knowledge.py` | 确认附件解析并正式入库 |
| `GET` | `/api/v1/brands/attachments/confirm/result/{job_id}` | 启用 | `routers/brand_knowledge.py` | 查询确认结果 |
| `POST` | `/api/v1/brands/attachments/review-changes` | 启用 | `routers/brand_knowledge.py` | 审稿变更对比 |
| `POST` | `/api/v1/brands/knowledge-base/conflict-sessions` | 启用 | `routers/brand_knowledge.py` | 创建冲突会话 |
| `POST` | `/api/v1/brands/knowledge-base/conflict-session/latest` | 启用 | `routers/brand_knowledge.py` | 读取最新冲突会话, 同时可作为品牌 AI 知识库统一展示态查询入口 |
| `POST` | `/api/v1/brands/knowledge-base/conflict-sessions/resolutions` | 启用 | `routers/brand_knowledge.py` | 提交冲突决议 |
| `POST` | `/api/v1/knowledge/update` | 启用 | `routers/knowledge.py` | 更新结构化品牌知识 |
| `GET` | `/api/v1/background-jobs/{job_id}` | 启用 | `routers/background_jobs.py` | 查询 background job |

## 当前未对外启用, 但旧文档仍可能出现的接口

下面这些接口在当前 `api_app` 路由里没有注册.

这意味着:

- Swagger 不会出现
- 外部请求不会命中
- 旧文档如果仍写着它们, 要按"历史遗留描述"理解, 不能再当成当前公开能力

| 方法 | 路径 | 当前状态 | 现状说明 |
| --- | --- | --- | --- |
| `POST` | `/api/v1/documents/delete` | 未启用 | 当前没有路由入口; 只有内部 `delete_document(...)` 能力 |
| `POST` | `/api/v1/fulltext` | 未启用 | 当前没有路由入口; 只有内部 `get_full_text(...)` 能力 |
| `POST` | `/api/v1/categories/facts/matched` | 未启用 | 当前没有路由入口; 只有内部 matched facts 检索方法 |
| `POST` | `/api/v1/documents/text` | 未启用 | 当前没有路由入口 |

旧文档残留位置示例:

- [API.md](../../API.md)
- [README.md](../../README.md)

## 当前属于"内部能力存在, 但不是公开 API"的功能

下面这些能力当前仍在 service / application 层存在, 但没有对外 HTTP 路由:

1. 文档删除
   - `KnowledgeBaseService.delete_document(...)`
   - `DocumentApplicationService.delete_document(...)`
2. 全文读取
   - `KnowledgeBaseService.get_full_text(...)`
   - `IngestApplicationService.get_full_text(...)`
3. matched facts 检索
   - `search_facts_by_brand_name_matched(...)`
   - `search_facts_by_category_matched(...)`

这类能力现在要理解成:

- 可以被内部流程复用
- 不能默认等同于"前端可直接调用的公开接口"

## `/brands/facts` 与 `/categories/facts` 的真相

这两个路径当前都存在, 并且共用同一个路由处理函数.

真实语义是:

- `/brands/facts` 是当前品牌名口径
- `/categories/facts` 是兼容旧 `category` 字段名的别名入口

因此:

- 它们不是两套独立实现
- 它们当前返回同一套 response 结构

代码锚点:

- [knowledge_base/api_app/routers/documents.py](../../knowledge_base/api_app/routers/documents.py)

## 当前判断接口是否"真的存在"的优先级

遇到文档不一致时, 当前推荐按下面顺序判断:

1. `knowledge_base/api_app/app.py` 里是否 `include_router(...)`
2. 对应 router 文件里是否真的存在 `@router.get(...)` / `@router.post(...)`
3. 请求模型和响应模型是否仍然被该路由引用
4. 最后才看 `API.md` / `README.md`

也就是说:

- `API.md` 不是接口启用状态的最高真相源
- `README.md` 也不是
- 当前最高真相源是实际注册路由

## 什么时候算"废弃"

当前规则里, 一个接口只要满足下面任一条件, 就应视为"未启用 / 已废弃对外暴露":

1. `app.py` 没有注册它所在 router
2. 对应 router 里没有这个路径
3. 只有 service 方法, 没有 HTTP 路由

即使:

- 底层代码还能调用
- 旧文档还保留示例
- 数据结构还存在

也不能把它当成当前公开 API.

## 调整接口时, 需要同步检查

1. `knowledge_base/api_app/app.py` 的 router 注册是否变化.
2. 对应 `router` 文件里的路径是否变化.
3. [API.md](../../API.md) 与 [README.md](../../README.md) 是否仍残留旧接口描述.
4. [docs/rules/INDEX.md](./INDEX.md) 是否需要补新分链路文档.
5. Swagger `/docs` 里展示的接口集合是否与规则文档一致.
