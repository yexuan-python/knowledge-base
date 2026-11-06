# competitors 字段映射现状

最后校对日期: 2026-07-18

## 这份文档解决什么问题

当前系统里的 `competitors` 不是只有一套字段结构.

至少同时存在下面 3 类形态:

1. `/api/v1/knowledge/update` 等外部调用更容易直接传入的字段形态
2. 附件解析、抽取、`brand_knowledge_json` 内部结构化写库常用的字段形态
3. 回调 `knowledge.competitors` 对外返回的字段形态

这会带来一个典型问题:

- 上游传了 `aliases`
- `brand_knowledge_json` 里也可能已经存了 `aliases`
- 但回调 mapper 只读 `competitors_alias`
- 最终回调里的 `knowledge.competitors[].aliases` 可能变空

这份文档只描述当前实现现状, 先把"现在到底有几套字段"固定下来, 方便后续统一.

## 当前主要代码锚点

- 回调输出映射:
  - [knowledge_base/brand/callback_mapper.py](../../knowledge_base/brand/callback_mapper.py)
- 品牌结构化读写与 Markdown 渲染:
  - [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py)
- 附件预解析 / 确认链路:
  - [knowledge_base/brand_knowledge/application/attachment_flow.py](../../knowledge_base/brand_knowledge/application/attachment_flow.py)
- 字段提示词:
  - [knowledge_base/brand_knowledge/field_hints.py](../../knowledge_base/brand_knowledge/field_hints.py)
- knowledge/update 请求模型:
  - [knowledge_base/brand/schemas/requests.py](../../knowledge_base/brand/schemas/requests.py)

## 现状概览

### A. 外部友好字段形态

这套字段更接近上游或前端直觉, 也更接近当前回调的最终展示结构.

常见字段:

- `name`
- `aliases`
- `introduction`
- `official_websites`
- `logo_urls`
- `strengths`
- `differentiated_positioning`
- `comparison_dimensions`
- `other_info`

这套字段目前常见于:

- `/api/v1/knowledge/update` 的 `competitors: list[dict[str, Any]]`
- 回调返回的 `knowledge.competitors.competitors[]`
- 某些品牌服务的读取兼容逻辑

注意:

- `KnowledgeUpdateRequest` 里的 `competitors` 现在是 `list[dict[str, Any]]`
- 也就是当前接口层没有强约束一套唯一子字段结构

对应代码:

- [knowledge_base/brand/schemas/requests.py](../../knowledge_base/brand/schemas/requests.py)
- [knowledge_base/brand/callback_mapper.py](../../knowledge_base/brand/callback_mapper.py)

### B. 内部结构化字段形态

这套字段是附件解析、抽取、内部 merge、更早期结构化链路更常见的字段命名.

常见字段:

- `name`
- `competitors_alias`
- `competitors_description`
- `website`
- `competitors_logo`
- `competitive_advantages`
- `differentiated_positioning`
- `comparison_dimensions`
- `source_section`

这套字段目前常见于:

- 附件解析抽取结果
- `brand_knowledge_json` 某些 section 内容
- 结构化 merge / normalize 逻辑
- Markdown 生成器的内部读取逻辑

对应代码:

- [knowledge_base/brand_knowledge/application/attachment_flow.py](../../knowledge_base/brand_knowledge/application/attachment_flow.py)
- [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py)
- [knowledge_base/brand_knowledge/field_hints.py](../../knowledge_base/brand_knowledge/field_hints.py)

### C. 回调输出字段形态

回调最终输出给调用方时, `knowledge.competitors` 当前目标结构是:

```json
{
  "competitors": [
    {
      "name": "新长福",
      "aliases": [],
      "introduction": "",
      "official_websites": [],
      "logo_urls": [],
      "strengths": [],
      "differentiated_positioning": [],
      "comparison_dimensions": [],
      "other_info": []
    }
  ]
}
```

但当前 mapper 读字段时主要是从内部结构化字段取值:

- `competitors_alias` -> `aliases`
- `competitors_description` -> `introduction`
- `website` -> `official_websites`
- `competitors_logo` -> `logo_urls`
- `competitive_advantages` -> `strengths`

对应代码:

- [knowledge_base/brand/callback_mapper.py](../../knowledge_base/brand/callback_mapper.py)

## 当前主要映射关系

| 语义 | 外部友好字段 | 内部结构化字段 | 回调输出字段 |
| --- | --- | --- | --- |
| 竞品名称 | `name` | `name` | `name` |
| 竞品别名 | `aliases` | `competitors_alias` | `aliases` |
| 竞品介绍 | `introduction` | `competitors_description` | `introduction` |
| 竞品官网 | `official_websites` | `website` | `official_websites` |
| 竞品 Logo | `logo_urls` | `competitors_logo` | `logo_urls` |
| 竞品优势 | `strengths` | `competitive_advantages` | `strengths` |
| 差异化定位 | `differentiated_positioning` | `differentiated_positioning` | `differentiated_positioning` |
| 对比维度 | `comparison_dimensions` | `comparison_dimensions` | `comparison_dimensions` |
| 其他信息 | `other_info` | 无统一稳定字段 | `other_info` |

## 当前代码里谁在兼容谁

### 1. 附件确认链路在把外部友好字段转成内部结构化字段

当前逻辑会把下面这些字段互相兼容:

- `aliases` 或 `competitors_alias`
- `introduction` 或 `competitors_description`
- `official_websites` 或 `website`
- `logo_urls` 或 `competitors_logo`
- `strengths` 或 `competitive_advantages`

