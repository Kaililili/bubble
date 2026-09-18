import client from "./client";

export type ModelType = "chat" | "embedding" | "rerank";

export interface ModelConfig {
  id: string;
  model_type: ModelType;
  provider: string;
  model_name: string;
  base_url: string;
  is_default: boolean;
  created_at: string;
}

export interface ModelPayload {
  model_type: ModelType;
  provider: string;
  model_name: string;
  api_key?: string;
  base_url?: string;
  is_default?: boolean;
  supports_function_call?: boolean;
}

export interface TestResult {
  success: boolean;
  message: string;
}

export const listModels = () => client.get("/models").then((r) => r.data as ModelConfig[]);

export const createModel = (payload: ModelPayload) =>
  client.post("/models", payload).then((r) => r.data as ModelConfig);

export const updateModel = (id: string, payload: ModelPayload) =>
  client.put(`/models/${id}`, payload).then((r) => r.data as ModelConfig);

export const deleteModel = (id: string) => client.delete(`/models/${id}`);

export const testModel = (payload: ModelPayload) =>
  client.post("/models/test", payload).then((r) => r.data as TestResult);
