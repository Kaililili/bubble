import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Col,
  Empty,
  Grid,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Tag,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, ReloadOutlined } from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import {
  EmotionEvent,
  EmotionHistoryPoint,
  EmotionProfile,
  EmotionSummary,
  EmotionWord,
  deleteEmotion,
  getEmotionHistory,
  getEmotionProfile,
  getEmotionSummary,
  getEmotionWordcloud,
  listEmotionEvents,
} from "../api/emotion";

const { Text } = Typography;

/** 情绪对应的展示色:按效价极性(消极冷/暖红,积极绿,中性灰) */
const POLARITY_COLORS: Record<string, string> = {
  喜悦: "#52c41a",
  平静: "#8c8c8c",
  期待: "#13c2c2",
  感动: "#36cfc9",
  惊讶: "#597ef7",
  悲伤: "#2f54eb",
  愤怒: "#f5222d",
  恐惧: "#722ed1",
  焦虑: "#fa8c16",
  疲惫: "#8c8c8c",
  厌恶: "#eb2f96",
  孤独: "#1d39c4",
  中性: "#bfbfbf",
};

function emotionColor(name: string): string {
  return POLARITY_COLORS[name] ?? "#8c8c8c";
}

function trendText(trend: string): string {
  return trend === "up" ? "上行" : trend === "down" ? "下行" : "平稳";
}

/** 气泡云配色:按情绪极性分三组柔和色,用词哈希稳定取色(同一个词颜色不变) */
const NEGATIVE_BUBBLES = ["#FF7875", "#FFA940", "#B37FEB"];
const POSITIVE_BUBBLES = ["#73D13D", "#36CFC9", "#40A9FF"];
const NEUTRAL_BUBBLES = ["#BFBFBF", "#9E9E9E", "#D3ADF7"];

function bubbleColor(word: string, valence: number): string {
  const band =
    valence < -0.2 ? NEGATIVE_BUBBLES : valence > 0.2 ? POSITIVE_BUBBLES : NEUTRAL_BUBBLES;
  let hash = 0;
  for (const ch of word) hash = (hash * 31 + ch.charCodeAt(0)) % 997;
  return band[hash % band.length];
}

interface Bubble {
  word: string;
  original: string;
  count: number;
  valence: number;
  x: number;
  y: number;
  r: number;
  color: string;
  fontSize: number;
}

const DISPLAY_MAX_CHARS = 5;

/** 圆形气泡云排布:字号按词频、半径按"文字宽度 + 词频"取大,螺旋贪心找不重叠位置 */
function layoutBubbles(
  words: EmotionWord[],
  box: number,
  maxBubbles: number,
  compact = false
): Bubble[] {
  const top = words.slice(0, maxBubbles);
  const maxCount = Math.max(1, ...top.map((w) => w.count));
  const cx = box / 2;
  const cy = box / 2;
  const placed: Bubble[] = [];
  for (const w of top) {
    const ratio = Math.sqrt(w.count / maxCount);
    const display =
      w.word.length > DISPLAY_MAX_CHARS ? `${w.word.slice(0, DISPLAY_MAX_CHARS)}…` : w.word;
    const fontSize = Math.round((compact ? 10 : 11) + (compact ? 4 : 6) * ratio);
    // 半径:至少能装下文字(中文近似 1em/字),同时随词频增大
    const r = Math.max((display.length * fontSize) / 2 + 7, box * 0.034 + box * 0.042 * ratio);
    let x = 0;
    let y = 0;
    let ok = false;
    for (let step = 0; step < 600; step += 1) {
      const t = step * 0.32;
      const radius = 4 + 2.1 * t;
      x = cx + radius * Math.cos(t) * 1.1;
      y = cy + radius * Math.sin(t) * 1.1;
      if (x - r < 2 || y - r < 2 || x + r > box - 2 || y + r > box - 2) continue;
      ok = placed.every(
        (p) => (p.x - x) ** 2 + (p.y - y) ** 2 >= (p.r + r + 4) ** 2
      );
      if (ok) break;
    }
    if (!ok) continue; // 放不下就跳过,不硬挤(避免重叠)
    placed.push({
      word: display,
      original: w.word,
      count: w.count,
      valence: w.valence,
      x,
      y,
      r,
      color: bubbleColor(w.word, w.valence),
      fontSize,
    });
  }
  return placed;
}

