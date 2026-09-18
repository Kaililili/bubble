import { Typography, Card, Space } from "antd";
import { SmileOutlined } from "@ant-design/icons";

const { Title, Paragraph, Text } = Typography;

function HomePage() {
  return (
    <div style={{ textAlign: "center", paddingTop: 60 }}>
      <Title level={1}>Bubble 🫧</Title>
      <Paragraph type="secondary" style={{ fontSize: 18 }}>
        你的个人 AI 生活助手
      </Paragraph>

      <Space direction="vertical" size="middle" style={{ marginTop: 40 }}>
        <Card style={{ width: 360, textAlign: "left" }}>
          <Space>
            <SmileOutlined style={{ fontSize: 24, color: "#7C5CFC" }} />
            <div>
              <Text strong>项目骨架已就绪 ✨</Text>
              <br />
              <Text type="secondary">
                后端 FastAPI + 前端 React + Docker 基础设施已搭建完成。
                <br />
                接下来将逐步实现认证、聊天、记忆等功能。
              </Text>
            </div>
          </Space>
        </Card>
      </Space>
    </div>
  );
}

export default HomePage;
