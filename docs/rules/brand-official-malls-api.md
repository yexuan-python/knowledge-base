# `/api/v1/brands/official-malls` 接口协议

最后校对日期: 2026-08-28

## 目标

提供一条独立的品牌官方商城读取接口。

这条接口只返回指定品牌的 `official_malls` 结构化数据。

## 入口与范围

- 接口: `POST /api/v1/brands/official-malls`
- 路由实现: [knowledge_base/api_app/routers/brands.py](../../knowledge_base/api_app/routers/brands.py)
- 应用服务: [knowledge_base/brand/application/brand_read_workflow.py](../../knowledge_base/brand/application/brand_read_workflow.py)
- Facade: [knowledge_base/service.py](../../knowledge_base/service.py)
- 请求模型: [knowledge_base/brand/schemas/requests.py](../../knowledge_base/brand/schemas/requests.py)
- 响应模型: [knowledge_base/brand/schemas/responses.py](../../knowledge_base/brand/schemas/responses.py)

## 请求协议

### Method

`POST`

### Path

`/api/v1/brands/official-malls`

### Content-Type

`application/json`

### Request Body

```json
{
  "brand_code": "100060"
}
```

### 请求字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `brand_code` | `string` | 是 | 品牌编码，按品牌编码精确读取官方商城结构化信息 |

### 请求规则

- `brand_code` 不能为空字符串
- 当前按 `brand_code` 读取品牌，不支持用 `brand_name` 替代

## 成功响应

### Response Body

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "brand_code": "100060",
    "brand_name": "北京嘉禾妇儿医院",
    "knowledge_revision": "V4",
    "official_malls": [
      {
        "store_name": "嘉禾官方商城",
        "platform": "微信小店",
        "homepage_urls": [
          "https://example.com/mall"
        ],
        "store_ids": [
          "mall-001"
        ],
        "main_categories": [
          "产检服务",
          "月子服务"
        ],
        "advantages": [
          "品牌直营",
          "官方售后"
        ],
        "related_products": [
          1001,
          "月子套餐"
        ],
        "other_info": [
          "支持在线预约"
        ]
      }
    ]
  }
}
```

### 响应字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | `integer` | 固定为 `0` 表示成功 |
| `message` | `string` | 固定为 `ok` |
| `data.brand_code` | `string` | 品牌编码 |
| `data.brand_name` | `string` | 品牌名称 |
| `data.knowledge_revision` | `string` | 当前品牌知识版本号 |
| `data.official_malls` | `array<object>` | 官方商城列表 |

### `official_malls[]` 字段定义

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `store_name` | `string` | 店铺名称 |
| `platform` | `string` | 开店平台 |
| `homepage_urls` | `array<string>` | 店铺主页链接列表 |
| `store_ids` | `array<string>` | 店铺 ID 列表 |
| `main_categories` | `array<string>` | 主营品类列表 |
| `advantages` | `array<string>` | 店铺优势列表 |
| `related_products` | `array<int \| string>` | 关联产品，可同时存在产品 ID 与产品名称 |
| `other_info` | `array<string>` | 其他说明信息 |

## 空数据语义

如果品牌存在，但当前没有官方商城信息，返回仍然是成功响应:

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "brand_code": "100060",
    "brand_name": "北京嘉禾妇儿医院",
    "knowledge_revision": "V4",
    "official_malls": []
  }
}
```

当前约定:

- 品牌存在但无官方商城: 返回 `200`
- `official_malls` 返回空数组 `[]`
- 不把“无商城数据”视为异常

## 错误响应

### `400 brand_code 不能为空`

```json
{
  "code": 40001,
  "message": "brand_code 不能为空",
  "data": null
}
```

### `404 brand_code 不存在`

```json
{
  "code": 40401,
  "message": "brand_code 不存在",
  "data": null
}
```

## 当前数据来源

这条接口当前读取:

1. `brands`
2. `brand_knowledge_json`

其中 `official_malls` 来自:

- `brand_knowledge_json`
- `knowledge_type = official_malls`


## 当前归一化规则

返回前会对 `official_malls` 做一次标准化:

- 非数组输入按空数组处理
- 仅保留有实际内容的商城项
- `homepage_urls`、`store_ids`、`main_categories`、`advantages`、`other_info` 统一归一化为数组
- `related_products` 保持为去重后的 `int | string` 混合列表

这意味着:

- 返回值不是底层原始 JSON 的无损透传
- 返回值是面向消费端的标准化结果


## 适用场景

适合以下场景直接调用:

- 品牌详情页单独展示“官方商城”模块
- 前端只需要结构化商城信息


## 当前示例 curl

```bash
curl -X POST 'http://127.0.0.1:9007/api/v1/brands/official-malls' \
  -H 'Content-Type: application/json' \
  -d '{
    "brand_code": "100060"
  }'
```
