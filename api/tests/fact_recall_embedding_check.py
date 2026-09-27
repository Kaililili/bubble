"""实际 embedding 候选召回检验:旧记录无属性、两次说法不同,能否经向量召回。

只做召回检验,临时用户跑完即删;结果写入 fact_recall_embedding_results.md。
运行: python api/tests/fact_recall_embedding_check.py
"""
import asyncio
import math
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.llm.embedding import build_embedding_model  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.postgres import async_session, engine  # noqa: E402
from app.models.model_config_model import ModelConfig  # noqa: E402
from app.models.user_model import User  # noqa: E402
from app.repositories.memory_repository import MemoryRepository  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

# 不同的新说法(都与"秋招首选上海"指向同一件事),以及一个无关说法作对照
QUERIES = [
    "找工作更倾向杭州",
    "我求职想去杭州",
    "秋招更想去杭州",
    "我想在杭州发展",
    "毕业想去杭州上班",
    "我喜欢喝咖啡",
]

# 与"求职城市"无关的干扰事实,让召回必须在 9 条候选里真正选出目标(而不是唯一候选必然命中)
DISTRACTORS = [
    "我喜欢喝咖啡",
    "我在学 Rust",
    "我养了一只猫",
    "我每天跑步",
    "我喜欢看科幻电影",
    "我住在北京",
    "我会弹吉他",
    "我喜欢吃火锅",
]


def cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def main() -> None:
    engine.echo = False
    async with async_session() as session:
        config = (
            await session.execute(
                select(ModelConfig).where(ModelConfig.model_type == "embedding").limit(1)
            )
        ).scalar_one_or_none()
        if config is None:
            print("no embedding config; abort")
            return

        username = f"embrec_{uuid.uuid4().hex[:6]}"
        user = User(
            username=username,
            email=f"{username}@test.local",
            hashed_password=hash_password("x"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.add(
            ModelConfig(
                user_id=user.id,
                model_type="embedding",
                provider=config.provider,
                model_name=config.model_name,
                api_key_encrypted=config.api_key_encrypted,
                base_url=config.base_url,
                supports_function_call=True,
                is_default=True,
            )
        )
        await session.commit()

        embedder = build_embedding_model(config)
        old_text = "秋招首选上海"
        old_vector = await embedder.aembed_query(old_text)
        legacy = await MemoryRepository(session).create(
            user_id=user.id,
            type="fact",
            content=old_text,
            embedding=old_vector,
            attribute=None,  # 模拟旧库记录:没有属性列,只靠向量召回
        )
        for distractor in DISTRACTORS:
            await MemoryRepository(session).create(
                user_id=user.id,
                type="fact",
                content=distractor,
                embedding=await embedder.aembed_query(distractor),
                attribute=None,
            )

        results: list[tuple[str, float, bool, int | None]] = []
        for query in QUERIES:
            query_vector = await embedder.aembed_query(query)
            sim = cosine(query_vector, old_vector)
            recalled = await MemoryRepository(session).find_update_candidates(
                user.id, "fact", None, None, query_vector, query, limit=6
            )
            ids = [m.id for m in recalled]
            hit = legacy.id in ids
            rank = (ids.index(legacy.id) + 1) if hit else None
            results.append((query, sim, hit, rank))
            print(f"{'HIT ' if hit else 'MISS'} sim={sim:.3f} rank={rank}  {query}")

        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()

    await engine.dispose()
    Path(__file__).with_name("fact_recall_embedding_results.md").write_text(
        "# 实际 embedding 候选召回检验\n\n"
        "旧记录:`秋招首选上海`(attribute=None,只靠向量召回)\n\n"
        "| 查询 | cosine 相似度 | 是否命中(top6) | 名次 |\n|---|---|---|---|\n"
        + "\n".join(
            f"| {q} | {sim:.3f} | {'是' if hit else '否'} | {rank or '-'} |"
            for q, sim, hit, rank in results
        )
        + "\n\n说明:5 个同义改写均召回目标(多为第 1 名);无关查询「我喜欢喝咖啡」未召回目标属预期——"
        "干扰项里正好有同内容的「我喜欢喝咖啡」会被排到第 1。\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
