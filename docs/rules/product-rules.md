# 产品规则

最后校对日期: 2026-10-09

## 这份文档讲什么

当前系统里的"产品"不是只有一份数据.

至少要区分两层:

1. 主产品白名单
2. 附件抽取产品副本

很多误解都来自把这两层混成一层.

## 一句话结论

现在产品的统一理解是:

- `brand_products` / 回调 `knowledge.products` 看主产品白名单
- `brand_knowledge_json.attachment_products` / `other_info -> 附件解析新增产品` 看附件产品副本

## 第一层: 主产品白名单

### 当前存在哪里

- MySQL `brand_products`

### 当前作用

这是:

- 主产品集合
- 对外主产品口径
- 回调里 `knowledge.products` 的主要来源

### 当前特点

- 不等于附件里抽到的全部产品
- 更像"当前允许当成正式主产品返回的那批产品"

### `brand_products` 表结构和迁移说明

`brand_products` 当前最终结构要支持两件事:

1. 有 `product_code` 的主产品, 用 `product_code` 作为身份.
2. 同一个品牌下允许出现同名但不同 `product_code` 的产品.

迁移演进如下:

| 迁移 | 作用 |
| --- | --- |
| `005_brand_products.sql` | 初始建表, 只有基础产品字段, 并加了 `uk_brand_product_name (brand_name, product_name)` |
| `012_alter_brand_products_add_detail_fields.sql` | 增加 `brand_id` 和产品详情字段, 并加了 `uk_brand_id_product_name (brand_id, product_name)` |
| `042_alter_brand_products_add_product_code.sql` | 增加 `product_code`, 加唯一索引 `uk_brand_products_product_code (product_code)` 和查询索引 `idx_brand_products_brand_product_code (brand_id, product_code)` |
| `044_alter_brand_products_allow_same_name_different_code.sql` | 删除基于产品名的两个唯一索引, 改成普通索引, 允许同名不同 `product_code` 共存 |

因此当前要保留的唯一性规则是:

- `product_code` 非空时, 当前系统把它当成全局唯一产品编码.
- `product_name` 只是展示名 / 查询辅助字段, 不是唯一身份.
- `brand_name + product_name` 和 `brand_id + product_name` 都只能做普通查询索引, 不能再做唯一约束.

当前建议索引状态:

| 索引 | 类型 | 说明 |
| --- | --- | --- |
| `uk_brand_products_product_code` | unique | 有编码产品的主身份 |
| `idx_brand_products_brand_product_code` | normal | 按品牌和产品编码查询 |
| `idx_brand_products_brand_name_product_name` | normal | 兼容按品牌名和产品名查询, 不能唯一 |
| `idx_brand_products_brand_id_product_name` | normal | 兼容按品牌 ID 和产品名查询, 不能唯一 |

注意:

- MySQL 里 `UNIQUE(product_code)` 允许多条 `product_code = NULL`, 所以历史无编码产品可以继续存在.
- 如果线上还没执行 `044`, 同品牌同名不同 `product_code` 的新产品会被旧唯一索引拦住.
- 如果未来上游的 `product_code` 只保证品牌内唯一, 需要同时调整索引和代码, 不能只改文档.

## 第二层: 附件抽取产品副本

### 当前存在哪里

主要有两份镜像:

1. `brand_knowledge_json`
   - `knowledge_type = attachment_products`
2. `brand_knowledge_json`
   - `knowledge_type = other_info`
   - 其中一条
     - `title = 附件解析新增产品`

### 当前作用

这是:

- 附件抽取出的产品副本
- 给知识快照、知识库正文、人工确认编辑、补充展示使用

它不是:

- 主产品白名单

## 当前为什么要拆两层

因为真实业务里经常会出现:

1. 附件里抽到了很多产品
2. 但业务上只希望其中一部分成为主产品

如果不拆层, 就会出现两个问题:

1. 回调 `knowledge.products` 会越来越脏
2. 结构化产品更新和附件补充产品会互相覆盖

所以现在的拆法是有意为之.

## 各条链路里的当前规则

## 第一类: `/api/v1/brands/upload`

核心文档:

- [brands-upload.md](./brands-upload.md)

### `products = []`

当前语义是:

- 本次没有主产品白名单
- 附件抽到的产品不会写入 `brand_products`
- completed 回调里的 `knowledge.products` 也返回 `[]`

但是:

- 附件抽到的产品仍然要写入 `attachment_products`
- 也仍然要镜像到 `other_info -> 附件解析新增产品`

### `products != []`

当前语义是:

- 请求里的 `products` 就是主产品白名单
- `brand_products` 只围绕这批白名单做 merge / 回填
- completed 回调里的 `knowledge.products` 也只返回这批白名单产品

与此同时:

- 附件抽到的产品仍然会额外保留到 `attachment_products`
- 也会镜像到 `other_info -> 附件解析新增产品`

## 第二类: `/api/v1/knowledge/update`

核心文档:

- [knowledge-update.md](./knowledge-update.md)

### 主产品怎么改

顶层 `products` 会尝试更新:

- `brand_products`

