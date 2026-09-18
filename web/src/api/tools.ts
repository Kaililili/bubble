import client from "./client";

export interface ToolInfo {
  key: string;
  name: string;
  description: string;
  enabled: boolean;
  needs_config: boolean;
  configured: boolean;
  default_enabled: boolean;
}

export const listTools = () => client.get("/tools").then((r) => r.data as ToolInfo[]);

export const setToolEnabled = (key: string, enabled: boolean) =>
  client.put(`/tools/${key}`, { enabled });