对应代码:

- [knowledge_base/brand_knowledge/application/attachment_flow.py](../../knowledge_base/brand_knowledge/application/attachment_flow.py): `_normalize_competitors_for_merge(...)`
- [knowledge_base/brand_knowledge/application/attachment_flow.py](../../knowledge_base/brand_knowledge/application/attachment_flow.py): 确认链路 competitors 组装逻辑

### 2. 品牌服务读取 competitors 时也在双向兼容

当前品牌服务读取 competitors 内容时, 会同时尝试:

- `aliases` / `competitors_alias`
- `introduction` / `competitors_description`
- `website` / `official_websites`

对应代码:

- [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py): `_build_competitor_entities(...)`
- [knowledge_base/brand/application/service.py](../../knowledge_base/brand/application/service.py): 竞品 Markdown 渲染逻辑

### 3. 回调 mapper 现在兼容不完整

回调输出时, 当前 mapper 主要读的是内部结构化字段:

- `competitors_alias`
- `competitors_description`
- `website`
- `competitors_logo`
- `competitive_advantages`

它当前没有把下面这些外部友好字段作为第一等输入来源:

- `aliases`
- `introduction`
- `official_websites`
- `logo_urls`
- `strengths`

对应代码:

- [knowledge_base/brand/callback_mapper.py](../../knowledge_base/brand/callback_mapper.py)

这正是"回调里的竞品别名信息和 `brand_knowledge_json` 不一样"最常见的直接原因.

## 当前最容易出现数据不一致的场景

### 场景 1: `/api/v1/knowledge/update` 直接写入外部友好字段

如果上游传入:

```json
{
  "name": "新长福",
  "aliases": ["新长福酒楼", "新长福酒家"],
  "official_websites": ["https://example.com"]
}
```

而中间没有先归一化成内部结构化字段:

```json
{
  "name": "新长福",
  "competitors_alias": ["新长福酒楼", "新长福酒家"],
  "website": ["https://example.com"]
}
```

那么回调 mapper 在读取时可能出现:

- `aliases` 丢失
- `official_websites` 丢失

因为它默认读的是 `competitors_alias` 和 `website`.

### 场景 2: `brand_knowledge_json` 内部已有新旧混写

同一品牌的同一 section 里, 可能同时存在:

- 某些竞品项用 `aliases`
- 另一些竞品项用 `competitors_alias`

这会导致:

- 某些路径读得出来
- 某些路径读不出来
- 排查时看起来像"偶发"

### 场景 3: Markdown 渲染和回调输出来自不同读取逻辑

当前品牌服务里有些读取点会做双向兼容, 所以:

- Markdown 或品牌详情页看起来正常

但回调 mapper 兼容不完整时:

- 回调 JSON 里仍然可能缺字段

这会造成"库里有、页面有、回调没有"的错觉.

## 字段提示词现状

抽取提示词目前更偏内部结构化字段:

- `competitor_alias` -> `competitors[].competitors_alias`
- `competitor_description` -> `competitors[].competitors_description`
- `competitor_website` -> `competitors[].website`
- `competitor_logo` -> `competitors[].competitors_logo`
- `competitor_advantages` -> `competitors[].competitive_advantages`

对应代码:

- [knowledge_base/brand_knowledge/field_hints.py](../../knowledge_base/brand_knowledge/field_hints.py)

这说明:

- 现有抽取链路天然更偏向内部结构化字段命名
- 如果未来要统一字段, 提示词也需要一起更新

## 推荐的统一方向

当前更适合先定一套"内部 canonical schema", 再让边界层兼容旧字段.

推荐的 canonical schema:

```json
{
  "name": "",
  "aliases": [],
  "introduction": "",
  "official_websites": [],
  "logo_urls": [],
  "strengths": [],
  "differentiated_positioning": [],
  "comparison_dimensions": [],
  "other_info": []
}
```

推荐原因:

1. 字段含义更直观
2. 更接近当前回调输出结构
3. 更接近 `/api/v1/knowledge/update` 上游直觉
4. 查库、排错、看 JSON 时更容易直接读懂

## 如果后续统一, 建议按两步走

### 第一步: 兼容读, 统一写

目标:

- 所有入口继续兼容旧字段
- 所有内部落库统一写成 canonical schema
- 所有回调 / 读取逻辑同时兼容旧字段和新字段

这一步最需要一起检查:

1. `/api/v1/knowledge/update`
2. 附件预解析与确认链路
3. `brand_knowledge_json` 写入点
4. `format_brand_callback_knowledge_from_snapshot(...)`
5. 竞品 Markdown 生成逻辑
6. 抽取 field hints

### 第二步: 清理旧字段

等新写入稳定后, 再考虑:

1. 是否回刷历史 `brand_knowledge_json`
2. 是否删除 `competitors_alias` / `website` 这套旧命名兼容
3. 是否同步调整提示词和文档

## 当前结论

当前 `competitors` 不是一套字段结构, 而是多套字段在并存:

- 外部输入一套
- 内部结构化一套
- 回调输出一套

现在最容易出问题的点不是"没有映射", 而是:

- 有些链路做了双向兼容
- 有些链路只兼容旧字段
- 所以不同出口看到的数据不一致

如果后面要改代码统一, 优先目标应该不是"局部补一个 alias 字段", 而是:

- 先确定唯一 canonical schema
- 再把所有入口和出口都收口到这一套
