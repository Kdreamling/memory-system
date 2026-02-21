"""
高德地图 API 服务 — 云逛街功能
支持：地理编码、周边搜索、关键词搜索、距离测量、路线规划
"""

import httpx
import re
import time
from typing import Optional, Dict, List, Tuple

import sys
sys.path.insert(0, '/home/dream/memory-system/gateway')
from config import get_settings

settings = get_settings()

AMAP_BASE_URL = "https://restapi.amap.com/v3"
AMAP_TIMEOUT = 10.0  # 高德是国内服务，10秒足够

# ============ 地理编码缓存 ============
# key: "地名|城市" -> value: (坐标字符串, 时间戳)
_geocode_cache: Dict[str, Tuple[str, float]] = {}
_CACHE_TTL = 600  # 缓存10分钟


# ============ 内部工具函数 ============

async def _amap_get(endpoint: str, params: dict) -> dict:
    """统一的高德 API GET 请求封装"""
    params["key"] = settings.amap_api_key
    params["output"] = "json"
    url = f"{AMAP_BASE_URL}/{endpoint}"

    async with httpx.AsyncClient(timeout=AMAP_TIMEOUT) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    if data.get("status") != "1":
        info = data.get("info", "未知错误")
        infocode = data.get("infocode", "")
        raise Exception(f"高德API错误: {info} (code={infocode})")

    return data


def _is_coordinate(text: str) -> bool:
    """判断输入是否为坐标格式 (经度,纬度)"""
    return bool(re.match(r'^\d+\.?\d*,\d+\.?\d*$', text.strip()))


async def _resolve_location(input_str: str, city: str = "") -> str:
    """
    智能解析位置输入：坐标直接返回，地名则调 geocode 转坐标。
    带缓存，避免同一地名重复调用 API。
    """
    input_str = input_str.strip()
    if _is_coordinate(input_str):
        return input_str

    # 查缓存
    cache_key = f"{input_str}|{city}"
    cached = _geocode_cache.get(cache_key)
    if cached:
        coord, ts = cached
        if time.time() - ts < _CACHE_TTL:
            print(f"[Amap] Geocode cache hit: {input_str} -> {coord}")
            return coord

    # 调 geocode API
    params = {"address": input_str}
    if city:
        params["city"] = city

    data = await _amap_get("geocode/geo", params)
    geocodes = data.get("geocodes", [])
    if not geocodes:
        raise Exception(f"找不到 '{input_str}' 的位置信息，请尝试更详细的地址")

    location = geocodes[0].get("location", "")
    if not location:
        raise Exception(f"'{input_str}' 的坐标数据异常")

    # 存缓存
    _geocode_cache[cache_key] = (location, time.time())
    print(f"[Amap] Geocoded: {input_str} -> {location}")
    return location


def _clean_field(value) -> str:
    """清理高德返回的字段，过滤空值和 '[]' 等"""
    if not value or value == "[]" or value == "":
        return ""
    return str(value)


def _format_poi(poi: dict, index: int, show_distance: bool = False) -> str:
    """格式化单个 POI 信息（maps_around 和 maps_search 共用）"""
    name = poi.get("name", "未知")
    ptype = poi.get("type", "")
    address = _clean_field(poi.get("address"))
    tel = _clean_field(poi.get("tel"))
    location = poi.get("location", "")

    biz = poi.get("biz_ext", {}) or {}
    rating = _clean_field(biz.get("rating"))
    cost = _clean_field(biz.get("cost"))
    opentime = _clean_field(biz.get("open_time"))

    lines = [f"{index}. {name}（{ptype}）"]

    if show_distance:
        distance = poi.get("distance", "")
        if distance:
            lines.append(f"   📏 距离: {distance}米")

    if address:
        lines.append(f"   📮 地址: {address}")
    if rating:
        lines.append(f"   ⭐ 评分: {rating}")
    if cost:
        lines.append(f"   💰 人均: ¥{cost}")
    if opentime:
        lines.append(f"   🕐 营业: {opentime}")
    if tel:
        lines.append(f"   📞 电话: {tel}")
    if location:
        lines.append(f"   📍 坐标: {location}")

    return "\n".join(lines)


