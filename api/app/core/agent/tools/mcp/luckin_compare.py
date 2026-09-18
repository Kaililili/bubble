"""瑞幸比价聚合工具:附近门店某饮品价格排序。

真实调用链(基于瑞幸官方 MCP 工具清单确认):
  queryShopList(经纬度) → 附近门店(distance 升序)
  searchProductForMcp(deptId, query) → 匹配商品(自带 initialPrice/estimatePrice)
  汇总 → 按 estimatePrice 升序返回 top 3

设计:
- 聚合工具始终注册,未配置/失败时返回明确提示(降级有信息量)。
- 内部用单个 MCP session 串行调用,避免每次工具调用重新握手。
- 只查询,不触碰 previewOrder/createOrder/cancelOrder 等副作用工具。
"""
import json
import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from ..base import ToolContext, register_tool

logger = logging.getLogger(__name__)

# 默认查询位置(未提供经纬度时用北京王府井)
DEFAULT_LONGITUDE = 116.397
DEFAULT_LATITUDE = 39.909
MAX_SHOPS = 5


def _match_score(keyword: str, name: str) -> int:
    """中文无分词,用 2-gram 交集衡量 query 与商品名的匹配度。

    例: query=葡萄柠檬茶 → 2-gram {葡萄,萄柠,柠檬,檬茶}
        "葡萄鲜切柠檬茶(超大杯)" 命中 葡萄/柠檬/檬茶 → 高分
        "柚C美式" 无命中 → 0
    """
    kw = keyword.replace(" ", "").lower()
    nm = (name or "").lower()
    if not kw or not nm:
        return 0
    if kw in nm:
        return 1000
    grams = {kw[i : i + 2] for i in range(len(kw) - 1)}
    if not grams:
        return 100 if kw in nm else 0
    return sum(1 for g in grams if g in nm)


def _query_variants(keyword: str) -> list[str]:
    """生成搜索词变体:瑞幸 search 对组合长词(如「葡萄柠檬茶」)常返回无关推荐,
    去掉 1-2 字前缀后用尾部品类词(如「柠檬茶」)补搜。
    """
    kw = keyword.replace(" ", "")
    variants = [kw]
    for i in (1, 2):
        if i < len(kw) and kw[i:] not in variants:
            variants.append(kw[i:])
    return variants


async def _search_best(mcp_session: Any, dept_id: Any, keyword: str) -> dict | None:
    """对一家门店用全名 + 变体补搜,返回 2-gram 最匹配的商品;无匹配返回 None。"""
    best: dict | None = None
    best_score = 0
    for q in _query_variants(keyword):
        data = await _call_json(
            mcp_session,
            "searchProductForMcp",
            {"deptId": dept_id, "query": q},
        )
        for p in data.get("data") or []:
            if not isinstance(p, dict):
                continue
            score = _match_score(keyword, p.get("productName", ""))
            if score > best_score:
                best, best_score = p, score
        if best_score > 0:
            break  # 全名已命中就不必拆词补搜(常见饮品保持快速)
    return best


class LuckinCompareArgs(BaseModel):
    keyword: str = Field(..., max_length=100, description="饮品关键词,如 生椰拿铁/葡萄柠檬茶")
    longitude: float | None = Field(None, description="经度,缺省用默认位置")
    latitude: float | None = Field(None, description="纬度,缺省用默认位置")


async def _call_json(session: Any, name: str, args: dict) -> dict:
    """调用 MCP 工具并把返回 content 解析为 JSON。"""
    result = await session.call_tool(name, args)
    text = ""
    for c in result.content:
        if getattr(c, "text", None) is not None:
            text += str(c.text)
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"data": None, "raw": text}


async def _open_session(server):
    """按 server 传输类型打开 MCP 会话(返回 context manager 与 session)。"""
    from app.core.agent.tools.mcp.connection import build_connection

    conn = await build_connection(server)
    url = conn["url"]
    headers = conn.get("headers")
    if conn.get("transport") == "sse":
        from mcp.client.sse import sse_client

        return sse_client(url, headers=headers), None
    from mcp.client.streamable_http import streamablehttp_client

    return streamablehttp_client(url, headers=headers), conn


