"""GraphRAG 多跳检索:向量种子 → 实体图扩展 → 联合重排 → 证据组装。

图里只有 Entity 与实体间关联;"种子"是用户关注的实体(INTERESTED_IN 指向的那些)。
打分与格式化是纯函数,便于单测;图库不可用时自动降级为 PG 种子结果。
"""
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from .embedding import build_embedder
from .graph_repo import MAX_HOPS, InterestGraphRepo
from .normalizer import normalize_key

logger = logging.getLogger(__name__)

HOP_WEIGHT = {0: 1.0, 1: 0.6, 2: 0.35, 3: 0.2}
W_VECTOR = 0.55
W_HOP = 0.25
W_HEAT = 0.12
W_RECENCY = 0.08
HEAT_CAP = 6
DEFAULT_LIMIT = 8
KEYWORD_SIM = 0.55
TOP_SIM = 0.3
# 向量种子最低相似度:低于阈值不当作种子,避免小语料下 top-k 全命中导致多跳被短路
MIN_SEED_SIM = 0.5
# 实体反查命中(问"CBA/库里"这类实体)时的种子相似度
ENTITY_SIM = 0.65
# 关系型问题才做"两两最短路",避免"我都关注过什么"这类列举问题误报无关联
_RELATION_INTENT = ("关系", "关联", "联系", "有关", "相关吗", "相关么", "什么关系", "有没有关系")

_FILLER_RE = re.compile(
    r"(我|你|他|她|以前|之前|现在|最近|还|也|都|又|看过|看看|看|关注过|关注|追过|追|"
    r"喜欢过|喜欢|是不是|有没有|有|跟|和|与|相关|关系|关联|联系|有关|"
    r"吗|么|呢|的|了|什么|哪些|哪个|大概|时间段|时间|是否)"
)
_LATIN_RE = re.compile(r"[A-Za-z0-9]{2,}")
_PUNCT_RE = re.compile(r"[?？!！。，,、;；:：\"'“”‘’\s]+")
# 关系型问句的尾巴("...(是)什么关系/有关联吗/有联系么"),切锚点前先剥掉
_RELATION_TAIL_RE = re.compile(
    r"(之间)?(是|为|算)?(有什么|有啥|什么|有没有|有)?(关系|关联|联系|有关)?(吗|么|呢)?$"
)
# 锚点词两端残留的系词/介词
_ANCHOR_TRIM_RE = re.compile(r"^(是|为|算|跟|和|与)+|(是|为|算)+$")
# 两侧实体的连接词
_ANCHOR_SPLIT_RE = re.compile(r"(?:和|与|跟|以及|还有|、)")


def query_terms(query: str) -> list[str]:
    """从问句里抽出用于实体反查的词:去掉人称/疑问噪声,再补上英文数字词"""
    text = (query or "").strip()
    if not text:
        return []
    terms: list[str] = []
    core = _PUNCT_RE.sub("", _FILLER_RE.sub("", text))
    if core:
        terms.append(core)
    lowered = {t.lower() for t in terms}
    for token in _LATIN_RE.findall(text):
        if token.lower() not in lowered:
            terms.append(token)
            lowered.add(token.lower())
    return terms[:5]


def relation_terms(query: str) -> list[str]:
    """关系型问句("A 和 B 有什么关系")里两侧的实体词,用于解析成最短路锚点。

    没有这个,只命中一侧种子时就无法判定"两者无关联",回答会退化成对单个实体的泛泛描述。
    """
    text = _PUNCT_RE.sub("", query or "")
    text = _RELATION_TAIL_RE.sub("", text)
    terms: list[str] = []
    for part in _ANCHOR_SPLIT_RE.split(text):
        cleaned = _ANCHOR_TRIM_RE.sub("", _FILLER_RE.sub("", part).strip()).strip()
        value = cleaned or part.strip()
        if value and value not in terms:
            terms.append(value)
    return terms[:4]


@dataclass
class Candidate:
    key: str
    name: str
    category: str = "其他"
    entity_type: str = "other"
    hops: int = 0
    vec_sim: float = 0.0
    mention_count: int = 0
    status: str = "active"
    since: date | None = None
    until: date | None = None
    last_seen: datetime | None = None
    path: list[str] = field(default_factory=list)
    via: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    reason: str = "seed"


def hop_weight(hops: int) -> float:
    return HOP_WEIGHT.get(max(0, min(int(hops or 0), MAX_HOPS)), 0.2)


