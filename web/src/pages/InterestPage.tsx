import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Card,
  Col,
  Empty,
  Grid,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CompressOutlined,
  DeleteOutlined,
  FireOutlined,
  HistoryOutlined,
  NodeIndexOutlined,
  ReloadOutlined,
  RiseOutlined,
  SearchOutlined,
  StarOutlined,
  ThunderboltOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import * as echarts from "echarts";
import { Graph } from "@antv/x6";
import {
  InterestGraphData,
  InterestCommunity,
  InterestItem,
  InterestSummary,
  RecallResult,
  EntityDetail,
  deleteInterest,
  getInterestGraph,
  getInterestSummary,
  getEntityDetail,
  listInterests,
  listCommunities,
  recallInterest,
} from "../api/interest";

const { Text } = Typography;

const CATEGORY_COLORS: Record<string, string> = {
  体育: "#2f6bff",
  科技: "#7a4dff",
  影视: "#eb2f96",
  音乐: "#13c2c2",
  美食: "#fa8c16",
  游戏: "#52c41a",
  学术: "#1d39c4",
  旅行: "#faad14",
  其他: "#8c8c8c",
};

const CATEGORY_OPTIONS = Object.keys(CATEGORY_COLORS).map((c) => ({ value: c, label: c }));

const SUGGESTIONS = [
  "我都关注过什么?",
  "跟 NBA 相关的我还关注过什么?",
  "我以前是不是关注过篮球?",
];

function toDateStr(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "";
}

function rangeText(item: InterestItem): string {
  const start = toDateStr(item.since) || toDateStr(item.last_seen);
  const end = toDateStr(item.until);
  if (start && end) return `${start} ~ ${end}`;
  if (start) return `${start} 至今`;
  if (end) return `截至 ${end}`;
  return "时间未知";
}

function statusTag(status: string) {
  return status === "cooled" ? (
    <Tag bordered={false} style={{ marginInlineEnd: 0, color: "#8c8c8c", background: "#f5f5f5" }}>
      已冷却
    </Tag>
  ) : (
    <Tag bordered={false} color="success" style={{ marginInlineEnd: 0 }}>
      活跃
    </Tag>
  );
}

function StatTile({
  icon,
  label,
  value,
  color,
}: {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  color: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        borderRadius: 12,
        background: "rgba(255,255,255,0.78)",
        border: "1px solid rgba(124,92,252,0.12)",
        minWidth: 0,
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 10,
          background: `${color}1a`,
          color,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 16,
          flexShrink: 0,
        }}
      >
        {icon}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, color: "#8c8c8c", lineHeight: "16px" }}>{label}</div>
        <div
          style={{
            fontSize: 18,
            fontWeight: 600,
            color: "#1f1f1f",
            lineHeight: "24px",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={typeof value === "string" ? value : undefined}
        >
          {value}
        </div>
      </div>
    </div>
  );
}