async def _find_luckin_server(session: AsyncSession, user_id: UUID):
    """找该用户已启用的瑞幸 MCP 配置(按名字含 luck/coffee)。"""
    from app.repositories.mcp_server_repository import MCPServerRepository

    servers = await MCPServerRepository(session).list_by_user(user_id, enabled_only=True)
    return next(
        (s for s in servers if "luck" in s.name.lower() or "coffee" in s.name.lower()),
        None,
    )


async def _resolve_position(
    session: AsyncSession,
    user_id: UUID,
    longitude: float | None,
    latitude: float | None,
) -> tuple[float, float]:
    """定位优先级:显式传入 > 用户背景「位置」(纬度,经度) > 默认位置。"""
    if longitude is None or latitude is None:
        from app.repositories.memory_repository import UserProfileRepository

        profiles = await UserProfileRepository(session).list_by_user(user_id)
        loc = next(
            (p for p in profiles if any(k in p.key for k in ("位置", "经纬度", "定位"))),
            None,
        )
        if loc is not None:
            try:
                parts = loc.value.replace("，", ",").split(",")
                if len(parts) >= 2:
                    if longitude is None:
                        longitude = float(parts[1].strip())
                    if latitude is None:
                        latitude = float(parts[0].strip())
            except (TypeError, ValueError):
                pass
    return (
        longitude if longitude is not None else DEFAULT_LONGITUDE,
        latitude if latitude is not None else DEFAULT_LATITUDE,
    )


def _shop_to_dict(shop: dict) -> dict:
    """瑞幸门店原始字段 → 对外统一结构。"""
    return {
        "dept_id": shop.get("deptId"),
        "shop": shop.get("deptName", f"门店{shop.get('deptId')}"),
        "distance_km": shop.get("distance"),
        "address": shop.get("address", ""),
        "status": shop.get("workStatus", ""),
        "hours": (
            f"{shop.get('workTimeStart', '')}-{shop.get('workTimeEnd', '')}"
            if shop.get("workTimeStart")
            else ""
        ),
    }


async def _fetch_shops(mcp_session: Any, lon: float, lat: float) -> list[dict]:
    """queryShopList → 最近门店数组(已按接口返回顺序取前 MAX_SHOPS)。"""
    data = await _call_json(mcp_session, "queryShopList", {"longitude": lon, "latitude": lat})
    shops = data.get("data") or []
    if not isinstance(shops, list):
        return []
    return shops[:MAX_SHOPS]


async def run_luckin_compare(
    session: AsyncSession,
    user_id: UUID,
    keyword: str,
    longitude: float | None = None,
    latitude: float | None = None,
) -> list[dict]:
    """比价主流程:定位 → 最近门店 → 逐店匹配饮品价格 → 按价排序。"""
    from mcp import ClientSession

    server = await _find_luckin_server(session, user_id)
    if server is None:
        return [{"error": "未配置瑞幸 MCP,请先在「设置 → MCP」添加 luckin 配置并测试连接"}]
    lon, lat = await _resolve_position(session, user_id, longitude, latitude)
    try:
        cm, _ = await _open_session(server)
        async with cm as (read, write, _):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()
                shops = await _fetch_shops(mcp_session, lon, lat)
                if not shops:
                    return [{"error": "附近没有找到瑞幸门店"}]

                results: list[dict] = []
                for shop in shops:
                    dept_id = shop.get("deptId")
                    if not dept_id:
                        continue
                    first = await _search_best(mcp_session, dept_id, keyword)
                    if first is None:
                        continue  # 该店没有匹配商品
                    product_name = first.get("productName", "")
                    product_id = first.get("productId")
                    # search 返回的是「超大杯」等高规格价;详情接口返回默认规格(大杯)的预估价,
                    # 与小程序默认展示一致,故以 detail 为准
                    price = first.get("estimatePrice")
                    if product_id:
                        try:
                            detail_data = await _call_json(
                                mcp_session,
                                "queryProductDetailInfo",
                                {"deptId": dept_id, "productId": product_id},
                            )
                            detail = detail_data.get("data") or {}
                            if isinstance(detail, dict):
                                price = detail.get("estimatePrice")
                                if price is None:
                                    price = detail.get("initialPrice")
                                if not product_name:
                                    product_name = detail.get("productName", "")
                        except Exception:  # noqa: BLE001
                            pass
                    results.append(
                        {
                            "dept_id": shop.get("deptId"),
                            "shop": shop.get("deptName", f"门店{dept_id}"),
                            "distance_km": shop.get("distance"),
                            "price": price,
                            "product": product_name,
                            "product_id": product_id,
                        }
                    )

                if not results:
                    return [
                        {
                            "error": (
                                f"已检查附近 {min(len(shops), MAX_SHOPS)} 家门店,"
                                f"没有找到与「{keyword}」匹配的在售饮品。"
                                "请确认商品名后重试,如「葡萄鲜切柠檬茶」「生椰拿铁」。"
                            )
                        }
                    ]
                results.sort(key=lambda x: (x["price"] is None, x["price"] or 0))
                return results[:3]
    except Exception as e:  # noqa: BLE001
        logger.warning("瑞幸比价失败: %s", e)
        return [{"error": f"瑞幸服务暂不可用: {e}"}]


