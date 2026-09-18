export type ChatEvent =
  | { type: "token"; text: string }
  | { type: "error"; message: string }
  | { type: "final"; text: string }
  | { type: "tool_start"; tool: string; query: string }
  | {
      type: "tool_result";
      tool: string;
      query: string;
      status: "success" | "error";
      text: string;
      full_text?: string;
      latency_ms: number;
    }
  | {
      type: "tool_approval_required";
      approval_id: string;
      tool: string;
      args?: Record<string, unknown>;
    };

/**
 * 通过 fetch 读取 SSE 流式聊天事件。
 * 后端事件格式: data: {json}\n\n, 以 data: [DONE] 结束。
 */
export async function streamChat(
  conversationId: string,
  content: string,
  onEvent: (event: ChatEvent) => void
): Promise<void> {
  const token = localStorage.getItem("token");
  const resp = await fetch(`/api/conversations/${conversationId}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content }),
  });

  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => "");
    throw new Error(text || `请求失败(HTTP ${resp.status})`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const payload = trimmed.slice(5).trim();
      if (payload === "[DONE]") continue;
      try {
        onEvent(JSON.parse(payload) as ChatEvent);
      } catch {
        // 忽略无法解析的帧
      }
    }
  }
}
