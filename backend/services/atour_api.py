"""亚朵价格查询服务（Atour 项目）。"""

from __future__ import annotations

import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

import requests


# 轻量 YAML 子集解析（纯标准库，不依赖 PyYAML）
def _yaml_scalar(value: str) -> Any:
    """把 yaml 标量字符串转成 Python 类型（int / float / bool / str）。"""
    v = value.strip().strip("'\"")
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def _load_config(path: str | None = None) -> dict[str, Any]:
    """从 yaml 文件加载配置（纯标准库解析）。"""
    if path is None:
        env_cfg = os.environ.get("ATOUR_CONFIG")
        if env_cfg:
            path = env_cfg
        else:
            here = os.path.dirname(os.path.abspath(__file__))
            root = os.path.dirname(os.path.dirname(here))  # services/../.. → 项目根
            path = os.path.join(root, "config.yaml")
    if not os.path.isfile(path):
        return {}

    result: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]  # (缩进, 所在字典)
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.strip()
            if ":" not in stripped:
                continue
            key, _, val = stripped.partition(":")
            key = key.strip().strip("'\"")
            val = val.strip()
            # 弹出所有比当前更深（或同级更深）的栈顶
            while len(stack) > 1 and indent <= stack[-1][0]:
                stack.pop()
            # 有值 → 标量节点；无值 → 进入子字典
            if val:
                stack[-1][1][key] = _yaml_scalar(val)
            else:
                child: dict[str, Any] = {}
                stack[-1][1][key] = child
                stack.append((indent, child))
    return result


_CONFIG = _load_config()
_TOKEN_CFG = (_CONFIG.get("token") or {}).get("atour_token")
_REQ_CFG = _CONFIG.get("request") or {}


class AtourAPIError(RuntimeError):
    pass


def _to_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


_ATOUR_API = "https://user-gateway.yaduo.com/api/product/search/chain"
_APP_VER = "4.13.2"
_CHANNEL_ID = "20001"
_PLAT_TYPE = "2"
_CLIENT_ID = "34F12C8D-5917-4EF2-8FE9-702AB944CD44"

ATOUR_TOKEN = _TOKEN_CFG if _TOKEN_CFG is not None else ""


def _request_delay() -> None:
    d = _REQ_CFG.get("list_delay") if _REQ_CFG.get("list_delay") is not None else {}
    _min = float(d.get("min", 0.3))
    _max = float(d.get("max", 0.5))
    if _min <= 0 and _max <= 0:
        return
    time.sleep(random.uniform(_min, _max))


def _request_delay_light() -> None:
    d = _REQ_CFG.get("light_delay") if _REQ_CFG.get("light_delay") is not None else {}
    _min = float(d.get("min", 0.25))
    _max = float(d.get("max", 0.6))
    if _min <= 0 and _max <= 0:
        return
    time.sleep(random.uniform(_min, _max))


_CITY_API = "https://api2.yaduo.com/atourlife/city/listOfChain"
_DETAIL_API = "https://api2.yaduo.com/atourlife/chain/chainDetailBase"
_QUOTE_API = "https://api2.yaduo.com/atourlife/chain/chainDetailQuote"

PROVINCE_ID_NAME = {
    11: "北京", 12: "天津", 13: "河北", 14: "山西", 15: "内蒙古",
    21: "辽宁", 22: "吉林", 23: "黑龙江", 31: "上海", 32: "江苏",
    33: "浙江", 34: "安徽", 35: "福建", 36: "江西", 37: "山东",
    41: "河南", 42: "湖北", 43: "湖南", 44: "广东", 45: "广西",
    46: "海南", 50: "重庆", 51: "四川", 52: "贵州", 53: "云南",
    54: "西藏", 61: "陕西", 62: "甘肃", 63: "青海", 64: "宁夏",
    65: "新疆", 71: "台湾", 81: "香港", 82: "澳门",
}

