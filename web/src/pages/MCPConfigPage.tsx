import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Collapse,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from "antd";
import { ApiOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  MCPServer,
  createServer,
  deleteServer,
  listServers,
  testServer,
  updateServer,
} from "../api/mcp";

const { Text } = Typography;

const STATUS_META: Record<string, { text: string; color: string }> = {
  ok: { text: "正常", color: "green" },
  error: { text: "异常", color: "red" },
  unknown: { text: "未测试", color: "default" },
};

// 与后端 loader 的默认策略一致:工具名含查询语义=查询类
const QUERY_HINTS = ["find", "query", "search", "detail", "get", "list", "price", "info"];
const isQueryTool = (name: string) =>
  QUERY_HINTS.some((h) => (name || "").toLowerCase().includes(h));

const annotationsOf = (s: MCPServer, name: string) =>
  (s.tools_cache ?? []).find((t) => t.name === name)?.annotations ?? {};

/** 默认是否暴露:只读声明→暴露;破坏性/非只读声明→不暴露;无声明回退查询词规则 */
const defaultExposed = (s: MCPServer, name: string): boolean => {
  const a = annotationsOf(s, name);
  if (a.destructiveHint === true || a.readOnlyHint === false) return false;
  if (a.readOnlyHint === true) return true;
  return isQueryTool(name);
};

/** 默认是否需确认:破坏性/非只读→需确认;只读声明→免确认;无声明回退启发式 */
const defaultSensitive = (s: MCPServer, name: string): boolean => {
  const a = annotationsOf(s, name);
  if (a.destructiveHint === true || a.readOnlyHint === false) return true;
  if (a.readOnlyHint === true) return false;
  return !isQueryTool(name);
};

/** 当前生效的"暴露给 AI"集合:显式配置优先,否则按默认查询白名单推导 */
const effectiveAllowed = (s: MCPServer): string[] =>
  s.allowed_tools ?? (s.tools_cache ?? []).filter((t) => defaultExposed(s, t.name)).map((t) => t.name);

/** 当前生效的"需确认"集合 */
const effectiveSensitive = (s: MCPServer): string[] =>
  s.sensitive_tools ?? (s.tools_cache ?? []).filter((t) => defaultSensitive(s, t.name)).map((t) => t.name);

