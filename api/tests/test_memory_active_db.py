"""阶段一(重写)DB 集成自测:显式 remember 普通事实的更新流程。

用脚本化模型(属性提取 + 关系判定)和脚本化 embedding 替代真实 LLM/向量,
只验证"最终数据库状态、superseded_by 关系、当前检索结果",不测模型标签本身。
真实模型/向量的开放措辞验收见 _staging/verify_fact_update.py。
"""
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.agent.tools.base import ToolContext  # noqa: E402
from app.core.agent.tools.builtin.memory_tools import remember  # noqa: E402
from app.core.security import encrypt_secret, hash_password  # noqa: E402
from app.db.postgres import async_session, engine  # noqa: E402
from app.models.model_config_model import ModelConfig  # noqa: E402
from app.models.user_model import User  # noqa: E402
from app.repositories.memory_repository import MemoryRepository  # noqa: E402
from sqlalchemy import delete  # noqa: E402

engine.echo = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


class ScriptedChat:
    """脚本化 chat 模型:按内容返回属性/关系,或按标记抛错模拟模型失败"""

    def __init__(self) -> None:
        self.attributes: dict = {}
        self.relations: dict = {}
        self.fail_for: set = set()

    def set_attr(self, content: str, attribute: str | None, scope: str | None = None) -> None:
        self.attributes[content] = {"attribute": attribute, "scope": scope}

    def set_relation(self, new_content: str, relations: list[dict]) -> None:
        self.relations[new_content] = relations

    async def ainvoke(self, messages):
        prompt = messages[-1].content
        if "事实属性提取器" in prompt:
            for content, attr in self.attributes.items():
                if f"事实内容:{content}" in prompt:
                    if content in self.fail_for:
                        raise RuntimeError("scripted attribute failure")
                    return SimpleNamespace(content=json.dumps(attr, ensure_ascii=False))
            return SimpleNamespace(content=json.dumps({"attribute": None, "scope": None}, ensure_ascii=False))
        if "记忆更新判定器" in prompt:
            for content, rels in self.relations.items():
                if f"新事实:{content}" in prompt:
                    if content in self.fail_for:
                        raise RuntimeError("scripted relation failure")
                    return SimpleNamespace(content=json.dumps({"relations": rels}, ensure_ascii=False))
            return SimpleNamespace(content=json.dumps({"relations": []}, ensure_ascii=False))
        return SimpleNamespace(content="{}")


class ScriptedEmbedder:
    """脚本化 embedding:内容 → 固定 1024 维向量,模拟"语义相近"的召回"""

    def __init__(self, mapping: dict[str, list]) -> None:
        self.mapping = mapping
        self.default = [0.0] * 1024

    async def aembed_query(self, text: str) -> list:
        return self.mapping.get(text, self.default)


async def _setup(session):
    username = f"codex_fact_{uuid.uuid4().hex[:6]}"
    user = User(username=username, email=f"{username}@test.local", hashed_password=hash_password("x"))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    for model_type, provider, model_name in (
        ("chat", "deepseek", "deepseek-chat"),
        ("embedding", "siliconflow", "BAAI/bge-m3"),
    ):
        session.add(
            ModelConfig(
                user_id=user.id,
                model_type=model_type,
                provider=provider,
                model_name=model_name,
                api_key_encrypted=encrypt_secret("dummy"),
                base_url="http://127.0.0.1:9/v1",
                supports_function_call=True,
                is_default=True,
            )
        )
    await session.commit()
    return user


async def _active(session, user_id):
    return {
        m.content: m
        for m in await MemoryRepository(session).list_by_user(user_id)
        if m.status == "active"
    }


