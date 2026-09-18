import { useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Checkbox,
  Grid,
  Input,
  Space,
  Spin,
  Tag,
  Typography,
  message,
  notification,
} from "antd";
import { useNavigate } from "react-router-dom";
import { ArrowUpOutlined, CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { useChatStore, ToolEvent } from "../stores/chatStore";
import MarkdownMessage from "../components/MarkdownMessage";
import LuckinOrderModal, { LuckinOrderTarget } from "../components/LuckinOrderModal";
import { approveTool, rejectTool } from "../api/mcp";
import { listRecentInterests } from "../api/interest";

const { TextArea } = Input;
const { Text } = Typography;
const CHAT_MAX_WIDTH = 820;

interface CompareChoice {
  dept_id?: number;
  product_id?: number;
  shop?: string;
  distance_km?: number;
  price?: number;
}

/** 从 luckin_compare 工具结果解析出门店比价选择卡片 */
function LuckinCompareChoices({
  toolEvents,
  onOrder,
}: {
  toolEvents: ToolEvent[];
  onOrder: (t: LuckinOrderTarget) => void;
}) {
  const choices = useMemo<CompareChoice[]>(() => {
    const ev = toolEvents.find((t) => t.tool === "luckin_compare" && t.status === "success");
    if (!ev?.text) return [];
    try {
      const arr = JSON.parse(ev.text);
      if (!Array.isArray(arr)) return [];
      return arr.filter(
        (x): x is CompareChoice =>
          !!x && typeof x.dept_id === "number" && typeof x.product_id === "number" && !x.error
      );
    } catch {
      return [];
    }
  }, [toolEvents]);

  if (choices.length === 0) return null;
  return (
    <div
      style={{
        marginBottom: 8,
        padding: "8px 12px",
        borderRadius: 8,
        background: "#fafafa",
        border: "1px solid #f0f0f0",
      }}
    >
      <Space style={{ marginBottom: 6 }}>
        <Text strong style={{ fontSize: 13 }}>选择门店下单</Text>
        <Tag color="red" style={{ marginInlineEnd: 0 }}>瑞幸</Tag>
      </Space>
      {choices.map((c) => (
        <div
          key={c.dept_id}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
            flexWrap: "wrap",
            padding: "4px 0",
          }}
        >
          <div style={{ minWidth: 0 }}>
            <Text strong style={{ fontSize: 13 }}>{c.shop}</Text>
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
              {c.distance_km != null ? `${c.distance_km.toFixed(1)} km` : ""}
              {c.price != null ? ` · ¥${c.price.toFixed(1)}` : ""}
            </Text>
          </div>
          <Button
            size="small"
            type="primary"
            style={{ flexShrink: 0 }}
            onClick={() => onOrder({ dept_id: c.dept_id!, product_id: c.product_id! })}
          >
            选这家下单
          </Button>
        </div>
      ))}
    </div>
  );
}

interface ComposerProps {
  draft: string;
  focused: boolean;
  streaming: boolean;
  onDraftChange: (value: string) => void;
  onFocusChange: (value: boolean) => void;
  onSend: () => void;
}