function MCPConfigPage() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MCPServer | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [form] = Form.useForm();

  const fetchAll = async () => {
    setLoading(true);
    try {
      setServers(await listServers());
    } catch {
      message.error("加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
  }, []);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (s: MCPServer) => {
    setEditing(s);
    form.setFieldsValue({ name: s.name, url: s.url, token: "" });
    setModalOpen(true);
  };

  const handleSubmit = async () => {
    const values = await form.validateFields();
    try {
      if (editing) {
        await updateServer(editing.id, values);
        message.success("已更新");
      } else {
        await createServer(values);
        message.success("已添加");
      }
      setModalOpen(false);
      fetchAll();
    } catch (e) {
      message.error((e as Error).message || "保存失败");
    }
  };

  const handleTest = async (s: MCPServer) => {
    setTesting(s.id);
    try {
      const res = await testServer(s.id);
      message.success(`连接成功,发现 ${res.count} 个工具`);
    } catch (e) {
      message.error((e as Error).message || "测试失败");
    } finally {
      setTesting(null);
      fetchAll();
    }
  };

  const handleToggle = async (s: MCPServer, v: boolean) => {
    try {
      await updateServer(s.id, { enabled: v });
      message.success(v ? `已启用 ${s.name}` : `已停用 ${s.name}`);
      fetchAll();
    } catch (e) {
      message.error((e as Error).message || "操作失败");
    }
  };

  const toggleExposed = async (s: MCPServer, name: string, v: boolean) => {
    const cur = effectiveAllowed(s);
    const next = v
      ? Array.from(new Set([...cur, name]))
      : cur.filter((x) => x !== name);
    try {
      await updateServer(s.id, { allowed_tools: next });
      message.success(v ? `已允许 AI 使用 ${name}` : `已禁止 AI 使用 ${name}`);
      fetchAll();
    } catch (e) {
      message.error((e as Error).message || "更新失败");
    }
  };

  const toggleSensitive = async (s: MCPServer, name: string, v: boolean) => {
    const cur = effectiveSensitive(s);
    const next = v
      ? Array.from(new Set([...cur, name]))
      : cur.filter((x) => x !== name);
    try {
      await updateServer(s.id, { sensitive_tools: next });
      message.success(v ? `${name} 已设为需确认` : `${name} 已设为免确认`);
      fetchAll();
    } catch (e) {
      message.error((e as Error).message || "更新失败");
    }
  };

  return (
    <Card
      title="MCP 服务"
      loading={loading}
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新增
        </Button>
      }
    >
      <Typography.Paragraph type="secondary">
        配置外部 MCP 服务(如瑞幸官方 MCP)。Token 加密存储;查询类工具默认对 AI 可见,
        下单/支付类工具默认隐藏。
      </Typography.Paragraph>
      <List
        dataSource={servers}
        locale={{ emptyText: "暂无 MCP 配置,点击右上角「新增」添加" }}
        renderItem={(s) => {
          const st = STATUS_META[s.status] ?? STATUS_META.unknown;
          return (
            <List.Item
              style={{ alignItems: "flex-start" }}
              actions={[
                <Switch key="sw" checked={s.enabled} onChange={(v) => handleToggle(s, v)} />,
                <Button
                  key="test"
                  size="small"
                  icon={<ReloadOutlined />}
                  loading={testing === s.id}
                  onClick={() => handleTest(s)}
                >
                  测试连接
                </Button>,
                <Button key="edit" size="small" onClick={() => openEdit(s)}>
                  编辑
                </Button>,
                <Popconfirm key="del" title="删除该 MCP 配置?" onConfirm={() => deleteServer(s.id).then(fetchAll)}>
                  <Button size="small" danger>
                    删除
                  </Button>
                </Popconfirm>,
              ]}
            >
              <div style={{ width: "100%", minWidth: 0 }}>
                <Space wrap>
                  <ApiOutlined style={{ color: "#1677ff" }} />
                  <Text strong>{s.name}</Text>
                  <Tag color={st.color}>{st.text}</Tag>
                  {!s.enabled && <Tag>已停用</Tag>}
                  <Text type="secondary" style={{ fontSize: 12, wordBreak: "break-all" }}>
                    {s.url}
                  </Text>
                </Space>
                <div style={{ marginTop: 4 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    Token: {s.token_masked || "未设置"} · 工具数: {s.tools_cache?.length ?? 0}
                  </Text>
                </div>
                {s.last_error && (
                  <div style={{ marginTop: 4 }}>
                    <Text type="danger" style={{ fontSize: 12 }}>
                      {s.last_error}
                    </Text>
                  </div>
                )}
                {s.tools_cache && s.tools_cache.length > 0 && (
                  <Collapse
                    ghost
                    size="small"
                    style={{ marginTop: 4 }}
                    items={[
                      {
                        key: "tools",
                        label: `工具清单(${s.tools_cache.length})`,
                        children: (
                          <List
                            size="small"
                            dataSource={s.tools_cache}
                            renderItem={(t) => (
                              <List.Item style={{ padding: "4px 0" }}>
                                <div style={{ width: "100%" }}>
                                  <Text code style={{ wordBreak: "break-all" }}>{t.name}</Text>
                                  {(() => {
                                    const a = annotationsOf(s, t.name);
                                    if (a.readOnlyHint === true)
                                      return <Tag color="green" style={{ marginLeft: 6 }}>只读</Tag>;
                                    if (a.destructiveHint === true)
                                      return <Tag color="red" style={{ marginLeft: 6 }}>破坏性</Tag>;
                                    if (a.readOnlyHint === false)
                                      return <Tag color="orange" style={{ marginLeft: 6 }}>可写</Tag>;
                                    return <Tag style={{ marginLeft: 6 }}>未声明</Tag>;
                                  })()}
                                  <Text type="secondary" style={{ fontSize: 12, display: "block" }}>
                                    {t.description || "无描述"}
                                  </Text>
                                  {(() => {
                                    const exposed = effectiveAllowed(s).includes(t.name);
                                    const sensitive = effectiveSensitive(s).includes(t.name);
                                    return (
                                      <Space wrap size={12} style={{ marginTop: 4 }}>
                                        <Space size={4}>
                                          <Switch
                                            size="small"
                                            checked={exposed}
                                            onChange={(v) => toggleExposed(s, t.name, v)}
                                          />
                                          <Text style={{ fontSize: 12 }}>对 AI 可用</Text>
                                        </Space>
                                        <Space size={4}>
                                          <Switch
                                            size="small"
                                            checked={sensitive}
                                            disabled={!exposed}
                                            onChange={(v) => toggleSensitive(s, t.name, v)}
                                          />
                                          <Text style={{ fontSize: 12, color: sensitive ? "#d46b08" : undefined }}>
                                            需确认
                                          </Text>
                                        </Space>
                                      </Space>
                                    );
                                  })()}
                                </div>
                              </List.Item>
                            )}
                          />
                        ),
                      },
                    ]}
                  />
                )}
              </div>
            </List.Item>
          );
        }}
      />

      <Modal
        open={modalOpen}
        title={editing ? "编辑 MCP 配置" : "新增 MCP 配置"}
        onCancel={() => setModalOpen(false)}
        onOk={handleSubmit}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="服务名" rules={[{ required: true, message: "请输入服务名" }]}>
            <Input placeholder="如 luckin" />
          </Form.Item>
          <Form.Item name="url" label="MCP 地址" rules={[{ required: true, message: "请输入 MCP 地址" }]}>
            <Input placeholder="https://gwmcp.lkcoffee.com/order/user/mcp" />
          </Form.Item>
          <Form.Item
            name="token"
            label="Bearer Token"
            extra={editing ? "留空表示不修改原 token" : undefined}
          >
            <Input.Password placeholder="登录瑞幸后复制的 token" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

export default MCPConfigPage;
