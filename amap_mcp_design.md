# 🗺️ Kelivo 云逛街 MCP 工具 — 设计文档

> 给 Claude Code 的实现指南
> 设计时间：2026-02-20

---

## 一、项目背景

Dream 想在 Kelivo App 里和 AI 一起"云逛街"。通过高德地图 API，让 AI 能够：
- 把 Dream 说的地名转成坐标
- 搜索附近好吃好玩的地方
- 在城市范围内找特定的店铺/景点
- 计算两个地方之间的距离和时间
- 规划从 A 到 B 的路线

**Dream 是路痴**，她给 AI 的位置信息通常是：
- 路边看到的路牌/店名："我在星巴克门口""我在xx路"
- 标志性建筑："我在广州塔附近"
- 手机地图上看到的坐标

所以所有工具都要同时支持**地名输入**和**坐标输入**，AI 根据情况灵活选用。

---

## 二、技术方案

### 2.1 API 选型

使用**高德地图 Web服务 API**（REST接口，服务端调用）。

- API Key: `a2cc0ee5445d1e8861b9c32081d79339`
- 基础URL: `https://restapi.amap.com/v3`
- 免费额度: 每天 5000 次调用
- Key 已验证可用（2026-02-20 测试 geocode 接口正常）

### 2.2 部署位置

加到 **Gateway（端口8001）** 的 MCP 工具中：
- 新建文件：`/home/dream/memory-system/gateway/services/amap_service.py`
- 修改文件：`/home/dream/memory-system/gateway/routers/mcp_tools.py`（注册新工具）
- 修改文件：`/home/dream/memory-system/.env`（添加 AMAP_API_KEY）

### 2.3 .env 新增配置

```env
# 高德地图 API
AMAP_API_KEY=a2cc0ee5445d1e8861b9c32081d79339
```

注意：config.py 中也需要添加对应字段读取这个环境变量。

---

## 三、MCP 工具设计（5个工具）

### 工具1: `maps_geo` — 地理编码（地名→坐标）

**用途**：把地名/地址转换为经纬度坐标。其他工具需要坐标时，先调这个。

**高德API**：`GET /v3/geocode/geo`

**MCP参数**：
```json
{
  "address": "string【必填】- 地名或地址，如'广州塔''北京路步行街''海珠区新港东路'",
  "city": "string - 城市名，提高精度，如'广州''深圳'。不填则全国范围搜索"
}
```

**返回格式**（文本）：
```
📍 广东省广州市海珠区广州塔
坐标: 113.324553,23.106414
省份: 广东省
城市: 广州市
区县: 海珠区
```

**高德API参数映射**：
| MCP参数 | 高德参数 | 说明 |
|---------|----------|------|
| address | address | 结构化地址 |
| city | city | 城市编码或城市名 |
| — | key | 从env读取 |
| — | output | 固定json |

**注意事项**：
- geocodes 数组可能返回多个结果，只取第一个
- location 格式是 "经度,纬度"（注意是经度在前！）

---

### 工具2: `maps_around` — 周边搜索（搜附近POI）

**用途**：以某个位置为中心，搜索周边的店铺、餐厅、景点等。云逛街的核心工具。

**高德API**：`GET /v3/place/around`

**MCP参数**：
```json
{
  "keyword": "string - 搜索关键词，如'奶茶''书店''火锅''咖啡馆'",
  "location": "string - 中心点坐标'经度,纬度'（和address二选一）",
  "address": "string - 中心点地名，如'天河城''北京路'（会自动转坐标）",
  "city": "string - 城市名（配合address使用）",
  "radius": "int - 搜索半径（米），默认1000，最大50000",
  "limit": "int - 返回数量，默认10，最大25"
}
```

**location 和 address 的关系**：
- 如果传了 location（坐标），直接用
- 如果传了 address（地名），先内部调 geocode 转成坐标再搜
- 两个都没传则报错

