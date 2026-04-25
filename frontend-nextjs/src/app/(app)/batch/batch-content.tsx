"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api-client";

// ============ Types ============

interface BatchItem {
  id: number; sku_code: string; batch_no: string; status: string;
  quantity: number; remark: string; create_time: string; update_time: string;
}

export interface BatchStats {
  success: boolean; total: number; active: number; frozen: number; expired: number;
}

export interface BatchListResult {
  success: boolean; items: BatchItem[]; total: number; pages: number; current_page: number;
}

// ============ Component ============

interface BatchContentProps {
  initialStats?: BatchStats;
  initialList?: BatchListResult;
}

export function BatchContent({ initialStats, initialList }: BatchContentProps) {
  const [page, setPage] = useState(1);
  const [fBatchNo, setFBatchNo] = useState("");
  const [fSkuCode, setFSkuCode] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [fStartDate, setFStartDate] = useState("");
  const [fEndDate, setFEndDate] = useState("");
  const [sortBy, setSortBy] = useState("create_time");
  const [sortOrder, setSortOrder] = useState("desc");
  const [detailItem, setDetailItem] = useState<BatchItem | null>(null);
  const [perPage, setPerPage] = useState(20);

  const { data: statsData } = useQuery<BatchStats>({
    queryKey: ["batch-stats"],
    queryFn: () => get<BatchStats>("/sku-batches/stats"),
    initialData: initialStats,
  });

  const { data: listData, isLoading } = useQuery<BatchListResult>({
    queryKey: ["batch-list", page, fBatchNo, fSkuCode, fStatus, fStartDate, fEndDate, sortBy, sortOrder, perPage],
    queryFn: () => get<BatchListResult>("/sku-batches/batches", {
      page: String(page), per_page: String(perPage),
      sort_by: sortBy, sort_order: sortOrder,
      ...(fBatchNo && { batch_no: fBatchNo }),
      ...(fSkuCode && { sku_code: fSkuCode }),
      ...(fStatus && { status: fStatus }),
      ...(fStartDate && { start_date: fStartDate }),
      ...(fEndDate && { end_date: fEndDate }),
    }),
    initialData: initialList && page === 1 && !fBatchNo && !fSkuCode && !fStatus && !fStartDate && !fEndDate
      ? initialList
      : undefined,
  });

  const items = listData?.items || [];
  const totalPages = listData?.pages || 1;
  const stats = statsData;

  const statusMap: Record<string, string> = { active: "在用", frozen: "冻结", expired: "过期" };
  const badgeMap: Record<string, string> = { active: "sb-badge-active", frozen: "sb-badge-frozen", expired: "sb-badge-expired" };

  const toggleSort = (field: string) => {
    if (sortBy === field) setSortOrder(prev => prev === "desc" ? "asc" : "desc");
    else { setSortBy(field); setSortOrder("asc"); }
    setPage(1);
  };

  const resetFilters = () => { setFBatchNo(""); setFSkuCode(""); setFStatus(""); setFStartDate(""); setFEndDate(""); setSortBy("create_time"); setSortOrder("desc"); setPage(1); };

  const sortIcon = (field: string) => sortBy === field ? (sortOrder === "asc" ? "fa-sort-up" : "fa-sort-down") : "fa-sort";

  const exportData = () => {
    if (!items.length) return;
    const headers = ["SKU编号","批次号","创建时间","批次状态","数量","备注","更新时间"];
    const rows = items.map(i => [i.sku_code, i.batch_no, i.create_time, statusMap[i.status]||i.status, i.quantity, i.remark||"", i.update_time]);
    let csv = "\uFEFF" + headers.join(",") + "\n";
    rows.forEach(r => { csv += r.map(c => `"${String(c).replace(/"/g,'""')}"`).join(",") + "\n"; });
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `批次管理_${new Date().toISOString().slice(0,10)}.csv`;
    link.click();
  };

  return (
    <div className="sb-wrap">
      {/* Header */}
      <div className="sb-header">
        <div>
          <h1><i className="fas fa-layer-group"></i> 批次管理</h1>
          <div className="sb-header-sub">SKU批次信息查询 · 状态追踪 · 批次筛选</div>
        </div>
        <div className="sb-header-stats">
          <div className="sb-header-stat"><b>{stats?.total ?? 0}</b><small>总批次</small></div>
          <div className="sb-header-stat"><b>{stats?.active ?? 0}</b><small>在用</small></div>
          <div className="sb-header-stat"><b>{stats?.frozen ?? 0}</b><small>冻结</small></div>
          <div className="sb-header-stat"><b>{stats?.expired ?? 0}</b><small>过期</small></div>
        </div>
      </div>

      {/* Stat cards */}
      <div className="sb-stats">
        <div className="sb-sc s-total"><div className="sb-sv">{stats?.total ?? 0}</div><div className="sb-sl">总批次</div></div>
        <div className="sb-sc s-active"><div className="sb-sv">{stats?.active ?? 0}</div><div className="sb-sl">在用</div></div>
        <div className="sb-sc s-frozen"><div className="sb-sv">{stats?.frozen ?? 0}</div><div className="sb-sl">冻结</div></div>
        <div className="sb-sc s-expired"><div className="sb-sv">{stats?.expired ?? 0}</div><div className="sb-sl">过期</div></div>
      </div>

      {/* Filters */}
      <div className="sb-card">
        <div className="sb-card-h">
          <div className="sb-card-t"><i className="fas fa-filter"></i> 筛选条件</div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="sb-btn sb-btn-o" onClick={exportData}><i className="fas fa-file-export"></i> 导出</button>
          </div>
        </div>
        <div className="sb-card-b">
          <div className="sb-filters">
            <div className="sb-fg"><label>批次号</label><input type="text" value={fBatchNo} onChange={e => setFBatchNo(e.target.value)} placeholder="请输入批次号" /></div>
            <div className="sb-fg"><label>SKU编号</label><input type="text" value={fSkuCode} onChange={e => setFSkuCode(e.target.value)} placeholder="请输入SKU编号" /></div>
            <div className="sb-fg"><label>批次状态</label><select value={fStatus} onChange={e => setFStatus(e.target.value)}><option value="">全部</option><option value="active">在用</option><option value="frozen">冻结</option><option value="expired">过期</option></select></div>
            <div className="sb-fg"><label>创建日期</label><input type="date" value={fStartDate} onChange={e => setFStartDate(e.target.value)} /><span style={{ color: "var(--sb-text3)" }}>~</span><input type="date" value={fEndDate} onChange={e => setFEndDate(e.target.value)} /></div>
            <button className="sb-btn sb-btn-p" onClick={() => setPage(1)}><i className="fas fa-search"></i> 查询</button>
            <button className="sb-btn sb-btn-o" onClick={resetFilters}><i className="fas fa-redo"></i> 重置</button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="sb-card">
        <div className="sb-card-b" style={{ padding: 0, overflowX: "auto" }}>
          <table className="sb-tbl" style={{ minWidth: 1000 }}>
            <thead>
              <tr>
                <th className="sortable" onClick={() => toggleSort("sku_code")}>SKU编号 <span className="sort-icon"><i className={`fas ${sortIcon("sku_code")}`}></i></span></th>
                <th className="sortable" onClick={() => toggleSort("batch_no")}>批次号 <span className="sort-icon"><i className={`fas ${sortIcon("batch_no")}`}></i></span></th>
                <th className="sortable" onClick={() => toggleSort("create_time")}>创建时间 <span className="sort-icon"><i className={`fas ${sortIcon("create_time")}`}></i></span></th>
                <th>批次状态</th>
                <th className="sortable" onClick={() => toggleSort("quantity")}>数量 <span className="sort-icon"><i className={`fas ${sortIcon("quantity")}`}></i></span></th>
                <th>备注</th>
                <th className="sortable" onClick={() => toggleSort("update_time")}>更新时间 <span className="sort-icon"><i className={`fas ${sortIcon("update_time")}`}></i></span></th>
                <th style={{ width: 80 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={8} className="sb-empty"><i className="fas fa-spinner fa-spin"></i><p>加载中...</p></td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={8} className="sb-empty"><i className="fas fa-inbox"></i><p>暂无批次数据</p></td></tr>
              ) : items.map(item => (
                <tr key={item.id}>
                  <td style={{ fontWeight: 500 }}>{item.sku_code}</td>
                  <td style={{ fontWeight: 600, color: "var(--sb-primary)" }}>{item.batch_no}</td>
                  <td style={{ color: "var(--sb-text2)" }}>{item.create_time}</td>
                  <td><span className={`sb-badge ${badgeMap[item.status] || ""}`}>{statusMap[item.status] || item.status}</span></td>
                  <td style={{ textAlign: "right", fontWeight: 600 }}>{Number(item.quantity).toLocaleString()}</td>
                  <td style={{ color: "var(--sb-text2)", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.remark || "-"}</td>
                  <td style={{ color: "var(--sb-text2)", fontSize: 13 }}>{item.update_time}</td>
                  <td><button className="btn-action btn-action-view" title="查看详情" onClick={() => setDetailItem(item)}><i className="fas fa-eye"></i></button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {/* Pagination */}
          <div className="sb-pagi">
            <div className="sb-pagi-left">
              <select value={perPage} onChange={e => { setPerPage(Number(e.target.value)); setPage(1); }}>
                {[10,20,50,100].map(n => <option key={n} value={n}>{n}条/页</option>)}
              </select>
              <span className="pi">共 {listData?.total ?? 0} 条</span>
            </div>
            <div className="sb-pagi-right">
              <button onClick={() => setPage(1)} disabled={page <= 1}><i className="fas fa-angle-double-left"></i></button>
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}><i className="fas fa-angle-left"></i></button>
              {Array.from({ length: totalPages }, (_, i) => i + 1).filter(p => Math.abs(p - page) <= 2 || p === 1 || p === totalPages).map(p => (
                <button key={p} onClick={() => setPage(p)} className={p === page ? "act" : ""}>{p}</button>
              ))}
              <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}><i className="fas fa-angle-right"></i></button>
              <button onClick={() => setPage(totalPages)} disabled={page >= totalPages}><i className="fas fa-angle-double-right"></i></button>
            </div>
          </div>
        </div>
      </div>

      {/* Detail modal */}
      {detailItem && (
        <div className="sb-mo show" onClick={() => setDetailItem(null)}>
          <div className="sb-mo-box" onClick={e => e.stopPropagation()}>
            <div className="sb-mo-h"><h3><i className="fas fa-clipboard-list" style={{ color: "var(--sb-primary)" }}></i> 批次详情</h3><button className="sb-mo-x" onClick={() => setDetailItem(null)}><i className="fas fa-times"></i></button></div>
            <div className="sb-mo-b">
              <div className="sb-det-grid">
                <div className="sb-det-item"><div className="sb-det-lb">SKU编号</div><div className="sb-det-vl">{detailItem.sku_code}</div></div>
                <div className="sb-det-item"><div className="sb-det-lb">批次号</div><div className="sb-det-vl" style={{ color: "var(--sb-primary)" }}>{detailItem.batch_no}</div></div>
                <div className="sb-det-item"><div className="sb-det-lb">批次状态</div><div className="sb-det-vl"><span className={`sb-badge ${badgeMap[detailItem.status] || ""}`}>{statusMap[detailItem.status] || detailItem.status}</span></div></div>
                <div className="sb-det-item"><div className="sb-det-lb">数量</div><div className="sb-det-vl">{Number(detailItem.quantity).toLocaleString()}</div></div>
                <div className="sb-det-item"><div className="sb-det-lb">创建时间</div><div className="sb-det-vl">{detailItem.create_time}</div></div>
                <div className="sb-det-item"><div className="sb-det-lb">更新时间</div><div className="sb-det-vl">{detailItem.update_time}</div></div>
              </div>
              <div style={{ marginTop: 20 }}>
                <div className="sb-det-lb" style={{ marginBottom: 8 }}>备注</div>
                <div style={{ padding: "12px 16px", background: "var(--sb-bg)", borderRadius: "var(--sb-r-sm)", color: "var(--sb-text)", fontSize: 14, minHeight: 40 }}>{detailItem.remark || "无"}</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* CSS - matches sku_batch.html exactly */}
      <style jsx global>{`
        :root { --sb-primary: #5B8DEF; --sb-primary-dark: #4A7DE8; --sb-primary-light: #E8F2FF; --sb-primary-lighter: #F0F6FF; --sb-success: #28C76F; --sb-warning: #FF9F43; --sb-danger: #EA5456; --sb-info: #00CFE8; --sb-purple: #8B5CF6; --sb-text: #2D3748; --sb-text2: #718096; --sb-text3: #A0AEC0; --sb-border: #E2E8F0; --sb-bg: #F8FAFC; --sb-r-sm: 6px; --sb-r-md: 10px; --sb-r-lg: 14px; --sb-shadow: 0 1px 3px rgba(0,0,0,0.08); --sb-shadow-md: 0 4px 12px rgba(0,0,0,0.1); --sb-ease: all 0.25s ease; }
        .sb-wrap { padding: 24px; max-width: 1920px; margin: 0 auto; font-family: "Microsoft YaHei","Segoe UI",sans-serif; }
        .sb-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding: 20px 28px; background: linear-gradient(135deg,#5B8DEF 0%,#8B5CF6 100%); border-radius: var(--sb-r-lg); color: #fff; box-shadow: var(--sb-shadow-md); }
        .sb-header h1 { font-size: 26px; font-weight: 700; margin: 0; display: flex; align-items: center; gap: 12px; }
        .sb-header-sub { font-size: 14px; opacity: 0.85; margin-top: 6px; }
        .sb-header-stats { display: flex; gap: 32px; }
        .sb-header-stat { text-align: center; }
        .sb-header-stat b { font-size: 30px; display: block; }
        .sb-header-stat small { font-size: 12px; opacity: 0.8; }
        .sb-card { background: #fff; border-radius: var(--sb-r-md); box-shadow: var(--sb-shadow); border: 1px solid var(--sb-border); margin-bottom: 24px; }
        .sb-card-h { padding: 18px 24px; border-bottom: 1px solid var(--sb-border); display: flex; justify-content: space-between; align-items: center; }
        .sb-card-t { font-size: 16px; font-weight: 600; color: var(--sb-text); display: flex; align-items: center; gap: 10px; }
        .sb-card-t i { color: var(--sb-primary); }
        .sb-card-b { padding: 24px; }
        .sb-filters { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
        .sb-fg { display: flex; align-items: center; gap: 6px; }
        .sb-fg label { font-size: 13px; color: var(--sb-text2); white-space: nowrap; font-weight: 500; }
        .sb-fg select, .sb-fg input { padding: 8px 12px; border: 1px solid var(--sb-border); border-radius: var(--sb-r-sm); font-size: 13px; min-width: 120px; transition: var(--sb-ease); background: #fff; color: var(--sb-text); }
        .sb-fg select:focus, .sb-fg input:focus { outline: none; border-color: var(--sb-primary); box-shadow: 0 0 0 3px rgba(91,141,239,0.1); }
        .sb-fg input::placeholder { color: var(--sb-text3); }
        .sb-fg input[type="date"] { min-width: 140px; }
        .sb-btn { padding: 8px 18px; border-radius: var(--sb-r-sm); font-size: 14px; font-weight: 500; cursor: pointer; transition: var(--sb-ease); border: none; display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
        .sb-btn-p { background: var(--sb-primary); color: #fff; }
        .sb-btn-p:hover { background: var(--sb-primary-dark); }
        .sb-btn-o { background: #fff; color: var(--sb-text); border: 1px solid var(--sb-border); }
        .sb-btn-o:hover { background: var(--sb-primary-lighter); border-color: var(--sb-primary); color: var(--sb-primary); }
        .sb-stats { display: grid; grid-template-columns: repeat(4,1fr); gap: 16px; margin-bottom: 24px; }
        .sb-sc { background: #fff; border-radius: var(--sb-r-md); padding: 20px; box-shadow: var(--sb-shadow); border: 1px solid var(--sb-border); transition: var(--sb-ease); position: relative; overflow: hidden; }
        .sb-sc:hover { transform: translateY(-2px); box-shadow: var(--sb-shadow-md); }
        .sb-sc::before { content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px; }
        .sb-sc.s-total::before { background: var(--sb-purple); }
        .sb-sc.s-active::before { background: var(--sb-success); }
        .sb-sc.s-frozen::before { background: var(--sb-warning); }
        .sb-sc.s-expired::before { background: var(--sb-danger); }
        .sb-sv { font-size: 30px; font-weight: 700; }
        .sb-sc.s-total .sb-sv { color: var(--sb-purple); }
        .sb-sc.s-active .sb-sv { color: var(--sb-success); }
        .sb-sc.s-frozen .sb-sv { color: var(--sb-warning); }
        .sb-sc.s-expired .sb-sv { color: var(--sb-danger); }
        .sb-sl { font-size: 14px; color: var(--sb-text2); margin-top: 6px; }
        .sb-tbl { width: 100%; border-collapse: collapse; font-size: 15px; table-layout: auto; }
        .sb-tbl th { background: var(--sb-primary-lighter); padding: 18px 22px; text-align: left; font-weight: 600; color: var(--sb-text); border-bottom: 2px solid var(--sb-border); font-size: 14px; white-space: nowrap; user-select: none; }
        .sb-tbl th.sortable { cursor: pointer; position: relative; padding-right: 28px; }
        .sb-tbl th.sortable:hover { color: var(--sb-primary); }
        .sb-tbl th .sort-icon { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); font-size: 10px; color: var(--sb-text3); opacity: 0.5; }
        .sb-tbl td { padding: 18px 22px; border-bottom: 1px solid var(--sb-border); vertical-align: middle; }
        .sb-tbl tbody tr { transition: var(--sb-ease); }
        .sb-tbl tbody tr:hover { background: var(--sb-primary-lighter); }
        .sb-badge { display: inline-flex; align-items: center; padding: 5px 12px; border-radius: 20px; font-size: 13px; font-weight: 500; gap: 4px; }
        .sb-badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
        .sb-badge-active { background: #D1FAE5; color: #059669; }
        .sb-badge-active::before { background: #059669; }
        .sb-badge-frozen { background: #FEF3C7; color: #D97706; }
        .sb-badge-frozen::before { background: #D97706; }
        .sb-badge-expired { background: #FEE2E2; color: #DC2626; }
        .sb-badge-expired::before { background: #DC2626; }
        .btn-action { width: 36px; height: 36px; border-radius: 10px; border: none; display: flex; align-items: center; justify-content: center; font-size: 0.9rem; transition: all 0.2s ease; cursor: pointer; }
        .btn-action-view { background: #dbeafe; color: #1d4ed8; }
        .btn-action-view:hover { background: #bfdbfe; transform: scale(1.1); }
        .sb-empty { text-align: center; padding: 60px 20px; color: var(--sb-text3); }
        .sb-empty i { font-size: 48px; margin-bottom: 16px; opacity: 0.5; display: block; }
        .sb-pagi { display: flex; justify-content: space-between; align-items: center; padding: 18px; border-top: 1px solid var(--sb-border); font-size: 14px; color: var(--sb-text2); }
        .sb-pagi-left { display: flex; align-items: center; gap: 8px; }
        .sb-pagi-right { display: flex; align-items: center; gap: 4px; }
        .sb-pagi select { padding: 6px 10px; border: 1px solid var(--sb-border); border-radius: var(--sb-r-sm); font-size: 13px; }
        .sb-pagi button { padding: 8px 14px; border: 1px solid var(--sb-border); background: #fff; border-radius: var(--sb-r-sm); cursor: pointer; transition: var(--sb-ease); font-size: 14px; min-width: 34px; text-align: center; }
        .sb-pagi button:hover:not(:disabled) { border-color: var(--sb-primary); color: var(--sb-primary); }
        .sb-pagi button.act { background: var(--sb-primary); color: #fff; border-color: var(--sb-primary); }
        .sb-pagi button:disabled { opacity: 0.4; cursor: not-allowed; }
        .sb-pagi .pi { font-size: 14px; color: var(--sb-text2); }
        .sb-mo { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; justify-content: center; align-items: center; z-index: 1000; backdrop-filter: blur(4px); }
        .sb-mo-box { background: #fff; border-radius: var(--sb-r-lg); width: 90%; max-width: 640px; max-height: 90vh; overflow: hidden; box-shadow: 0 8px 24px rgba(0,0,0,0.12); }
        .sb-mo-h { padding: 20px 24px; border-bottom: 1px solid var(--sb-border); display: flex; justify-content: space-between; align-items: center; }
        .sb-mo-h h3 { margin: 0; font-size: 18px; color: var(--sb-text); display: flex; align-items: center; gap: 8px; }
        .sb-mo-x { background: none; border: none; font-size: 20px; cursor: pointer; color: var(--sb-text3); }
        .sb-mo-x:hover { color: var(--sb-danger); }
        .sb-mo-b { padding: 28px; max-height: calc(90vh - 80px); overflow-y: auto; }
        .sb-det-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .sb-det-item { margin-bottom: 4px; }
        .sb-det-lb { font-size: 12px; color: var(--sb-text3); margin-bottom: 6px; }
        .sb-det-vl { font-size: 15px; font-weight: 600; color: var(--sb-text); }
        @media (max-width: 1200px) { .sb-stats { grid-template-columns: repeat(2,1fr); } }
        @media (max-width: 768px) { .sb-filters { flex-direction: column; align-items: stretch; } .sb-fg { width: 100%; } .sb-fg select,.sb-fg input { min-width: 0; flex: 1; } .sb-header { flex-direction: column; gap: 12px; } .sb-tbl { font-size: 12px; } .sb-tbl th,.sb-tbl td { padding: 10px 12px; } .sb-pagi { flex-direction: column; gap: 8px; } .sb-stats { grid-template-columns: 1fr; } .sb-det-grid { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
