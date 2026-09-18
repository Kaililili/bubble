import { useEffect, useState } from "react";
import { Button, Card, Empty, Input, InputNumber, List, Modal, Select, Space, Tag, Typography, message } from "antd";
import { CoffeeOutlined, EnvironmentOutlined, MoneyCollectOutlined, ShoppingCartOutlined } from "@ant-design/icons";
import {
  CompareItem,
  compareLuckin,
  listServers,
} from "../api/mcp";
import { upsertProfile } from "../api/memory";
import LuckinOrderModal, { LuckinOrderTarget } from "../components/LuckinOrderModal";

const { Text, Title } = Typography;

// 常用城市坐标 [纬度, 经度] (定位失败时手动选择)
const CITY_POS: Record<string, [number, number]> = {
  北京: [39.909, 116.397],
  上海: [31.2304, 121.4737],
  广州: [23.1291, 113.2644],
  深圳: [22.5431, 114.0579],
  杭州: [30.2741, 120.1551],
  成都: [30.5728, 104.0668],
  武汉: [30.5928, 114.3055],
  南京: [32.0603, 118.7969],
  重庆: [29.563, 106.5516],
  西安: [34.3416, 108.9398],
  长沙: [28.2282, 112.9388],
  苏州: [31.2989, 120.5853],
};