async def _run() -> None:
    from app.core.llm import client as llm_client
    from app.core.llm import embedding as llm_embedding

    chat = ScriptedChat()
    embedder = ScriptedEmbedder({})
    llm_client.build_chat_model = lambda config, **kwargs: chat
    llm_embedding.build_embedding_model = lambda config: embedder

    async with async_session() as session:
        user = await _setup(session)
        uid = user.id
        ctx = ToolContext(session, uid)
        repo = MemoryRepository(session)
        try:
            # 1. 秋招首选上海 → 找工作更倾向杭州(同属性,不同措辞/城市) → 旧失效
            chat.set_attr("秋招首选上海", "求职意向城市")
            await remember(ctx, "秋招首选上海", type="fact")
            old = (await _active(session, uid))["秋招首选上海"]
            chat.set_attr("找工作更倾向杭州", "求职意向城市")
            chat.set_relation("找工作更倾向杭州", [{"candidate_id": str(old.id), "relation": "SUPERSEDE"}])
            await remember(ctx, "找工作更倾向杭州", type="fact")
            rows = {m.content: m for m in await repo.list_by_user(uid)}
            assert rows["秋招首选上海"].status == "superseded", rows["秋招首选上海"].status
            assert rows["秋招首选上海"].superseded_by == rows["找工作更倾向杭州"].id
            assert rows["找工作更倾向杭州"].status == "active"
            active = await _active(session, uid)
            assert "找工作更倾向杭州" in active and "秋招首选上海" not in active
            print("1. reworded same-attribute supersede ok")

            # 2. 喜欢篮球 → 也喜欢电影(同属性可并列) → 并存
            chat.set_attr("喜欢篮球", "兴趣爱好")
            await remember(ctx, "喜欢篮球", type="fact")
            chat.set_attr("也喜欢电影", "兴趣爱好")
            chat.set_relation("也喜欢电影", [])
            await remember(ctx, "也喜欢电影", type="fact")
            active = await _active(session, uid)
            assert {"喜欢篮球", "也喜欢电影"} <= set(active), active
            print("2. coexisting hobbies ok")

            # 3. 喜欢篮球 → 不再喜欢篮球(明确否定) → 旧偏好失效
            hoops = active["喜欢篮球"]
            chat.set_attr("不再喜欢篮球", "兴趣爱好")
            chat.set_relation("不再喜欢篮球", [{"candidate_id": str(hoops.id), "relation": "SUPERSEDE"}])
            await remember(ctx, "不再喜欢篮球", type="fact")
            rows = {m.content: m for m in await repo.list_by_user(uid)}
            assert rows["喜欢篮球"].status == "superseded"
            assert rows["不再喜欢篮球"].status == "active"
            print("3. explicit negation supersedes old preference ok")

            # 4. 秋招首选杭州 → 常住上海(不同属性) → 并存
            chat.set_attr("秋招首选杭州", "求职意向城市")
            await remember(ctx, "秋招首选杭州", type="fact")
            chat.set_attr("常住上海", "常住城市")
            chat.set_relation("常住上海", [])
            await remember(ctx, "常住上海", type="fact")
            active = await _active(session, uid)
            assert {"秋招首选杭州", "常住上海"} <= set(active), active
            print("4. different attributes coexist ok")

            # 5. 相同事实重复记住 → 只有一条有效记录
            before = len(await _active(session, uid))
            result = await remember(ctx, "常住上海", type="fact")
            assert "与既有记录一致" in result, result
            assert len(await _active(session, uid)) == before
            print("5. exact duplicate reuses single record ok")

            # 6. 旧记录没有新增属性(向量兜底召回) → 仍可更新
            vec = [1.0] + [0.0] * 1023
            legacy = await repo.create(
                user_id=uid, type="fact", content="秋招想去北京", embedding=vec, attribute=None
            )
            embedder.mapping["找工作更想去深圳"] = vec
            chat.set_relation("找工作更想去深圳", [{"candidate_id": str(legacy.id), "relation": "SUPERSEDE"}])
            await remember(ctx, "找工作更想去深圳", type="fact")
            rows = {m.content: m for m in await repo.list_by_user(uid)}
            assert rows["秋招想去北京"].status == "superseded", "旧无属性记录没被召回/更新"
            assert rows["秋招想去北京"].superseded_by == rows["找工作更想去深圳"].id
            print("6. legacy attribute-less record recall + update ok")

            # 7. 多个相关候选,仅一个被明确取代
            chat.set_attr("想读研", "学业规划")
            await remember(ctx, "想读研", type="fact")
            chat.set_attr("想考公", "学业规划")
            await remember(ctx, "想考公", type="fact")
            active = await _active(session, uid)
            chat.set_attr("想直接就业", "学业规划")
            chat.set_relation(
                "想直接就业",
                [
                    {"candidate_id": str(active["想读研"].id), "relation": "SUPERSEDE"},
                    {"candidate_id": str(active["想考公"].id), "relation": "COEXIST"},
                ],
            )
            await remember(ctx, "想直接就业", type="fact")
            rows = {m.content: m for m in await repo.list_by_user(uid)}
            assert rows["想读研"].status == "superseded"
            assert rows["想考公"].status == "active"
            assert rows["想直接就业"].status == "active"
            print("7. only targeted candidate superseded ok")

            # 8. 模型失败 / 非法 ID / 无法确定 → 旧记录保留,新内容正常保存
            chat.set_attr("喜欢游泳", "兴趣爱好")
            await remember(ctx, "喜欢游泳", type="fact")
            swim = (await _active(session, uid))["喜欢游泳"]
            # 8a 非法 ID
            chat.set_attr("喜欢跑步", "兴趣爱好")
            chat.set_relation("喜欢跑步", [{"candidate_id": "bad-id", "relation": "SUPERSEDE"}])
            await remember(ctx, "喜欢跑步", type="fact")
            rows = {m.content: m for m in await repo.list_by_user(uid)}
            assert rows["喜欢游泳"].status == "active", "非法 ID 不应使旧记录失效"
            # 8b 模型抛错(失败)
            chat.set_attr("喜欢骑行", "兴趣爱好")
            chat.fail_for.add("喜欢骑行")
            chat.set_relation("喜欢骑行", [{"candidate_id": str(swim.id), "relation": "SUPERSEDE"}])
            await remember(ctx, "喜欢骑行", type="fact")
            rows = {m.content: m for m in await repo.list_by_user(uid)}
            assert rows["喜欢游泳"].status == "active"
            assert rows["喜欢骑行"].status == "active"
            # 8c UNCERTAIN
            chat.fail_for.discard("喜欢骑行")
            chat.set_attr("喜欢爬山", "兴趣爱好")
            chat.set_relation("喜欢爬山", [{"candidate_id": str(swim.id), "relation": "UNCERTAIN"}])
            await remember(ctx, "喜欢爬山", type="fact")
            rows = {m.content: m for m in await repo.list_by_user(uid)}
            assert rows["喜欢游泳"].status == "active", "UNCERTAIN 不应使旧记录失效"
            assert rows["喜欢爬山"].status == "active"
            print("8. invalid/failed/uncertain keep old records ok")

            # 9. event/todo 不做新旧版本判断:两个不同待办并存
            await remember(ctx, "明天交周报", type="todo")
            await remember(ctx, "明天开会", type="todo")
            active = await _active(session, uid)
            assert {"明天交周报", "明天开会"} <= set(active), active
            print("9. event/todo not fact-superseded ok")
        finally:
            await session.execute(delete(User).where(User.id == uid))
            await session.commit()
            print("cleanup: temp user removed")


def test_memory_lifecycle_db() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    test_memory_lifecycle_db()
    print("ALL PASS")
