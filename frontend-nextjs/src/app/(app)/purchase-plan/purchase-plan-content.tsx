"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, put, del } from "@/lib/api-client";

// ============ Types ============

interface PlanItem {
  id: number; customer_name: string; product_name: string; barcode: string;
  quantity: number; inventory_qty: number; shipped_qty: number; remaining_qty: number;
  diff: number; stock_status: string; shipment_status: string;
  plan_date: string; status: string; remark: string | null;
}
interface MonthlySummary {
  total_plan_qty: number; total_inventory_qty: number; total_shipped_qty: number;
  total_remaining_qty: number; warning_count: number; customer_summary: Record<string, { plan_qty: number; inventory_qty: number; shipped_qty: number; remaining_qty: number; warning_count: number }>;
}
interface PlanListResult { success: boolean; plans: PlanItem[]; monthly_summary: MonthlySummary | null; total: number }
interface CustomerName { id: number; name: string }
interface TimelineResult { year: number; month: number; days_in_month: number; timeline: { date: string; day: number; plans: PlanItem[]; total_plan_qty: number; has_warning: boolean }[]; customers: string[] }
interface ActionRes { success: boolean; message: string }
interface BarcodeRes { valid: boolean; product_name?: string; message?: string }

const statusLabel: Record<string, string> = { pending: "待确认", confirmed: "已确认", completed: "已完成", cancelled: "已取消" };
const shipLabel: Record<string, string> = { pending: "待出货", partial: "部分出货", completed: "已完成" };
const stockLabel: Record<string, string> = { sufficient: "充足", shortage: "不足", no_stock: "无库存", normal: "正常", warning: "不足" };

// ============ Component ============

