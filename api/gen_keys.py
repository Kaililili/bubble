"""生成 .env 需要的两个密钥(JWT_SECRET / FERNET_KEY)。

用法(仓库根目录或 api/ 目录下都行):
    python api/gen_keys.py              # 只打印,自己复制到 .env
    python api/gen_keys.py --write      # 直接写入 .env(不存在则从 .env.example 复制)

**只用标准库**(secrets / base64),所以任何 Python 3.8+ 都能跑,不需要先装依赖;
没装 Python 也可以用 uv 跑:`uv run --no-project python api/gen_keys.py --write`

注意:FERNET_KEY 用于加密已存的 API Key / MCP token,**一旦使用就不要更换**,
否则旧密文无法解密(需要在界面上重新填写)。
"""
import argparse
import base64
import re
import secrets
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]


def generate() -> tuple[str, str]:
    """JWT_SECRET 用 urlsafe 随机串;FERNET_KEY 就是 32 字节随机数的 urlsafe base64

    和 `Fernet.generate_key()` 的产物完全等价(它就是 urlsafe_b64encode(32 随机字节)),
    这样不依赖 cryptography 也能生成合法的 Fernet 密钥。
    """
    jwt_secret = secrets.token_urlsafe(32)
    fernet_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    return jwt_secret, fernet_key

def upsert(text: str, key: str, value: str) -> str:
    """把 .env 里的 KEY=... 替换成新值;没有这一行就追加"""
    pattern = re.compile(rf"^{key}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(f"{key}={value}", text, count=1)
    if not text.endswith("\n"):
        text += "\n"
    return text + f"{key}={value}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 JWT_SECRET / FERNET_KEY")
    parser.add_argument("--write", action="store_true", help="写回 .env(默认只打印)")
    parser.add_argument("--env-file", default=str(ROOT / ".env"), help="目标 .env 路径")
    args = parser.parse_args()

    jwt_secret, fernet_key = generate()
    env_path = Path(args.env_file)

    if not args.write:
        print("生成结果(复制到 .env):")
        print(f"JWT_SECRET={jwt_secret}")
        print(f"FERNET_KEY={fernet_key}")
        print("\n或直接一条命令写入:python api/gen_keys.py --write")
        return

    if not env_path.exists():
        sample = ROOT / ".env.example"
        if sample.exists():
            shutil.copyfile(sample, env_path)
            print(f"已从 .env.example 创建 {env_path}")
        else:
            env_path.write_text("", encoding="utf-8")
    text = env_path.read_text(encoding="utf-8")
    had_fernet = bool(re.search(r"^FERNET_KEY=.+$", text, re.MULTILINE))
    text = upsert(upsert(text, "JWT_SECRET", jwt_secret), "FERNET_KEY", fernet_key)
    env_path.write_text(text, encoding="utf-8")
    print(f"已写入 {env_path}")
    if had_fernet:
        print("提示:该文件原本已有 FERNET_KEY,现在被覆盖 —— 如果里面存过加密数据(API Key / MCP token),")
        print("      需要用新密钥重新填写一次,否则读不出来。")


if __name__ == "__main__":
    main()