async def run_luckin_nearby_shops(
    session: AsyncSession,
    user_id: UUID,
    longitude: float | None = None,
    latitude: float | None = None,
) -> list[dict]:
    """查附近瑞幸门店:定位 → queryShopList → 门店列表(名称/距离/地址/营业状态)。"""
    from mcp import ClientSession

    server = await _find_luckin_server(session, user_id)
    if server is None:
        return [{"error": "未配置瑞幸 MCP,请先在「设置 → MCP」添加 luckin 配置并测试连接"}]
    lon, lat = await _resolve_position(session, user_id, longitude, latitude)
    try:
        cm, _ = await _open_session(server)
        async with cm as (read, write, _):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()
                shops = await _fetch_shops(mcp_session, lon, lat)
                if not shops:
                    return [{"error": "附近没有找到瑞幸门店"}]
                return [_shop_to_dict(s) for s in shops]
    except Exception as e:  # noqa: BLE001
        logger.warning("查询瑞幸门店失败: %s", e)
        return [{"error": f"瑞幸服务暂不可用: {e}"}]


class LuckinNearbyShopsArgs(BaseModel):
    """无参数:位置自动从用户背景读取"""


@register_tool(
    "luckin_nearby_shops",
    "查询用户附近有哪些瑞幸咖啡门店(名称/距离/地址/营业时间)。"
    "当用户问附近有没有瑞幸、哪家瑞幸近、列出附近瑞幸门店时调用。"
    "无需参数,位置自动读取。返回 JSON 数组。",
    LuckinNearbyShopsArgs,
)
async def luckin_nearby_shops(ctx: ToolContext, **kwargs) -> str:
    items = await run_luckin_nearby_shops(ctx.session, ctx.user_id)
    return json.dumps(items, ensure_ascii=False)


@register_tool(
    "luckin_compare",
    "瑞幸饮品比价:用户问某款饮品哪家门店便宜、多少钱时调用,"
    "自动查最近门店该饮品价格并按价格从低到高排序。"
    "注意:只是查附近门店列表请用 luckin_nearby_shops。返回 JSON 数组。",
    LuckinCompareArgs,
)
async def luckin_compare(
    ctx: ToolContext,
    keyword: str,
    longitude: float | None = None,
    latitude: float | None = None,
) -> str:
    items = await run_luckin_compare(ctx.session, ctx.user_id, keyword, longitude, latitude)
    return json.dumps(items, ensure_ascii=False)


# ── 下单链路(预览/创建/取消/查单) ─────────────────────────────
# 注意:createOrder/cancelOrder 有真实副作用(生成待支付订单),只允许用户显式确认后
# 通过 REST 调用(瑞幸页按钮),**不注册为工具**,LLM 无法自主触发下单。


async def _order_sku(mcp_session: Any, dept_id: Any, product_id: Any) -> str | None:
    """detail 拿商品默认规格的 skuCode(下单/预览必需)。"""
    detail = await _call_json(
        mcp_session, "queryProductDetailInfo", {"deptId": dept_id, "productId": product_id}
    )
    d = detail.get("data") or {}
    return d.get("skuCode") if isinstance(d, dict) else None


