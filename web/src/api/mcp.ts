import client from "./client";

export interface MCPToolMeta {
  name: string;
  description: string;
  annotations?: {
    readOnlyHint?: boolean | null;
    destructiveHint?: boolean | null;
    idempotentHint?: boolean | null;
    openWorldHint?: boolean | null;
    title?: string | null;
  } | null;
}

export interface MCPServer {
  id: string;
  name: string;
  transport: string;
  url: string;
  token_masked: string;
  enabled: boolean;
  allowed_tools: string[] | null;
  sensitive_tools?: string[] | null;
  status: string;
  last_error: string | null;
  tools_cache: MCPToolMeta[] | null;
  synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompareItem {
  dept_id?: number | null;
  shop: string;
  distance_km?: number | null;
  price?: number | null;
  product?: string | null;
  product_id?: number | null;
  address?: string | null;
  status?: string | null;
  hours?: string | null;
}

export interface OrderPreview {
  dept_id?: number;
  product_id?: number;
  shop: string;
  address?: string;
  product?: string;
  spec?: string;
  amount?: number;
  original_price?: number | null;
  discount_price?: number | null;
  privilege_money?: number | null;
  about_time?: string;
  sku_code?: string;
}

export interface OrderAttrOption {
  sub_attribute_id?: number;
  name?: string;
  price_delta?: number | null;
  selected?: boolean;
  can_select?: boolean;
}

export interface OrderAttr {
  attribute_id?: number;
  name?: string;
  options: OrderAttrOption[];
}

export interface OrderOptions {
  dept_id?: number;
  product_id?: number;
  product?: string;
  sku_code?: string;
  initial_price?: number | null;
  estimate_price?: number | null;
  attributes?: OrderAttr[];
}

export interface ToolApproval {
  id: string;
  tool: string;
  args?: Record<string, unknown> | null;
  status: string;
  result?: string | null;
  error?: string | null;
  created_at?: string;
}

export interface OrderCreated {
  order_id: string;
  pay_qr_url?: string | null;
  pay_url?: string | null;
  discount_price?: number | null;
  need_pay?: boolean | null;
}

export const listServers = () => client.get("/mcp/servers").then((r) => r.data as MCPServer[]);

export const createServer = (payload: {
  name: string;
  url: string;
  transport?: string;
  token?: string;
}) => client.post("/mcp/servers", payload).then((r) => r.data as MCPServer);

export const updateServer = (
  id: string,
  payload: {
    name?: string;
    url?: string;
    token?: string;
    enabled?: boolean;
    allowed_tools?: string[] | null;
    sensitive_tools?: string[] | null;
  }
) => client.put(`/mcp/servers/${id}`, payload).then((r) => r.data as MCPServer);

export const deleteServer = (id: string) => client.delete(`/mcp/servers/${id}`);

export const testServer = (id: string) =>
  client.post(`/mcp/servers/${id}/test`).then((r) => r.data as { count: number; tools: MCPToolMeta[] });

export const compareLuckin = (keyword: string, longitude?: number, latitude?: number) =>
  client
    .post("/mcp/luckin/compare", { keyword, longitude, latitude })
    .then((r) => r.data as { keyword: string; items: CompareItem[] });

export const previewLuckinOrder = (payload: {
  dept_id: number;
  product_id: number;
  amount?: number;
  specs?: { attribute_id: number; sub_attribute_id: number }[];
}) =>
  client.post("/mcp/luckin/order/preview", payload).then((r) => r.data as OrderPreview);

export const getLuckinOrderOptions = (dept_id: number, product_id: number) =>
  client.post("/mcp/luckin/order/options", { dept_id, product_id }).then((r) => r.data as OrderOptions);

export const createLuckinOrder = (payload: {
  dept_id: number;
  product_id: number;
  amount?: number;
  sku_code?: string;
  remark?: string;
}) => client.post("/mcp/luckin/order/create", payload).then((r) => r.data as OrderCreated);

export const cancelLuckinOrder = (order_id: string) =>
  client.post("/mcp/luckin/order/cancel", { order_id }).then((r) => r.data as { cancelled: boolean });

export const queryLuckinOrder = (order_id: string) =>
  client.get(`/mcp/luckin/order/${order_id}`).then((r) => r.data as Record<string, unknown>);

export const listApprovals = (status = "pending") =>
  client.get("/mcp/approvals", { params: { status } }).then((r) => r.data as ToolApproval[]);

export const approveTool = (id: string, remember = false) =>
  client
    .post(`/mcp/approvals/${id}/approve`, { remember })
    .then((r) => r.data as { id: string; status: string; result?: string | null; error?: string | null });

export const rejectTool = (id: string) =>
  client.post(`/mcp/approvals/${id}/reject`).then((r) => r.data as { id: string; status: string });
