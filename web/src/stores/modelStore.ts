import { create } from "zustand";
import {
  ModelConfig,
  ModelPayload,
  createModel,
  deleteModel,
  listModels,
  updateModel,
} from "../api/models";

interface ModelState {
  models: ModelConfig[];
  loading: boolean;
  fetchModels: () => Promise<void>;
  addModel: (payload: ModelPayload) => Promise<void>;
  editModel: (id: string, payload: ModelPayload) => Promise<void>;
  removeModel: (id: string) => Promise<void>;
}

export const useModelStore = create<ModelState>((set, get) => ({
  models: [],
  loading: false,

  fetchModels: async () => {
    set({ loading: true });
    try {
      const models = await listModels();
      set({ models, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  addModel: async (payload) => {
    await createModel(payload);
    await get().fetchModels();
  },

  editModel: async (id, payload) => {
    await updateModel(id, payload);
    await get().fetchModels();
  },

  removeModel: async (id) => {
    await deleteModel(id);
    await get().fetchModels();
  },
}));
