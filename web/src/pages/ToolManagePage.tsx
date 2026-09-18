import { useEffect } from "react";
import { Card, List, Space, Switch, Tag, Typography, message } from "antd";
import { useToolStore } from "../stores/toolStore";

function ToolManagePage() {
  const { tools, loading, fetchTools, toggle } = useToolStore();

  useEffect(() => {
    fetchTools();
  }, []);

  return (
    <Card title="工具管理" loading={loading}>
      <Typography.Paragraph type="secondary">
        AI 在对话中会自动判断是否调用这些工具。「联网搜索」需要先在模型配置里添加 Tavily 类型的配置。
      </Typography.Paragraph>
      <List
        dataSource={tools}
        renderItem={(t) => (
          <List.Item
            actions={[
              <Switch
                key="sw"
                checked={t.enabled}
                disabled={t.needs_config && !t.configured}
                onChange={(v) => {
                  toggle(t.key, v);
                  message.success(v ? `已启用 ${t.name}` : `已停用 ${t.name}`);
                }}
              />,
            ]}
          >
            <List.Item.Meta
              title={
                <Space>
                  <span>{t.name}</span>
                  {t.needs_config && !t.configured && <Tag color="orange">未配置</Tag>}
                  {!t.enabled && <Tag>已停用</Tag>}
                </Space>
              }
              description={t.description}
            />
          </List.Item>
        )}
      />
    </Card>
  );
}

export default ToolManagePage;