def _format_distance(meters: str) -> str:
    """米转友好显示（<1000显示米，>=1000显示公里）"""
    try:
        m = int(meters)
        if m < 1000:
            return f"{m}米"
        return f"{m / 1000:.1f}公里"
    except (ValueError, TypeError):
        return f"{meters}米"


def _format_duration(seconds: str) -> str:
    """秒转友好显示"""
    try:
        s = int(seconds)
        if s < 60:
            return f"{s}秒"
        minutes = round(s / 60)
        if minutes < 60:
            return f"约{minutes}分钟"
        hours = minutes // 60
        remain = minutes % 60
        if remain == 0:
            return f"约{hours}小时"
        return f"约{hours}小时{remain}分钟"
    except (ValueError, TypeError):
        return f"{seconds}秒"


# ============ 5 个 MCP 工具的执行函数 ============

async def maps_geo(address: str, city: str = "") -> dict:
    """工具1: 地理编码（地名→坐标）"""
    if not address:
        return _error("请提供要查询的地名或地址")

    try:
        params = {"address": address}
        if city:
            params["city"] = city

        data = await _amap_get("geocode/geo", params)
        geocodes = data.get("geocodes", [])
        if not geocodes:
            return _error(f"找不到 '{address}' 的位置信息")

        geo = geocodes[0]
        location = geo.get("location", "")
        province = geo.get("province", "")
        city_name = geo.get("city", "")
        district = geo.get("district", "")
        formatted = geo.get("formatted_address", address)

        # 存入缓存
        cache_key = f"{address}|{city}"
        _geocode_cache[cache_key] = (location, time.time())

        text = f"📍 {formatted}\n坐标: {location}\n省份: {province}\n城市: {city_name}\n区县: {district}"
        return _ok(text)

    except Exception as e:
        return _error(str(e))


async def maps_around(keyword: str = "", location: str = "", address: str = "",
                      city: str = "", radius: int = 1000, limit: int = 10) -> dict:
    """工具2: 周边搜索"""
    try:
        # 解析中心点位置
        if location:
            center = location.strip()
        elif address:
            center = await _resolve_location(address, city)
        else:
            return _error("请提供搜索中心点：坐标(location)或地名(address)")

        if radius > 50000:
            radius = 50000
        if limit > 25:
            limit = 25

        params = {
            "location": center,
            "radius": str(radius),
            "offset": str(limit),
            "page": "1",
            "extensions": "all",
            "sortrule": "distance",
        }
        if keyword:
            params["keywords"] = keyword

        data = await _amap_get("place/around", params)
        pois = data.get("pois", [])

        if not pois:
            center_name = address or location
            return _ok(f"在 '{center_name}' 附近{radius}米内没有找到相关结果")

        center_name = address or location
        header = f"🗺️ 在\"{center_name}\"附近{radius}米内"
        if keyword:
            header += f"搜索\"{keyword}\""
        header += f"找到 {len(pois)} 个结果：\n"

        poi_texts = [_format_poi(p, i, show_distance=True) for i, p in enumerate(pois, 1)]
        text = header + "\n" + "\n\n".join(poi_texts)
        return _ok(text)

    except Exception as e:
        return _error(str(e))


async def maps_search(keyword: str, city: str = "", limit: int = 10) -> dict:
    """工具3: 关键词搜索（城市内找地方）"""
    if not keyword:
        return _error("请提供搜索关键词")

    try:
        if limit > 25:
            limit = 25

        params = {
            "keywords": keyword,
            "offset": str(limit),
            "page": "1",
            "extensions": "all",
        }
        if city:
            params["city"] = city

        data = await _amap_get("place/text", params)
        pois = data.get("pois", [])

        if not pois:
            scope = f"在{city}" if city else ""
            return _ok(f"{scope}没有找到\"{keyword}\"相关的地点")

        scope = f"在{city}" if city else ""
        header = f"🔍 {scope}搜索\"{keyword}\"找到 {len(pois)} 个结果：\n"

        poi_texts = [_format_poi(p, i, show_distance=False) for i, p in enumerate(pois, 1)]
        text = header + "\n" + "\n\n".join(poi_texts)
        return _ok(text)

    except Exception as e:
        return _error(str(e))


