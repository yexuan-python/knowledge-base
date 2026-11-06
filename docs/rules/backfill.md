# 回补规则

最后校对日期: 2026-07-18

## 这份文档讲什么

这里的"回补", 指的是:

- 已经有了某份品牌知识来源
- 再把它结构化后写回 `brands` / `brand_products` / `brand_knowledge_json`

当前代码里, 不是只有 1 套回补, 而是至少有 3 套:

1. 附件抽取回补
2. Markdown 结构化快照回补
3. 手工 backfill 脚本回补

## 三套回补的总览

| 回补类型 | 典型入口 | 主要输入 | 写库策略 | 典型产物 |
| --- | --- | --- | --- | --- |
| 附件抽取回补 | `/api/v1/brands/upload` | 品牌附件解析结果 | merge 后直接写结构化表 | `brands`、`brand_products`、`brand_knowledge_json` |
| Markdown 结构化快照回补 | `/api/v1/documents/upload` 上传正式品牌 AI 知识库文件；附件冲突确认完成后生成最终 Markdown | `【品牌名】品牌AI知识库_Vx_日期.md` | 结构化解析后回写；`/documents/upload` 保留当前混合 merge 规则，不是全量替换 | `brand_knowledge_json`，部分链路再同步 `brands` / `brand_products` |
| 手工 backfill 脚本 | `scripts/backfill_brand_from_markdown.py` | 本地或 OSS 的 Markdown | 可全量写，也可只补空值 / 只写部分 section | `brands`、`brand_products`、`brand_knowledge_json` |

## 第一套: 附件抽取回补

### 入口

- `POST /api/v1/brands/upload`
- 旧品牌主上传链路里的附件抽取与 merge

核心代码锚点:

- [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py)
- [knowledge_base/brand/knowledge_extraction.py](../../knowledge_base/brand/knowledge_extraction.py)

### 当前行为

这套回补更像:

1. 先解析附件
2. 按知识分区做抽取
3. 程序化 merge
4. 再把 merge 结果直接写回结构化表

当前主要会写:

- `brands`
- `brand_products`
- `brand_knowledge_json`

### 产品规则

这套回补里的产品现在统一分成两层:

1. 主产品白名单
   - 来自请求里的顶层 `products`
   - 写入 `brand_products`
2. 附件抽取产品副本
   - 写入 `brand_knowledge_json.attachment_products`
   - 同时镜像到 `brand_knowledge_json.other_info` 里的
     - `title = 附件解析新增产品`

也就是说:

- `brand_products` 不等于附件里抽到的全部产品
- 附件里新增的产品副本会单独保留

### 当前适用场景

- 需要用原始品牌附件直接驱动结构化品牌知识生成
- 不需要先人工确认附件内容

## 第二套: Markdown 结构化快照回补

### 入口

当前主要有两种来源:

1. `/api/v1/documents/upload` 上传正式品牌 AI 知识库文件
2. 附件冲突确认完成后, 已生成最终 `【品牌名】品牌AI知识库_Vx_日期.md`

核心代码锚点:

- [knowledge_base/brand/application/ai_knowledge_ingestion.py](../../knowledge_base/brand/application/ai_knowledge_ingestion.py)
- [knowledge_base/brand/knowledge_extraction.py](../../knowledge_base/brand/knowledge_extraction.py)
- [knowledge_base/brand_knowledge/application/service.py](../../knowledge_base/brand_knowledge/application/service.py)

### 这套回补和附件抽取回补的差别

它不是"根据原始附件抽结构化结果", 而是:

- 直接把一份已经成形的品牌知识 Markdown
- 当成最终知识源
- 重新结构化成 snapshot
- 再写回结构化表

所以它更接近:

- 最终稿回写
- 最终知识快照回写

### 当前两种具体用法

#### A. `/documents/upload` 上传正式知识库文件

当前行为:

1. 先把正式品牌 AI 知识库文件入正式知识库链路
2. 成功后, 再对这份 Markdown 做结构化解析
3. 然后按当前保留的 merge 规则回写 `brand_knowledge_json`

这里的关键词是:

- `backfill_brand_knowledge_json_empty_only = true`

也就是:

