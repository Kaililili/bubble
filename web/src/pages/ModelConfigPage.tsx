import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useModelStore } from "../stores/modelStore";
import { ModelConfig, ModelPayload, testModel } from "../api/models";

const { Text } = Typography;

const PROVIDERS = [
  { label: "DeepSeek", value: "deepseek", base: "https://api.deepseek.com" },
  { label: "OpenAI", value: "openai", base: "https://api.openai.com/v1" },
  { label: "智谱", value: "zhipu", base: "https://open.bigmodel.cn/api/paas/v4" },
  { label: "通义千问", value: "qwen", base: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { label: "豆包", value: "doubao", base: "https://ark.cn-beijing.volces.com/api/v3" },
  { label: "Tavily(联网搜索)", value: "tavily", base: "https://api.tavily.com" },
  { label: "硅基流动", value: "siliconflow", base: "https://api.siliconflow.cn/v1" },
];

const TYPE_LABEL: Record<string, string> = {
  chat: "对话",
  embedding: "Embedding",
  rerank: "Rerank",
  websearch: "联网搜索",
};

const TYPE_OPTIONS = [
  { label: "对话模型", value: "chat" },
  { label: "Embedding 模型", value: "embedding" },
  { label: "Rerank 模型", value: "rerank" },
  { label: "联网搜索(Tavily)", value: "websearch" },
];

function ModelConfigPage() {
  const { models, loading, fetchModels, addModel, editModel, removeModel } = useModelStore();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ModelConfig | null>(null);
  const [testing, setTesting] = useState(false);
  const [form] = Form.useForm();
  const modelType = Form.useWatch("model_type", form);

  useEffect(() => {
    fetchModels();
  }, []);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      model_type: "chat",
      provider: "deepseek",
      supports_function_call: true,
      is_default: false,
    });
    setModalOpen(true);
  };

  const openEdit = (item: ModelConfig) => {
    setEditing(item);
    form.resetFields();
    form.setFieldsValue({ ...item, api_key: "" });
    setModalOpen(true);
  };

  const handleProviderChange = (value: string) => {
    const provider = PROVIDERS.find((p) => p.value === value);
    if (provider) form.setFieldValue("base_url", provider.base);
  };

  const handleTest = async () => {
    const values = await form.validateFields();
    setTesting(true);
    try {
      const res = await testModel(values as ModelPayload);
      if (res.success) message.success(res.message);
      else message.error(res.message);
    } catch {
      message.error("测试请求失败");
    } finally {
      setTesting(false);
    }
  };

  const handleOk = async () => {
    const values = await form.validateFields();
    const payload: ModelPayload = { ...values };
    if (!payload.base_url) {
      payload.base_url = PROVIDERS.find((p) => p.value === payload.provider)?.base;
    }
    if (!payload.api_key) delete payload.api_key;
    if (payload.model_type !== "chat") delete payload.supports_function_call;

    if (editing) {
      await editModel(editing.id, payload);
      message.success("模型配置已更新");
    } else {
      await addModel(payload);
      message.success("模型配置已添加");
    }
    setModalOpen(false);
  };

  const columns: ColumnsType<ModelConfig> = [
    {
      title: "类型",
      dataIndex: "model_type",
      width: 100,
      render: (v: string) => <Tag color="purple">{TYPE_LABEL[v] ?? v}</Tag>,
    },
    { title: "提供商", dataIndex: "provider", width: 110 },
    { title: "模型名", dataIndex: "model_name", width: 170 },
    {
      title: "Base URL",
      dataIndex: "base_url",
      ellipsis: true,
      render: (v: string) => <Text type="secondary">{v}</Text>,
    },
    {
      title: "函数调用",
      dataIndex: "supports_function_call",
      width: 90,
      render: (v: boolean | undefined) =>
        v === false ? <Tag color="orange">ReAct</Tag> : <Tag color="green">原生</Tag>,
    },
    {
      title: "默认",
      dataIndex: "is_default",
      width: 80,
      render: (v: boolean) => (v ? <Tag color="green">默认</Tag> : <Text type="secondary">-</Text>),
    },
    {
      title: "操作",
      width: 150,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="删除该模型配置?" onConfirm={() => removeModel(record.id)}>
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="模型配置"
      extra={
        <Button icon={<ReloadOutlined />} onClick={fetchModels}>
          刷新
        </Button>
      }
    >
      <Button type="primary" icon={<PlusOutlined />} onClick={openCreate} style={{ marginBottom: 16 }}>
        添加模型
      </Button>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={models}
        columns={columns}
        pagination={false}
        scroll={{ x: 720 }}
      />

      <Modal
        title={editing ? "编辑模型配置" : "添加模型配置"}
        open={modalOpen}
        onOk={handleOk}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={"min(560px, 92vw)"}
        footer={
          <Space style={{ display: "flex", justifyContent: "space-between" }}>
            <Button loading={testing} onClick={handleTest}>
              测试连接
            </Button>
            <Space>
              <Button onClick={() => setModalOpen(false)}>取消</Button>
              <Button type="primary" onClick={handleOk}>
                保存
              </Button>
            </Space>
          </Space>
        }
      >
        <Form form={form} layout="vertical" initialValues={{ model_type: "chat", provider: "deepseek" }}>
          <Form.Item name="model_type" label="模型类型" rules={[{ required: true }]}>
            <Select options={TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="provider" label="提供商" rules={[{ required: true }]}>
            <Select options={PROVIDERS.map((p) => ({ label: p.label, value: p.value }))} onChange={handleProviderChange} />
          </Form.Item>
          <Form.Item name="model_name" label="模型名" rules={[{ required: true }]}>
            <Input placeholder="如 deepseek-chat" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={editing ? [] : [{ required: true, message: "请输入 API Key" }]}>
            <Input.Password placeholder={editing ? "留空则保持不变" : "会加密存储,不会明文保存"} />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL">
            <Input placeholder="默认使用官方地址" />
          </Form.Item>
          {modelType === "chat" && (
            <Form.Item
              name="supports_function_call"
              label="支持函数调用(Function Calling)"
              valuePropName="checked"
              tooltip="开启:模型原生返回工具调用;关闭:走 ReAct 提示词降级路径"
            >
              <Switch />
            </Form.Item>
          )}
          <Form.Item name="is_default" label="设为默认" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

export default ModelConfigPage;
