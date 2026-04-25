"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/lib/api-client";

// ============ Types ============

interface ApprovalItem {
  id: number; order_no: string; operation_type: string;
  requester_name: string; request_time: string; status: string;
  approver_name: string; approval_time: string;
}

export interface ApprovalListResult {
  success: boolean; approvals: ApprovalItem[];
  pending_count: number; approved_count: number; rejected_count: number;
  total: number; pages: number; current_page: number;
}

interface ApprovalDetailResult {
  success: boolean; approval: Record<string, unknown>;
}

// ============ Component ============

interface ApprovalContentProps {
  initialData?: ApprovalListResult;
}

export function ApprovalContent({ initialData }: ApprovalContentProps) {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("pending");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectId, setRejectId] = useState<number | null>(null);
  const [rejectReason, setRejectReason] = useState("");

  const { data, isLoading } = useQuery<ApprovalListResult>({
    queryKey: ["approvals", statusFilter, search, page],
    queryFn: () => get<ApprovalListResult>("/approvals/list", {
      status: statusFilter,
      ...(search && { search }),
      page: String(page),
      per_page: "20",
    }),
    initialData: initialData && statusFilter === "pending" && !search && page === 1 ? initialData : undefined,
  });

  const approveMut = useMutation({
    mutationFn: (id: number) => post<Record<string, unknown>>(`/approvals/approve/${id}`, {}),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["approvals"] }); },
  });

  const rejectMut = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) => post<Record<string, unknown>>(`/approvals/reject/${id}`, { reason }),
    onSuccess: () => { setRejectOpen(false); setRejectReason(""); qc.invalidateQueries({ queryKey: ["approvals"] }); },
  });

  const approvals = data?.approvals || [];
  const pendingCount = data?.pending_count || 0;
  const approvedCount = data?.approved_count || 0;
  const rejectedCount = data?.rejected_count || 0;
  const totalPages = data?.pages || 1;

  const statusBadge = (s: string) => {
    const m: Record<string, string> = { pending: "bg-warning", approved: "bg-success", rejected: "bg-danger", cancelled: "bg-secondary" };
    const t: Record<string, string> = { pending: "待审批", approved: "已同意", rejected: "已拒绝", cancelled: "已取消" };
    return <span className={`ap-badge ${m[s] || "bg-info"}`}>{t[s] || s}</span>;
  };

  const opBadge = (t: string) => t === "edit"
    ? <span className="ap-badge bg-primary"><i className="fas fa-edit" style={{ marginRight: 2 }}></i>编辑</span>
    : <span className="ap-badge bg-danger"><i className="fas fa-trash" style={{ marginRight: 2 }}></i>删除</span>;

  return (
    <div className="ap-page-root">
      <h2 className="ap-page-title">审批管理</h2>

      {/* Stats cards */}
      <div className="ap-stats-row">
        <div className="ap-stat-card" style={{ borderLeft: "4px solid #f59e0b" }}>
          <div className="ap-stat-body">
            <div><h6 style={{ color: "#6c757d", margin: "0 0 4px" }}>待审批</h6><h3 style={{ margin: 0, color: "#f59e0b" }}>{pendingCount}</h3></div>
            <div className="ap-stat-icon" style={{ background: "rgba(245,158,11,0.1)", borderRadius: "50%", padding: 12 }}><i className="fas fa-clock" style={{ color: "#f59e0b", fontSize: 18 }}></i></div>
          </div>
        </div>
        <div className="ap-stat-card" style={{ borderLeft: "4px solid #10b981" }}>
          <div className="ap-stat-body">
            <div><h6 style={{ color: "#6c757d", margin: "0 0 4px" }}>已同意</h6><h3 style={{ margin: 0, color: "#10b981" }}>{approvedCount}</h3></div>
            <div className="ap-stat-icon" style={{ background: "rgba(16,185,129,0.1)", borderRadius: "50%", padding: 12 }}><i className="fas fa-check" style={{ color: "#10b981", fontSize: 18 }}></i></div>
          </div>
        </div>
        <div className="ap-stat-card" style={{ borderLeft: "4px solid #ef4444" }}>
          <div className="ap-stat-body">
            <div><h6 style={{ color: "#6c757d", margin: "0 0 4px" }}>已拒绝</h6><h3 style={{ margin: 0, color: "#ef4444" }}>{rejectedCount}</h3></div>
            <div className="ap-stat-icon" style={{ background: "rgba(239,68,68,0.1)", borderRadius: "50%", padding: 12 }}><i className="fas fa-times" style={{ color: "#ef4444", fontSize: 18 }}></i></div>
          </div>
        </div>
        <div className="ap-stat-card" style={{ borderLeft: "4px solid #6b7280" }}>
          <div className="ap-stat-body">
            <div><h6 style={{ color: "#6c757d", margin: "0 0 4px" }}>总计</h6><h3 style={{ margin: 0 }}>{pendingCount + approvedCount + rejectedCount}</h3></div>
            <div className="ap-stat-icon" style={{ background: "rgba(107,114,128,0.1)", borderRadius: "50%", padding: 12 }}><i className="fas fa-list" style={{ color: "#6b7280", fontSize: 18 }}></i></div>
          </div>
        </div>
      </div>

      {/* List */}
      <div className="ap-card" style={{ marginTop: 16 }}>
        <div className="ap-card-header">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span>审批列表</span>
            <div style={{ display: "flex", width: 250 }}>
              <input type="text" className="ap-form-control" placeholder="搜索订单号/申请人..." value={search} onChange={e => setSearch(e.target.value)} onKeyDown={e => { if (e.key === "Enter") { setPage(1); qc.invalidateQueries({ queryKey: ["approvals"] }); } }} style={{ fontSize: 13, borderRadius: "6px 0 0 6px" }} />
              <button className="ap-btn ap-btn-outline-secondary" style={{ borderRadius: "0 6px 6px 0", padding: "4px 10px" }} onClick={() => { setPage(1); qc.invalidateQueries({ queryKey: ["approvals"] }); }}><i className="fas fa-search"></i></button>
            </div>
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            {(["pending", "approved", "rejected", "all"] as const).map(s => {
              const cls: Record<string, string> = { pending: "ap-btn-warning", approved: "ap-btn-success", rejected: "ap-btn-danger", all: "ap-btn-secondary" };
              const labels: Record<string, string> = { pending: "待审批", approved: "已同意", rejected: "已拒绝", all: "全部" };
              return (
                <button key={s} className={`ap-btn ap-btn-sm ${statusFilter === s ? cls[s] : `ap-btn-outline-${s === "pending" ? "warning" : s === "approved" ? "success" : s === "rejected" ? "danger" : "secondary"}`}`}
                  onClick={() => { setStatusFilter(s); setPage(1); }}>{labels[s]}</button>
              );
            })}
          </div>
        </div>
        <div className="ap-card-body" style={{ padding: 0 }}>
          {isLoading ? (
            <div className="ap-empty"><i className="fas fa-spinner fa-spin" style={{ fontSize: 32 }}></i><p>加载中...</p></div>
          ) : approvals.length === 0 ? (
            <div className="ap-empty"><i className="fas fa-inbox" style={{ fontSize: 48, opacity: 0.3 }}></i><p>{search ? `未找到匹配"${search}"的审批记录` : "暂无审批记录"}</p></div>
          ) : (
            <>
              <table className="ap-table">
                <thead><tr><th>审批ID</th><th>订单编号</th><th>操作类型</th><th>申请人</th><th>申请时间</th><th>状态</th><th>审批人</th><th>审批时间</th><th>操作</th></tr></thead>
                <tbody>
                  {approvals.map(item => (
                    <tr key={item.id}>
                      <td>#{item.id}</td>
                      <td>{item.order_no || <span style={{ color: "#6c757d" }}>订单已删除</span>}</td>
                      <td>{opBadge(item.operation_type)}</td>
                      <td>{item.requester_name || "-"}</td>
                      <td>{item.request_time || "-"}</td>
                      <td>{statusBadge(item.status)}</td>
                      <td>{item.approver_name || "-"}</td>
                      <td>{item.approval_time || "-"}</td>
                      <td>
                        <button className="ap-btn ap-btn-sm ap-btn-outline-primary" style={{ marginRight: 4 }}><i className="fas fa-eye" style={{ marginRight: 2 }}></i>详情</button>
                        {item.status === "pending" && (
                          <>
                            <button className="ap-btn ap-btn-sm ap-btn-outline-success" style={{ marginRight: 4 }} onClick={() => approveMut.mutate(item.id)}><i className="fas fa-check"></i></button>
                            <button className="ap-btn ap-btn-sm ap-btn-outline-danger" onClick={() => { setRejectId(item.id); setRejectReason(""); setRejectOpen(true); }}><i className="fas fa-times"></i></button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {/* Pagination */}
              {totalPages > 1 && (
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", borderTop: "1px solid #dee2e6", fontSize: 13 }}>
                  <span style={{ color: "#6c757d" }}>{approvals.length} 条记录</span>
                  <div style={{ display: "flex", gap: 4 }}>
                    {Array.from({ length: totalPages }, (_, i) => i + 1).filter(p => p === 1 || p === totalPages || Math.abs(p - page) <= 2).map(p => (
                      <button key={p} className={`ap-btn ap-btn-sm ${p === page ? "ap-btn-primary" : "ap-btn-outline-secondary"}`} onClick={() => setPage(p)}>{p}</button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Reject modal */}
      {rejectOpen && (
        <div className="ap-modal-overlay" onClick={() => setRejectOpen(false)}>
          <div className="ap-modal" onClick={e => e.stopPropagation()}>
            <div className="ap-modal-header"><h5>拒绝原因</h5><button className="ap-modal-close" onClick={() => setRejectOpen(false)}>&times;</button></div>
            <div className="ap-modal-body">
              <label className="ap-form-label">请输入拒绝原因</label>
              <textarea className="ap-form-control" rows={3} placeholder="请说明拒绝原因（可选）" value={rejectReason} onChange={e => setRejectReason(e.target.value)} />
            </div>
            <div className="ap-modal-footer">
              <button className="ap-btn ap-btn-secondary" onClick={() => setRejectOpen(false)}>取消</button>
              <button className="ap-btn ap-btn-danger" onClick={() => rejectId && rejectMut.mutate({ id: rejectId, reason: rejectReason })} disabled={rejectMut.isPending}>确认拒绝</button>
            </div>
          </div>
        </div>
      )}

      {/* CSS */}
      <style jsx global>{`
        .ap-page-root { padding: 16px 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; font-size: 14px; color: #333; }
        .ap-page-title { font-size: 22px; font-weight: 600; margin-bottom: 16px; }

        .ap-stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
        .ap-stat-card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); overflow: hidden; }
        .ap-stat-body { display: flex; justify-content: space-between; align-items: center; padding: 16px; }

        .ap-card { background: #fff; border: 1px solid #dee2e6; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
        .ap-card-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; background: #f8f9fa; border-bottom: 1px solid #dee2e6; font-weight: 600; font-size: 14px; flex-wrap: wrap; gap: 8px; }
        .ap-card-body { padding: 16px; }

        .ap-badge { display: inline-flex; align-items: center; gap: 2px; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: #fff; }
        .ap-badge.bg-warning { background: #ffc107; color: #333; }
        .ap-badge.bg-success { background: #28a745; }
        .ap-badge.bg-danger { background: #dc3545; }
        .ap-badge.bg-secondary { background: #6c757d; }
        .ap-badge.bg-primary { background: #007bff; }
        .ap-badge.bg-info { background: #17a2b8; }

        .ap-btn { display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; transition: all 0.15s; }
        .ap-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .ap-btn-primary { background: #007bff; color: #fff; }
        .ap-btn-secondary { background: #6c757d; color: #fff; }
        .ap-btn-danger { background: #dc3545; color: #fff; }
        .ap-btn-warning { background: #ffc107; color: #333; }
        .ap-btn-success { background: #28a745; color: #fff; }
        .ap-btn-outline-secondary { background: transparent; color: #6c757d; border-color: #6c757d; }
        .ap-btn-outline-secondary:hover:not(:disabled) { background: #6c757d; color: #fff; }
        .ap-btn-outline-primary { background: transparent; color: #007bff; border-color: #007bff; }
        .ap-btn-outline-primary:hover:not(:disabled) { background: #007bff; color: #fff; }
        .ap-btn-outline-success { background: transparent; color: #28a745; border-color: #28a745; }
        .ap-btn-outline-success:hover:not(:disabled) { background: #28a745; color: #fff; }
        .ap-btn-outline-danger { background: transparent; color: #dc3545; border-color: #dc3545; }
        .ap-btn-outline-danger:hover:not(:disabled) { background: #dc3545; color: #fff; }
        .ap-btn-outline-warning { background: transparent; color: #e0a800; border-color: #e0a800; }
        .ap-btn-outline-warning:hover:not(:disabled) { background: #e0a800; color: #fff; }
        .ap-btn-sm { padding: 3px 8px; font-size: 12px; }

        .ap-form-control { width: 100%; padding: 6px 10px; border: 1px solid #ced4da; border-radius: 6px; font-size: 13px; box-sizing: border-box; font-family: inherit; }
        .ap-form-control:focus { border-color: #80bdff; outline: none; box-shadow: 0 0 0 3px rgba(0,123,255,0.15); }
        .ap-form-label { display: block; margin-bottom: 4px; font-size: 13px; font-weight: 500; color: #495057; }

        .ap-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .ap-table th { padding: 8px 12px; background: #f8f9fa; border-bottom: 2px solid #dee2e6; font-weight: 600; text-align: left; white-space: nowrap; }
        .ap-table td { padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: middle; }
        .ap-table tbody tr:hover { background: #f8f9fa; }

        .ap-empty { text-align: center; padding: 40px; color: #6c757d; }
        .ap-empty p { margin: 8px 0 0; font-size: 14px; }

        .ap-modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1050; }
        .ap-modal { background: #fff; border-radius: 12px; width: 480px; max-width: 90vw; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
        .ap-modal-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid #dee2e6; }
        .ap-modal-header h5 { margin: 0; font-size: 16px; font-weight: 600; }
        .ap-modal-close { background: none; border: none; font-size: 22px; cursor: pointer; color: #6c757d; }
        .ap-modal-close:hover { color: #333; }
        .ap-modal-body { padding: 20px; }
        .ap-modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid #dee2e6; }

        @media (max-width: 992px) { .ap-stats-row { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 768px) { .ap-stats-row { grid-template-columns: 1fr; } .ap-page-root { padding: 8px 12px; } }
      `}</style>
    </div>
  );
}
