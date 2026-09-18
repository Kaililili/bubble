import { Tabs } from "antd";
import ModelConfigPage from "./ModelConfigPage";
import ToolManagePage from "./ToolManagePage";
import MCPConfigPage from "./MCPConfigPage";

function SettingsPage() {
  return (
    <Tabs
      items={[
        { key: "models", label: "模型配置", children: <ModelConfigPage /> },
        { key: "tools", label: "工具", children: <ToolManagePage /> },
        { key: "mcp", label: "MCP", children: <MCPConfigPage /> },
      ]}
    />
  );
}

export default SettingsPage;
