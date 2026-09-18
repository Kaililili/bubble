import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { KeyOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import {
  MemoryItem,
  UserProfile,
  deleteMemory,
  deleteProfile,
  listMemories,
  listProfiles,
  revealMemory,
  upsertCredential,
  upsertProfile,
} from "../api/memory";

const { Text } = Typography;

const TYPE_LABEL: Record<string, { text: string; color: string }> = {
  credential: { text: "凭证", color: "red" },
  fact: { text: "事实", color: "blue" },
  event: { text: "事件", color: "green" },
  todo: { text: "待办", color: "orange" },
};

function MemoryPage() {
  const [profiles, setProfiles] = useState<UserProfile[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [keyword, setKeyword] = useState("");
  const [revealed, setRevealed] = useState<{ id: string; content: string } | null>(null);
  const [profileForm] = Form.useForm();
  const [credentialForm] = Form.useForm();

  const fetchAll = async (type?: string, kw?: string) => {
    setLoading(true);
    try {
      const [p, m] = await Promise.all([
        listProfiles(),
        listMemories({ type: type ?? typeFilter, keyword: (kw ?? keyword) || undefined }),
      ]);
      setProfiles(p);
      setMemories(m);
    } catch {
      message.error("加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter]);

  const handleAddProfile = async () => {
    const values = await profileForm.validateFields();
    await upsertProfile(values);
    message.success("已添加");
    profileForm.resetFields();
    fetchAll();
  };

  const handleDeleteProfile = async (id: string) => {
    await deleteProfile(id);
    fetchAll();
  };

  const handleSaveCredential = async () => {
    const values = await credentialForm.validateFields();
    try {
      const res = await upsertCredential(values);
      message.success(res.message);
      credentialForm.resetFields();
      fetchAll();
    } catch (e) {
      message.error((e as Error).message || "保存失败");
    }
  };

  const handleEditCredential = (item: MemoryItem) => {
    // 后端已返回归一化归属 key,直接回填表单
    credentialForm.setFieldsValue({ key: item.credential_key ?? "", value: "" });
  };

  const handleDeleteMemory = async (id: string) => {
    await deleteMemory(id);
    fetchAll();
  };

  const handleReveal = (id: string) => {
    Modal.confirm({
      title: "查看敏感凭证",
      content: "该操作将解密并显示凭证真实值，确认查看？",
      okText: "确认查看",
      cancelText: "取消",
      onOk: async () => {
        const res = await revealMemory(id);
        setRevealed({ id, content: res.content });
      },
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card title="用户背景" extra={<Text type="secondary">每轮对话会自动带上这些信息</Text>}>
        <Form form={profileForm} layout="inline" style={{ marginBottom: 16, rowGap: 8 }}>
          <Form.Item name="key" rules={[{ required: true, message: "请输入字段名" }]}>
            <Input placeholder="字段名(如 过敏)" style={{ width: 150 }} />
          </Form.Item>
          <Form.Item name="value" rules={[{ required: true, message: "请输入值" }]}>
            <Input placeholder="值(如 虾)" style={{ width: 180 }} />
          </Form.Item>
          <Form.Item name="importance" initialValue={0}>
            <InputNumber min={0} max={10} placeholder="重要性" style={{ width: 100 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddProfile}>
              添加
            </Button>
          </Form.Item>
        </Form>
        <List
          dataSource={profiles}
          locale={{ emptyText: <Empty description="暂无用户背景" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          renderItem={(item) => (
            <List.Item
              actions={[
                <Popconfirm key="del" title="删除该背景?" onConfirm={() => handleDeleteProfile(item.id)}>
                  <Button size="small" danger>
                    删除
                  </Button>
                </Popconfirm>,
              ]}
            >
              <Space>
                <Text strong>{item.key}</Text>
                <Text>{item.value}</Text>
                {item.importance > 0 && <Tag color="purple">重要 {item.importance}</Tag>}
              </Space>
            </List.Item>
          )}
        />
      </Card>

      <Card
        title="记忆"
        extra={
          <Space wrap>
            <Select
              allowClear
              placeholder="类型"
              style={{ width: 110 }}
              value={typeFilter}
              onChange={setTypeFilter}
              options={Object.entries(TYPE_LABEL).map(([value, v]) => ({ value, label: v.text }))}
            />
            <Input
              placeholder="搜索"
              prefix={<SearchOutlined />}
              style={{ width: 180 }}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onPressEnter={() => fetchAll(typeFilter, keyword)}
            />
            <Button onClick={() => fetchAll(typeFilter, keyword)}>搜索</Button>
          </Space>
        }
      >
        <div
          style={{
            marginBottom: 16,
            padding: 12,
            borderRadius: 8,
            background: "#fff1f0",
            border: "1px solid #ffccc7",
          }}
        >
          <Space style={{ marginBottom: 8 }}>
            <KeyOutlined style={{ color: "#d4380d" }} />
            <Text strong>凭证管理</Text>
            <Text type="secondary">key 填应用/网站名(如 bubble)，不同叫法会归一到同一应用，保存后仅显示脱敏</Text>
          </Space>
          <Form form={credentialForm} layout="inline" style={{ rowGap: 8 }}>
            <Form.Item name="key" rules={[{ required: true, message: "请输入归属" }]}>
              <Input placeholder="应用/网站(如 bubble)" style={{ minWidth: 150 }} />
            </Form.Item>
            <Form.Item name="value" rules={[{ required: true, message: "请输入凭证值" }]}>
              <Input.Password placeholder="密码值(同应用保存会覆盖)" style={{ minWidth: 180 }} />
            </Form.Item>
            <Form.Item>
              <Button type="primary" icon={<PlusOutlined />} onClick={handleSaveCredential}>
                保存
              </Button>
            </Form.Item>
          </Form>
        </div>
        <List
          loading={loading}
          dataSource={memories}
          locale={{ emptyText: <Empty description="暂无记忆" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
          renderItem={(item) => {
            const meta = TYPE_LABEL[item.type] ?? { text: item.type, color: "default" };
            return (
              <List.Item
                actions={[
                  ...(item.type === "credential"
                    ? [
                        <Button key="edit" size="small" onClick={() => handleEditCredential(item)}>
                          编辑
                        </Button>,
                        <Button key="reveal" size="small" onClick={() => handleReveal(item.id)}>
                          查看
                        </Button>,
                      ]
                    : []),
                  <Popconfirm key="del" title="删除该记忆?" onConfirm={() => handleDeleteMemory(item.id)}>
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <Space>
                  <Tag color={meta.color}>{meta.text}</Tag>
                  {item.type === "credential" ? (
                    <>
                      <Text strong>{item.credential_key ?? "credential"}</Text>
                      <Text type="secondary">{item.credential_value ?? item.content}</Text>
                    </>
                  ) : (
                    <Text>{item.content}</Text>
                  )}
                </Space>
              </List.Item>
            );
          }}
        />
      </Card>

      <Modal
        open={!!revealed}
        title="凭证内容(请勿泄露)"
        onCancel={() => setRevealed(null)}
        footer={
          <Button type="primary" onClick={() => setRevealed(null)}>
            关闭
          </Button>
        }
      >
        <Text>{revealed?.content}</Text>
      </Modal>
    </div>
  );
}

export default MemoryPage;