/** ChatGPT 风格圆角输入框:圆角容器 + 内嵌无边框输入区 + 圆形发送按钮 */
function Composer({ draft, focused, streaming, onDraftChange, onFocusChange, onSend }: ComposerProps) {
  const canSend = draft.trim().length > 0;
  return (
    <>
      <div
        style={{
          width: "100%",
          maxWidth: 768,
          position: "relative",
          background: "#fff",
          border: `1px solid ${focused ? "#7C5CFC" : "#e3e3e3"}`,
          borderRadius: 24,
          boxShadow: focused
            ? "0 0 0 3px rgba(124,92,252,0.15), 0 4px 12px rgba(0,0,0,0.06)"
            : "0 2px 8px rgba(0,0,0,0.05)",
          transition: "border-color 0.2s, box-shadow 0.2s",
          padding: "10px 12px",
        }}
      >
        <TextArea
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onFocus={() => onFocusChange(true)}
          onBlur={() => onFocusChange(false)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          placeholder="给 Bubble 发消息..."
          autoSize={{ minRows: 1, maxRows: 8 }}
          disabled={streaming}
          variant="borderless"
          style={{
            resize: "none",
            background: "transparent",
            padding: "8px 44px 8px 8px",
            fontSize: 15,
            lineHeight: 1.6,
          }}
        />
        <Button
          type="primary"
          shape="circle"
          icon={<ArrowUpOutlined />}
          onClick={onSend}
          loading={streaming}
          disabled={!canSend}
          style={{
            position: "absolute",
            right: 10,
            bottom: 10,
            width: 34,
            height: 34,
            minWidth: 34,
            background: canSend && !streaming ? "#7C5CFC" : "#d9d9d9",
            border: "none",
          }}
        />
      </div>
      <div style={{ marginTop: 8, fontSize: 12, color: "#999", textAlign: "center" }}>
        Bubble 可能会犯错,请核实重要信息
      </div>
    </>
  );
}

/** 敏感工具待确认卡片:LLM 发起 → 用户确认 → 后端才真正执行 */
function ApprovalCard({ event }: { event: ToolEvent }) {
  const [status, setStatus] = useState<string>(event.status);
  const [result, setResult] = useState<string | null>(event.text ?? null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [remember, setRemember] = useState(false);

  const act = async (kind: "approve" | "reject") => {
    if (!event.approval_id) return;
    setLoading(true);
    try {
      if (kind === "approve") {
        const r = await approveTool(event.approval_id, remember);
        setStatus(r.status);
        setResult(r.result || r.error || "");
        if (r.status === "executed")
          message.success(remember ? "已执行,该工具以后不再询问" : "已确认执行");
        else message.error(r.error || "执行失败");
      } else {
        await rejectTool(event.approval_id);
        setStatus("rejected");
        message.info("已拒绝该操作");
      }
    } catch (e) {
      message.error((e as Error).message || "操作失败");
    } finally {
      setLoading(false);
    }
  };

  const pending = status === "pending";
  const argsText = JSON.stringify(event.args ?? {}, null, 2);
  const isLong = argsText.length > 120;

  return (
    <div
      style={{
        marginBottom: 8,
        padding: "8px 12px",
        borderRadius: 8,
        background: pending ? "#fffbe6" : "#fafafa",
        border: `1px solid ${pending ? "#ffe58f" : "#f0f0f0"}`,
        fontSize: 13,
        maxWidth: "100%",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {status === "executed" ? (
          <CheckCircleOutlined style={{ color: "#52c41a" }} />
        ) : status === "rejected" || status === "failed" ? (
          <CloseCircleOutlined style={{ color: "#ff4d4f" }} />
        ) : (
          <Spin size="small" />
        )}
        <Text strong style={{ flexShrink: 0 }}>需确认操作</Text>
        <Text code style={{ minWidth: 0, wordBreak: "break-all" }}>{event.tool}</Text>
        <Tag color={pending ? "orange" : status === "executed" ? "green" : "default"} style={{ flexShrink: 0 }}>
          {pending ? "等待确认" : status === "executed" ? "已执行" : status === "rejected" ? "已拒绝" : status}
        </Tag>
      </div>

      <div style={{ marginTop: 6 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>调用参数:</Text>
        <Text
          type="secondary"
          style={{ display: "block", whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 12 }}
        >
          {isLong && !expanded ? `${argsText.slice(0, 120)}...` : argsText}
        </Text>
        {isLong && (
          <Button
            type="link"
            size="small"
            style={{ padding: 0, height: "auto", fontSize: 12 }}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "收起参数" : "展开参数"}
          </Button>
        )}
      </div>

      {pending ? (
        <>
          <Checkbox
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            style={{ marginTop: 8, fontSize: 12, display: "block" }}
          >
            <Text style={{ fontSize: 12 }}>以后都允许该工具(不再询问)</Text>
          </Checkbox>
          <Space wrap style={{ marginTop: 8 }}>
            <Button size="small" type="primary" loading={loading} onClick={() => act("approve")}>
              确认执行
            </Button>
            <Button size="small" danger disabled={loading} onClick={() => act("reject")}>
              拒绝
            </Button>
          </Space>
        </>
      ) : (
        result && (
          <div style={{ marginTop: 6 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>执行结果:</Text>
            <Text
              style={{
                display: "block",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontSize: 12,
                maxHeight: 200,
                overflowY: "auto",
              }}
            >
              {result}
            </Text>
          </div>
        )
      )}
    </div>
  );
}

/** 工具调用卡片 */
function ToolEventCard({ event }: { event: ToolEvent }) {
  if (event.type === "approval") return <ApprovalCard event={event} />;

  const running = event.status === "running";
  const [expanded, setExpanded] = useState(false);
  const text = event.full_text || event.text || "";
  const isLong = text.length > 160;
  const showText = !running && text.length > 0;

  return (
    <div
      style={{
        marginBottom: 8,
        padding: "8px 12px",
        borderRadius: 8,
        background: "#fafafa",
        border: "1px solid #f0f0f0",
        fontSize: 13,
        maxWidth: "100%",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {running ? (
          <Spin size="small" />
        ) : event.status === "success" ? (
          <CheckCircleOutlined style={{ color: "#52c41a" }} />
        ) : (
          <CloseCircleOutlined style={{ color: "#ff4d4f" }} />
        )}
        <Text strong style={{ flexShrink: 0 }}>{event.tool}</Text>
        {event.query && (
          <Text
            type="secondary"
            ellipsis
            title={event.query}
            style={{ flex: "1 1 auto", minWidth: 0, maxWidth: "100%" }}
          >
            "{event.query}"
          </Text>
        )}
        {!running && event.latency_ms != null && (
          <Text type="secondary" style={{ marginLeft: "auto", flexShrink: 0 }}>
            {event.latency_ms}ms
          </Text>
        )}
      </div>

      {showText && (
        <div style={{ marginTop: 6 }}>
          {isLong && !expanded ? (
            <Button
              type="link"
              size="small"
              style={{ padding: 0, height: "auto", fontSize: 13 }}
              onClick={() => setExpanded(true)}
            >
              展开完整结果
            </Button>
          ) : (
            <>
              <Text
                type="secondary"
                style={{
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  display: "block",
                }}
              >
                {text}
              </Text>
              {isLong && (
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, height: "auto", fontSize: 13 }}
                  onClick={() => setExpanded(false)}
                >
                  收起
                </Button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ChatPage() {
  const screens = Grid.useBreakpoint();
  const isMobile = !screens.md;
  const bubbleMaxWidth = isMobile ? "85%" : "72%";

  const activeId = useChatStore((s) => s.activeId);
  const messages = useChatStore((s) => s.messages);
  const streaming = useChatStore((s) => s.streaming);
  const newConversation = useChatStore((s) => s.newConversation);
  const send = useChatStore((s) => s.send);

  const [draft, setDraft] = useState("");
  const [focused, setFocused] = useState(false);
  const [orderTarget, setOrderTarget] = useState<LuckinOrderTarget | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const handleSend = async () => {
    const content = draft.trim();
    if (!content || streaming) return;
    setDraft("");
    // 兴趣抽取是回复结束后的后台任务:记下时间起点,回复结束后轮询"已加入兴趣"
    const since = new Date(Date.now() - 30_000).toISOString();
    const looksLikeQuestion = /[?？]|吗\s*$|什么|哪些|是不是/.test(content);
    if (!activeId) {
      await newConversation();
    }
    await send(content);
    if (!looksLikeQuestion) {
      void pollNewInterests(since);
    }
  };

  /** 后台抽取通常 10~40s 完成:每 8s 轮询一次,发现新兴趣就提示,最多 8 次 */
  const pollNewInterests = (since: string) => {
    let attempts = 0;
    const timer = window.setInterval(async () => {
      attempts += 1;
      try {
        const items = await listRecentInterests(since, 10);
        const fresh = items.filter((i) => i.is_new);
        if (fresh.length > 0) {
          window.clearInterval(timer);
          notification.success({
            message: "已加入兴趣档案",
            description: fresh.map((i) => i.name).join("、"),
            duration: 8,
            placement: "bottomRight",
            btn: (
              <Button
                size="small"
                type="link"
                onClick={() => {
                  notification.destroy();
                  navigate("/interest");
                }}
              >
                去看看
              </Button>
            ),
          });
          return;
        }
      } catch {
        // 网络抖动忽略,继续轮询
      }
      if (attempts >= 8) window.clearInterval(timer);
    }, 8000);
  };

  const composerProps = {
    draft,
    focused,
    streaming,
    onDraftChange: setDraft,
    onFocusChange: setFocused,
    onSend: handleSend,
  };

  const isEmpty = messages.length === 0;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}>
      {isEmpty ? (
        /* 空会话:欢迎语 + 输入框整体垂直水平居中(仿 ChatGPT 新会话) */
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "center",
            minHeight: 0,
            padding: "0 8px 6vh",
          }}
        >
          <div style={{ fontSize: 30, fontWeight: 700, color: "#7C5CFC", marginBottom: 6 }}>
            Bubble 🫧
          </div>
          <div style={{ fontSize: 14, color: "#999", marginBottom: 32 }}>
            {activeId ? "你的个人 AI 生活助手" : "从左侧新建一个对话开始"}
          </div>
          <div style={{ width: "100%", maxWidth: 768, display: "flex", flexDirection: "column", alignItems: "center" }}>
            <Composer {...composerProps} />
          </div>
        </div>
      ) : (
        <>
          {/* 消息区 */}
          <div style={{ flex: 1, overflowY: "auto", padding: "8px 8px 8px 16px", minHeight: 0 }}>
            <div style={{ maxWidth: CHAT_MAX_WIDTH, margin: "0 auto", minHeight: "100%" }}>
              {messages.map((m) => {
                const isUser = m.role === "user";
                return (
                  <div
                    key={m.id}
                    style={{ marginBottom: 8 }}
                  >
                    {!isUser && m.toolEvents && m.toolEvents.length > 0 && (
                      <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 4 }}>
                        <div style={{ maxWidth: bubbleMaxWidth, width: "100%" }}>
                          {m.toolEvents.map((t, i) => (
                            <ToolEventCard key={i} event={t} />
                          ))}
                        </div>
                      </div>
                    )}
                    {!isUser && m.toolEvents && (
                      <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 4 }}>
                        <div style={{ maxWidth: bubbleMaxWidth, width: "100%" }}>
                          <LuckinCompareChoices toolEvents={m.toolEvents} onOrder={setOrderTarget} />
                        </div>
                      </div>
                    )}
                    <div style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start" }}>
                      <div
                        style={{
                          maxWidth: bubbleMaxWidth,
                          minWidth: 0,
                          padding: "10px 14px",
                          borderRadius: 12,
                          background: isUser ? "#7C5CFC" : "#f5f5f5",
                          color: isUser ? "#fff" : "inherit",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        {isUser ? (
                          m.content
                        ) : m.content ? (
                          <MarkdownMessage content={m.content} />
                        ) : streaming ? (
                          "正在思考..."
                        ) : (
                          ""
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
              <div ref={bottomRef} />
            </div>
          </div>

          <LuckinOrderModal target={orderTarget} onClose={() => setOrderTarget(null)} />

          {/* 有消息时:输入框固定在底部 */}
          <div style={{ paddingTop: 12, display: "flex", flexDirection: "column", alignItems: "center" }}>
            <Composer {...composerProps} />
          </div>
        </>
      )}
    </div>
  );
}

export default ChatPage;