def heat_score(mention_count: int | None) -> float:
    count = max(0, int(mention_count or 0))
    return min(1.0, math.log(1 + count) / math.log(1 + HEAT_CAP))


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def recency_score(last_seen, now: datetime | None = None) -> float:
    ts = _parse_dt(last_seen)
    if ts is None:
        return 0.5
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - ts).total_seconds() / 86400)
    if days <= 30:
        return 1.0
    if days <= 90:
        return 0.6
    return 0.3


def score_candidate(cand: Candidate, now: datetime | None = None) -> float:
    return (
        W_VECTOR * max(0.0, min(float(cand.vec_sim or 0.0), 1.0))
        + W_HOP * hop_weight(cand.hops)
        + W_HEAT * heat_score(cand.mention_count)
        + W_RECENCY * recency_score(cand.last_seen, now)
    )


def _fmt_date(value) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value[:10]
    return None


def fmt_range(since, until) -> str:
    start, end = _fmt_date(since), _fmt_date(until)
    if start and end:
        return f"{start} ~ {end}"
    if start:
        return f"{start} 至今"
    if end:
        return f"截至 {end}"
    return ""


def _merge_candidate(cands: dict[str, Candidate], incoming: Candidate) -> None:
    existing = cands.get(incoming.key)
    if existing is None:
        cands[incoming.key] = incoming
        return
    if incoming.hops < existing.hops:
        existing.hops = incoming.hops
        existing.reason = incoming.reason
        existing.path = incoming.path or existing.path
    existing.vec_sim = max(existing.vec_sim, incoming.vec_sim)
    existing.via = list(dict.fromkeys([*existing.via, *incoming.via]))
    existing.related = list(dict.fromkeys([*existing.related, *incoming.related]))
    if incoming.path and not existing.path:
        existing.path = incoming.path
    existing.mention_count = max(existing.mention_count, incoming.mention_count)
    if incoming.last_seen and (not existing.last_seen or incoming.last_seen > existing.last_seen):
        existing.last_seen = incoming.last_seen
    if existing.status != "cooled" and incoming.status == "cooled":
        existing.status = incoming.status


async def _embed_query(session, user_id, query: str) -> list | None:
    embedder = await build_embedder(session, user_id)
    if embedder is None:
        return None
    try:
        return await embedder.aembed_query(query)
    except Exception as e:  # noqa: BLE001
        logger.warning("interest query embedding failed: %s", e)
        return None