async def _apply_specs(
    mcp_session: Any,
    dept_id: Any,
    product_id: Any,
    start_sku: str,
    specs: list[dict] | None,
) -> str:
    """链式应用口味修改:每次 switchProduct 返回新 skuCode,作为下一次修改的基础。"""
    sku = start_sku
    for spec in specs or []:
        attribute_id = spec.get("attribute_id") or spec.get("attributeId")
        sub_attribute_id = spec.get("sub_attribute_id") or spec.get("subAttributeId")
        if not attribute_id or not sub_attribute_id:
            continue
        result = await _call_json(
            mcp_session,
            "switchProduct",
            {
                "deptId": dept_id,
                "productId": product_id,
                "skuCode": sku,
                "attrOperationParam": {
                    "attributeId": attribute_id,
                    "subAttr": {"attributeId": sub_attribute_id, "operation": 1},
                },
                "amount": 1,
            },
        )
        data = result.get("data") or {}
        if isinstance(data, dict) and data.get("skuCode"):
            sku = data["skuCode"]
    return sku


async def run_order_preview(
    session: AsyncSession,
    user_id: UUID,
    dept_id: int,
    product_id: int,
    amount: int = 1,
    specs: list[dict] | None = None,
) -> dict:
    """订单预览(无副作用):detail 默认 sku →(可选)链式应用口味 → previewOrder → 明细。"""
    from mcp import ClientSession

    server = await _find_luckin_server(session, user_id)
    if server is None:
        return {"error": "未配置瑞幸 MCP,请先在「设置 → MCP」添加 luckin 配置并测试连接"}
    try:
        cm, _ = await _open_session(server)
        async with cm as (read, write, _):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                sku = await _order_sku(mcp, dept_id, product_id)
                if not sku:
                    return {"error": "获取商品规格失败,请重试"}
                sku = await _apply_specs(mcp, dept_id, product_id, sku, specs)
                preview = await _call_json(
                    mcp,
                    "previewOrder",
                    {
                        "deptId": dept_id,
                        "productList": [
                            {"amount": amount, "productId": product_id, "skuCode": sku}
                        ],
                    },
                )
                if preview.get("code") != 0:
                    return {"error": preview.get("msg") or "订单预览失败"}
                data = preview.get("data") or {}
                shop_info = data.get("shopInfo") or {}
                prod_info = (data.get("productInfoList") or [{}])[0]
                about_ts = data.get("aboutTime")
                about = ""
                if about_ts:
                    from datetime import datetime, timedelta, timezone

                    about = (
                        datetime.fromtimestamp(about_ts / 1000, tz=timezone(timedelta(hours=8)))
                        .strftime("%H:%M")
                    )
                return {
                    "dept_id": dept_id,
                    "product_id": product_id,
                    "shop": shop_info.get("deptName", ""),
                    "address": shop_info.get("address", ""),
                    "product": prod_info.get("name", ""),
                    "spec": prod_info.get("additionDesc", ""),
                    "amount": amount,
                    "original_price": data.get("totalInitialPrice"),
                    "discount_price": data.get("discountPrice"),
                    "privilege_money": data.get("privilegeMoney"),
                    "about_time": about,
                    "sku_code": sku,
                }
    except Exception as e:  # noqa: BLE001
        logger.warning("瑞幸订单预览失败: %s", e)
        return {"error": f"订单预览失败: {e}"}


async def run_order_options(
    session: AsyncSession,
    user_id: UUID,
    dept_id: int,
    product_id: int,
) -> dict:
    """商品口味选项(无副作用):返回属性树(杯型/温度/糖度等)供前端渲染选择器。"""
    from mcp import ClientSession

    server = await _find_luckin_server(session, user_id)
    if server is None:
        return {"error": "未配置瑞幸 MCP,请先在「设置 → MCP」添加 luckin 配置并测试连接"}
    try:
        cm, _ = await _open_session(server)
        async with cm as (read, write, _):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                detail = await _call_json(
                    mcp, "queryProductDetailInfo", {"deptId": dept_id, "productId": product_id}
                )
                d = detail.get("data") or {}
                if not isinstance(d, dict) or not d:
                    return {"error": "获取商品信息失败,请重试"}
                attrs = []
                for a in d.get("productAttrs") or []:
                    if not isinstance(a, dict):
                        continue
                    subs = []
                    for s in a.get("productSubAttrs") or []:
                        if not isinstance(s, dict):
                            continue
                        subs.append(
                            {
                                "sub_attribute_id": s.get("attributeId"),
                                "name": s.get("attributeName"),
                                "price_delta": s.get("price"),
                                "selected": bool(s.get("selected")),
                                "can_select": s.get("canSelected") != 0,
                            }
                        )
                    attrs.append(
                        {
                            "attribute_id": a.get("attributeId"),
                            "name": a.get("attributeName"),
                            "options": subs,
                        }
                    )
                return {
                    "dept_id": dept_id,
                    "product_id": product_id,
                    "product": d.get("productName", ""),
                    "sku_code": d.get("skuCode", ""),
                    "initial_price": d.get("initialPrice"),
                    "estimate_price": d.get("estimatePrice"),
                    "attributes": attrs,
                }
    except Exception as e:  # noqa: BLE001
        logger.warning("获取瑞幸口味选项失败: %s", e)
        return {"error": f"获取商品选项失败: {e}"}