**返回格式**（文本）：
```
🗺️ 在"天河城"附近1000米内找到 8 个结果：

1. 喜茶（天河城店）（餐饮服务;饮品店）
   📏 距离: 50米
   📮 地址: 天河路208号天河城B1层
   ⭐ 评分: 4.5
   💰 人均: ¥28
   🕐 营业: 10:00-22:00
   📍 坐标: 113.329884,23.137903

2. 星巴克（天河城店）（餐饮服务;咖啡厅）
   📏 距离: 80米
   ...
```

**高德API参数映射**：
| MCP参数 | 高德参数 | 说明 |
|---------|----------|------|
| keyword | keywords | 搜索关键词 |
| location | location | 中心点坐标 |
| radius | radius | 搜索半径 |
| limit | offset | 每页记录数 |
| — | page | 固定1 |
| — | extensions | 固定"all"（返回详细信息含评分等） |
| — | sortrule | 固定"distance"（按距离排序） |

**注意事项**：
- keyword 为空时搜索所有类型 POI
- biz_ext 里有 rating（评分）、cost（人均）、opentime（营业时间），但不是所有POI都有
- tel、address 有时返回 "[]" 空数组字符串，需要过滤
- distance 字段是字符串类型的米数

---

### 工具3: `maps_search` — 关键词搜索（城市内找地方）

**用途**：在整个城市范围内搜索地点。适合"这个城市有什么好的xxx"这种需求。

**高德API**：`GET /v3/place/text`

**MCP参数**：
```json
{
  "keyword": "string【必填】- 搜索关键词，如'网红书店''密室逃脱''猫咖'",
  "city": "string - 城市名【建议填写】，如'广州''上海'",
  "limit": "int - 返回数量，默认10，最大25"
}
```

**返回格式**（与 maps_around 类似，但没有"距离"字段）：
```
🔍 在广州搜索"猫咖"找到 6 个结果：

1. 猫小院猫咖（体育西路店）（餐饮服务;咖啡厅）
   📮 地址: 天河区体育西路xxx
   ⭐ 评分: 4.7
   💰 人均: ¥58
   📍 坐标: 113.xxx,23.xxx
   ...
```

**高德API参数映射**：
| MCP参数 | 高德参数 | 说明 |
|---------|----------|------|
| keyword | keywords | 搜索关键词 |
| city | city | 城市名 |
| limit | offset | 每页记录数 |
| — | page | 固定1 |
| — | extensions | 固定"all" |

---

### 工具4: `maps_distance` — 距离测量

**用途**：计算两个地点之间的距离和预估时间。

**高德API**：`GET /v3/distance`

**MCP参数**：
```json
{
  "origin": "string【必填】- 起点，可以是坐标'经度,纬度'或地名",
  "destination": "string【必填】- 终点，可以是坐标'经度,纬度'或地名",
  "city": "string - 城市名（当origin/destination是地名时提高精度）",
  "mode": "int - 出行方式：0驾车(默认) 1步行 3直线距离"
}
```

**内部逻辑**：
- 先检测 origin/destination 是坐标还是地名（判断是否匹配 `数字,数字` 格式）
- 如果是地名，先调 geocode 转坐标
- 然后调距离API

**返回格式**（文本）：
```
📏 从"天河城"到"广州塔"：
🚶 步行距离: 3.2公里
⏱️ 预计时间: 约42分钟
📍 起点坐标: 113.329884,23.137903
📍 终点坐标: 113.324553,23.106414
```

**高德API参数映射**：
| MCP参数 | 高德参数 | 说明 |
|---------|----------|------|
| origin坐标 | origins | 起点坐标 |
| destination坐标 | destination | 终点坐标 |
| mode | type | 路径计算方式 |

**注意事项**：
- 距离API返回的 distance 单位是米，duration 单位是秒
- 需要在返回时做单位换算（米→公里，秒→分钟）
- mode=1(步行)最实用，Dream逛街大概率步行

---

### 工具5: `maps_route` — 路线规划

