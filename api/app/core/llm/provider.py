"""Provider 元信息与连接测试"""
import httpx

# 各 provider 的默认 base_url(用户可覆盖)
PROVIDER_DEFAULT_BASE_URL: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "tavily": "https://api.tavily.com",
    "siliconflow": "https://api.siliconflow.cn/v1",
}


async def test_connection(
    model_type: str, base_url: str, api_key: str, model_name: str
) -> tuple[bool, str]:
    """发送最小请求验证 API Key / base_url / 模型是否可用。返回 (是否成功, 中文提示)"""
    if model_type == "websearch":
        return await _test_websearch(base_url, api_key)

    base = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if model_type == "embedding":
                resp = await client.post(
                    f"{base}/embeddings", headers=headers, json={"model": model_name, "input": "ping"}
                )
            elif model_type == "rerank":
                resp = await client.post(
                    f"{base}/rerank",
                    headers=headers,
                    json={"model": model_name, "query": "ping", "documents": ["doc"]},
                )
            else:
                resp = await client.post(
                    f"{base}/chat/completions",
                    headers=headers,
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
    except httpx.TimeoutException:
        return False, "连接超时,请检查 base_url 是否可达"
    except httpx.RequestError as e:
        return False, f"连接失败:{e}"

    if resp.status_code == 200:
        return True, "连接成功"
    if resp.status_code in (401, 403):
        return False, "API Key 无效或无权限"
    if resp.status_code == 404:
        return False, "模型不存在或 base_url 路径错误"
    detail = ""
    try:
        body = resp.json()
        detail = body.get("error", {}).get("message", "") or str(body)
    except Exception:
        detail = resp.text[:200]
    return False, f"测试失败(HTTP {resp.status_code}):{detail}"


async def _test_websearch(base_url: str, api_key: str) -> tuple[bool, str]:
    """Tavily 搜索连接测试:发一次最小搜索"""
    base = (base_url or "https://api.tavily.com").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base}/search",
                headers={"Authorization": f"Bearer {api_key}"}, json={"query": "ping", "max_results": 1},
            )
            resp.raise_for_status()
        return True, "连接成功"
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return False, "API Key 无效或无权限"
        return False, f"测试失败(HTTP {e.response.status_code})"
    except Exception as e:
        return False, f"连接失败:{e}"
