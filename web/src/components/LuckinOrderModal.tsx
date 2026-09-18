import { useEffect, useState } from "react";
import { Button, Modal, Space, Tag, Typography, message } from "antd";
import {
  OrderAttr,
  OrderCreated,
  OrderOptions,
  OrderPreview,
  cancelLuckinOrder,
  createLuckinOrder,
  getLuckinOrderOptions,
  previewLuckinOrder,
  queryLuckinOrder,
} from "../api/mcp";

const { Text } = Typography;

export interface LuckinOrderTarget {
  dept_id: number;
  product_id: number;
}

/** 瑞幸下单通用弹窗:选口味 → 预览确认 → 支付二维码(瑞幸页与聊天共用) */
function LuckinOrderModal({
  target,
  onClose,
}: {
  target: LuckinOrderTarget | null;
  onClose: () => void;
}) {
  const [options, setOptions] = useState<OrderOptions | null>(null);
  const [picks, setPicks] = useState<Record<number, number>>({});
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [order, setOrder] = useState<OrderCreated | null>(null);
  const [phase, setPhase] = useState<"options" | "preview" | "pay">("options");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!target) return;
    setLoading(true);
    setOptions(null);
    setPreview(null);
    setOrder(null);
    setPhase("options");
    getLuckinOrderOptions(target.dept_id, target.product_id)
      .then((opts) => {
        setOptions(opts);
        // 初始选中:默认规格(selected=true 优先,否则第一个可选)
        const init: Record<number, number> = {};
        (opts.attributes || []).forEach((a) => {
          const def = a.options.find((o) => o.selected) ?? a.options.find((o) => o.can_select !== false);
          if (def?.sub_attribute_id != null) init[a.attribute_id ?? -1] = def.sub_attribute_id;
        });
        setPicks(init);
      })
      .catch((e) => message.error((e as Error).message || "获取选项失败"))
      .finally(() => setLoading(false));
  }, [target]);

  const changedSpecs = () => {
    const specs: { attribute_id: number; sub_attribute_id: number }[] = [];
    (options?.attributes || []).forEach((a) => {
      const aid = a.attribute_id;
      if (aid == null) return;
      const def = a.options.find((o) => o.selected)?.sub_attribute_id;
      const cur = picks[aid];
      // 只传与默认不同的属性,避免无谓 switch
      if (cur != null && cur !== def) specs.push({ attribute_id: aid, sub_attribute_id: cur });
    });
    return specs;
  };

  const handleNext = async () => {
    if (!options?.dept_id || !options.product_id) return;
    setLoading(true);
    try {
      const p = await previewLuckinOrder({
        dept_id: options.dept_id,
        product_id: options.product_id,
        specs: changedSpecs(),
      });
      setPreview(p);
      setPhase("preview");
    } catch (e) {
      message.error((e as Error).message || "预览失败");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!preview?.dept_id || !preview.product_id) return;
    setLoading(true);
    try {
      const res = await createLuckinOrder({
        dept_id: preview.dept_id,
        product_id: preview.product_id,
        amount: preview.amount ?? 1,
        sku_code: preview.sku_code,
      });
      if (!res.order_id) {
        message.error("下单失败,请重试");
        return;
      }
      setOrder(res);
      setPhase("pay");
    } catch (e) {
      message.error((e as Error).message || "下单失败");
    } finally {
      setLoading(false);
    }
  };

  const handleCancelOrder = async () => {
    if (!order?.order_id) return;
    try {
      await cancelLuckinOrder(order.order_id);
      message.success("订单已取消");
      onClose();
    } catch (e) {
      message.error((e as Error).message || "取消失败");
    }
  };

  const handleCheckPaid = async () => {
    if (!order?.order_id) return;
    try {
      const info = await queryLuckinOrder(order.order_id);
      const statusName = (info?.status_name as string) || "";
      const statusCode = info?.status_code;
      if (statusCode === 10 || statusName === "待付款") {
        message.warning("还没有检测到支付,订单仍为待付款。请先扫码完成支付,或点「取消订单」放弃这笔订单。");
        return;
      }
      if (statusName.includes("取消") || statusCode === 100) {
        message.info("订单已取消,如需购买请重新下单。");
        close();
        return;
      }
      if (statusName.includes("完成") || statusName.includes("支付")) {
        message.success(`支付成功!当前状态:${statusName || "已完成"}。`);
        close();
        return;
      }
      message.success(`订单状态:${statusName || `码 ${statusCode}`}。如已支付请稍候再确认。`);
    } catch (e) {
      message.error((e as Error).message || "查询失败");
    }
  };

  const close = () => {
    setPreview(null);
    setOrder(null);
    onClose();
  };

  return (
    <>
      {/* 第一步:选口味 */}
      <Modal
        open={!!target && phase === "options"}
        title={`选择口味 · ${options?.product ?? ""}`}
        onCancel={close}
        onOk={handleNext}
        okText="下一步"
        cancelText="取消"
        okButtonProps={{ loading }}
      >
        {options && (
          <Space direction="vertical" size={14} style={{ width: "100%" }}>
            {(options.attributes || []).map((a: OrderAttr) => (
              <div key={a.attribute_id}>
                <Text strong style={{ fontSize: 13, display: "block", marginBottom: 6 }}>
                  {a.name}
                </Text>
                <Space wrap>
                  {a.options.map((o) => {
                    const selected = picks[a.attribute_id ?? -1] === o.sub_attribute_id;
                    return (
                      <Button
                        key={o.sub_attribute_id}
                        size="small"
                        type={selected ? "primary" : "default"}
                        disabled={o.can_select === false}
                        onClick={() =>
                          setPicks((prev) => ({
                            ...prev,
                            [a.attribute_id ?? -1]: o.sub_attribute_id ?? -1,
                          }))
                        }
                      >
                        {o.name}
                        {o.price_delta ? ` +¥${o.price_delta}` : ""}
                      </Button>
                    );
                  })}
                </Space>
              </div>
            ))}
            {options.estimate_price != null && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                参考价 ¥{options.estimate_price.toFixed(1)},口味调整后以下一步预览为准
              </Text>
            )}
          </Space>
        )}
      </Modal>

      {/* 第二步:确认明细 */}
      <Modal
        open={!!target && phase === "preview"}
        title="确认下单"
        onCancel={close}
        footer={[
          <Button key="back" onClick={() => setPhase("options")}>
            上一步
          </Button>,
          <Button key="ok" type="primary" loading={loading} onClick={handleConfirm}>
            确认下单
          </Button>,
        ]}
      >
        {preview && (
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Text strong>{preview.shop}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>{preview.address}</Text>
            <div style={{ padding: "8px 12px", background: "#fafafa", borderRadius: 8 }}>
              <Space direction="vertical" size={2}>
                <Text>
                  {preview.product} × {preview.amount ?? 1}
                </Text>
                {preview.spec && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    规格: <Tag style={{ marginInlineEnd: 0 }}>{preview.spec}</Tag>
                  </Text>
                )}
              </Space>
            </div>
            <Space wrap>
              {preview.original_price != null && (
                <Text type="secondary" delete>¥{preview.original_price.toFixed(1)}</Text>
              )}
              {preview.discount_price != null && (
                <Text style={{ fontSize: 20, color: "#d4380d", fontWeight: 600 }}>
                  ¥{preview.discount_price.toFixed(1)}
                </Text>
              )}
            </Space>
            {preview.privilege_money ? (
              <Text type="success" style={{ fontSize: 12 }}>
                已优惠 ¥{preview.privilege_money.toFixed(1)}
              </Text>
            ) : null}
            {preview.about_time && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                预计可取餐时间约 {preview.about_time}
              </Text>
            )}
            <Text type="warning" style={{ fontSize: 12 }}>
              确认后将在瑞幸账户生成待支付订单(不支付不会扣款),请到瑞幸小程序/App 完成支付。
            </Text>
          </Space>
        )}
      </Modal>

      {/* 第三步:支付 */}
      <Modal
        open={!!target && phase === "pay" && !!order}
        title="订单已创建,请扫码支付"
        onCancel={close}
        footer={[
          <Button key="check" onClick={handleCheckPaid}>
            我已支付
          </Button>,
          <Button key="cancel" danger onClick={handleCancelOrder}>
            取消订单
          </Button>,
        ]}
      >
        {order && (
          <Space direction="vertical" size={12} style={{ width: "100%" }} align="center">
            {order.discount_price != null && (
              <Text style={{ fontSize: 24, color: "#d4380d", fontWeight: 600 }}>
                ¥{order.discount_price.toFixed(1)}
              </Text>
            )}
            {order.pay_qr_url ? (
              <img
                src={order.pay_qr_url}
                alt="支付二维码"
                style={{ width: 220, height: 220, objectFit: "contain" }}
              />
            ) : (
              <Text type="secondary">暂无二维码,请到瑞幸 App 支付</Text>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              订单号: {order.order_id}
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              请使用瑞幸小程序/微信扫码支付;完成后点「我已支付」查询状态,不支付可取消订单。
            </Text>
          </Space>
        )}
      </Modal>
    </>
  );
}

export default LuckinOrderModal;
