import { create } from "zustand";
import { ToolInfo, listTools, setToolEnabled } from "../api/tools";

interface ToolState {
  tools: ToolInfo[];
  loading: boolean;
  fetchTools: () => Promise<void>;
  toggle: (key: string, enabled: boolean) => Promise<void>;
}

export const useToolStore = create<ToolState>((set, get) => ({
  tools: [],
  loading: false,

  fetchTools: async () => {
    set({ loading: true });
    try {
      const tools = await listTools();
      set({ tools, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  toggle: async (key, enabled) => {
    await setToolEnabled(key, enabled);
    const tools = get().tools.map((t) => (t.key === key ? { ...t, enabled } : t));
    set({ tools });
  },
}));