export function PurchasePlanContent() {
  const qc = useQueryClient();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [selectedCustomer, setSelectedCustomer] = useState("");
  const [searched, setSearched] = useState(false);

  // Add modal
  const [addOpen, setAddOpen] = useState(false);
  const [addCustomer, setAddCustomer] = useState("");
  const [addMonth, setAddMonth] = useState(`${year}-${String(month).padStart(2, "0")}`);
  const [addBarcode, setAddBarcode] = useState("");
  const [addProductName, setAddProductName] = useState("");
  const [addQuantity, setAddQuantity] = useState(1);
  const [addDate, setAddDate] = useState("");
  const [addRemark, setAddRemark] = useState("");
  const [addRows, setAddRows] = useState<{ barcode: string; productName: string; quantity: number; date: string; productId: number }[]>([{ barcode: "", productName: "", quantity: 1, date: "", productId: 0 }]);

  // Edit modal
  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState(0);
  const [editStatus, setEditStatus] = useState("");
  const [editRemark, setEditRemark] = useState("");

  // Upload modal
  const [uploadOpen, setUploadOpen] = useState(false);

  // Delete confirm
  const [deleteId, setDeleteId] = useState<number | null>(null);

  // Customer list
  const { data: customerNames } = useQuery<CustomerName[]>({
    queryKey: ["customer-active-names"],
    queryFn: () => get<CustomerName[]>("/customers/active-names"),
  });

  // Plan list
  const { data: planData, isLoading } = useQuery<PlanListResult>({
    queryKey: ["production-plans", year, month, selectedCustomer],
    queryFn: () => get<PlanListResult>("/production-plans/list", {
      year: String(year), month: String(month),
      ...(selectedCustomer && { customer: selectedCustomer }),
    }),
    enabled: searched,
  });

  // Timeline
  const { data: timelineData } = useQuery<TimelineResult>({
    queryKey: ["production-plans-timeline", year, month, selectedCustomer],
    queryFn: () => get<TimelineResult>("/production-plans/timeline", {
      year: String(year), month: String(month),
      ...(selectedCustomer && { customer: selectedCustomer }),
    }),
    enabled: searched,
  });

  const plans = planData?.plans || [];
  const summary = planData?.monthly_summary;
  const customers = timelineData?.customers || [];

  // Calendar
  const calDays = useMemo(() => {
    const dim = new Date(year, month, 0).getDate();
    const firstDow = new Date(year, month - 1, 1).getDay();
    const offset = firstDow === 0 ? 6 : firstDow - 1; // Monday=0
    const tl = timelineData?.timeline || [];
    const tlMap = new Map(tl.map(d => [d.day, d]));
    const cells: { day: number; empty: boolean; hasWarning: boolean; planCount: number; plans: PlanItem[] }[] = [];
    for (let i = 0; i < offset; i++) cells.push({ day: 0, empty: true, hasWarning: false, planCount: 0, plans: [] });
    for (let d = 1; d <= dim; d++) {
      const td = tlMap.get(d);
      cells.push({ day: d, empty: false, hasWarning: td?.has_warning || false, planCount: td?.plans?.length || 0, plans: td?.plans || [] });
    }
    return cells;
  }, [year, month, timelineData]);

  const today = new Date();
  const isToday = (d: number) => d === today.getDate() && month === today.getMonth() + 1 && year === today.getFullYear();

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: { customer_name: string; product_name: string; barcode: string; quantity: number; plan_date: string; remark?: string }) =>
      post<ActionRes>("/production-plans/create", data),
    onSuccess: () => { setAddOpen(false); qc.invalidateQueries({ queryKey: ["production-plans"] }); qc.invalidateQueries({ queryKey: ["production-plans-timeline"] }); },
  });

  const editMut = useMutation({
    mutationFn: (data: { id: number; status?: string; remark?: string }) =>
      put<ActionRes>(`/production-plans/edit/${data.id}`, data),
    onSuccess: () => { setEditOpen(false); qc.invalidateQueries({ queryKey: ["production-plans"] }); qc.invalidateQueries({ queryKey: ["production-plans-timeline"] }); },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => del<ActionRes>(`/production-plans/delete/${id}`),
    onSuccess: () => { setDeleteId(null); qc.invalidateQueries({ queryKey: ["production-plans"] }); qc.invalidateQueries({ queryKey: ["production-plans-timeline"] }); },
  });

  const doSearch = () => { setSearched(true); };

  const openEdit = (p: PlanItem) => { setEditId(p.id); setEditStatus(p.status); setEditRemark(p.remark || ""); setEditOpen(true); };

  const doAddSubmit = () => {
    for (const row of addRows) {
      if (!addCustomer || !row.barcode || !row.productName || !row.date) continue;
      createMut.mutate({ customer_name: addCustomer, product_name: row.productName, barcode: row.barcode, quantity: row.quantity, plan_date: row.date, remark: addRemark || undefined });
    }
  };

  const addDetailRow = () => setAddRows(prev => [...prev, { barcode: "", productName: "", quantity: 1, date: "", productId: 0 }]);
  const removeDetailRow = (idx: number) => setAddRows(prev => prev.filter((_, i) => i !== idx));
  const updateAddRow = (idx: number, field: string, value: string | number) => setAddRows(prev => prev.map((r, i) => i === idx ? { ...r, [field]: value } : r));

  // Barcode validation
  const validateBarcode = async (barcode: string, idx: number) => {
    if (!barcode) return;
    try {
      const res = await get<BarcodeRes>(`/production-plans/validate-barcode?q=${encodeURIComponent(barcode)}`);
      if (res.valid && res.product_name) {
        updateAddRow(idx, "productName", res.product_name);
      }
    } catch { /* ignore */ }
  };

  const downloadTemplate = () => {
    const headers = ["客户名称", "产品名称", "69码", "数量", "计划日期", "备注"];
    let csv = "\uFEFF" + headers.join(",") + "\n";
    csv += `示例客户,示例产品,6901234567890,100,${year}-${String(month).padStart(2, "0")}-01,备注\n`;
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "采购计划模板.csv";
    link.click();
  };

  return (
    <div className="pp-wrap">
      <h2><i className="fas fa-clipboard-list" style={{ marginRight: 8 }}></i>采购计划管理</h2>

      {/* Top bar */}
      <div className="pp-top-bar">
        <div className="pp-top-left">
          <label className="form-label" style={{ marginBottom: 0, marginRight: 4 }}>月份:</label>
          <input type="number" className="form-control form-control-sm" value={year} onChange={e => setYear(Number(e.target.value))} min={2020} max={2099} style={{ width: 90 }} />
          <span style={{ fontWeight: 700 }}>年</span>
          <input type="number" className="form-control form-control-sm" value={month} onChange={e => setMonth(Math.max(1, Math.min(12, Number(e.target.value))))} min={1} max={12} style={{ width: 70 }} />
          <span style={{ fontWeight: 700 }}>月</span>
          <button className="btn btn-primary btn-sm" onClick={doSearch}><i className="fas fa-search" style={{ marginRight: 4 }}></i>查询</button>
        </div>
        <div className="pp-top-right">
          <button className="btn btn-outline-secondary btn-sm" onClick={downloadTemplate}><i className="fas fa-download" style={{ marginRight: 4 }}></i>下载模板</button>
          <button className="btn btn-success btn-sm" onClick={() => setUploadOpen(true)}><i className="fas fa-file-excel" style={{ marginRight: 4 }}></i>批量上传</button>
          <button className="btn btn-primary btn-sm" onClick={() => {
            setAddOpen(true);
            setAddCustomer(""); setAddBarcode(""); setAddProductName(""); setAddQuantity(1); setAddDate(""); setAddRemark("");
            setAddRows([{ barcode: "", productName: "", quantity: 1, date: "", productId: 0 }]);
          }}><i className="fas fa-plus" style={{ marginRight: 4 }}></i>手动添加</button>
        </div>
      </div>

      {/* Customer filter */}
      <div className="card pp-card" style={{ marginTop: 12 }}>
        <div className="card-body" style={{ padding: "8px 16px" }}>
          <div className="pp-customer-bar">
            <span className={`pp-chip ${selectedCustomer === "" ? "active" : ""}`} onClick={() => setSelectedCustomer("")}>
              <i className="fas fa-globe" style={{ fontSize: 14 }}></i>全部
            </span>
            {customers.map(c => (
              <span key={c} className={`pp-chip ${selectedCustomer === c ? "active" : ""}`} onClick={() => setSelectedCustomer(c)}>{c}</span>
            ))}
          </div>
        </div>
      </div>

      {/* Summary panel */}
      {searched && summary && (
        <div style={{ marginTop: 12 }}>
          <div className="card pp-card"><div className="card-body">
            <div className="pp-stats-row">
              <div className="pp-stat"><h3>{summary.total_plan_qty}</h3><small>计划总量</small></div>
              <div className="pp-stat"><h3>{summary.total_inventory_qty}</h3><small>库存总量</small></div>
              <div className="pp-stat"><h3>{summary.total_shipped_qty}</h3><small>出货总量</small></div>
              <div className="pp-stat"><h3>{summary.total_remaining_qty}</h3><small>剩余计划</small></div>
              <div className="pp-stat"><h3 style={{ color: "#ffc107" }}>{summary.warning_count}</h3><small>库存不足</small></div>
            </div>
          </div></div>
        </div>
      )}

      {/* Calendar */}
      {searched && (
        <div className="card pp-card" style={{ marginTop: 12 }}>
          <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span><i className="fas fa-calendar-alt" style={{ marginRight: 4 }}></i>计划日历</span>
            <small style={{ color: "#6c757d" }}>点击日期查看当日计划</small>
          </div>
          <div className="card-body">
            <div className="pp-cal-grid">
              {["一", "二", "三", "四", "五", "六", "日"].map(d => <div key={d} className="pp-cal-hd">{d}</div>)}
              {calDays.map((cell, i) => cell.empty ? (
                <div key={i} className="pp-cal-cell empty"></div>
              ) : (
                <div key={i} className={`pp-cal-cell${isToday(cell.day) ? " today" : ""}${cell.hasWarning ? " has-warning" : ""}`}>
                  <div className="cell-date">{cell.day}</div>
                  {cell.plans.slice(0, 3).map((p, j) => (
                    <div key={j} className="cell-item">
                      <span className={`stock-dot ${p.stock_status === "warning" ? "shortage" : "sufficient"}`}></span>
                      {p.customer_name}: {p.quantity}
                    </div>
                  ))}
                  {cell.planCount > 3 && <div className="cell-more">+{cell.planCount - 3}更多</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Detail table */}
      <div className="card pp-card" style={{ marginTop: 12 }}>
        <div className="card-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span><i className="fas fa-list" style={{ marginRight: 4 }}></i>计划明细</span>
          <span style={{ color: "#6c757d" }}>共 {planData?.total ?? 0} 条记录</span>
        </div>
        <div className="card-body" style={{ overflowX: "auto" }}>
          <table className="table table-hover table-sm">
            <thead>
              <tr>
                <th>客户</th><th>产品名称</th><th>69码</th>
                <th style={{ textAlign: "center" }}>计划量</th>
                <th style={{ textAlign: "center" }}>库存量</th>
                <th style={{ textAlign: "center" }}>已出货</th>
                <th style={{ textAlign: "center" }}>剩余</th>
                <th>库存状态</th><th>出货进度</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={10} className="pp-td-center"><div className="spinner-border text-primary"></div><p style={{ color: "#718096", marginTop: 8 }}>加载中...</p></td></tr>
              ) : !searched ? (
                <tr><td colSpan={10} className="pp-td-center"><i className="fas fa-inbox" style={{ fontSize: 48, opacity: 0.3, marginBottom: 12 }}></i><p style={{ color: "#718096" }}>请选择月份查询采购计划</p></td></tr>
              ) : plans.length === 0 ? (
                <tr><td colSpan={10} className="pp-td-center"><i className="fas fa-inbox" style={{ fontSize: 48, opacity: 0.3, marginBottom: 12 }}></i><p style={{ color: "#718096" }}>暂无数据</p></td></tr>
              ) : plans.map(p => (
                <tr key={p.id} className={p.stock_status === "warning" ? "pp-row-warning" : p.shipment_status === "completed" ? "pp-row-completed" : ""}>
                  <td>{p.customer_name || "-"}</td>
                  <td>{p.product_name || "-"}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{p.barcode || "-"}</td>
                  <td style={{ textAlign: "center" }}>{p.quantity}</td>
                  <td style={{ textAlign: "center" }}>{p.inventory_qty}</td>
                  <td style={{ textAlign: "center" }}>{p.shipped_qty}</td>
                  <td style={{ textAlign: "center" }}>{p.remaining_qty}</td>
                  <td><span className={`badge pp-badge-${p.stock_status === "warning" ? "shortage" : "sufficient"}`}>{stockLabel[p.stock_status] || p.stock_status}</span></td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <div className="pp-progress" style={{ width: 60 }}><div className={`pp-progress-bar pp-pb-${p.shipment_status}`} style={{ width: `${p.quantity > 0 ? Math.min(100, (p.shipped_qty / p.quantity) * 100) : 0}%` }}></div></div>
                      <small style={{ fontSize: 11 }}>{shipLabel[p.shipment_status] || p.shipment_status}</small>
                    </div>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 4 }}>
                      <button className="btn btn-outline-primary btn-sm" onClick={() => openEdit(p)} title="编辑"><i className="fas fa-edit"></i></button>
                      <button className="btn btn-outline-danger btn-sm" onClick={() => setDeleteId(p.id)} title="删除"><i className="fas fa-trash"></i></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Modal */}
      {addOpen && (
        <div className="pp-mo show" onClick={() => setAddOpen(false)}>
          <div className="pp-mo-box" onClick={e => e.stopPropagation()}>
            <div className="pp-mo-h"><h5>新增采购计划</h5><button className="pp-mo-x" onClick={() => setAddOpen(false)}><i className="fas fa-times"></i></button></div>
            <div className="pp-mo-b">
              <div className="mb-3">
                <label className="form-label">客户 <span style={{ color: "red" }}>*</span></label>
                <select className="form-select" value={addCustomer} onChange={e => setAddCustomer(e.target.value)}>
                  <option value="">请选择客户</option>
                  {customerNames?.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                </select>
              </div>
              <div className="mb-3">
                <label className="form-label">计划月份 <span style={{ color: "red" }}>*</span></label>
                <input type="month" className="form-control" value={addMonth} onChange={e => setAddMonth(e.target.value)} />
              </div>
              <hr />
              <h6>计划明细</h6>
              {addRows.map((row, idx) => (
                <div key={idx} className="pp-detail-row">
                  <div className="mb-2">
                    <label className="form-label" style={{ fontSize: 12, marginBottom: 2 }}>69码 <span style={{ color: "red" }}>*</span></label>
                    <input type="text" className="form-control form-control-sm" value={row.barcode}
                      onChange={e => { updateAddRow(idx, "barcode", e.target.value); validateBarcode(e.target.value, idx); }}
                      placeholder="输入69码" />
                  </div>
                  <div className="row g-2">
                    <div className="col-6">
                      <label className="form-label" style={{ fontSize: 12, marginBottom: 2 }}>产品名称</label>
                      <input type="text" className="form-control form-control-sm" value={row.productName} readOnly placeholder="自动填充" />
                    </div>
                    <div className="col-3">
                      <label className="form-label" style={{ fontSize: 12, marginBottom: 2 }}>数量</label>
                      <input type="number" className="form-control form-control-sm" value={row.quantity} onChange={e => updateAddRow(idx, "quantity", Number(e.target.value))} min={1} max={999999} />
                    </div>
                    <div className="col-3">
                      <label className="form-label" style={{ fontSize: 12, marginBottom: 2 }}>日期</label>
                      <input type="date" className="form-control form-control-sm" value={row.date} onChange={e => updateAddRow(idx, "date", e.target.value)} />
                    </div>
                  </div>
                  {addRows.length > 1 && <button className="btn btn-sm btn-outline-danger mt-1" onClick={() => removeDetailRow(idx)}><i className="fas fa-minus"></i> 删除行</button>}
                </div>
              ))}
              <button className="btn btn-sm btn-outline-primary" onClick={addDetailRow}><i className="fas fa-plus" style={{ marginRight: 4 }}></i>添加明细行</button>
              <div className="mb-3 mt-2"><label className="form-label">备注</label><input type="text" className="form-control" value={addRemark} onChange={e => setAddRemark(e.target.value)} maxLength={500} /></div>
            </div>
            <div className="pp-mo-f">
              <button className="btn btn-secondary" onClick={() => setAddOpen(false)}>取消</button>
              <button className="btn btn-primary" onClick={doAddSubmit} disabled={createMut.isPending}>{createMut.isPending ? "提交中..." : "创建计划"}</button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editOpen && (
        <div className="pp-mo show" onClick={() => setEditOpen(false)}>
          <div className="pp-mo-box" onClick={e => e.stopPropagation()}>
            <div className="pp-mo-h"><h5>编辑采购计划</h5><button className="pp-mo-x" onClick={() => setEditOpen(false)}><i className="fas fa-times"></i></button></div>
            <div className="pp-mo-b">
              <div className="mb-3"><label className="form-label">状态</label>
                <select className="form-select" value={editStatus} onChange={e => setEditStatus(e.target.value)}>
                  <option value="pending">待确认</option><option value="confirmed">已确认</option><option value="completed">已完成</option><option value="cancelled">已取消</option>
                </select>
              </div>
              <div className="mb-3"><label className="form-label">备注</label><input type="text" className="form-control" value={editRemark} onChange={e => setEditRemark(e.target.value)} maxLength={500} /></div>
            </div>
            <div className="pp-mo-f">
              <button className="btn btn-secondary" onClick={() => setEditOpen(false)}>取消</button>
              <button className="btn btn-primary" onClick={() => editMut.mutate({ id: editId, status: editStatus, remark: editRemark })} disabled={editMut.isPending}>保存</button>
            </div>
          </div>
        </div>
      )}

      {/* Upload Modal */}
      {uploadOpen && (
        <div className="pp-mo show" onClick={() => setUploadOpen(false)}>
          <div className="pp-mo-box pp-mo-lg" onClick={e => e.stopPropagation()}>
            <div className="pp-mo-h"><h5><i className="fas fa-file-excel" style={{ marginRight: 8 }}></i>批量上传采购计划</h5><button className="pp-mo-x" onClick={() => setUploadOpen(false)}><i className="fas fa-times"></i></button></div>
            <div className="pp-mo-b">
              <div className="pp-upload-zone" onClick={() => document.getElementById("ppUploadFile")?.click()}>
                <i className="fas fa-cloud-upload-alt" style={{ fontSize: 32, marginBottom: 8, color: "#6c757d" }}></i>
                <p style={{ marginBottom: 4 }}>拖拽Excel文件到此处，或点击选择文件</p>
                <small style={{ color: "#6c757d" }}>支持 .xlsx / .xls，单次最多10000行</small>
                <input type="file" id="ppUploadFile" accept=".xlsx,.xls" style={{ display: "none" }} onChange={() => { /* TODO: upload logic */ }} />
              </div>
              <div style={{ marginTop: 12, padding: 8, background: "#f8f9fa", borderRadius: 4 }}>
                <small style={{ color: "#6c757d" }}><i className="fas fa-info-circle" style={{ marginRight: 4 }}></i>
                  Excel格式：第1行标题（客户名称、产品名称、69码、数量、计划日期、备注），从第2行起为数据。所有行必须属于同一月份。</small>
              </div>
            </div>
            <div className="pp-mo-f">
              <button className="btn btn-secondary" onClick={() => setUploadOpen(false)}>关闭</button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirm */}
      {deleteId !== null && (
        <div className="pp-mo show" onClick={() => setDeleteId(null)}>
          <div className="pp-mo-box" onClick={e => e.stopPropagation()} style={{ maxWidth: 400 }}>
            <div className="pp-mo-h"><h5>确认删除</h5><button className="pp-mo-x" onClick={() => setDeleteId(null)}><i className="fas fa-times"></i></button></div>
            <div className="pp-mo-b"><p>确定删除该采购计划吗？此操作不可撤销。</p></div>
            <div className="pp-mo-f">
              <button className="btn btn-secondary" onClick={() => setDeleteId(null)}>取消</button>
              <button className="btn btn-danger" onClick={() => deleteMut.mutate(deleteId)} disabled={deleteMut.isPending}>{deleteMut.isPending ? "删除中..." : "删除"}</button>
            </div>
          </div>
        </div>
      )}

      <style jsx global>{`
        .pp-wrap { padding: 20px; max-width: 1400px; margin: 0 auto; font-family: "Microsoft YaHei","Segoe UI",sans-serif; }
        .pp-wrap h2 { font-size: 22px; font-weight: 600; color: #5A4A4A; margin-bottom: 16px; display: flex; align-items: center; }
        .pp-top-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
        .pp-top-left { display: flex; align-items: center; gap: 6px; }
        .pp-top-right { display: flex; gap: 8px; }
        .form-control-sm { padding: 4px 8px; font-size: 14px; }
        .pp-card { border: none; border-radius: var(--radius-card); box-shadow: 0 4px 16px rgba(176,224,230,0.25); overflow: hidden; background: #fff; }
        .pp-card .card-header { padding: 12px 20px; background: #FFFFFF; border-bottom: 2px solid #87CEEB; font-weight: 600; font-size: 14px; color: #5A4A4A; }
        .pp-card .card-body { padding: 20px; }
        .pp-customer-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .pp-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 12px; border-radius: 20px; font-size: 13px; cursor: pointer; transition: all 0.2s; border: 2px solid #D4F1F4; background: #fff; color: #5A4A4A; white-space: nowrap; }
        .pp-chip:hover { border-color: #87CEEB; color: #5A4A4A; transform: translateY(-1px); }
        .pp-chip.active { background: linear-gradient(135deg, #B0E0E6, #87CEEB); color: #2c5282; border-color: #87CEEB; }
        .pp-stats-row { display: flex; text-align: center; }
        .pp-stats-row > div { flex: 1; padding: 4px; }
        .pp-stat { background: #fff; padding: 8px; border-radius: var(--radius-md); box-shadow: 0 4px 16px rgba(176,224,230,0.25); text-align: center; }
        .pp-stat h3 { font-size: 1.4rem; font-weight: 700; color: #5A4A4A; margin: 0; }
        .pp-stat small { color: #595959; }
        .pp-cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
        .pp-cal-hd { text-align: center; font-weight: 600; padding: 6px 0; background: #FFFFFF; border-radius: var(--radius-sm); font-size: 13px; color: #595959; }
        .pp-cal-cell { min-height: 80px; padding: 4px; border: 2px solid #D4F1F4; border-radius: var(--radius-md); font-size: 12px; overflow: hidden; position: relative; cursor: pointer; transition: box-shadow 0.15s; }
        .pp-cal-cell:hover { box-shadow: 0 2px 8px rgba(176,224,230,0.25); }
        .pp-cal-cell.empty { background: #FAFBFC; cursor: default; }
        .pp-cal-cell .cell-date { font-weight: 700; font-size: 14px; color: #5A4A4A; margin-bottom: 2px; }
        .pp-cal-cell .cell-item { padding: 1px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .pp-cal-cell .cell-more { color: #02669e; font-weight: 500; cursor: pointer; }
        .pp-cal-cell.today { border: 2px solid #87CEEB; }
        .pp-cal-cell.has-warning { background: #FFF8E1; }
        .stock-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 3px; vertical-align: middle; }
        .stock-dot.sufficient { background: #2E7D32; }
        .stock-dot.shortage { background: #F57C00; }
        .pp-row-warning { background-color: #FFF3CD !important; border-left: 3px solid #E57373; }
        .pp-row-completed { background-color: #E8F5E9 !important; border-left: 3px solid #66BB6A; }
        .pp-badge-sufficient { background-color: #2E7D32; }
        .pp-badge-shortage { background-color: #F57C00; color: #212529; }
        .pp-badge-no_stock { background-color: #E57373; }
        .pp-progress { height: 6px; border-radius: 3px; background: #E8ECF0; overflow: hidden; }
        .pp-progress-bar { height: 100%; border-radius: 3px; transition: width 0.3s; }
        .pp-pb-completed { background-color: #2E7D32; }
        .pp-pb-partial { background-color: #87CEEB; }
        .pp-pb-pending { background-color: #B0BEC5; }
        .pp-td-center { text-align: center; padding: 40px 20px; }
        .pp-mo { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; justify-content: center; align-items: center; z-index: 1000; }
        .pp-mo-box { background: #fff; border-radius: var(--radius-xl); width: 90%; max-width: 500px; max-height: 90vh; overflow: hidden; box-shadow: 0 12px 48px rgba(135,206,235,0.35); display: flex; flex-direction: column; border: 3px solid #D4F1F4; }
        .pp-mo-lg { max-width: 700px; }
        .pp-mo-h { padding: 16px 20px; border-bottom: 2px solid #87CEEB; display: flex; justify-content: space-between; align-items: center; }
        .pp-mo-h h5 { margin: 0; font-size: 16px; display: flex; align-items: center; color: #5A4A4A; }
        .pp-mo-x { background: none; border: none; font-size: 18px; cursor: pointer; color: #6c757d; }
        .pp-mo-x:hover { color: #C62828; }
        .pp-mo-b { padding: 20px; overflow-y: auto; flex: 1; }
        .pp-mo-f { padding: 12px 20px; border-top: 2px solid #D4F1F4; display: flex; justify-content: flex-end; gap: 8px; }
        .pp-detail-row { border: 2px solid #D4F1F4; border-radius: var(--radius-sm); padding: 8px; margin-bottom: 8px; }
        .pp-upload-zone { border: 2px dashed #B0E0E6; border-radius: var(--radius-lg); padding: 24px; text-align: center; cursor: pointer; transition: border-color 0.2s; }
        .pp-upload-zone:hover { border-color: #87CEEB; background: #F0F7FF; }
        @keyframes pp-spin { to { transform: rotate(360deg); } }
        .col-3 { flex: 0 0 25%; max-width: 25%; }
        .col-6 { flex: 0 0 50%; max-width: 50%; }
        @media (max-width: 768px) {
          .pp-top-bar { flex-direction: column; align-items: flex-start; }
          .pp-cal-grid { font-size: 10px; }
          .pp-cal-cell { min-height: 50px; }
          .pp-stats-row { flex-wrap: wrap; }
          .pp-stats-row > div { flex: 0 0 33.333%; }
        }
      `}</style>
    </div>
  );
}
