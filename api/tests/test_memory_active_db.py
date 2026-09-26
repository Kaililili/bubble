"""Stage-1 DB integration check: fact update / idempotency / forget / review filter / stale profile.

Needs local Postgres (same .env as runtime). Creates one temp user, deletes it afterwards.
Run: python api/tests/test_memory_active_db.py
"""
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# 关掉 SQL echo(DEBUG=true 时默认打开),只留断言结果
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from app.core.agent.memory.retrieval import search_memories  # noqa: E402
from app.core.agent.memory.supersede import apply_supersede  # noqa: E402
from app.core.agent.plan.steps import step_collect_memories  # noqa: E402
from app.core.agent.tools.base import ToolContext  # noqa: E402
from app.core.agent.tools.builtin.memory_tools import (  # noqa: E402
    forget,
    recall,
    remember,
    save_profile,
)
from app.core.llm.client import build_chat_model  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.postgres import async_session, engine  # noqa: E402
from app.models.memory_model import UserProfile  # noqa: E402
from app.models.model_config_model import ModelConfig  # noqa: E402
from app.models.user_model import User  # noqa: E402
from app.repositories.conversation_repository import ConversationRepository  # noqa: E402
from app.repositories.memory_repository import MemoryRepository  # noqa: E402
from app.repositories.message_repository import MessageRepository  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402
from sqlalchemy import delete, select, text, update  # noqa: E402

# DEBUG=true 时引擎默认回显 SQL;测试只关心断言结果,这里关掉
engine.echo = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def _borrow_chat_model(session):
    """借一份**可用的** chat 配置当裁决模型(逐个探测,不打印任何密钥)"""
    from langchain_core.messages import HumanMessage

    configs = (
        await session.execute(
            select(ModelConfig).where(ModelConfig.model_type == "chat").limit(8)
        )
    ).scalars().all()
    for config in configs:
        try:
            model = build_chat_model(config, streaming=False, temperature=0)
            await asyncio.wait_for(model.ainvoke([HumanMessage(content="ping")]), timeout=30)
            print(f"borrowed chat model: {config.provider}/{config.model_name}")
            return model
        except Exception as exc:  # noqa: BLE001
            print(f"chat config unusable ({config.provider}): {type(exc).__name__}")
    return None


