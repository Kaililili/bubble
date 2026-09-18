import { create } from "zustand";
import { streamChat, ChatEvent } from "../api/chat";
import {
  Conversation,
  Message,
  ToolEvent,
  createConversation,
  deleteConversation,
  listConversations,
  listMessages,
} from "../api/conversations";

export type { ToolEvent };

interface ChatState {
  conversations: Conversation[];
  activeId: string | null;
  messages: Message[];
  streaming: boolean;
  fetchConversations: () => Promise<void>;
  newConversation: () => Promise<void>;
  removeConversation: (id: string) => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  send: (content: string) => Promise<void>;
}

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  activeId: null,
  messages: [],
  streaming: false,

  fetchConversations: async () => {
    const conversations = await listConversations();
    set({ conversations });
  },

  newConversation: async () => {
    const conv = await createConversation();
    set({ activeId: conv.id, messages: [] });
    await get().fetchConversations();
  },

  removeConversation: async (id) => {
    await deleteConversation(id);
    const { activeId, conversations } = get();
    if (activeId === id) {
      const next = conversations.find((c) => c.id !== id);
      if (next) {
        await get().selectConversation(next.id);
      } else {
        set({ activeId: null, messages: [] });
      }
    }
    await get().fetchConversations();
  },

  selectConversation: async (id) => {
    set({ activeId: id, messages: [] });
    const msgs = await listMessages(id);
    const normalized = msgs.map((m) => {
      const events = (m.tool_calls as { events?: ToolEvent[] } | null)?.events;
      return { ...m, toolEvents: events && events.length ? events : undefined };
    });
    set({ messages: normalized });
  },

  send: async (content) => {
    const { activeId, messages, streaming } = get();
    if (!activeId || streaming) return;

    const userMsg: Message = {
      id: `local-u-${Date.now()}`,
      role: "user",
      content,
      tool_calls: null,
      meta: null,
      created_at: new Date().toISOString(),
    };
    const assistantMsg: Message = {
      id: `local-a-${Date.now()}`,
      role: "assistant",
      content: "",
      tool_calls: null,
      meta: null,
      created_at: new Date().toISOString(),
      toolEvents: [],
    };
    set({ messages: [...messages, userMsg, assistantMsg], streaming: true });

    const patchLastAssistant = (fn: (content: string) => string) => {
      const msgs = get().messages;
      set({
        messages: msgs.map((m, i) =>
          i === msgs.length - 1 && m.role === "assistant" ? { ...m, content: fn(m.content) } : m
        ),
      });
    };

    const patchLastAssistantTools = (fn: (list: ToolEvent[]) => ToolEvent[]) => {
      const msgs = get().messages;
      set({
        messages: msgs.map((m, i) =>
          i === msgs.length - 1 && m.role === "assistant"
            ? { ...m, toolEvents: fn(m.toolEvents || []) }
            : m
        ),
      });
    };

    try {
      await streamChat(activeId, content, (event: ChatEvent) => {
        if (event.type === "token") {
          patchLastAssistant((c) => c + event.text);
        } else if (event.type === "error") {
          patchLastAssistant((c) => c || `⚠️ ${event.message}`);
        } else if (event.type === "tool_start") {
          patchLastAssistantTools((list) => [
            ...list,
            { tool: event.tool, query: event.query, status: "running" },
          ]);
        } else if (event.type === "tool_result") {
          patchLastAssistantTools((list) => {
            let target = -1;
            for (let i = list.length - 1; i >= 0; i--) {
              if (list[i].tool === event.tool && list[i].status === "running") {
                target = i;
                break;
              }
            }
            const done: ToolEvent = {
              tool: event.tool,
              query: event.query,
              status: event.status,
              text: event.text,
              full_text: event.full_text || event.text,
              latency_ms: event.latency_ms,
            };
            const next = [...list];
            if (target >= 0) next[target] = done;
            else next.push(done);
            return next;
          });
        } else if (event.type === "tool_approval_required") {
          patchLastAssistantTools((list) => [
            ...list,
            {
              type: "approval",
              tool: event.tool,
              status: "pending",
              approval_id: event.approval_id,
              args: event.args,
            },
          ]);
        }
      });
    } catch (e) {
      patchLastAssistant((c) => c || `⚠️ 请求失败:${(e as Error).message}`);
    } finally {
      set({ streaming: false });
      await get().fetchConversations();
    }
  },
}));