- 这个开关名保留了历史含义, 但当前实际行为已经不是“所有字段都只补空值”
- 当前这条线不是拿正式 Markdown 去强覆盖所有结构化字段
- 当前保留的实际规则是:
  - `competitors`: 只补已有竞品的空字段, 不新增, 不整表替换
  - `brand_products`: 不直接改
  - `attachment_products`: 用 Markdown 抽出的产品, 扣掉 `brand_products` 已有产品后, 重建副本并写回
  - `brands.intro`: 保留旧值优先, 只有旧值为空时才用 incoming
  - 其他大部分 `brand_knowledge_json` 分区: 新值非空时优先覆盖, 新值为空时保留旧值

#### B. 附件冲突确认完成后的最终稿回写

当前行为:

1. 先生成最终正式知识库 Markdown / PDF
2. 再基于最终 Markdown 构建结构化 snapshot
3. 再同步更新 `brands`、`brand_products`、`brand_knowledge_json`

这条线和上面的 `/documents/upload` 差别在于:

- 它不是"只补空值"就结束
- 而是把本次最终确认结果当成最新知识真相同步回结构化表

## 第三套: 手工 backfill 脚本回补

### 入口

- [scripts/backfill_brand_from_markdown.py](../../scripts/backfill_brand_from_markdown.py)

### 当前行为

这套脚本复用现有抽取和部分回调格式能力, 但它不经过线上上传接口.

它可以:

1. 读本地 Markdown
2. 读 OSS `品牌名/converted/`
3. 做 LLM 抽取
4. 可选做天眼查补空
5. 再把结果写回品牌表

### 当前可控参数

它至少支持这些模式:

- `--dry-run`
- `--skip-tianyancha`
- `--write-sections`
- `--fill-empty-only`
- `--callback` / `--callback-url`

也就是说这套脚本既可以:

- 只预览结果不写库
- 只写指定分区
- 只补空值
- 写库成功后回调上游

### 当前写库范围

脚本里定义的可写 section 包括:

- `basic_info`
- `products`
- `attachment_products`
- `company_profile`
- `management_team`
- `competitors`
- `authority_honors`
- `customers_cases`
- `sensitive_topics`
- `attachments`
- `official_malls`
- `official_media_matrix`
- `other_info`

## 三套回补的共同规则

### 1. 最终目标表还是那三张

结构化回补最终重点仍然是:

- `brands`
- `brand_products`
- `brand_knowledge_json`

### 2. 产品规则现在要统一看两层

不管哪条回补线, 当前都要区分:

- `brand_products`: 主产品白名单
- `brand_knowledge_json.attachment_products`: 附件产品副本

并且附件产品副本还要镜像到:

- `other_info -> 附件解析新增产品`

### 3. 回补不等于正式知识库入库

要特别注意:

- 回补是在更新结构化表
- 正式知识库入库是在更新 `brand_full_knowledge_files` / `brand_knowledge_facts`

二者相关, 但不是同一件事

## 最容易混的地方

### "现在只有一套回补吗"

不是.

当前至少有:

1. 附件抽取回补
2. Markdown 结构化快照回补
3. 手工 backfill 脚本回补

### "正式知识库文件上传成功, 就一定全量改了 `brand_knowledge_json` 吗"

不一定.

当前 `/documents/upload` 的正式知识库文件分支, 文档规则是:

- 先正式入库
- 再做 Markdown 结构化快照回补
- 这一步默认按当前保留的混合 merge 规则写 `brand_knowledge_json`

其中实际口径是:

- `competitors`: 只补已有竞品的空字段, 不新增, 不整表替换
- `brand_products`: 不直接改
- `attachment_products`: 只重建附件产品副本
- 其他大部分分区: 新值非空时优先覆盖, 新值为空时保留旧值

### "附件确认完成后, 现在是不是只生成 Markdown"

不是.

当前会在生成最终 Markdown 后, 再把最终结构化 snapshot 同步回结构化表.

## 调整回补规则时, 至少要同步检查

1. 是哪一套回补在改.
2. 输入源是原始附件, 还是最终 Markdown.
3. 写库是全量覆盖, 还是当前这种混合 merge 规则.
4. 产品是写 `brand_products`, 还是写 `attachment_products`, 还是两者都写.
5. 回补完成后, 回调口径是否也需要同步调整.