async def recall(
    session,
    user_id,
    query: str = "",
    *,
    hops: int = 2,
    include_cooled: bool = True,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """GraphRAG 多跳检索,返回结构化结果 + 供 LLM 使用的证据文本"""
    from ....repositories.interest_repository import InterestRepository

    repo = InterestRepository(session)
    hops = max(1, min(int(hops or 2), MAX_HOPS))
    limit = max(1, min(int(limit or DEFAULT_LIMIT), 20))
    query = (query or "").strip()

    # ① 种子:向量 → 关键词 → 实体反查 → 活跃兜底
    seeds: list[tuple[object, float, str, list[str]]] = []
    if query:
        vector = await _embed_query(session, user_id, query)
        if vector is not None:
            seeds = [
                (n, sim, "seed", [])
                for n, sim in await repo.search_by_vector(user_id, vector, top_k=5)
                if sim >= MIN_SEED_SIM
            ]
        if not seeds:
            normalized = normalize_key(query)
            nodes = await repo.search_by_keyword(user_id, normalized or query, limit=5)
            if not nodes and normalized != query:
                nodes = await repo.search_by_keyword(user_id, query, limit=5)
            seeds = [(n, KEYWORD_SIM, "keyword", []) for n in nodes]
    if not seeds:
        # 实体反查:用户问的可能不是被关注的实体本身,而是它的关联实体(如"CBA""库里")
        terms = query_terms(query)
        if terms:
            try:
                hits = await InterestGraphRepo().find_interests_by_entity(
                    user_id=user_id, terms=terms, limit=5
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("interest entity lookup failed: %s", e)
                hits = []
            if hits:
                nodes = await repo.list_by_keys(user_id, [h["key"] for h in hits])
                node_by_key = {n.key: n for n in nodes}
                via_by_key = {
                    h["key"]: [str(v) for v in (h.get("via") or [])] for h in hits
                }
                for hit in hits:
                    node = node_by_key.get(hit["key"])
                    if node is not None:
                        seeds.append(
                            (node, ENTITY_SIM, "entity_match", via_by_key.get(hit["key"], []))
                        )
    # 关系型问句("A 和 B 有什么关系"):两侧实体都解析成锚点,
    # 否则只命中一侧种子时判定不了"两者无关联"(会退化成泛泛描述)
    if query and any(k in query for k in _RELATION_INTENT):
        seed_keys = {n.key for n, _, _, _ in seeds}
        for term in relation_terms(query):
            key = normalize_key(term)
            if not key or key in seed_keys:
                continue
            try:
                anchors = await repo.search_by_keyword(user_id, key, limit=1)
            except Exception as e:  # noqa: BLE001
                logger.warning("interest anchor lookup failed: %s", e)
                anchors = []
            for node in anchors:
                if node.key in seed_keys:
                    continue
                seeds.append((node, ENTITY_SIM, "query_anchor", []))
                seed_keys.add(node.key)
    if not seeds:
        seeds = [(n, TOP_SIM, "top", []) for n in await repo.top_active(user_id, limit=5)]
    if not seeds:
        return {
            "items": [],
            "paths": [],
            "bridges": [],
            "graph_available": False,
            "seed_count": 0,
            "multi_count": 0,
            "text": "还没有记录到你的兴趣,暂时无法回顾。",
        }

    # ② 图扩展(失败降级为纯 PG)
    graph_available = False
    graph_data: dict = {"seeds": [], "neighbors": [], "bridges": []}
    try:
        graph_data = await InterestGraphRepo().neighborhood(
            user_id=user_id, keys=[n.key for n, _, _, _ in seeds], hops=hops, limit=limit
        )
        graph_available = True
    except Exception as e:  # noqa: BLE001
        logger.warning("interest graph expansion failed, degrade to PG seeds: %s", e)

    # ③ 合并候选并重排
    cands: dict[str, Candidate] = {}
    for node, sim, reason, via in seeds:
        _merge_candidate(
            cands,
            Candidate(
                key=node.key,
                name=node.name,
                category=node.category,
                entity_type=getattr(node, "entity_type", None) or "other",
                hops=0,
                vec_sim=float(sim),
                mention_count=node.mention_count or 0,
                status=node.status,
                since=node.since,
                until=node.until,
                last_seen=node.last_seen,
                via=list(via),
                reason=reason,
            ),
        )
    # 关注实体的关联实体(1~2 跳邻居)按种子归类,用于证据展示
    related_by_seed: dict[str, list[str]] = {}
    for row in graph_data.get("neighbors") or []:
        seed_name = row.get("seed_name")
        if seed_name:
            related_by_seed.setdefault(seed_name, [])
            name = row.get("name")
            if name and name not in related_by_seed[seed_name]:
                related_by_seed[seed_name].append(name)
    for cand in cands.values():
        if cand.hops == 0 and related_by_seed.get(cand.name):
            cand.related = related_by_seed[cand.name]

    for row in graph_data.get("neighbors") or []:
        _merge_candidate(
            cands,
            Candidate(
                key=row.get("key"),
                name=row.get("name") or row.get("key"),
                category=row.get("category") or "其他",
                entity_type=row.get("type") or "other",
                hops=int(row.get("hops") or 1),
                path=[str(v) for v in (row.get("path") or [])],
                reason="entity_neighbor",
            ),
        )
    for row in graph_data.get("bridges") or []:
        _merge_candidate(
            cands,
            Candidate(
                key=row.get("key"),
                name=row.get("name") or row.get("key"),
                category=row.get("category") or "其他",
                entity_type=row.get("type") or "other",
                hops=2,
                via=[str(v) for v in (row.get("via_entities") or [])],
                reason="shared_entity",
            ),
        )
    missing = [
        k for k in cands if not cands[k].mention_count and k in {n.key for n, _, _, _ in seeds}
    ]
    if missing:
        for node in await repo.list_by_keys(user_id, missing):
            cand = cands[node.key]
            cand.mention_count = node.mention_count or 0
            cand.status = node.status
            cand.since, cand.until, cand.last_seen = node.since, node.until, node.last_seen

    candidates = list(cands.values())
    if not include_cooled:
        candidates = [c for c in candidates if c.status != "cooled"]
    for cand in candidates:
        cand.score = score_candidate(cand)  # type: ignore[attr-defined]
    candidates.sort(key=lambda c: getattr(c, "score", 0.0), reverse=True)
    pair_pool = [c for c in candidates if c.hops == 0][:3]
    candidates = candidates[:limit]

    # 路径型问题:两个种子实体之间的最短路(最多 3 对,失败降级)
    no_path_pairs: list[tuple[str, str]] = []
    relation_intent = any(k in query for k in _RELATION_INTENT)
    if graph_available and relation_intent and len(pair_pool) >= 2:
        for i in range(len(pair_pool)):
            for j in range(i + 1, len(pair_pool)):
                try:
                    nodes = await InterestGraphRepo().shortest_path(
                        user_id=user_id,
                        a_key=pair_pool[i].key,
                        b_key=pair_pool[j].key,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("interest shortest path failed: %s", e)
                    nodes = None
                if nodes and len(nodes) >= 2:
                    graph_data.setdefault("shortest_paths", []).append(
                        {
                            "from": pair_pool[i].name,
                            "to": pair_pool[j].name,
                            "nodes": nodes,
                            "hops": len(nodes) - 1,
                        }
                    )
                else:
                    no_path_pairs.append((pair_pool[i].name, pair_pool[j].name))

    # ④ 组装证据
    items = [
        {
            "key": c.key,
            "name": c.name,
            "category": c.category,
            "entity_type": c.entity_type,
            "status": c.status,
            "hops": c.hops,
            "score": round(float(getattr(c, "score", 0.0)), 4),
            "vec_sim": round(float(c.vec_sim or 0.0), 4),
            "mention_count": c.mention_count,
            "since": _fmt_date(c.since),
            "until": _fmt_date(c.until),
            "last_seen": _fmt_date(c.last_seen),
            "via": c.via,
            "path": c.path,
            "reason": c.reason,
            "entities": c.related,
        }
        for c in candidates
    ]
    paths = [
        {"from": item["path"][0], "to": item["path"][-1], "hops": item["hops"], "nodes": item["path"]}
        for item in items
        if item["path"]
    ]
    for sp in graph_data.get("shortest_paths") or []:
        paths.append(
            {"from": sp["from"], "to": sp["to"], "hops": sp["hops"], "nodes": sp["nodes"]}
        )
    bridges = [
        {"to": item["name"], "via": item["via"]}
        for item in items
        if item["reason"] == "shared_entity" and item["via"]
    ]
    text = format_evidence(
        items, paths, graph_available=graph_available, hops=hops, no_path_pairs=no_path_pairs
    )
    return {
        "items": items,
        "paths": paths,
        "bridges": bridges,
        "graph_available": graph_available,
        "seed_count": sum(1 for i in items if i["hops"] == 0),
        "multi_count": sum(1 for i in items if i["hops"] > 0),
        "text": text,
    }


def format_evidence(
    items: list[dict],
    paths: list[dict],
    *,
    graph_available: bool,
    hops: int,
    no_path_pairs: list[tuple[str, str]] | None = None,
) -> str:
    """把检索结果拼成给 LLM 的证据文本(纯函数,可单测)"""
    if not items:
        return "没有检索到相关兴趣。"
    seeds = sum(1 for i in items if i["hops"] == 0)
    multi = sum(1 for i in items if i["hops"] > 0)
    lines = [f"[兴趣检索] 命中 {len(items)} 条(关注实体 {seeds} / 关联实体 {multi},hops<={hops})"]
    for item in items:
        line = f"- {item['name']}({item.get('category', '其他')})"
        span = fmt_range(item.get("since"), item.get("until"))
        if span:
            line += f" {span}"
        if item.get("mention_count"):
            line += f",提及 {item['mention_count']} 次"
        if item.get("status") == "cooled":
            line += "(已冷却)"
        if item["hops"] > 0:
            line += f"({item['hops']} 跳关联)"
        lines.append(line)
        own = item.get("entities") or []
        if own:
            lines.append(f"  关联实体: {'、'.join(own[:6])}")
        if item.get("via"):
            lines.append(f"  桥接实体: {'、'.join(item['via'][:5])}")
        if item.get("path"):
            lines.append(f"  多跳路径({item['hops']}跳): {' -> '.join(item['path'])}")
    if paths:
        lines.append("路径汇总: " + " | ".join(" -> ".join(p["nodes"]) for p in paths[:5]))
    if no_path_pairs:
        pairs_text = " | ".join(f"{a} ↔ {b}" for a, b in no_path_pairs[:5])
        lines.append(f"未找到关联路径: {pairs_text}(可如实回答「没有找到关联」)。")
    if not graph_available:
        lines.append("提示:图数据库暂不可用,以上仅基于向量/关键词召回。")
    lines.append('时间提示:回答"以前是否关注过"时给出时间区间,不要编造未返回的兴趣。')
    return "\n".join(lines)


async def recall_text(
    session,
    user_id,
    query: str = "",
    *,
    hops: int = 2,
    include_cooled: bool = True,
    limit: int = DEFAULT_LIMIT,
) -> str:
    result = await recall(
        session, user_id, query, hops=hops, include_cooled=include_cooled, limit=limit
    )
    return result["text"]