**用途**：规划从A到B的具体路线，包含详细步骤。

**高德API**：
- 步行：`GET /v3/direction/walking`
- 驾车：`GET /v3/direction/driving`
- 公交：`GET /v3/direction/transit/integrated`

**MCP参数**：
```json
{
  "origin": "string【必填】- 起点，可以是坐标或地名",
  "destination": "string【必填】- 终点，可以是坐标或地名",
  "city": "string - 城市名（地名转坐标用 + 公交规划必填）",
  "mode": "string - 出行方式：walking(默认) / driving / transit"
}
```

**内部逻辑**：
- 同 maps_distance，先将地名转坐标
- 根据 mode 调用不同的API端点
- 解析 steps 返回简洁的路线描述

**返回格式**（步行示例）：
```
🚶 从"天河城"步行到"广州塔"
总距离: 3.2公里 | 预计: 约42分钟

路线：
1. 从天河路向南步行200米
2. 右转进入体育东路，步行500米
3. 左转进入天河南一路，步行300米
...
```

**返回格式**（公交示例）：
```
🚌 从"天河城"乘公交到"广州塔"
预计: 约25分钟

方案1:
1. 步行150米到体育中心站
2. 乘坐地铁3号线(番禺广场方向)，2站
3. 在广州塔站下车(A出口)
4. 步行200米到达
```

**高德API参数映射**：

步行 `/v3/direction/walking`:
| MCP参数 | 高德参数 |
|---------|----------|
| origin坐标 | origin |
| destination坐标 | destination |

驾车 `/v3/direction/driving`:
| MCP参数 | 高德参数 |
|---------|----------|
| origin坐标 | origin |
| destination坐标 | destination |
| — | strategy=0 (速度优先) |

公交 `/v3/direction/transit/integrated`:
| MCP参数 | 高德参数 |
|---------|----------|
| origin坐标 | origin |
| destination坐标 | destination |
| city | city (必填) |
| — | strategy=0 (最快捷) |

**注意事项**：
- 步行路线的 steps 在 `route.paths[0].steps` 里
- 公交路线结构更复杂，在 `route.transits` 里，每个方案有 segments
- 公交的 segments 里混合了步行段(walking)和乘车段(bus)
- 路线规划建议只返回第一个方案（最优方案），避免信息过多

---

## 四、代码实现要点

### 4.1 文件结构

```
/home/dream/memory-system/
├── .env                           # 新增 AMAP_API_KEY
├── gateway/
│   ├── config.py                  # 新增 amap_api_key 字段
│   ├── services/
│   │   ├── amap_service.py        # 🆕 高德地图API服务（所有5个功能）
│   │   └── ... (其他不动)
│   └── routers/
│       └── mcp_tools.py           # 修改：注册5个新MCP工具
```

### 4.2 amap_service.py 设计原则

1. **统一的HTTP请求封装**：写一个 `_amap_get(endpoint, params)` 内部函数处理所有API调用
2. **智能输入检测**：写一个 `_resolve_location(input_str, city)` 辅助函数，判断输入是坐标还是地名，如果是地名则自动调 geocode
3. **坐标格式判断**：用正则 `^\d+\.\d+,\d+\.\d+$` 判断是否为坐标
4. **错误处理**：高德API返回 status != "1" 时返回友好的中文错误提示
5. **单位换算**：距离米→公里（保留1位小数），时间秒→分钟（四舍五入）
6. **空值过滤**：POI的tel、address等字段可能是"[]"空数组，需要过滤

### 4.3 mcp_tools.py 修改要点

在 `tools/list` 的返回中新增5个工具定义。在 `tools/call` 的分发逻辑中新增5个工具的处理。

工具定义参考现有格式（JSON-RPC 2.0），每个工具需要：
- name: 工具名
- description: 中文描述（AI读这个来决定什么时候调用）
- inputSchema: JSON Schema 参数定义

**description 要写得对AI友好**，让AI知道什么场景该用哪个工具：

