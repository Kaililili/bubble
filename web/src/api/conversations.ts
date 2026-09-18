import client from "./client";

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: string;
  content: string;
  tool_calls: Record<string, unknown> | null;
  meta: Record<string, unknown> | null;
  created_at: string;
  /** 前端本地字段:该条 assistant 消息关联的工具调用事件,不持久化 */
  toolEvents?: ToolEvent[];
}

export interface ToolEvent {
  /** tool=普通工具事件; approval=敏感工具待确认 */
  type?: "tool" | "approval";
  tool: string;
  query?: string;
  status: "running" | "success" | "error" | "pending" | "executed" | "rejected" | "failed";
  text?: string;
  full_text?: string;
  latency_ms?: number;
  approval_id?: string;
  args?: Record<string, unknown> | null;
}

export const listConversations = () =>
  client.get("/conversations").then((r) => r.data as Conversation[]);

export const createConversation = (title?: string) =>
  client.post("/conversations", { title }).then((r) => r.data as Conversation);

export const deleteConversation = (id: string) => client.delete(`/conversations/${id}`);

export const listMessages = (id: string) =>
  client.get(`/conversations/${id}/messages`).then((r) => r.data as Message[]);
