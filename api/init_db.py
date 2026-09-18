"""手动入口:初始化数据库(应用启动时也会自动执行同一逻辑)。

用法(在 api/ 目录下): uv run python init_db.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.bootstrap import ensure_schema  # noqa: E402
from app.db.postgres import engine  # noqa: E402


async def main() -> None:
    await ensure_schema()
    await engine.dispose()
    print("[OK] db init done: 建表 / 补列 / 向量索引")


if __name__ == "__main__":
    asyncio.run(main())