function LuckinPage() {
  const [keyword, setKeyword] = useState("");
  const [items, setItems] = useState<CompareItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [searched, setSearched] = useState(false);
  const [located, setLocated] = useState<boolean | null>(null);
  const [locModalOpen, setLocModalOpen] = useState(false);
  const [city, setCity] = useState<string | undefined>();
  const [manualLat, setManualLat] = useState<number | null>(null);
  const [manualLon, setManualLon] = useState<number | null>(null);
  const [orderTarget, setOrderTarget] = useState<LuckinOrderTarget | null>(null);

  /** 高精度浏览器定位:成功返回坐标,失败返回原因(区分权限/超时/不可用) */
  const getPosition = (): Promise<{ lon: number; lat: number } | { error: string }> =>
    new Promise((resolve) => {
      if (!navigator.geolocation) {
        resolve({ error: "浏览器不支持定位" });
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({ lon: pos.coords.longitude, lat: pos.coords.latitude }),
        (err) => {
          const msg =
            err.code === err.PERMISSION_DENIED
              ? "定位权限被拒绝,请在浏览器地址栏左侧允许位置权限"
              : err.code === err.TIMEOUT
              ? "定位超时,请检查系统定位服务(手机需开启 GPS/位置)"
              : "暂时无法获取定位,请检查网络或系统设置";
          resolve({ error: msg });
        },
        { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
      );
    });

  useEffect(() => {
    listServers()
      .then((ss) => setConfigured(ss.length > 0))
      .catch(() => setConfigured(false));
  }, []);

  const handleCompare = async () => {
    const kw = keyword.trim();
    if (!kw) return;
    setLoading(true);
    try {
      let lon: number | undefined;
      let lat: number | undefined;
      const pos = await getPosition();
      if (!("error" in pos)) {
        lon = pos.lon;
        lat = pos.lat;
        try {
          await upsertProfile({ key: "位置", value: `${lat.toFixed(5)},${lon.toFixed(5)}` });
        } catch {
          // 位置保存失败不阻断比价
        }
      }
      setLocated(!("error" in pos));
      const res = await compareLuckin(kw, lon, lat);
      setItems(res.items);
      setSearched(true);
    } catch (e) {
      message.error((e as Error).message || "比价失败");
    } finally {
      setLoading(false);
    }
  };

  const saveLocation = async (lat: number, lon: number) => {
    await upsertProfile({ key: "位置", value: `${lat.toFixed(5)},${lon.toFixed(5)}` });
    setLocated(true);
    message.success("位置已保存,后续比价与聊天都会使用");
  };

  const handleSaveManualLoc = async () => {
    try {
      if (city && CITY_POS[city]) {
        await saveLocation(CITY_POS[city][0], CITY_POS[city][1]);
      } else if (manualLat != null && manualLon != null) {
        await saveLocation(manualLat, manualLon);
      } else {
        message.warning("请选择城市或输入经纬度");
        return;
      }
      setLocModalOpen(false);
    } catch (e) {
      message.error((e as Error).message || "保存失败");
    }
  };

  const handleLocate = async () => {
    const pos = await getPosition();
    if ("error" in pos) {
      setLocated(false);
      message.warning(pos.error);
      return;
    }
    try {
      await saveLocation(pos.lat, pos.lon);
      message.success(`已获取精确定位并保存: ${pos.lat.toFixed(5)}, ${pos.lon.toFixed(5)}`);
    } catch (e) {
      message.error((e as Error).message || "保存失败");
    }
  };

  const handleOrderClick = async (item: CompareItem) => {
    if (!item.dept_id || !item.product_id) {
      message.warning("该门店暂无下单信息");
      return;
    }
    setOrderTarget({ dept_id: item.dept_id, product_id: item.product_id });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card title="瑞幸比价">
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space.Compact style={{ width: "100%" }}>
            <Input
              placeholder="输入饮品,如 生椰拿铁"
              prefix={<CoffeeOutlined />}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onPressEnter={handleCompare}
            />
            <Button type="primary" loading={loading} onClick={handleCompare}>
              比价
            </Button>
          </Space.Compact>
          {configured === false && (
            <Text type="secondary">
              尚未配置 MCP 服务,请先到「设置 → MCP」添加瑞幸官方 MCP 配置并测试连接。
            </Text>
          )}
          {located !== null && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {located
                ? "已使用你的当前位置查询"
                : "未获取到定位,将按默认位置查询,可点击右侧按钮获取精确定位"}
            </Text>
          )}
          <Space wrap>
            <Button size="small" icon={<EnvironmentOutlined />} onClick={handleLocate}>
              获取我的位置
            </Button>
            <Button size="small" onClick={() => setLocModalOpen(true)}>
              手动设置位置
            </Button>
          </Space>
        </Space>
      </Card>

      <Modal
        open={locModalOpen}
        title="设置我的位置"
        onCancel={() => setLocModalOpen(false)}
        onOk={handleSaveManualLoc}
        okText="保存"
        cancelText="取消"
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Select
            allowClear
            placeholder="选择常用城市"
            style={{ width: "100%" }}
            value={city}
            onChange={(v) => {
              setCity(v);
              if (v && CITY_POS[v]) {
                setManualLat(CITY_POS[v][0]);
                setManualLon(CITY_POS[v][1]);
              }
            }}
            options={Object.keys(CITY_POS).map((c) => ({ value: c, label: c }))}
          />
          <Text type="secondary">或手动输入经纬度:</Text>
          <Space wrap>
            <InputNumber
              placeholder="纬度(北纬)"
              style={{ width: 140 }}
              value={manualLat}
              onChange={(v) => setManualLat(v)}
            />
            <InputNumber
              placeholder="经度(东经)"
              style={{ width: 140 }}
              value={manualLon}
              onChange={(v) => setManualLon(v)}
            />
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            保存后会存到「用户背景 → 位置」,聊天里问瑞幸也会用这个位置
          </Text>
        </Space>
      </Modal>

      <Card title={searched ? `比价结果:${keyword}` : "比价结果"}>
        {items.length === 0 ? (
          <Empty
            description={searched ? "没有查询到结果" : "输入饮品后点击「比价」,按价格从低到高展示附近门店"}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        ) : (
          <List
            dataSource={items}
            renderItem={(item, idx) => (
              <List.Item
                actions={[
                  <Button
                    key="order"
                    size="small"
                    type="primary"
                    icon={<ShoppingCartOutlined />}
                    onClick={() => handleOrderClick(item)}
                  >
                    下单
                  </Button>,
                ]}
              >
                <div style={{ width: "100%" }}>
                  <Space wrap>
                    {idx === 0 && <Tag color="red">最低价</Tag>}
                    <Text strong>{item.shop}</Text>
                    {item.product && (
                      <Tag color="blue">{item.product}</Tag>
                    )}
                  </Space>
                  <div style={{ marginTop: 4 }}>
                    <Space wrap size="large">
                      {item.distance_km != null && (
                        <Text type="secondary">
                          <EnvironmentOutlined /> {item.distance_km.toFixed(1)} km
                        </Text>
                      )}
                      {item.price != null && (
                        <Text type="secondary">
                          <MoneyCollectOutlined /> ¥{item.price.toFixed(1)}(默认规格预估价)
                        </Text>
                      )}
                    </Space>
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </Card>
      <LuckinOrderModal target={orderTarget} onClose={() => setOrderTarget(null)} />
    </div>
  );
}

export default LuckinPage;