function InterestPage() {
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  // 上面两张卡片共用同一高度,保证左右严格对齐
  const cardHeight = isMobile ? 420 : 500;
  const maxTimelineRows = Math.max(
    4,
    Math.floor((cardHeight - 150) / (isMobile ? 30 : 34))
  );

  const [summary, setSummary] = useState<InterestSummary | null>(null);
  const [items, setItems] = useState<InterestItem[]>([]);
  const [graphData, setGraphData] = useState<InterestGraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [category, setCategory] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const [query, setQuery] = useState("");
  const [recall, setRecall] = useState<RecallResult | null>(null);
  const [recalling, setRecalling] = useState(false);
  const [highlight, setHighlight] = useState<string[]>([]);
  const [lastLoaded, setLastLoaded] = useState<Date | null>(null);
  const [communities, setCommunities] = useState<InterestCommunity[]>([]);
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const chartWrapRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<any>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [s, t, g, c] = await Promise.all([
        getInterestSummary(),
        listInterests({ category, status }),
        getInterestGraph(120),
        listCommunities(),
      ]);
      setSummary(s);
      setItems(t);
      setGraphData(g);
      setCommunities(c);
      setLastLoaded(new Date());
    } catch {
      if (!silent) message.error("兴趣数据加载失败");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [category, status]);

  const openDetail = useCallback(async (key: string) => {
    if (!key) return;
    setDetailLoading(true);
    try {
      setDetail(await getEntityDetail(key));
    } catch {
      message.error("加载节点详情失败");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // 兴趣抽取是后台任务(10~40s),面板定时静默刷新,避免"我刚说了却没显示"
    const timer = window.setInterval(() => {
      void load(true);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const activeCategories = useMemo(
    () => Array.from(new Set(items.map((i) => i.category))).filter(Boolean),
    [items]
  );

  const timelineRows = useMemo(
    () =>
      items
        .slice()
        .sort((a, b) => (b.last_seen ?? "").localeCompare(a.last_seen ?? ""))
        .slice(0, maxTimelineRows),
    [items, maxTimelineRows]
  );

  // 兴趣 → 下挂实体(从图数据的 HAS_ENTITY 边推导,用于明细卡片展示)
  const entitiesByInterest = useMemo(() => {
    const labelById = new Map((graphData?.nodes ?? []).map((n) => [n.id, n.label]));
    const kindById = new Map((graphData?.nodes ?? []).map((n) => [n.id, n.kind]));
    const map: Record<string, string[]> = {};
    (graphData?.edges ?? []).forEach((e) => {
      const pairs: [string, string][] = [
        [e.source, e.target],
        [e.target, e.source],
      ];
      pairs.forEach(([owner, other]) => {
        if (kindById.get(owner) !== "followed" || kindById.get(other) !== "related") return;
        if (!owner.startsWith("entity:") || !other.startsWith("entity:")) return;
        const key = owner.slice("entity:".length);
        const label = labelById.get(other);
        if (!label) return;
        map[key] = [...(map[key] ?? []), label];
      });
    });
    return map;
  }, [graphData]);

  // 时间线:甘特式色块,按分类着色,冷却态半透明
  const timelineOption = useMemo(() => {
    const today = Date.now();
    const data = timelineRows.map((item, index) => {
      const start = Date.parse(toDateStr(item.since) || toDateStr(item.last_seen) || "");
      const endRaw = toDateStr(item.until);
      const end = endRaw ? Date.parse(endRaw) : today;
      const safeStart = Number.isNaN(start) ? today - 30 * 86400000 : start;
      return {
        value: [index, safeStart, Math.max(end, safeStart + 5 * 86400000)],
        itemStyle: {
          color: CATEGORY_COLORS[item.category] ?? "#8c8c8c",
          opacity: item.status === "cooled" ? 0.42 : 1,
          borderRadius: 6,
          shadowBlur: 6,
          shadowColor: "rgba(0,0,0,0.08)",
        },
      };
    });
    return {
      tooltip: {
        backgroundColor: "rgba(255,255,255,0.96)",
        borderColor: "#f0f0f0",
        textStyle: { fontSize: 12, color: "#333" },
        formatter: (params: { value: number[] }) => {
          const row = timelineRows[params.value[0]];
          if (!row) return "";
          return `${row.name} · ${row.category}<br/>${rangeText(row)}<br/>提及 ${row.mention_count} 次${
            row.status === "cooled" ? " · 已冷却" : ""
          }`;
        },
      },
      grid: { left: isMobile ? 62 : 96, right: 18, top: 8, bottom: 24 },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: "#e8e8e8" } },
        axisTick: { show: false },
        axisLabel: { fontSize: 11, color: "#999" },
        splitLine: { lineStyle: { color: "#f5f5f5", type: "dashed" } },
      },
      yAxis: {
        type: "category",
        data: timelineRows.map((r) => r.name),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          fontSize: isMobile ? 10 : 12,
          color: "#595959",
          width: isMobile ? 54 : 86,
          overflow: "truncate",
        },
      },
      series: [
        {
          type: "custom",
          renderItem: (params: any, api: any) => {
            const categoryIndex = api.value(0);
            const start = api.coord([api.value(1), categoryIndex]);
            const end = api.coord([api.value(2), categoryIndex]);
            const height = Math.min(api.size([0, 1])[1] * 0.58, 24);
            const rect = echarts.graphic.clipRectByRect(
              {
                x: start[0],
                y: start[1] - height / 2,
                width: Math.max(end[0] - start[0], 6),
                height,
              },
              {
                x: params.coordSys.x,
                y: params.coordSys.y,
                width: params.coordSys.width,
                height: params.coordSys.height,
              }
            );
            return rect && { type: "rect", shape: rect, style: api.style() };
          },
          encode: { x: [1, 2], y: 0 },
          data,
          z: 3,
        },
        {
          type: "custom",
          renderItem: (params: any, api: any) => {
            const x = api.coord([api.value(1), 0])[0];
            const { y, height } = params.coordSys;
            return {
              type: "line",
              shape: { x1: x, y1: y, x2: x, y2: y + height },
              style: { stroke: "#ff7875", lineWidth: 1, lineDash: [4, 4], opacity: 0.8 },
            };
          },
          encode: { x: [1, 2], y: 0 },
          data: [{ value: [0, today, today] }],
          silent: true,
          z: 2,
        },
      ],
    };
  }, [timelineRows, isMobile]);

  // ECharts 不会自动跟随 flex 容器尺寸:用 ResizeObserver 强制撑满卡片
  useEffect(() => {
    const el = chartWrapRef.current;
    if (!el) return;
    const resize = () => {
      const instance = chartRef.current?.getEchartsInstance?.();
      if (!instance || !el) return;
      // 显式传尺寸,避免 ECharts 缓存了布局早期的旧高度
      instance.resize({ width: el.clientWidth, height: el.clientHeight });
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    const timers = [80, 300, 800, 1500].map((ms) => window.setTimeout(resize, ms));
    return () => {
      observer.disconnect();
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, []);

  useEffect(() => {
    const id = window.requestAnimationFrame(() =>
      chartRef.current?.getEchartsInstance?.()?.resize()
    );
    return () => window.cancelAnimationFrame(id);
  }, [timelineRows, isMobile, cardHeight]);

  // X6 关系图:兴趣在外圈、实体在内圈,点击节点高亮一跳
  useEffect(() => {
    if (!containerRef.current) return;
    const graph = new Graph({
      container: containerRef.current,
      autoResize: true,
      panning: true,
      mousewheel: { enabled: true, modifiers: ["ctrl", "meta"] },
      interacting: { nodeMovable: false, edgeMovable: false },
      background: { color: "#fff" },
    });
    graphRef.current = graph;
    return () => {
      graph.dispose();
      graphRef.current = null;
    };
  }, []);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || !graphData) return;
    graph.clearCells();
    const interests = graphData.nodes.filter((n) => n.kind === "followed");
    const entities = graphData.nodes.filter((n) => n.kind !== "followed");
    const width = containerRef.current?.clientWidth ?? 460;
    const height = containerRef.current?.clientHeight ?? 380;
    const cx = width / 2;
    const cy = height / 2;
    const rOuter = Math.max(90, Math.min(width, height) / 2 - 54);
    const rInner = rOuter * 0.42;
    const pos: Record<string, { x: number; y: number }> = {};
    interests.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(interests.length, 1) - Math.PI / 2;
      pos[n.id] = { x: cx + rOuter * Math.cos(angle), y: cy + rOuter * Math.sin(angle) };
    });
    entities.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / Math.max(entities.length, 1) - Math.PI / 2 + Math.PI / 8;
      pos[n.id] = { x: cx + rInner * Math.cos(angle), y: cy + rInner * Math.sin(angle) };
    });
    interests.forEach((n) => {
      const color = CATEGORY_COLORS[n.category ?? "其他"] ?? "#8c8c8c";
      graph.addNode({
        id: n.id,
        x: pos[n.id].x - 44,
        y: pos[n.id].y - 22,
        width: 88,
        height: 44,
        shape: "rect",
        attrs: {
          body: {
            rx: 12,
            ry: 12,
            fill: n.status === "cooled" ? "#ffffff" : color,
            stroke: n.status === "cooled" ? color : "#ffffff",
            strokeWidth: n.status === "cooled" ? 1.5 : 0,
            strokeDasharray: n.status === "cooled" ? "4 3" : undefined,
            shadowBlur: 10,
            shadowColor: "rgba(0,0,0,0.10)",
          },
          label: {
            fill: n.status === "cooled" ? color : "#ffffff",
            fontSize: 12,
            fontWeight: 500,
            textWrap: { width: 76, ellipsis: true },
          },
        },
        label: n.label,
        data: { kind: "interest", name: n.label },
      });
    });
    entities.forEach((n) => {
      graph.addNode({
        id: n.id,
        x: pos[n.id].x - 32,
        y: pos[n.id].y - 15,
        width: 64,
        height: 30,
        shape: "rect",
        attrs: {
          body: { rx: 15, ry: 15, fill: "#f7f7f7", stroke: "#e8e8e8", strokeWidth: 1 },
          label: { fill: "#8c8c8c", fontSize: 11, textWrap: { width: 54, ellipsis: true } },
        },
        label: n.label,
        data: { kind: "entity", name: n.label },
      });
    });
    graphData.edges.forEach((e, i) => {
      if (!pos[e.source] || !pos[e.target]) return;
      const isBroader = e.type === "broader";
      graph.addEdge({
        id: `edge-${i}`,
        source: e.source,
        target: e.target,
        attrs: {
          line: {
            stroke: isBroader ? "#a8b6d6" : "#d9d9d9",
            strokeWidth: isBroader ? 1.4 : 1,
            strokeDasharray: isBroader ? undefined : "4 3",
            targetMarker: isBroader ? { name: "block", size: 5, fill: "#a8b6d6" } : null,
          },
        },
        data: { kind: "edge" },
        zIndex: -1,
      });
    });
    graph.centerContent();

    graph.off("node:click");
    graph.on("node:click", ({ node }: { node: any }) => {
      const name = (node.getData() as { name?: string })?.name ?? "";
      const key = String(node.id ?? "").replace(/^entity:/, "");
      const neighbors = new Set<string>([name]);
      graph.getEdges().forEach((edge) => {
        const src = (edge.getSourceCell()?.getData() as { name?: string })?.name;
        const dst = (edge.getTargetCell()?.getData() as { name?: string })?.name;
        if (src === name && dst) neighbors.add(dst);
        if (dst === name && src) neighbors.add(src);
      });
      setHighlight(Array.from(neighbors));
      void openDetail(key);
    });
    graph.off("blank:click");
    graph.on("blank:click", () => setHighlight([]));
    setHighlight([]);
  }, [graphData, cardHeight, openDetail]);

  // 高亮 = 点击的邻居 ∪ 检索结果涉及的兴趣/实体/路径
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    const keys = new Set(highlight);
    recall?.items?.forEach((i) => {
      keys.add(i.name);
      i.path?.forEach((p) => keys.add(p));
      i.via?.forEach((v) => keys.add(v));
    });
    const names = Array.from(keys);
    graph.getNodes().forEach((node) => {
      const name = (node.getData() as { name?: string })?.name ?? "";
      const active = names.length === 0 || names.includes(name);
      node.attr("body/opacity", active ? 1 : 0.12);
      node.attr("label/opacity", active ? 1 : 0.12);
    });
    graph.getEdges().forEach((edge) => {
      // 两端都在高亮集合里的边保持可见(否则高亮节点之间的连线会被一起压暗,像关系断了)
      const src = (edge.getSourceCell()?.getData() as { name?: string })?.name;
      const dst = (edge.getTargetCell()?.getData() as { name?: string })?.name;
      const edgeActive =
        names.length === 0 || (!!src && !!dst && names.includes(src) && names.includes(dst));
      edge.attr("line/opacity", edgeActive ? 1 : 0.1);
    });
  }, [highlight, recall]);

  const runRecall = async (text: string) => {
    const value = text.trim();
    if (!value) return;
    setQuery(value);
    setRecalling(true);
    try {
      const result = await recallInterest({ query: value, hops: 2 });
      setRecall(result);
      if (!result.items.length) message.info("还没有记录到相关兴趣");
    } catch {
      message.error("检索失败");
    } finally {
      setRecalling(false);
    }
  };

  const handleDelete = async (item: InterestItem) => {
    try {
      await deleteInterest(item.id);
      message.success(`已删除「${item.name}」`);
      setRecall(null);
      await load();
    } catch {
      message.error("删除失败");
    }
  };

  const hasData = (summary?.total_count ?? 0) > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 概览 + 多跳检索(全宽,避免与明细卡高度不齐) */}
      <div
        style={{
          borderRadius: 16,
          padding: isMobile ? "16px 14px" : "18px 20px",
          background: "linear-gradient(135deg, #f4f0ff 0%, #eef5ff 55%, #f0fbff 100%)",
          border: "1px solid rgba(124,92,252,0.10)",
        }}
      >
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            marginBottom: 14,
          }}
        >
          <div>
            <div style={{ fontSize: isMobile ? 18 : 20, fontWeight: 700, color: "#1f1f1f" }}>
              兴趣图谱
            </div>
            <div style={{ fontSize: 12, color: "#8c8c8c", marginTop: 2 }}>
              从日常聊天自动积累的兴趣画像 · 向量种子 + 图多跳检索
            </div>
          </div>
          <Space size={8} wrap>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {lastLoaded ? `更新于 ${lastLoaded.toLocaleTimeString()}` : ""}
            </Text>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
              刷新
            </Button>
            <Button
              size="small"
              icon={<ThunderboltOutlined />}
              onClick={() => runRecall("我都关注过什么?")}
              loading={recalling}
            >
              一键回顾
            </Button>
          </Space>
        </div>

        <Row gutter={[10, 10]}>
          <Col xs={12} md={6}>
            <StatTile icon={<FireOutlined />} label="当前活跃" value={summary?.active_count ?? 0} color="#2f6bff" />
          </Col>
          <Col xs={12} md={6}>
            <StatTile icon={<HistoryOutlined />} label="历史总数" value={summary?.total_count ?? 0} color="#7a4dff" />
          </Col>
          <Col xs={12} md={6}>
            <StatTile
              icon={<StarOutlined />}
              label="最久兴趣"
              value={summary?.longest_interest?.name ?? "-"}
              color="#fa8c16"
            />
          </Col>
          <Col xs={12} md={6}>
            <StatTile icon={<RiseOutlined />} label="近 30 天新增" value={summary?.new_last_30d ?? 0} color="#13c2c2" />
          </Col>
        </Row>

        <div style={{ marginTop: 14 }}>
          <Space.Compact style={{ width: "100%" }}>
            <Input
              placeholder="问一句,如:我以前是不是关注过篮球"
              prefix={<SearchOutlined style={{ color: "#bfbfbf" }} />}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onPressEnter={() => runRecall(query)}
            />
            <Button type="primary" loading={recalling} onClick={() => runRecall(query)}>
              检索
            </Button>
          </Space.Compact>
          <Space wrap size={[6, 6]} style={{ marginTop: 8 }}>
            {SUGGESTIONS.map((s) => (
              <Tag
                key={s}
                bordered={false}
                style={{ cursor: "pointer", background: "rgba(255,255,255,0.85)", color: "#7C5CFC" }}
                onClick={() => runRecall(s)}
              >
                {s}
              </Tag>
            ))}
          </Space>
          {recall && (
            <div
              style={{
                marginTop: 10,
                padding: "10px 12px",
                borderRadius: 12,
                background: "rgba(255,255,255,0.85)",
                border: "1px solid rgba(124,92,252,0.12)",
              }}
            >
              {recall.items.length > 0 && (
                <Space wrap size={[6, 6]} style={{ marginBottom: 6 }}>
                  {recall.items.map((i) => (
                    <Tag
                      key={i.key}
                      bordered={false}
                      style={{
                        background: `${CATEGORY_COLORS[i.category] ?? "#8c8c8c"}1a`,
                        color: CATEGORY_COLORS[i.category] ?? "#8c8c8c",
                      }}
                    >
                      {i.name}
                      {i.hops > 0 ? ` · ${i.hops}跳` : ""}
                      {i.status === "cooled" ? " · 已冷却" : ""}
                    </Tag>
                  ))}
                </Space>
              )}
              {recall.paths.length > 0 && (
                <div style={{ marginBottom: 6 }}>
                  {recall.paths.slice(0, 4).map((p, idx) => (
                    <div key={idx} style={{ fontSize: 12, color: "#7C5CFC" }}>
                      {p.nodes.join("  →  ")}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {" "}
                        ({p.hops} 跳)
                      </Text>
                    </div>
                  ))}
                </div>
              )}
              <div
                style={{
                  maxHeight: 150,
                  overflowY: "auto",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontSize: 12.5,
                  lineHeight: 1.7,
                  color: "#595959",
                }}
              >
                {recall.text}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 时间线 + 关系图:同一高度,左右严格对齐 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14} style={{ display: "flex" }}>
          <Card
            size="small"
            title="兴趣时间线"
            style={{
              width: "100%",
              height: cardHeight,
              display: "flex",
              flexDirection: "column",
            }}
            styles={{ body: { flex: 1, display: "flex", flexDirection: "column", minHeight: 0, paddingTop: 12 } }}
            extra={
              <Space wrap size={8}>
                <Select
                  allowClear
                  size="small"
                  placeholder="全部分类"
                  style={{ width: isMobile ? 96 : 112 }}
                  value={category}
                  onChange={setCategory}
                  options={CATEGORY_OPTIONS}
                />
                <Select
                  allowClear
                  size="small"
                  placeholder="全部状态"
                  style={{ width: isMobile ? 96 : 112 }}
                  value={status}
                  onChange={setStatus}
                  options={[
                    { value: "active", label: "活跃" },
                    { value: "cooled", label: "已冷却" },
                  ]}
                />
              </Space>
            }
          >
            <Space wrap size={[6, 6]} style={{ marginBottom: 6 }}>
              {activeCategories.map((c) => (
                <Tag
                  key={c}
                  bordered={false}
                  style={{
                    background: `${CATEGORY_COLORS[c] ?? "#8c8c8c"}1a`,
                    color: CATEGORY_COLORS[c] ?? "#8c8c8c",
                  }}
                >
                  {c}
                </Tag>
              ))}
              {hasData && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  红色虚线 = 今天
                  {items.length > timelineRows.length
                    ? ` · 显示最近 ${timelineRows.length}/${items.length} 条`
                    : ""}
                </Text>
              )}
            </Space>
            {/* 注意:这里不能让 antd Spin 包住图表——它的中间层不继承高度,会把 height:100% 链条截断,
                图表只能拿到 100px 高度,10 条时间线全挤在顶部、卡片下半段空着 */}
            <div
              ref={chartWrapRef}
              style={{ flex: 1, minHeight: 0, position: "relative", overflow: "hidden" }}
            >
              {items.length === 0 && !loading ? (
                <div
                  style={{
                    height: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Empty
                    description={
                      hasData ? "当前筛选下没有兴趣" : "还没有记录到兴趣,聊聊你最近在关注什么吧"
                    }
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                  />
                </div>
              ) : (
                <ReactECharts
                  ref={chartRef}
                  option={timelineOption}
                  style={{ height: "100%", width: "100%" }}
                  notMerge
                />
              )}
              {loading && (
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: "rgba(255,255,255,0.45)",
                    borderRadius: 8,
                  }}
                >
                  <Spin />
                </div>
              )}
            </div>
          </Card>
        </Col>

        <Col xs={24} lg={10} style={{ display: "flex" }}>
          <Card
            size="small"
            title={
              <Space size={6}>
                <NodeIndexOutlined />
                <span>兴趣关系图</span>
              </Space>
            }
            style={{
              width: "100%",
              height: cardHeight,
              display: "flex",
              flexDirection: "column",
            }}
            styles={{ body: { flex: 1, display: "flex", flexDirection: "column", minHeight: 0, paddingTop: 12 } }}
            extra={
              <Space size={2}>
                <Tooltip title="放大">
                  <Button
                    size="small"
                    type="text"
                    icon={<ZoomInOutlined />}
                    onClick={() => graphRef.current?.zoom(0.15)}
                  />
                </Tooltip>
                <Tooltip title="缩小">
                  <Button
                    size="small"
                    type="text"
                    icon={<ZoomOutOutlined />}
                    onClick={() => graphRef.current?.zoom(-0.15)}
                  />
                </Tooltip>
                <Tooltip title="适应窗口">
                  <Button
                    size="small"
                    type="text"
                    icon={<CompressOutlined />}
                    onClick={() => graphRef.current?.centerContent()}
                  />
                </Tooltip>
              </Space>
            }
          >
            {graphData && !graphData.available && (
              <Text type="warning" style={{ display: "block", marginBottom: 6, fontSize: 12 }}>
                图数据库暂不可用,仅显示兴趣节点(时间线与统计不受影响)
              </Text>
            )}
            <Space wrap size={[10, 4]} style={{ marginBottom: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 10,
                    height: 10,
                    borderRadius: 3,
                    background: "#2f6bff",
                    marginRight: 5,
                  }}
                />
                关注实体
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 10,
                    height: 10,
                    borderRadius: 6,
                    background: "#f7f7f7",
                    border: "1px solid #e8e8e8",
                    marginRight: 5,
                  }}
                />
                关联实体
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                实线箭头 = 上下位,虚线 = 其他关联(点击节点查看详情)
              </Text>
            </Space>
            {/* 固定尺寸外层 + 绝对定位画布:X6 autoResize 不会被内容反向撑高 */}
            <div
              style={{
                flex: 1,
                minHeight: 0,
                position: "relative",
                overflow: "hidden",
                borderRadius: 12,
                border: "1px solid #f5f5f5",
                background: "linear-gradient(180deg, #ffffff 0%, #fbfbff 100%)",
              }}
            >
              {graphData && graphData.nodes.length === 0 ? (
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Empty description="暂无图谱数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                </div>
              ) : (
                <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />
              )}
            </div>
          </Card>
        </Col>
      </Row>

      {/* 兴趣主线:社区聚类 + LLM 摘要(全局检索的检索单元) */}
      {communities.filter((c) => c.members.length >= 2).length > 0 && (
        <Card
          size="small"
          title={`兴趣主线(社区聚类 · ${communities.filter((c) => c.members.length >= 2).length})`}
        >
          <Row gutter={[10, 10]}>
            {communities
              .filter((c) => c.members.length >= 2)
              .map((c) => (
                <Col xs={24} sm={12} xl={8} key={c.key}>
                  <div
                    style={{
                      height: "100%",
                      padding: "10px 12px",
                      borderRadius: 12,
                      border: "1px solid #f0f0f0",
                      background: "linear-gradient(180deg,#fff 0%,#fbfbff 100%)",
                    }}
                  >
                    <Space wrap size={6} style={{ marginBottom: 4 }}>
                      <Text strong style={{ fontSize: 13 }}>
                        {c.name}
                      </Text>
                      <Tag bordered={false} style={{ background: "#f5f2ff", color: "#7C5CFC" }}>
                        {c.members.length} 个实体
                      </Tag>
                    </Space>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 6 }}>
                      {c.members.slice(0, 6).map((m) => (
                        <Tag
                          key={m}
                          bordered={false}
                          style={{ fontSize: 11, background: "#fafafa", color: "#8c8c8c" }}
                        >
                          {m}
                        </Tag>
                      ))}
                    </div>
                    <Text type="secondary" style={{ fontSize: 12, lineHeight: 1.6 }}>
                      {c.summary}
                    </Text>
                  </div>
                </Col>
              ))}
          </Row>
        </Card>
      )}

      {/* 兴趣明细:整行全宽,不再与检索框并排 */}
      <Card size="small" title={`兴趣明细(${items.length})`}>
        {items.length === 0 ? (
          <Empty description="暂无兴趣" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Row gutter={[10, 10]}>
            {items.map((item) => (
              <Col xs={24} sm={12} xl={8} key={item.id}>
                <div
                  style={{
                    display: "flex",
                    gap: 10,
                    padding: "10px 12px",
                    borderRadius: 12,
                    border: "1px solid #f0f0f0",
                    background: "#fff",
                    height: "100%",
                  }}
                >
                  <div
                    style={{
                      width: 4,
                      borderRadius: 2,
                      background: CATEGORY_COLORS[item.category] ?? "#8c8c8c",
                      opacity: item.status === "cooled" ? 0.4 : 1,
                      flexShrink: 0,
                    }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        flexWrap: "wrap",
                      }}
                    >
                      <Text strong style={{ fontSize: 13 }} ellipsis={{ tooltip: item.name }}>
                        {item.name}
                      </Text>
                      {statusTag(item.status)}
                    </div>
                    <div style={{ fontSize: 12, color: "#8c8c8c", marginTop: 2 }}>
                      {item.category} · {rangeText(item)} · 提及 {item.mention_count} 次
                    </div>
                    {(entitiesByInterest[item.key] ?? []).length > 0 && (
                      <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {(entitiesByInterest[item.key] ?? []).slice(0, 5).map((ent) => (
                          <Tag
                            key={ent}
                            bordered={false}
                            style={{
                              marginInlineEnd: 0,
                              fontSize: 11,
                              lineHeight: "16px",
                              color: "#8c8c8c",
                              background: "#fafafa",
                            }}
                          >
                            {ent}
                          </Tag>
                        ))}
                      </div>
                    )}
                  </div>
                  <Tooltip title="删除">
                    <Button
                      size="small"
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => {
                        void handleDelete(item);
                      }}
                    />
                  </Tooltip>
                </div>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {/* 节点详情:连接到的关注实体 + 出现的原句 */}
      <Modal
        open={!!detail}
        title={
          detail && (
            <Space wrap size={6}>
              <span>{detail.name}</span>
              <Tag bordered={false} style={{ background: "#f5f2ff", color: "#7C5CFC" }}>
                {detail.type || "entity"}
              </Tag>
              {detail.category && <Tag bordered={false}>{detail.category}</Tag>}
              {detail.followed ? (
                <Tag bordered={false} color="success">
                  关注中
                </Tag>
              ) : (
                <Tag bordered={false} style={{ color: "#8c8c8c" }}>
                  关联实体
                </Tag>
              )}
            </Space>
          )
        }
        onCancel={() => setDetail(null)}
        footer={
          <Button type="primary" onClick={() => setDetail(null)}>
            关闭
          </Button>
        }
        width="min(560px, 92vw)"
      >
        {detailLoading ? (
          <div style={{ padding: "24px 0", textAlign: "center" }}>
            <Spin />
          </div>
        ) : (
          detail && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {detail.followed && (
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    关注区间 / 提及
                  </Text>
                  <div style={{ fontSize: 13 }}>
                    {detail.since || "?"} ~ {detail.until || "至今"} · 提及{" "}
                    {detail.mention_count ?? 0} 次
                    {detail.status === "cooled" ? " · 已冷却" : ""}
                  </div>
                </div>
              )}
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  连接到的实体
                </Text>
                {detail.links.length === 0 ? (
                  <div style={{ fontSize: 13, color: "#8c8c8c" }}>暂无(孤立实体)</div>
                ) : (
                  <Space direction="vertical" size={4} style={{ width: "100%" }}>
                    {detail.links.map((l) => (
                      <div key={`${l.entity_key}-${l.relation}`} style={{ fontSize: 13 }}>
                        <Tag
                          bordered={false}
                          style={{ background: "#fafafa", color: "#8c8c8c", marginInlineEnd: 6 }}
                        >
                          {l.relation}
                        </Tag>
                        {l.display}
                        <Tag
                          bordered={false}
                          color={l.followed ? "success" : undefined}
                          style={{
                            marginInlineStart: 6,
                            ...(l.followed ? {} : { background: "#fafafa", color: "#8c8c8c" }),
                          }}
                        >
                          {l.followed ? "关注实体" : "关联实体"}
                        </Tag>
                      </div>
                    ))}
                  </Space>
                )}
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  出现在这些原话里
                </Text>
                {detail.evidence.length === 0 ? (
                  <div style={{ fontSize: 13, color: "#8c8c8c" }}>没有找到包含它的原句</div>
                ) : (
                  <Space direction="vertical" size={6} style={{ width: "100%" }}>
                    {detail.evidence.map((e, i) => (
                      <div
                        key={i}
                        style={{
                          fontSize: 13,
                          background: "#fafafa",
                          borderRadius: 8,
                          padding: "6px 10px",
                        }}
                      >
                        <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                          “{e.text}”
                        </div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {e.at ? e.at.slice(0, 10) : ""}
                          {e.from_entity ? ` · 来自「${e.from_entity}」` : ""}
                        </Text>
                      </div>
                    ))}
                  </Space>
                )}
              </div>
            </div>
          )
        )}
      </Modal>
    </div>
  );
}

export default InterestPage;