_CITY_CACHE: dict[str, list[str]] | None = None
_OPEN_DATE_CACHE: dict[str, str] = {}
_ROOM_CACHE: dict[tuple, list[dict[str, Any]]] = {}


_AUTONOMOUS = {
    "广西": "广西壮族自治区",
    "内蒙古": "内蒙古自治区",
    "西藏": "西藏自治区",
    "宁夏": "宁夏回族自治区",
    "新疆": "新疆维吾尔自治区",
    "香港": "香港特别行政区",
    "澳门": "澳门特别行政区",
}

PROVINCE_CITIES = {
    "北京": ["北京市"],
    "上海": ["上海市"],
    "重庆": ["重庆市"],
    "广东": ["广州市", "深圳市", "珠海市", "东莞市", "佛山市", "中山市", "惠州市"],
    "浙江": ["杭州市", "宁波市", "温州市", "金华市", "绍兴市", "嘉兴市"],
    "江苏": ["南京市", "苏州市", "无锡市", "常州市", "徐州市", "南通市"],
    "四川": ["成都市", "绵阳市", "宜宾市", "泸州市", "南充市"],
    "湖北": ["武汉市", "宜昌市", "襄阳市", "黄石市"],
    "陕西": ["西安市", "咸阳市", "宝鸡市"],
    "福建": ["福州市", "厦门市", "泉州市", "漳州市"],
    "山东": ["济南市", "青岛市", "烟台市", "潍坊市", "临沂市"],
    "湖南": ["长沙市", "株洲市", "常德市", "岳阳市"],
}