completed 回调里的:

- `knowledge.products`

也看这一层.

当前这条链路的精确语义是:

- 只有带非空 `product_code` 的顶层产品才会写入 `brand_products`
- 没有 `product_code` 的产品会跳过主产品表写入, 不报错
- 没有 `product_code` 的产品仍然可以作为结构化变更参与审计和正式知识库重建
- `products` 不是全量替换语义, 没传或少传某个旧产品都不会删除 `brand_products` 里的旧数据

主产品身份以 `product_code` 为准:

- `product_code` 相同: 更新同一个产品
- `product_code` 不同: 视为不同产品, 即使 `product_name` 相同也允许同时保存
- `product_name` 不是主产品唯一性判断依据
- 历史同品牌同名但没有 `product_code` 的旧产品, 可以被后续带 `product_code` 的请求回填为正式主产品

### 附件产品副本怎么改

当前不允许显式直传顶层:

```json
{
  "attachment_products": [...]
}
```

当前唯一对外写法是改:

- 顶层 `other_info`
- 其中 `title = 附件解析新增产品`

系统收到后会自动:

1. 解析为 `attachment_products`
2. 同步写回 `brand_knowledge_json.attachment_products`
3. 重建 `other_info`

### 当前最重要的闭环

这条线现在是:

1. 改 `products` -> 只把带 `product_code` 的产品更新到主产品白名单
2. 改 `other_info.附件解析新增产品` -> 更新附件产品副本
3. completed 回调:
   - `knowledge.products` 返回主产品白名单
   - `knowledge.other_info` 返回附件产品副本镜像

## 第三类: `/brands/attachments/preview-parse + /confirm`

核心文档:

- [attachment-preview-confirm.md](./attachment-preview-confirm.md)

当前确认完成后:

- 最终结构化结果会写回 `brands` / `brand_products` / `brand_knowledge_json`

就产品规则来说, 当前也要遵守同一原则:

- 主产品看 `brand_products`
- 附件产品副本看 `attachment_products` + `other_info.附件解析新增产品`

## 第四类: Markdown 结构化快照回补

核心文档:

- [backfill.md](./backfill.md)

当前这条线会把 Markdown 里的产品做结构化快照回写.

现在的设计目标仍然是:

- 主产品层和附件产品副本层不要混掉

也就是说:

- 如果这条回补线需要保留附件产品副本, 也应该继续写 `attachment_products`
- 不应该简单把所有 Markdown 产品都直接塞进 `brand_products`

## 回调里的当前产品规则

## `knowledge.products`

当前统一目标:

- 返回主产品白名单

不要把它理解成:

- 当前品牌所有被抽出来的产品全集

## `knowledge.other_info`

当前会通过:

- `title = 附件解析新增产品`

来暴露附件产品副本.

所以如果你在回调里看到:

- `products = []`
- 但 `other_info` 里有 `附件解析新增产品`

这在当前规则下是完全正常的.

## 查询 / 排查时该看哪

### 想知道主产品是什么

优先看:

1. `brand_products`
2. completed 回调里的 `knowledge.products`

### 想知道附件里额外抽到了什么产品

优先看:

1. `brand_knowledge_json.attachment_products`
2. `brand_knowledge_json.other_info -> 附件解析新增产品`
3. completed 回调里的 `knowledge.other_info`

### 想看"综合展示产品"

当前部分读接口会做展示层合并:

- 先显示 `brand_products`
- 再补不重名的 `attachment_products`

但这个"展示并集"不等于主产品白名单.

## 当前最容易混的地方

### 1. `knowledge.products` 为什么不是所有产品

因为当前规则就是:

- 它只看主产品白名单

### 2. `attachment_products` 为什么还要在 `other_info` 里再放一份

因为:

- `other_info` 更适合给编辑界面 / 回调消费 / 非标准分区展示使用
- `attachment_products` 更像系统内部结构化副本

所以现在保留两份镜像是有意设计.

### 3. `/knowledge/update` 为什么不能直接传 `attachment_products`

因为当前对外约定已经改成:

- 通过 `other_info.附件解析新增产品` 编辑

这样可以把:

- 编辑入口
- 存储副本
- 回调展示

收敛成一套联动规则.

## 当前产品相关字段总表

| 字段 / 表 | 当前含义 |
| --- | --- |
| `brand_products` | 主产品白名单, 主身份看 `product_code` |
| `brand_knowledge_json.attachment_products` | 附件产品副本 |
| `other_info -> 附件解析新增产品` | 附件产品副本的展示 / 编辑镜像 |
| `knowledge.products` | 回调里的主产品白名单 |
| `knowledge.other_info` | 回调里的附件产品副本镜像 |

## 调整产品规则时, 至少同步检查

1. 改的是主产品白名单, 还是附件产品副本.
2. `knowledge.products` 的口径是否会变化.
3. `attachment_products` 和 `other_info.附件解析新增产品` 是否还能保持同步.
4. `/brands/upload`、`/knowledge/update`、附件确认链路是否还遵守同一套产品规则.
5. 回调和回补是不是也跟着一起改了.
