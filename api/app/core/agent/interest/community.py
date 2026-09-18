"""兴趣社区:标签传播聚类(LPA) + LLM 社区摘要 + 全局检索(Global Search)。

图里只有实体与实体间关系;社区 = 实体图上连接紧密的一组实体(如"篮球线""咖啡线""技术线")。
社区摘要按"用户视角"写,作为 Global Search 的检索单元,回答"我整体关注哪些方向/兴趣主线"。
"""
import hashlib
import json
import logging
from collections import defaultdict

from langchain_core.messages import HumanMessage, SystemMessage

from .embedding import build_embedder
from .graph_repo import InterestGraphRepo
from ....prompts.interest import COMMUNITY_SUMMARY_PROMPT as _SUMMARY_PROMPT

logger = logging.getLogger(__name__)

# 关系越"实",聚类时的连接权重越高
REL_WEIGHT = {"broader": 1.5, "member_of": 1.5, "part_of": 1.5, "related": 1.0, "co_occur": 0.5}
MAX_ITERS = 20
MIN_ENTITIES = 3


def label_propagation(
    nodes: list[str], edges: list[tuple[str, str, float]], max_iters: int = MAX_ITERS
) -> dict[str, str]:
    """标签传播聚类(纯函数,可单测):同步更新 + 平票保持原标签,避免标签互换/震荡"""
    labels = {n: n for n in nodes}
    adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for a, b, weight in edges:
        if a in labels and b in labels and a != b:
            adj[a].append((b, weight))
            adj[b].append((a, weight))
    order = sorted(nodes)
    for _ in range(max_iters):
        changed = 0
        updates: dict[str, str] = {}
        for node in order:
            votes: dict[str, float] = defaultdict(float)
            for neighbor, weight in adj[node]:
                votes[labels[neighbor]] += weight
            if not votes:
                continue
            current = labels[node]
            # 平票时保留当前标签,避免两个节点互相交换标签导致永不收敛
            best = max(votes.items(), key=lambda kv: (kv[1], kv[0] == current, kv[0]))[0]
            if current != best:
                updates[node] = best
        if updates:
            labels.update(updates)
            changed = len(updates)
        if changed == 0:
            break
    return labels


