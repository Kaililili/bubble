import client from "./client";

export interface EmotionHistoryPoint {
  bucket: string;
  avg_valence: number;
  avg_arousal: number;
  count: number;
  dominant_emotion: string;
}

export interface EmotionDistributionItem {
  emotion_type: string;
  count: number;
  polarity: number;
}

export interface EmotionWord {
  word: string;
  count: number;
  valence: number;
}

export interface EmotionEvent {
  id: string;
  emotion_type: string;
  intensity: number;
  valence: number;
  arousal: number;
  keywords: string[];
  trigger: string | null;
  summary: string | null;
  evidence: string;
  source: string;
  created_at: string;
}

export interface EmotionSummary {
  days: number;
  count: number;
  avg_valence: number;
  avg_arousal: number;
  dominant_emotion: string;
  trend: "up" | "flat" | "down" | string;
  negative_ratio: number;
  distribution: EmotionDistributionItem[];
  top_triggers: { trigger: string; count: number }[];
}

export interface EmotionProfile {
  dominant_emotion: string;
  avg_valence: number;
  avg_arousal: number;
  sample_count: number;
  trend: string;
  recent_triggers: string[];
  negative_ratio: number;
}

export const getEmotionHistory = (granularity: "day" | "week" | "month" = "day", days = 30) =>
  client
    .get("/emotions/history", { params: { granularity, days } })
    .then((r) => r.data as EmotionHistoryPoint[]);

export const getEmotionSummary = (days = 30) =>
  client.get("/emotions/summary", { params: { days } }).then((r) => r.data as EmotionSummary);

export const getEmotionProfile = (days = 7) =>
  client.get("/emotions/profile", { params: { days } }).then((r) => r.data as EmotionProfile);

export const getEmotionWordcloud = (days = 30) =>
  client.get("/emotions/wordcloud", { params: { days } }).then((r) => r.data as EmotionWord[]);

export const listEmotionEvents = (limit = 20) =>
  client.get("/emotions/events", { params: { limit } }).then((r) => r.data as EmotionEvent[]);

export const deleteEmotion = (id: string) => client.delete(`/emotions/${id}`);