def get_atour_cities(token: str = ATOUR_TOKEN, force: bool = False) -> dict[str, list[str]]:
    """获取亚朵已开业的全部城市，并按省份聚合。"""
    global _CITY_CACHE
    if _CITY_CACHE is not None and not force:
        return _CITY_CACHE
    params = {
        "appVer": _APP_VER,
        "channelId": _CHANNEL_ID,
        "platType": _PLAT_TYPE,
        "token": token.strip(),
    }
    body = {
        "At-App-Version": _APP_VER,
        "At-Channel-Id": _CHANNEL_ID,
        "At-Client-Id": _CLIENT_ID,
        "At-Platform-Type": _PLAT_TYPE,
        "appVer": _APP_VER,
        "at-client-code": _CLIENT_ID,
        "channelId": _CHANNEL_ID,
        "deviceId": _CLIENT_ID,
        "platType": _PLAT_TYPE,
        "token": token.strip(),
    }
    headers = _build_headers(token)
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        resp = requests.post(_CITY_API, params=params, headers=headers, data=body, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise AtourAPIError(f"获取城市列表失败：{exc}") from exc
    if not payload.get("success", True):
        raise AtourAPIError(f"城市列表接口返回错误：code={payload.get('code')} msg={payload.get('msg_code')}")
    cities = (payload.get("result") or {}).get("cityList", [])
    grouped: dict[str, list[str]] = {}
    for c in cities:
        pid = c.get("provinceId")
        pname = PROVINCE_ID_NAME.get(pid, f"未知省({pid})")
        name = c.get("cityName")
        if name:
            grouped.setdefault(pname, []).append(name)
    for names in grouped.values():
        names.sort()
    _CITY_CACHE = grouped
    return grouped


def _fetch_open_date(chain_id: object, token: str) -> str:
    """按 chainId 取酒店开业时间。"""
    key = str(chain_id)
    if key in _OPEN_DATE_CACHE:
        return _OPEN_DATE_CACHE[key]
    _request_delay_light()
    params = {
        "platType": _PLAT_TYPE,
        "appVer": _APP_VER,
        "token": token.strip(),
        "channelId": _CHANNEL_ID,
    }
    try:
        resp = requests.post(
            _DETAIL_API,
            params=params,
            headers=_build_headers(token),
            json={"chainId": key},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException:
        _OPEN_DATE_CACHE[key] = "—"
        return "—"
    if not payload.get("success", True):
        _OPEN_DATE_CACHE[key] = "—"
        return "—"
    base = (payload.get("result") or {}).get("chainBase") or {}
    _OPEN_DATE_CACHE[key] = base.get("openDate") or "—"
    return _OPEN_DATE_CACHE[key]


def get_hotel_rooms(chain_id: object, start_date: date, end_date: date, token: str = ATOUR_TOKEN) -> list[dict[str, Any]]:
    """按 chainId 取某酒店在指定日期内的全部房型与价格。"""
    key = (str(chain_id), str(start_date), str(end_date))
    if key in _ROOM_CACHE:
        return _ROOM_CACHE[key]
    _request_delay_light()
    params = {
        "platType": _PLAT_TYPE,
        "appVer": _APP_VER,
        "token": token.strip(),
        "channelId": _CHANNEL_ID,
    }
    body = {
        "beginDate": str(start_date),
        "chainId": str(chain_id),
        "delegatorId": "",
        "sortByPriceWithCoupon": 1,
        "endDate": str(end_date),
        "delegatorMebId": "",
        "corporationId": "",
    }
    try:
        resp = requests.post(_QUOTE_API, params=params, headers=_build_headers(token), json=body, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException:
        _ROOM_CACHE[key] = []
        return []
    if not payload.get("success", True):
        _ROOM_CACHE[key] = []
        return []
    price_resp = (payload.get("result") or {}).get("priceResponse") or {}
    raw_rooms = price_resp.get("chainRoomList", []) or []
    out: list[dict[str, Any]] = []
    for rm in raw_rooms:
        info = rm.get("roomTypeInfoResponse") or {}
        mp = rm.get("minRoomPrice") or {}
        member = mp.get("showPrice")
        out.append({
            "房型": info.get("roomTypeName") or "",
            "铂金会员价": float(member) if member is not None else None,
            "门市价": float(mp.get("marketPrice")) if mp.get("marketPrice") is not None else None,
            "早餐数": mp.get("breakFastNum"),
            "取消政策": mp.get("cancelTips") or "",
            "最少入住晚数": mp.get("minimumBookDays"),
            "是否满房": "满房" if mp.get("isFullRoom") else "有房",
        })
    _ROOM_CACHE[key] = out
    return out


def _lowest_room_types(chain_id: object, start_date: date, end_date: date, token: str) -> str:
    rooms = get_hotel_rooms(chain_id, start_date, end_date, token)
    prices = [r["铂金会员价"] for r in rooms if r["铂金会员价"] is not None]
    if not prices:
        return "—"
    min_price = min(prices)
    lowest = [r for r in rooms if r["铂金会员价"] == min_price]

    extra = any((r.get("最少入住晚数") or 1) > 1 for r in lowest)
    if extra:
        return "—"
    return " / ".join(sorted({r["房型"] for r in lowest if r["房型"]}))


_CITY_SUFFIXES = ("市", "省", "县", "盟", "旗", "自治州", "地区", "自治区", "特别行政区")


def _normalize_location(location: str, scope: str) -> str:
    loc = location.strip()
    if not loc:
        return loc
    if scope == "province":
        if loc in _AUTONOMOUS:
            return _AUTONOMOUS[loc]
        if not (loc.endswith("省") or loc.endswith("市") or loc.endswith("自治区")):
            return loc + "省"
        return loc
    if not loc.endswith(_CITY_SUFFIXES):
        return loc + "市"
    return loc


def _build_headers(token: str) -> dict[str, str]:
    return {
        "At-Access-Token": token.strip(),
        "At-Platform-Type": _PLAT_TYPE,
        "At-Client-Id": _CLIENT_ID,
        "At-App-Version": _APP_VER,
        "At-Channel-Id": _CHANNEL_ID,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh-Hans;q=0.9",
        "User-Agent": "AtourLife/663 CFNetwork/3860.700.1 Darwin/25.6.0",
    }


def _query_chain(city_full: str, start_date: date, end_date: date, token: str, max_pages: int = 50, on_page=None) -> list[dict[str, Any]]:
    params = {
        "appVer": _APP_VER,
        "channelId": _CHANNEL_ID,
        "platType": _PLAT_TYPE,
        "token": token.strip(),
    }
    raw: list[dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        body = {
            "model": {
                "searchWord": "",
                "locationType": 1,
                "searchType": 0,
                "longitude": "0",
                "latitude": "0",
                "cityName": "",
                "order": 0,
                "brandList": [],
                "distanceCode": "",
                "poiId": "",
                "pageNo": page,
                "locationLatitude": "",
                "locationCityName": city_full,
                "startDate": str(start_date),
                "endDate": str(end_date),
                "locationLongitude": "",
                "tagCodeList": [],
            }
        }

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                _request_delay()
                resp = requests.post(_ATOUR_API, params=params, headers=_build_headers(token), json=body, timeout=15)
                resp.raise_for_status()
                payload = resp.json()
                if not payload.get("success"):
                    code = payload.get("code")
                    msg = payload.get("msg_code") or payload.get("msg") or payload.get("message")
                    raise AtourAPIError(
                        f"亚朵接口返回错误：code={code} msg={msg}。"
                        f"若需登录态请更新 config.yaml 中的 token；若为限流请稍后重试。"
                    )
                last_exc = None
                break
            except (requests.RequestException, AtourAPIError) as exc:
                last_exc = exc
                if attempt < 2:
                    _backoff = float(_REQ_CFG.get("retry_backoff", 1.5))
                    time.sleep(_backoff * (attempt + 1))
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        raw.extend(data.get("chainListResponseList", []))
        if on_page is not None:
            on_page(list(raw))
        if not data.get("hasNext"):
            break
        page += 1
    return [_normalize_hotel(h) for h in raw]


def _normalize_hotel(h: dict[str, Any]) -> dict[str, Any]:
    member = h.get("showPrice")
    full = h.get("fullRoom")

    img = (
        h.get("chainImgList") or h.get("chainImg")
        or h.get("imgList") or h.get("imgUrl")
        or h.get("coverImg") or h.get("mainImg") or h.get("image")
    )
    if isinstance(img, str):
        image_urls = [img]
    elif isinstance(img, list):
        image_urls = [str(x) for x in img if x]
    else:
        image_urls = []
    score = _to_float(h.get("judgementScore") or h.get("score") or h.get("grade"))
    comment_count = _to_int(h.get("judgementCount") or h.get("commentCount") or h.get("commentNum"))
    distance_km = _to_float(h.get("distance") or h.get("distanceKm") or h.get("distanceKM"))
    original_price = _to_float(h.get("marketPrice") or h.get("originalPrice"))
    discount_text = (
        h.get("discountText") or h.get("priceWithCouponDesc")
        or h.get("couponText") or h.get("priceTag") or ""
    )
    return {
        "酒店名称": h.get("name", ""),
        "酒店类型": _brand_from_name(h.get("name", "")),
        "开业时间": "—",

        "位置": h.get("chainArea") or h.get("cityName") or "",
        "地段/商圈": h.get("nearBusiness") or h.get("chainArea") or "",
        "房型": "—",
        "铂金会员价": float(member) if member is not None else None,
        "是否有房": "满房" if full else "有房",

        "latitude": _to_float(h.get("latitude")),
        "longitude": _to_float(h.get("longitude")),
        "chainId": h.get("chainId"),

        "封面图": image_urls[0] if image_urls else None,
        "评分": score,
        "点评数": comment_count,
        "距市公里": distance_km,
        "门市价": original_price,
        "优惠文本": str(discount_text) if discount_text else "",
    }


def _brand_from_name(name: str) -> str:
    # 名称含 v3.6/V3.6 的统一归为「亚朵V3.6」，优先于其他规则。
    if "3.6" in name:
        return "亚朵V3.6"
    for brand in ("亚朵S", "亚朵X", "轻居", "见野"):
        if brand in name:
            return "亚朵轻居" if brand == "轻居" else ("亚朵见野" if brand == "见野" else brand)
    return "亚朵"


_PROVINCE_SUFFIXES = ("壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "特别行政区", "省", "市")


def _province_short(loc: str) -> str:
    for suf in _PROVINCE_SUFFIXES:
        if loc.endswith(suf):
            return loc[: -len(suf)]
    return loc


def fetch_atour_prices(
    location: str,
    start_date: date,
    end_date: date,
    token: str = ATOUR_TOKEN,
    scope: str = "city",
    enrich_open_date: bool = True,
    on_progress=None,
) -> list[dict[str, Any]]:
    """获取指定地区内的酒店房型与会员价格。"""
    if not location.strip():
        raise ValueError("地区不能为空")
    if start_date >= end_date:
        raise ValueError("退房日期必须晚于入住日期")


    if scope == "city" and location.strip():

        known = {c for cs in _safe_province_cities(token).values() for c in cs}
        loc = location.strip() if location.strip() in known else _normalize_location(location, scope)
    else:
        loc = _normalize_location(location, scope)

    if scope == "province":
        short = _province_short(loc)
        grouped = _safe_province_cities(token)
        cities = grouped.get(short) or PROVINCE_CITIES.get(short)
        if not cities:
            raise ValueError(f"暂不支持省份「{short}」，请改用具体城市查询，或在省份列表中选择。")
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        failed = 0
        for city in cities:
            def _emit_prov(raw, _city=city):
                if on_progress is not None:
                    merged = records + [_normalize_hotel(h) for h in raw]
                    on_progress(merged, f"{_city}：已加载 {len(raw)} 家（累计 {len(merged)} 家）…")
            try:
                sub = _query_chain(city, start_date, end_date, token, on_page=_emit_prov)
            except AtourAPIError:
        
                failed += 1
                continue
            for r in sub:
                key = r["酒店名称"]
                if key not in seen:
                    seen.add(key)
                    records.append(r)
            if on_progress is not None:
                on_progress(records, f"已完成 {city}（累计 {len(records)} 家）")
        if not records and failed:
            raise AtourAPIError(
                f"该省份下 {failed}/{len(cities)} 个城市请求均失败（接口可能限流或临时不可用），"
                f"请稍后重试，或直接在「城市」范围查询具体城市。"
            )
    else:
        def _emit_city(raw):
            if on_progress is not None:
                on_progress([_normalize_hotel(h) for h in raw], f"已加载 {len(raw)} 家酒店…")
        records = _query_chain(loc, start_date, end_date, token, on_page=_emit_city)

    if enrich_open_date and records:
        seen_id: set[str] = set()
        unique_records: list[dict[str, Any]] = []
        for r in records:
            cid = r.get("chainId")
            if not cid or cid in seen_id:
                continue
            seen_id.add(cid)
            unique_records.append(r)
        total_unique = len(unique_records)

        def _enrich_one(idx_r):
            idx, r = idx_r
            cid = r["chainId"]
            open_date = _fetch_open_date(cid, token)
            return idx, open_date

        done = 0
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_enrich_one, (i, r)): i for i, r in enumerate(unique_records)}
            for future in as_completed(futures):
                idx, open_date = future.result()
                unique_records[idx]["开业时间"] = open_date
                done += 1
                if on_progress is not None and (done % 5 == 0 or done == total_unique):
                    on_progress(records, f"补全开业时间：{done}/{total_unique} 家…")

    return records


def _safe_province_cities(token: str) -> dict[str, list[str]]:
    try:
        return get_atour_cities(token)
    except AtourAPIError:
        return {}