async def maps_distance(origin: str, destination: str, city: str = "", mode: int = 0) -> dict:
    """工具4: 距离测量"""
    if not origin or not destination:
        return _error("请提供起点和终点")

    try:
        origin_coord = await _resolve_location(origin, city)
        dest_coord = await _resolve_location(destination, city)

        params = {
            "origins": origin_coord,
            "destination": dest_coord,
            "type": str(mode),
        }

        data = await _amap_get("distance", params)
        results = data.get("results", [])

        if not results:
            return _error("无法计算距离，请检查输入的地点")

        result = results[0]
        distance = result.get("distance", "0")
        duration = result.get("duration", "0")

        mode_labels = {0: "🚗 驾车", 1: "🚶 步行", 3: "📏 直线"}
        mode_label = mode_labels.get(mode, "")

        origin_name = origin if not _is_coordinate(origin) else origin
        dest_name = destination if not _is_coordinate(destination) else destination

        lines = [
            f"📏 从\"{origin_name}\"到\"{dest_name}\"：",
            f"{mode_label}距离: {_format_distance(distance)}",
        ]
        if mode != 3:
            lines.append(f"⏱️ 预计时间: {_format_duration(duration)}")
        lines.append(f"📍 起点坐标: {origin_coord}")
        lines.append(f"📍 终点坐标: {dest_coord}")

        return _ok("\n".join(lines))

    except Exception as e:
        return _error(str(e))


async def maps_route(origin: str, destination: str, city: str = "", mode: str = "walking") -> dict:
    """工具5: 路线规划"""
    if not origin or not destination:
        return _error("请提供起点和终点")

    if mode == "transit" and not city:
        return _error("公交规划需要指定城市名哦，请在 city 参数中填写城市")

    try:
        origin_coord = await _resolve_location(origin, city)
        dest_coord = await _resolve_location(destination, city)

        if mode == "walking":
            return await _route_walking(origin, destination, origin_coord, dest_coord)
        elif mode == "driving":
            return await _route_driving(origin, destination, origin_coord, dest_coord)
        elif mode == "transit":
            return await _route_transit(origin, destination, origin_coord, dest_coord, city)
        else:
            return _error(f"不支持的出行方式: {mode}，可选: walking / driving / transit")

    except Exception as e:
        return _error(str(e))


# ============ 路线规划子函数 ============

async def _route_walking(origin_name: str, dest_name: str,
                         origin_coord: str, dest_coord: str) -> dict:
    """步行路线规划"""
    data = await _amap_get("direction/walking", {
        "origin": origin_coord,
        "destination": dest_coord,
    })

    paths = data.get("route", {}).get("paths", [])
    if not paths:
        return _error("无法规划步行路线")

    path = paths[0]
    distance = path.get("distance", "0")
    duration = path.get("duration", "0")
    steps = path.get("steps", [])

    o = origin_name if not _is_coordinate(origin_name) else "起点"
    d = dest_name if not _is_coordinate(dest_name) else "终点"

    lines = [
        f"🚶 从\"{o}\"步行到\"{d}\"",
        f"总距离: {_format_distance(distance)} | 预计: {_format_duration(duration)}",
        "",
        "路线：",
    ]

    for i, step in enumerate(steps, 1):
        instruction = step.get("instruction", "")
        step_dist = step.get("distance", "")
        if instruction:
            suffix = f"（{_format_distance(step_dist)}）" if step_dist and step_dist != "0" else ""
            lines.append(f"{i}. {instruction}{suffix}")

    return _ok("\n".join(lines))