```
maps_geo: "地理编码：把地名、地址、路牌名转换为经纬度坐标。当需要获取某个地方的精确坐标时调用。"

maps_around: "周边搜索：以某个位置为中心，搜索附近的餐厅、商店、景点等。适合'附近有什么好吃的''周围有没有书店'等场景。支持坐标或地名作为中心点。"

maps_search: "城市搜索：在整个城市范围内搜索地点。适合'这个城市有什么好的咖啡馆''广州哪里有密室逃脱'等场景。"

maps_distance: "距离测量：计算两个地点之间的距离和预估到达时间。支持步行、驾车计算。起点终点可以用坐标或地名。"

maps_route: "路线规划：规划从A到B的详细路线，包含每一步怎么走。支持步行、驾车、公交三种方式。起点终点可以用坐标或地名。"
```

### 4.4 config.py 修改

在 Settings 类中新增：
```python
amap_api_key: str = ""
```

amap_service.py 中从 config 读取 key，而不是直接 os.getenv。

### 4.5 httpx 客户端

amap_service.py 中调高德API**不需要走代理**（高德是国内服务），所以 httpx.AsyncClient 不要设置 proxy。可以考虑复用 Gateway 的全局 local_client（如果有的话），或者单独创建一个无代理的 client。

---

## 五、System Prompt 建议

在 Kelivo 的 AI System Prompt 中可以加上这段，帮助 AI 理解如何使用地图工具：

```
## 地图工具使用规则
1. 当Dream提到位置、地名时，用 maps_geo 获取坐标
2. 当Dream想逛附近、找吃的/玩的时，用 maps_around 搜周边
3. 当Dream想找某个城市里的特定地方时，用 maps_search 搜索
4. 当Dream问"多远""多久能到"时，用 maps_distance 计算
5. 当Dream问"怎么去""怎么走"时，用 maps_route 规划路线
6. 收到搜索结果后，用自然的语气和Dream聊，像真的在一起逛街一样
7. 可以主动推荐觉得Dream会喜欢的地方，给出理由
```

---

## 六、测试验证

部署完成后用以下命令测试：

```bash
# 测试 maps_geo
curl -s -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"maps_geo","arguments":{"address":"广州塔","city":"广州"}}}' | python3 -m json.tool

# 测试 maps_around
curl -s -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"maps_around","arguments":{"address":"广州塔","city":"广州","keyword":"奶茶","radius":500}}}' | python3 -m json.tool

# 测试 maps_search
curl -s -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"maps_search","arguments":{"keyword":"猫咖","city":"广州"}}}' | python3 -m json.tool

# 测试 maps_distance
curl -s -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"maps_distance","arguments":{"origin":"天河城","destination":"广州塔","city":"广州","mode":1}}}' | python3 -m json.tool

# 测试 maps_route
curl -s -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"maps_route","arguments":{"origin":"天河城","destination":"广州塔","city":"广州","mode":"walking"}}}' | python3 -m json.tool
```

---

## 七、注意事项

1. **不要动现有的4个MCP工具**（search_memory / init_context / save_diary / send_sticker），只是新增
2. **备份再改**：修改 mcp_tools.py 和 config.py 前先 `cp xxx xxx.bak.$(date +%Y%m%d%H%M%S)`
3. **高德Key安全**：Key 放在 .env 里，不要硬编码在代码中
4. **不走代理**：高德API是国内服务，httpx 调用时不设置 proxy
5. **重启Gateway**：修改完成后需要重启8001端口的服务
6. **Kelivo MCP刷新**：Gateway重启后，Kelivo App 里的 MCP 工具列表应该会自动更新（从 4个变成 9个）

---

## 八、后续可扩展

- **收藏功能**：AI推荐的地方可以存到 Supabase（新建 `favorites` 表）
- **逛街记录**：记录每次云逛街去了哪些地方
- **天气联动**：搭配天气API，下雨天推荐室内活动
- **美食收藏**：专门的"想去吃"清单