async def run_order_create(
    session: AsyncSession,
    user_id: UUID,
    dept_id: int,
    product_id: int,
    amount: int = 1,
    remark: str = "",
    sku_code: str | None = None,
    specs: list[dict] | None = None,
    longitude: float | None = None,
    latitude: float | None = None,
) -> dict:
    """创建订单(真实副作用):sku_code 优先(预览确认后定稿),否则按默认或 specs 计算。"""
    from mcp import ClientSession

    server = await _find_luckin_server(session, user_id)
    if server is None:
        return {"error": "未配置瑞幸 MCP,请先在「设置 → MCP」添加 luckin 配置并测试连接"}
    lon, lat = await _resolve_position(session, user_id, longitude, latitude)
    try:
        cm, _ = await _open_session(server)
        async with cm as (read, write, _):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                sku = sku_code or await _order_sku(mcp, dept_id, product_id)
                if not sku:
                    return {"error": "获取商品规格失败,请重试"}
                if not sku_code:
                    sku = await _apply_specs(mcp, dept_id, product_id, sku, specs)
                created = await _call_json(
                    mcp,
                    "createOrder",
                    {
                        "deptId": dept_id,
                        "productList": [
                            {"amount": amount, "productId": product_id, "skuCode": sku}
                        ],
                        "longitude": lon,
                        "latitude": lat,
                        "remark": remark,
                    },
                )
                if created.get("code") != 0:
                    return {"error": created.get("msg") or "下单失败"}
                data = created.get("data") or {}
                return {
                    "order_id": data.get("orderIdStr") or str(data.get("orderId", "")),
                    "pay_qr_url": data.get("payOrderQrCodeUrl"),
                    "pay_url": data.get("payOrderUrl"),
                    "discount_price": data.get("discountPrice"),
                    "need_pay": data.get("needPay"),
                }
    except Exception as e:  # noqa: BLE001
        logger.warning("瑞幸下单失败: %s", e)
        return {"error": f"下单失败: {e}"}


async def run_order_cancel(session: AsyncSession, user_id: UUID, order_id: str) -> dict:
    """取消订单(有副作用,仅用于清理未支付订单)。"""
    from mcp import ClientSession

    server = await _find_luckin_server(session, user_id)
    if server is None:
        return {"error": "未配置瑞幸 MCP,请先在「设置 → MCP」添加 luckin 配置并测试连接"}
    try:
        cm, _ = await _open_session(server)
        async with cm as (read, write, _):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                result = await _call_json(mcp, "cancelOrder", {"orderId": str(order_id)})
                if result.get("code") != 0:
                    return {"error": result.get("msg") or "取消失败"}
                return {"cancelled": bool(result.get("data"))}
    except Exception as e:  # noqa: BLE001
        return {"error": f"取消失败: {e}"}


async def run_order_query(session: AsyncSession, user_id: UUID, order_id: str) -> dict:
    """查询订单状态(支付确认用,无副作用)。"""
    from mcp import ClientSession

    server = await _find_luckin_server(session, user_id)
    if server is None:
        return {"error": "未配置瑞幸 MCP,请先在「设置 → MCP」添加 luckin 配置并测试连接"}
    try:
        cm, _ = await _open_session(server)
        async with cm as (read, write, _):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                result = await _call_json(mcp, "queryOrderDetailInfo", {"orderId": str(order_id)})
                if result.get("code") != 0:
                    return {"error": result.get("msg") or "查询失败"}
                data = result.get("data") or {}
                if not isinstance(data, dict):
                    return {"data": data}
                return {
                    "order_id": data.get("orderId") or str(data.get("orderId", "")),
                    "status_code": data.get("orderStatus"),
                    "status_name": data.get("orderStatusName") or "",
                    "pay_amount": data.get("orderPayAmount"),
                }
    except Exception as e:  # noqa: BLE001
        return {"error": f"查询订单失败: {e}"}