async def _route_driving(origin_name: str, dest_name: str,
                         origin_coord: str, dest_coord: str) -> dict:
    """驾车路线规划"""
    data = await _amap_get("direction/driving", {
        "origin": origin_coord,
        "destination": dest_coord,
        "strategy": "0",
    })

    paths = data.get("route", {}).get("paths", [])
    if not paths:
        return _error("无法规划驾车路线")

    path = paths[0]
    distance = path.get("distance", "0")
    duration = path.get("duration", "0")
    tolls = path.get("tolls", "0")
    steps = path.get("steps", [])

    o = origin_name if not _is_coordinate(origin_name) else "起点"
    d = dest_name if not _is_coordinate(dest_name) else "终点"

    lines = [
        f"🚗 从\"{o}\"驾车到\"{d}\"",
        f"总距离: {_format_distance(distance)} | 预计: {_format_duration(duration)}",
    ]
    try:
        if int(tolls) > 0:
            lines.append(f"💰 过路费: ¥{tolls}")
    except (ValueError, TypeError):
        pass

    lines.append("")
    lines.append("路线：")

    for i, step in enumerate(steps, 1):
        instruction = step.get("instruction", "")
        if instruction:
            lines.append(f"{i}. {instruction}")

    return _ok("\n".join(lines))


async def _route_transit(origin_name: str, dest_name: str,
                         origin_coord: str, dest_coord: str, city: str) -> dict:
    """公交路线规划"""
    data = await _amap_get("direction/transit/integrated", {
        "origin": origin_coord,
        "destination": dest_coord,
        "city": city,
        "strategy": "0",
    })

    transits = data.get("route", {}).get("transits", [])
    if not transits:
        return _error("无法规划公交路线")

    # 只取第一个方案（最优）
    transit = transits[0]
    duration = transit.get("duration", "0")
    walking_dist = transit.get("walking_distance", "0")
    cost_val = _clean_field(transit.get("cost"))

    o = origin_name if not _is_coordinate(origin_name) else "起点"
    d = dest_name if not _is_coordinate(dest_name) else "终点"

    lines = [
        f"🚌 从\"{o}\"乘公交到\"{d}\"",
        f"预计: {_format_duration(duration)} | 步行: {_format_distance(walking_dist)}",
    ]
    if cost_val:
        lines.append(f"💰 费用: ¥{cost_val}")

    lines.append("")
    lines.append("路线：")

    segments = transit.get("segments", [])
    step_num = 1
    for seg in segments:
        # 步行段
        walking = seg.get("walking", {})
        if walking:
            w_steps = walking.get("steps", [])
            if w_steps:
                w_dist = walking.get("distance", "")
                # 合并步行段的描述
                w_instructions = []
                for ws in w_steps:
                    inst = ws.get("instruction", "")
                    if inst:
                        w_instructions.append(inst)
                if w_instructions:
                    w_text = "；".join(w_instructions)
                    suffix = f"（{_format_distance(w_dist)}）" if w_dist and w_dist != "0" else ""
                    lines.append(f"{step_num}. 🚶 {w_text}{suffix}")
                    step_num += 1

        # 乘车段
        bus_info = seg.get("bus", {})
        buslines = bus_info.get("buslines", []) if bus_info else []
        for bl in buslines:
            name = bl.get("name", "")
            departure = bl.get("departure_stop", {}).get("name", "")
            arrival = bl.get("arrival_stop", {}).get("name", "")
            via_num = bl.get("via_num", "")
            via_text = f"，{via_num}站" if via_num else ""

            if departure and arrival:
                lines.append(f"{step_num}. 🚌 乘坐{name}，从{departure}到{arrival}{via_text}")
            elif name:
                lines.append(f"{step_num}. 🚌 乘坐{name}{via_text}")
            step_num += 1

        # 地铁（也在 bus 里）
        railway = seg.get("railway", {})
        if railway:
            name = railway.get("name", "")
            departure = railway.get("departure_stop", {}).get("name", "")
            arrival = railway.get("arrival_stop", {}).get("name", "")
            via_num = railway.get("via_num", "")
            via_text = f"，{via_num}站" if via_num else ""

            if departure and arrival:
                lines.append(f"{step_num}. 🚄 乘坐{name}，从{departure}到{arrival}{via_text}")
            elif name:
                lines.append(f"{step_num}. 🚄 乘坐{name}{via_text}")
            step_num += 1

    return _ok("\n".join(lines))


# ============ 返回格式辅助 ============

def _ok(text: str) -> dict:
    """MCP 标准成功返回"""
    return {
        "content": [{"type": "text", "text": text}]
    }


def _error(msg: str) -> dict:
    """MCP 标准错误返回"""
    return {
        "content": [{"type": "text", "text": f"❌ {msg}"}],
        "isError": True
    }