def group_members(labels: dict[str, str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for node, label in labels.items():
        groups[label].append(node)
    return {label: sorted(nodes) for label, nodes in groups.items()}


def merge_connected_communities(
    groups: dict[str, list[str]], edges: list[tuple[str, str, float]]
) -> dict[str, list[str]]:
    """把仍有直接边相连的社区合并(修掉 LPA 标签互换造成的假拆分),直到收敛"""
    parent = {label: label for label in groups}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    owner: dict[str, str] = {}
    for label, members in groups.items():
        for member in members:
            owner[member] = label
    for a, b, _weight in edges:
        if a in owner and b in owner:
            union(owner[a], owner[b])
    merged: dict[str, list[str]] = defaultdict(list)
    for label, members in groups.items():
        merged[find(label)].extend(members)
    return {label: sorted(set(members)) for label, members in merged.items()}




def _fingerprint(members: list[str], triples: list[str]) -> str:
    raw = "|".join(members) + "##" + "|".join(sorted(triples))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


async def build_communities(session, user_id) -> list[dict]:
    """跑一次 LPA,返回社区列表(不分层,当前图规模足够)"""
    graph = InterestGraphRepo()
    entities = await graph.list_entities(user_id=user_id, limit=500)
    keys = [e["key"] for e in entities if e.get("key")]
    if len(keys) < MIN_ENTITIES:
        return []
    data = await graph.fetch_graph(user_id=user_id, limit=500)
    edges = [
        (e["source"], e["target"], REL_WEIGHT.get(e.get("type") or "related", 1.0))
        for e in data["edges"]
        if e.get("source") and e.get("target")
    ]
    labels = label_propagation(keys, edges)
    groups = merge_connected_communities(group_members(labels), edges)
    name_by_key = {e["key"]: e.get("name") or e["key"] for e in entities}
    # 关注实体的时间信息(让社区摘要能讲"从什么时候开始关注")
    from ....repositories.interest_repository import InterestRepository

    followed_nodes = {
        n.key: n for n in await InterestRepository(session).list_by_keys(user_id, keys)
    }
    communities: list[dict] = []
    for label, members in groups.items():
        member_set = set(members)
        triples = [
            f"{e['source']} -{e.get('type')}-> {e['target']}"
            for e in data["edges"]
            if e["source"] in member_set and e["target"] in member_set
        ]
        communities.append(
            {
                "key": label,
                "members": sorted(member_set),
                "member_names": [name_by_key.get(m, m) for m in sorted(member_set)],
                "triples": triples,
                "member_details": [
                    {
                        "name": name_by_key.get(m, m),
                        "type": next((e.get("type") for e in entities if e["key"] == m), None),
                        "since": (
                            str(followed_nodes[m].since)
                            if m in followed_nodes and followed_nodes[m].since
                            else None
                        ),
                        "until": (
                            str(followed_nodes[m].until)
                            if m in followed_nodes and followed_nodes[m].until
                            else None
                        ),
                        "status": followed_nodes[m].status if m in followed_nodes else None,
                    }
                    for m in sorted(member_set)
                ],
                "fingerprint": _fingerprint(sorted(member_set), triples),
            }
        )
    communities.sort(key=lambda c: len(c["members"]), reverse=True)
    return communities


async def refresh_communities(session, user_id, force: bool = False) -> int:
    """重算社区;只有成员/关系变化的社区才重新生成摘要(省 LLM 调用)"""
    from ....models.interest_community_model import InterestCommunity
    from sqlalchemy import delete, select

    communities = await build_communities(session, user_id)
    if not communities:
        return 0
    existing = {
        row.key: row
        for row in (
            await session.execute(
                select(InterestCommunity).where(InterestCommunity.user_id == user_id)
            )
        ).scalars().all()
    }
    embedder = await build_embedder(session, user_id)
    judge = None
    regenerated = 0
    for community in communities:
        key = community["key"]
        row = existing.get(key)
        if row and row.fingerprint == community["fingerprint"] and not force:
            continue
        if judge is None:
            try:
                from ....core.llm.client import build_chat_model
                from ....core.llm.resolver import get_default_config

                config = await get_default_config(session, user_id, "chat")
                judge = build_chat_model(config, streaming=False, temperature=0)
            except Exception as e:  # noqa: BLE001
                logger.warning("community summary model unavailable: %s", e)
                judge = False  # type: ignore[assignment]
        name, summary = "", ""
        if judge:
            payload = {
                "成员": community["member_names"],
                "成员信息": community["member_details"],
                "关系": community["triples"][:20],
            }
            try:
                resp = await judge.ainvoke(
                    [
                        SystemMessage(content=_SUMMARY_PROMPT),
                        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
                    ]
                )
                content = resp.content
                if isinstance(content, list):
                    content = "".join(
                        str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content
                    )
                text = str(content).strip()
                start, end = text.find("{"), text.rfind("}")
                if start >= 0 and end > start:
                    parsed = json.loads(text[start : end + 1])
                    name = str(parsed.get("name") or "").strip()[:64]
                    summary = str(parsed.get("summary") or "").strip()
            except Exception as e:  # noqa: BLE001
                logger.warning("community summary failed: %s", e)
        if not name:
            name = "/".join(community["member_names"][:2]) + "线"
        embedding = None
        if embedder is not None and (name or summary):
            try:
                embedding = await embedder.aembed_query(f"{name}。{summary}".strip("。"))
            except Exception as e:  # noqa: BLE001
                logger.warning("community embedding failed: %s", e)
        if row is None:
            row = InterestCommunity(user_id=user_id, key=key)
            session.add(row)
        row.name = name
        row.summary = summary
        row.members = community["members"]
        row.fingerprint = community["fingerprint"]
        row.embedding = embedding
        regenerated += 1
    await session.commit()

    # 清掉已不存在的社区(重组/合并后)
    current_keys = {c["key"] for c in communities}
    stale = [key for key in existing if key not in current_keys]
    if stale:
        await session.execute(
            delete(InterestCommunity).where(
                InterestCommunity.user_id == user_id, InterestCommunity.key.in_(stale)
            )
        )
        await session.commit()
    return regenerated


async def list_communities(session, user_id) -> list:
    from sqlalchemy import select

    from ....models.interest_community_model import InterestCommunity

    return list(
        (
            await session.execute(
                select(InterestCommunity)
                .where(InterestCommunity.user_id == user_id)
                .order_by(InterestCommunity.updated_at.desc())
            )
        ).scalars().all()
    )


async def global_recall(session, user_id, query: str = "", limit: int = 6) -> dict:
    """Global Search:按问题检索社区摘要,返回概览证据"""
    rows = await list_communities(session, user_id)
    if not rows:
        return {
            "items": [],
            "text": "还没有形成兴趣社区(需要先积累一些兴趣实体)。",
        }
    embedder = await build_embedder(session, user_id)
    clustered = [r for r in rows if len(r.members or []) >= 2]
    singles = [r for r in rows if len(r.members or []) == 1]
    ranked = list(clustered)
    best_sim = 0.0
    if query and embedder is not None:
        try:
            vec = await embedder.aembed_query(query)
            import math

            def cosine(a, b):
                dot = sum(x * y for x, y in zip(a, b))
                na = math.sqrt(sum(x * x for x in a))
                nb = math.sqrt(sum(x * x for x in b))
                return dot / (na * nb) if na and nb else 0.0

            ranked = sorted(
                clustered,
                key=lambda r: cosine(vec, list(r.embedding)) if r.embedding is not None else 0.0,
                reverse=True,
            )
            best_sim = max(
                (cosine(vec, list(r.embedding)) for r in clustered if r.embedding is not None),
                default=0.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("community query embedding failed: %s", e)
    # 概览型问题(没有明确指向某个社区)按"规模"给主线,而不是按相似度随机取前几名
    if best_sim < 0.5:
        ranked = sorted(clustered, key=lambda r: len(r.members or []), reverse=True)
    ranked = ranked[:limit]
    items = [
        {
            "key": r.key,
            "name": r.name,
            "summary": r.summary,
            "members": list(r.members or []),
        }
        for r in ranked
    ]
    lines = [f"[兴趣全局检索] 共 {len(rows)} 个兴趣社区,命中 {len(items)} 个:"]
    for item in items:
        lines.append(f"- 社区「{item['name']}」({len(item['members'])} 个实体)")
        if item["summary"]:
            lines.append(f"  摘要: {item['summary']}")
        lines.append(f"  成员: {'、'.join(str(m) for m in item['members'][:10])}")
    if singles:
        names = "、".join(r.name for r in singles[:12])
        lines.append(f"- 零散兴趣(尚未成线,共 {len(singles)} 个): {names}")
    lines.append("提示:全局问题用社区摘要回答;具体时间区间仍以本地检索结果为准。")
    return {
        "items": items,
        "singles": [{"key": r.key, "name": r.name, "members": list(r.members or [])} for r in singles],
        "text": "\n".join(lines),
    }