async def _run() -> None:
    username = f"codex_stage1_{uuid.uuid4().hex[:8]}"
    async with async_session() as session:
        null_status = (
            await session.execute(text("select count(*) from memories where status is null"))
        ).scalar_one()
        assert not null_status, f"existing memories with NULL status would be missed: {null_status}"

        user = User(
            username=username,
            email=f"{username}@test.local",
            hashed_password=hash_password("x"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        uid = user.id
        repo = MemoryRepository(session)
        ctx = ToolContext(session, uid)
        try:
            # background first: "常驻城市: 上海", updated_at pushed one hour back
            await save_profile(ctx, "常驻城市", "上海")
            await session.execute(
                update(UserProfile)
                .where(UserProfile.user_id == uid, UserProfile.key == "常驻城市")
                .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=1))
            )
            await session.commit()

            # A explicit correction
            first = await remember(ctx, "秋招优先上海")
            assert first.startswith("已记住"), first
            second = await remember(ctx, "现在改为优先杭州")
            assert "已把旧记录标记为失效" in second, second

            rows = {m.content: m for m in await repo.list_by_user(uid)}
            old = rows["秋招优先上海"]
            new = rows["现在改为优先杭州"]
            assert old.status == "superseded" and old.superseded_by == new.id, "old fact not linked"
            assert new.status == "active"
            print("A. explicit update -> superseded + superseded_by ok")

            # B retrieval drops superseded
            hits = [
                m.content
                for m in await search_memories(session, uid, "优先", limit=6, touch=False)
            ]
            assert "现在改为优先杭州" in hits and "秋招优先上海" not in hits, hits
            print("B. retrieval drops superseded ok")

            # C review collects only active facts, change expressed as relation
            collected = await step_collect_memories(session, uid, {"days": 7}, {})
            assert collected["status"] == "ok", collected
            items = collected["data"]["items"]
            contents = [i["content"] for i in items]
            assert "现在改为优先杭州" in contents and "秋招优先上海" not in contents, contents
            assert all(i.get("memory_id") for i in items), "review items missing memory id"
            changes = collected["data"]["changes"]
            assert changes and changes[0]["from"] == "秋招优先上海", changes
            assert changes[0]["to"] == "现在改为优先杭州", changes
            print("C. review collects active facts + change summary ok")

            # D stale background value no longer injected
            block = await ChatService(session)._load_profile_block(uid)
            assert "上海" not in block, block
            assert "常驻城市" in block and "已被更新的记录取代" in block, block
            print("D. stale profile value suppressed ok")

            # E two distinct hobbies both kept
            await remember(ctx, "我喜欢篮球")
            third = await remember(ctx, "我喜欢电影")
            assert "已把旧记录标记为失效" not in third, third
            active = {m.content for m in await repo.list_by_user(uid) if m.status == "active"}
            assert {"我喜欢篮球", "我喜欢电影"} <= active, active
            print("E. two distinct hobbies both kept (rule path) ok")

            judge = await _borrow_chat_model(session)
            if judge is None:
                print("E2. skipped (no chat config to borrow)")
            else:
                probe = SimpleNamespace(id=uuid.uuid4(), content="我喜欢游泳", type="fact")
                marked = await apply_supersede(session, uid, probe, None, model=judge)
                assert not marked, f"model wrongly superseded one hobby: {marked}"
                active = {m.content for m in await repo.list_by_user(uid) if m.status == "active"}
                assert {"我喜欢篮球", "我喜欢电影"} <= active, active
                print("E2. two distinct hobbies both kept (real model judge) ok")

            # F idempotent duplicate write
            again = await remember(ctx, "我喜欢电影")
            assert "未重复保存" in again, again
            same = [
                m
                for m in await repo.list_by_user(uid)
                if m.status == "active" and m.content == "我喜欢电影"
            ]
            assert len(same) == 1, f"duplicate write produced {len(same)} rows"
            print("F. duplicate write is idempotent ok")

            # G forget only touches the active record
            removed = await forget(ctx, "优先")
            assert removed.startswith("已删除记忆"), removed
            kept = await repo.count_matching(uid, "秋招优先上海", status="superseded")
            assert kept == 1, "superseded history was deleted"
            assert await repo.count_matching(uid, "优先杭州") == 0
            again_forget = await forget(ctx, "优先")
            assert "没有找到仍有效的记忆" in again_forget, again_forget
            print("G. forget only touches active memory ok")

            # H credential stays encrypted and out of the review
            cred = await remember(ctx, "招行银行卡 密码 abc123456", type="credential")
            assert cred.startswith(("已记住", "已更新")), cred
            creds = [m for m in await repo.list_by_user(uid) if m.type == "credential"]
            assert creds and creds[0].content_encrypted, "credential not encrypted"
            assert "abc123456" not in (creds[0].content or ""), "plaintext in display field"
            collected = await step_collect_memories(session, uid, {"days": 7}, {})
            assert all(i["type"] != "credential" for i in collected["data"]["items"])
            print("H. credential encrypted + excluded from review ok")

            # I 来源溯源:记忆回指当次用户消息,recall 输出带证据;凭证不回指原话
            conv = await ConversationRepository(session).create(uid, title="trace")
            msg = await MessageRepository(session).create(
                conv.id, role="user", content="帮我记住:我下周三面试字节"
            )
            trace_ctx = ToolContext(session, uid, conv.id, msg.id)
            saved = await remember(trace_ctx, "我下周三面试字节")
            assert saved.startswith("已记住"), saved
            traced = await repo.find_active_by_content(uid, "fact", "我下周三面试字节")
            assert traced is not None and traced.source == "chat", "来源类型没有落库"
            assert traced.source_message_id == msg.id, "记忆没有回指当次用户消息"
            evidence = await recall(trace_ctx, "面试")
            assert "记忆ID" in evidence and "用户原话" in evidence, evidence
            assert "下周三面试字节" in evidence and "来源 未知" not in evidence, evidence
            await remember(trace_ctx, "招行 密码 zzz999888", type="credential")
            cred_evidence = await recall(trace_ctx, "密码")
            assert "zzz999888" not in cred_evidence, "recall 泄露了凭证明文"
            assert "记忆ID" in cred_evidence
            # 老数据(无来源)如实标注,不伪造用户原话
            legacy = await repo.create(user_id=uid, type="fact", content="我是 2024 年毕业的")
            legacy_evidence = await recall(trace_ctx, "毕业")
            assert "来源 未知" in legacy_evidence, legacy_evidence
            assert str(legacy.id)[:8] in legacy_evidence
            print("I. memory source trace + recall evidence ok")

            # J ReAct 路径回归:supports_function_call=False 时,工具说明必须渲染进 system prompt
            # (prepare 里工具构建被移到消息落库之后,这里防止"变量未定义/顺序错"的回归)
            from app.core.security import encrypt_secret

            session.add(
                ModelConfig(
                    user_id=uid,
                    model_type="chat",
                    provider="openai",
                    model_name="gpt-4o-mini",
                    api_key_encrypted=encrypt_secret("dummy-key"),
                    base_url="http://127.0.0.1:9/v1",
                    supports_function_call=False,
                    is_default=True,
                )
            )
            await session.commit()
            react_conv = await ConversationRepository(session).create(uid, title="react path")
            svc = ChatService(session)
            _model, react_tools, supports, history, _conv_id = await svc.prepare(
                react_conv.id, uid, "帮我看看现在几点"
            )
            assert supports is False and react_tools, "ReAct 路径没有拿到工具"
            assert "你有以下工具可用" in history[0].content, "工具说明没有渲染进 system prompt"
            assert any(getattr(t, "name", "") == "recall" for t in react_tools)
            print("J. react path renders tools prompt ok")
        finally:
            await session.execute(delete(User).where(User.id == uid))
            await session.commit()
            print("cleanup: temp user removed")


def test_memory_lifecycle_db() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    test_memory_lifecycle_db()
    print("ALL PASS")
