import client from "./client";

export type MemoryType = "credential" | "fact" | "event" | "todo";

export interface UserProfile {
  id: string;
  key: string;
  value: string;
  importance: number;
  created_at: string;
  updated_at: string;
}

export interface MemoryItem {
  id: string;
  type: MemoryType;
  content: string;
  importance: number;
  created_at: string;
  updated_at: string;
  credential_key?: string;
  credential_value?: string;
}

export const listProfiles = () => client.get("/profile").then((r) => r.data as UserProfile[]);

export const upsertProfile = (payload: { key: string; value: string; importance?: number }) =>
  client.put("/profile", payload).then((r) => r.data as UserProfile);

export const deleteProfile = (id: string) => client.delete(`/profile/${id}`);

export const upsertCredential = (payload: { key: string; value: string }) =>
  client.put("/memories/credential", payload).then((r) => r.data as { message: string });

export const listMemories = (params?: { type?: string; keyword?: string }) =>
  client.get("/memories", { params }).then((r) => r.data as MemoryItem[]);

export const deleteMemory = (id: string) => client.delete(`/memories/${id}`);

export const revealMemory = (id: string) =>
  client.post(`/memories/${id}/reveal`).then((r) => r.data as { content: string });
