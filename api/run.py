import sys
from pathlib import Path

# 将 api/ 目录加入 Python path，确保从根目录运行时也能正确导入 app.*
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
