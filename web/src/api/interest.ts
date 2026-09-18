import client from "./client";

export interface InterestItem {
  id: string;
  key: string;
  name: string;
  category: string;
  status: "active" | "cooled" | string;
  since: string | null;
  until: string | null;
  last_seen: string | null;
  mention_count: number;
}

export interface InterestGraphNode {
  id: string;
  label: string;
  /** 实体类型:league/team/sport/person/product/work/... */
  type: string;
  /** followed = 用户关注的实体(兴趣);related = 关联实体 */
  kind: "followed" | "related" | string;
  category: string | null;
  status: string | null;
  mention_count: number | null;
  description?: string | null;
}

export interface InterestGraphEdge {
  source: string;
  target: string;
  type: string;
  weight: number;
}

export interface InterestGraphData {
  available: boolean;
  reason: string | null;
  nodes: InterestGraphNode[];
  edges: InterestGraphEdge[];
}

export interface InterestSummary {
  total_count: number;
  active_count: number;
  cooled_count: number;
  new_last_30d: number;
  category_dist: Record<string, number>;
  longest_interest: {
    id: string;
    name: string;
    category: string;
    first_seen: string | null;
  } | null;
}

export interface RecallItem {
  key: string;
  name: string;
  category: string;
  status: string;
  hops: number;
  score: number;
  mention_count: number;
  since: string | null;
  until: string | null;
  via: string[];
  path: string[];
  reason: string;
}

export interface RecallResult {
  items: RecallItem[];
  paths: { from: string; to: string; hops: number; nodes: string[] }[];
  bridges: { to: string; via: string[] }[];
  graph_available: boolean;
  seed_count: number;
  multi_count: number;
  text: string;
}

export const listInterests = (params?: { category?: string; status?: string }) =>
  client.get("/interests/timeline", { params }).then((r) => r.data as InterestItem[]);

export const getInterestGraph = (limit = 100) =>
  client.get("/interests/graph", { params: { limit } }).then((r) => r.data as InterestGraphData);

export const getInterestSummary = () =>
  client.get("/interests/summary").then((r) => r.data as InterestSummary);

export interface RecentInterest {
  id: string;
  name: string;
  category: string;
  entity_type: string | null;
  status: string;
  mention_count: number;
  is_new: boolean;
  updated_at: string | null;
}

export const listRecentInterests = (since: string, limit = 10) =>
  client
    .get("/interests/recent", { params: { since, limit } })
    .then((r) => r.data as RecentInterest[]);

export interface InterestCommunity {
  key: string;
  name: string;
  summary: string;
  members: string[];
  updated_at: string | null;
}

export const listCommunities = () =>
  client.get("/interests/communities").then((r) => r.data as InterestCommunity[]);

export interface EntityLink {
  entity_key: string;
  entity_name: string;
  relation: string;
  direction: string;
  followed: boolean;
  display: string;
}

export interface EntityEvidence {
  text: string;
  at: string | null;
  from_entity: string;
}

export interface EntityDetail {
  key: string;
  name: string;
  type: string | null;
  category: string | null;
  followed: boolean;
  status: string | null;
  since: string | null;
  until: string | null;
  mention_count: number | null;
  links: EntityLink[];
  evidence: EntityEvidence[];
}

export const getEntityDetail = (key: string) =>
  client.get("/interests/entity", { params: { key } }).then((r) => r.data as EntityDetail);

export const recallInterest = (payload: { query: string; hops?: number; include_cooled?: boolean }) =>
  client.post("/interests/recall", payload).then((r) => r.data as RecallResult);

export const deleteInterest = (id: string) => client.delete(`/interests/${id}`);
