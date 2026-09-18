import { useEffect, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Button, Dropdown, Empty, Grid, Layout, List, Menu, Popconfirm, Typography, theme } from "antd";
import {
  BulbOutlined,
  CoffeeOutlined,
  DeleteOutlined,
  FireOutlined,
  LogoutOutlined,
  MessageOutlined,
  PlusOutlined,
  SettingOutlined,
  SmileOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useAuthStore } from "../stores/authStore";
import { useChatStore } from "../stores/chatStore";

const { Sider, Header, Content } = Layout;
const { Text } = Typography;

const MENU_ITEMS = [
  { key: "/chat", icon: <MessageOutlined />, label: "对话" },
  { key: "/memory", icon: <BulbOutlined />, label: "记忆" },
  { key: "/interest", icon: <FireOutlined />, label: "兴趣" },
  { key: "/emotion", icon: <SmileOutlined />, label: "情绪" },
  { key: "/luckin", icon: <CoffeeOutlined />, label: "瑞幸" },
  { key: "/settings", icon: <SettingOutlined />, label: "设置" },
];

function MainLayout() {
  const { token } = theme.useToken();
  const screens = Grid.useBreakpoint();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  const conversations = useChatStore((s) => s.conversations);
  const activeId = useChatStore((s) => s.activeId);
  const fetchConversations = useChatStore((s) => s.fetchConversations);
  const newConversation = useChatStore((s) => s.newConversation);
  const removeConversation = useChatStore((s) => s.removeConversation);
  const selectConversation = useChatStore((s) => s.selectConversation);

  const selectedKey = MENU_ITEMS.some((i) => i.key === location.pathname)
    ? location.pathname
    : "/chat";

  const isMobile = !screens.md;
  const contentPadding = isMobile ? 12 : 24;

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const handleNewChat = async () => {
    await newConversation();
    navigate("/chat");
  };

  const handleSelectChat = async (id: string) => {
    await selectConversation(id);
    navigate("/chat");
  };

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <Layout style={{ height: "100vh", overflow: "hidden" }}>
      <Sider
        theme="light"
        width={240}
        breakpoint="lg"
        collapsedWidth={64}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        style={{ borderRight: `1px solid ${token.colorBorderSecondary}` }}
      >
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <div
            style={{
              height: 56,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: collapsed ? 20 : 18,
              fontWeight: 600,
              color: token.colorPrimary,
              overflow: "hidden",
              whiteSpace: "nowrap",
            }}
          >
            {collapsed ? "🫧" : "Bubble 🫧"}
          </div>

          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={MENU_ITEMS}
            onClick={({ key }) => navigate(key)}
            style={{ borderInlineEnd: "none" }}
          />

          {/* 导航下方:新建对话 + 会话列表 */}
          {!collapsed && (
            <div
              style={{
                borderTop: `1px solid ${token.colorBorderSecondary}`,
                margin: "12px 12px 0",
                paddingTop: 12,
                display: "flex",
                flexDirection: "column",
                flex: 1,
                minHeight: 0,
              }}
            >
              <Button type="primary" icon={<PlusOutlined />} block onClick={handleNewChat}>
                新建对话
              </Button>
              <div style={{ marginTop: 12, flex: 1, overflowY: "auto", minHeight: 0 }}>
                <List
                  dataSource={conversations}
                  locale={{ emptyText: <Empty description="暂无会话" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
                  renderItem={(item) => (
                    <div
                      key={item.id}
                      onClick={() => handleSelectChat(item.id)}
                      style={{
                        cursor: "pointer",
                        padding: "8px 10px",
                        borderRadius: 8,
                        marginBottom: 4,
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        background: activeId === item.id ? "#f2edff" : "transparent",
                      }}
                    >
                      <Text ellipsis style={{ maxWidth: 140 }}>{item.title}</Text>
                      <Popconfirm
                        title="删除该会话?"
                        onConfirm={(e) => {
                          e?.stopPropagation();
                          removeConversation(item.id);
                        }}
                      >
                        <DeleteOutlined style={{ color: "#999" }} onClick={(e) => e.stopPropagation()} />
                      </Popconfirm>
                    </div>
                  )}
                />
              </div>
            </div>
          )}
        </div>
      </Sider>

      <Layout>
        <Header
          style={{
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            padding: "0 24px",
            height: 56,
            flex: "none",
          }}
        >
          <Dropdown
            menu={{
              items: [
                {
                  key: "logout",
                  icon: <LogoutOutlined />,
                  label: "退出登录",
                  onClick: handleLogout,
                },
              ],
            }}
            placement="bottomRight"
          >
            <Button type="text" icon={<UserOutlined />}>
              {user?.username ?? "用户"}
            </Button>
          </Dropdown>
        </Header>

        <Content
          style={{
            flex: 1,
            overflow: "auto",
            padding: contentPadding,
            minHeight: 0,
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

export default MainLayout;