function EmotionPage() {
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const chartHeight = isMobile ? 200 : 300;
  // 词云与触发事件两张卡片共用同一高度,保证左右对齐
  const panelHeight = isMobile ? 300 : 380;

  const [granularity, setGranularity] = useState<"day" | "week" | "month">("day");
  const [days, setDays] = useState(30);
  const [history, setHistory] = useState<EmotionHistoryPoint[]>([]);
  const [summary, setSummary] = useState<EmotionSummary | null>(null);
  const [profile, setProfile] = useState<EmotionProfile | null>(null);
  const [words, setWords] = useState<EmotionWord[]>([]);
  const [events, setEvents] = useState<EmotionEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastLoaded, setLastLoaded] = useState<Date | null>(null);
  const [wordFilter, setWordFilter] = useState<string | undefined>();

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const [h, s, p, w, e] = await Promise.all([
          getEmotionHistory(granularity, days),
          getEmotionSummary(days),
          getEmotionProfile(7),
          getEmotionWordcloud(days),
          listEmotionEvents(50),
        ]);
        setHistory(h);
        setSummary(s);
        setProfile(p);
        setWords(w);
        setEvents(e);
        setLastLoaded(new Date());
      } catch {
        if (!silent) message.error("情绪数据加载失败");
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [granularity, days]
  );

  useEffect(() => {
    void load();
    // 情绪分析是后台任务(约 10~40s),面板定时静默刷新
    const timer = window.setInterval(() => void load(true), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const historyOption = useMemo(
    () => ({
      tooltip: {
        trigger: "axis",
        formatter: (params: any[]) => {
          const point = params[0]?.dataIndex ?? 0;
          const row = history[point];
          if (!row) return "";
          return `${row.bucket}<br/>主导情绪:${row.dominant_emotion}<br/>效价:${row.avg_valence}<br/>唤醒度:${row.avg_arousal}<br/>记录:${row.count} 条`;
        },
      },
      legend: { data: ["效价", "唤醒度"], bottom: 0, itemWidth: 12, textStyle: { fontSize: 11 } },
      grid: { left: 40, right: 40, top: 16, bottom: 40 },
      xAxis: {
        type: "category",
        data: history.map((h) => h.bucket),
        axisLabel: { fontSize: 10, color: "#999" },
      },
      yAxis: [
        { type: "value", min: -1, max: 1, name: "效价", nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 } },
        { type: "value", min: 0, max: 1, name: "唤醒", nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 } },
      ],
      series: [
        {
          name: "效价",
          type: "line",
          smooth: true,
          symbolSize: 6,
          data: history.map((h) => h.avg_valence),
          itemStyle: { color: "#2f6bff" },
          areaStyle: { color: "rgba(47,107,255,0.08)" },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: "#d9d9d9", type: "dashed" },
            data: [{ yAxis: 0 }],
          },
        },
        {
          name: "唤醒度",
          type: "line",
          smooth: true,
          yAxisIndex: 1,
          symbolSize: 4,
          data: history.map((h) => h.avg_arousal),
          itemStyle: { color: "#fa8c16" },
          lineStyle: { type: "dashed" },
        },
      ],
    }),
    [history]
  );

  const pieOption = useMemo(
    () => ({
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      series: [
        {
          type: "pie",
          radius: isMobile ? ["42%", "66%"] : ["46%", "70%"],
          center: ["50%", "52%"],
          label: { fontSize: 11 },
          data: (summary?.distribution ?? []).map((d) => ({
            name: d.emotion_type,
            value: d.count,
            itemStyle: { color: emotionColor(d.emotion_type) },
          })),
        },
      ],
    }),
    [summary, isMobile]
  );

  const bubbleBox = panelHeight;
  const bubbles = useMemo(
    () => layoutBubbles(words, bubbleBox, isMobile ? 14 : 24, isMobile),
    [words, bubbleBox, isMobile]
  );
  // 仅开发环境暴露气泡坐标,便于自动化检查"是否重叠"
  useEffect(() => {
    const isDev = Boolean(
      (import.meta as unknown as { env?: { DEV?: boolean } }).env?.DEV
    );
    if (isDev) {
      (window as unknown as { __emotionBubbles?: Bubble[] }).__emotionBubbles = bubbles;
    }
  }, [bubbles]);
  const bubbleOption: any = useMemo(
    () => ({
      animationDuration: 500,
      tooltip: {
        formatter: (p: any) => `${p.data.original}:出现 ${p.data.count} 次`,
        textStyle: { fontSize: 12 },
      },
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: { type: "value", min: 0, max: bubbleBox, show: false },
      yAxis: { type: "value", min: 0, max: bubbleBox, show: false, inverse: true },
      series: [
        {
          type: "scatter",
          symbolSize: (val: any, params: any) => (params?.data?.r ?? 10) * 2,
          data: bubbles.map((b) => ({
            value: [b.x, b.y],
            word: b.word,
            original: b.original,
            count: b.count,
            r: b.r,
            itemStyle: {
              color: b.color,
              shadowBlur: 10,
              shadowColor: "rgba(0,0,0,0.12)",
              borderColor: "rgba(255,255,255,0.85)",
              borderWidth: 1,
            },
            label: {
              show: true,
              formatter: b.word,
              position: "inside",
              color: "#fff",
              fontWeight: 700,
              fontSize: b.fontSize,
            },
          })),
          emphasis: { scale: 1.08, label: { fontWeight: 800 } },
          labelLayout: { hideOverlap: true },
        },
      ],
    }),
    [bubbles, bubbleBox]
  );
  const filteredEvents = wordFilter
    ? events.filter(
        (e) => e.keywords?.includes(wordFilter) || (e.trigger ?? "").includes(wordFilter)
      )
    : events;

  const handleDelete = async (item: EmotionEvent) => {
    try {
      await deleteEmotion(item.id);
      message.success("已删除该条情绪记录");
      await load();
    } catch {
      message.error("删除失败");
    }
  };

  const hasData = (summary?.count ?? 0) > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        style={{
          borderRadius: 16,
          padding: isMobile ? "16px 14px" : "18px 20px",
          background: "linear-gradient(135deg, #f2f6ff 0%, #f7f2ff 55%, #fff7f0 100%)",
          border: "1px solid rgba(124,92,252,0.10)",
        }}
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
            marginBottom: 14,
          }}
        >
          <div>
            <div style={{ fontSize: isMobile ? 18 : 20, fontWeight: 700 }}>情绪助手</div>
            <div style={{ fontSize: 12, color: "#8c8c8c", marginTop: 2 }}>
              每轮对话后台识别情绪 · 效价/唤醒度(Russell 情绪环)
            </div>
          </div>
          <Space size={8} wrap>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {lastLoaded ? `更新于 ${lastLoaded.toLocaleTimeString()}` : ""}
            </Text>
            <Select
              size="small"
              value={days}
              style={{ width: 96 }}
              onChange={setDays}
              options={[
                { value: 7, label: "近 7 天" },
                { value: 30, label: "近 30 天" },
                { value: 90, label: "近 90 天" },
              ]}
            />
            <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
              刷新
            </Button>
          </Space>
        </div>
        <Row gutter={[10, 10]}>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic
                title="平均效价"
                value={summary?.avg_valence ?? 0}
                precision={2}
                valueStyle={{
                  color: (summary?.avg_valence ?? 0) < -0.2 ? "#f5222d" : "#2f6bff",
                  fontSize: isMobile ? 18 : 22,
                }}
              />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic
                title="主导情绪"
                value={summary?.dominant_emotion ?? "-"}
                valueStyle={{ fontSize: isMobile ? 18 : 22, color: emotionColor(summary?.dominant_emotion ?? "中性") }}
              />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic title={`记录数(${summary?.days ?? days}天)`} value={summary?.count ?? 0} />
            </Card>
          </Col>
          <Col xs={12} md={6}>
            <Card size="small">
              <Statistic
                title="情绪趋势"
                value={trendText(summary?.trend ?? "flat")}
                valueStyle={{
                  fontSize: isMobile ? 18 : 22,
                  color: summary?.trend === "up" ? "#52c41a" : summary?.trend === "down" ? "#fa8c16" : "#8c8c8c",
                }}
              />
            </Card>
          </Col>
        </Row>
        {profile && profile.sample_count > 0 && profile.recent_triggers.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              近期触发:{profile.recent_triggers.join("、")}
            </Text>
          </div>
        )}
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card
            size="small"
            title="情绪曲线"
            extra={
              <Segmented
                size="small"
                value={granularity}
                onChange={(value) => setGranularity(value as "day" | "week" | "month")}
                options={[
                  { label: "日", value: "day" },
                  { label: "周", value: "week" },
                  { label: "月", value: "month" },
                ]}
              />
            }
          >
            {history.length === 0 ? (
              <Empty description="还没有情绪记录,多聊几句我就能画出你的情绪曲线" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <ReactECharts option={historyOption} style={{ height: chartHeight }} notMerge />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title="情绪分布">
            {hasData ? (
              <ReactECharts option={pieOption} style={{ height: chartHeight }} notMerge />
            ) : (
              <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10} style={{ display: "flex" }}>
          <Card
            size="small"
            title="情绪词云"
            style={{ width: "100%", height: "100%" }}
            extra={
              wordFilter ? (
                <Button size="small" type="link" onClick={() => setWordFilter(undefined)}>
                  清除筛选
                </Button>
              ) : (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  点击词语筛选事件
                </Text>
              )
            }
          >
            {bubbles.length === 0 ? (
              <div
                style={{
                  height: bubbleBox,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Empty description="暂无关键词" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              </div>
            ) : (
              <div
                style={{
                  height: bubbleBox,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <ReactECharts
                  option={bubbleOption}
                  style={{ width: bubbleBox, height: bubbleBox, maxWidth: "100%" }}
                  notMerge
                  onEvents={{
                    click: (params: any) =>
                      params?.data?.original && setWordFilter(params.data.original),
                  }}
                />
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={14} style={{ display: "flex" }}>
          <Card
            size="small"
            title={`触发事件(${filteredEvents.length})`}
            style={{ width: "100%", height: "100%" }}
            extra={
              wordFilter ? <Tag color="red">筛选:{wordFilter}</Tag> : undefined
            }
          >
            {filteredEvents.length === 0 ? (
              <div style={{ height: panelHeight, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Empty description="暂无触发事件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              </div>
            ) : (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  height: panelHeight,
                  overflowY: "auto",
                }}
              >
                {filteredEvents.map((e) => (
                  <div
                    key={e.id}
                    style={{
                      padding: "8px 10px",
                      borderRadius: 10,
                      border: "1px solid #f0f0f0",
                      background: "#fff",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <Tag bordered={false} style={{ color: "#fff", background: emotionColor(e.emotion_type), marginInlineEnd: 0 }}>
                        {e.emotion_type}
                      </Tag>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {e.created_at.slice(0, 16).replace("T", " ")} · 强度 {e.intensity.toFixed(2)} · 效价{" "}
                        {e.valence.toFixed(2)}
                      </Text>
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        style={{ marginLeft: "auto" }}
                        onClick={() => void handleDelete(e)}
                      />
                    </div>
                    {e.trigger && (
                      <div style={{ marginTop: 4, fontSize: 13 }}>
                        <Text strong>触发:</Text>
                        {e.trigger}
                      </div>
                    )}
                    {e.summary && (
                      <div style={{ fontSize: 12, color: "#8c8c8c", marginTop: 2 }}>{e.summary}</div>
                    )}
                    {e.evidence && (
                      <div
                        style={{
                          marginTop: 4,
                          fontSize: 12,
                          color: "#595959",
                          background: "#fafafa",
                          borderRadius: 8,
                          padding: "6px 8px",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        “{e.evidence}”
                      </div>
                    )}
                    {e.keywords?.length > 0 && (
                      <Space wrap size={[4, 4]} style={{ marginTop: 4 }}>
                        {e.keywords.map((k) => (
                          <Tag key={k} bordered={false} style={{ fontSize: 11, background: "#fafafa", color: "#8c8c8c" }}>
                            {k}
                          </Tag>
                        ))}
                      </Space>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}

export default EmotionPage;
