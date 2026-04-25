"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, del } from "@/lib/api-client";
import { ChevronDownIcon } from "lucide-react";

interface Supplier {
  id: number;
  name: string;
  contact_person: string;
  phone: string;
  address: string;
  remark: string;
  created_at: string;
}

export interface SupplierListResult {
  success: boolean;
  data: Supplier[];
  total: number;
}

interface SupplierContentProps {
  initialData?: SupplierListResult;
}

export function SupplierContent({ initialData }: SupplierContentProps) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [contactPerson, setContactPerson] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [remark, setRemark] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [formCollapsed, setFormCollapsed] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["suppliers-list"],
    queryFn: () => get<SupplierListResult>("/suppliers/list"),
    initialData,
  });

  const createMutation = useMutation({
    mutationFn: () => post<{ success: boolean; message?: string }>("/suppliers/create", { name, contact_person: contactPerson, phone, address, remark }),
    onSuccess: (res) => { alert(res.message || "添加成功"); setName(""); setContactPerson(""); setPhone(""); setAddress(""); setRemark(""); qc.invalidateQueries({ queryKey: ["suppliers-list"] }); },
    onError: (err: Error) => alert(err.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => del<{ success: boolean; error?: string }>(`/suppliers/delete/${id}`),
    onSuccess: (res) => { if (res.success) { qc.invalidateQueries({ queryKey: ["suppliers-list"] }); } else { alert(res.error || "删除失败"); } },
    onError: (err: Error) => alert(err.message),
  });

  const suppliers = (data?.data ?? []).filter(s => !searchTerm || s.name.toLowerCase().includes(searchTerm.toLowerCase()));

  return (
    <div className="sp-page-root">
      <div className="container-fluid">
        <div className="page-header-wrapper">
          <h2 className="page-title">供应商管理</h2>
          <p className="page-subtitle">管理供应商信息，支持添加、编辑、删除供应商</p>
        </div>

        <div className="row g-5">
          <div className="col-xl-3 col-lg-4">
            <div className="sidebar-panel">
              <div className="card">
                <div
                  className="card-header d-flex justify-content-between align-items-center collapse-trigger"
                  style={{ cursor: "pointer" }}
                  role="button"
                  tabIndex={0}
                  aria-expanded={!formCollapsed}
                  onClick={() => setFormCollapsed(!formCollapsed)}
                  onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setFormCollapsed(!formCollapsed); } }}
                >
                  <h6 className="mb-0 fw-bold">
                    <i className="fas fa-truck-loading" style={{ marginRight: 8, color: "var(--plush-blue-text, #007bff)" }}></i>添加新供应商
                  </h6>
                  <ChevronDownIcon style={{ width: 16, height: 16, transition: "transform 0.3s ease", transform: formCollapsed ? "rotate(-90deg)" : "rotate(0deg)" }} />
                </div>
                <div className={`collapse-content ${formCollapsed ? "" : "show"}`}>
                  <div className="card-body">
                  <div className="form-group-enhanced">
                    <label className="form-label"><i className="fas fa-building" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>供应商名称 <span className="text-danger">*</span></label>
                    <input type="text" className="form-control" value={name} onChange={e => setName(e.target.value)} placeholder="例如：广州面料有限公司" />
                  </div>
                  <div className="form-group-enhanced">
                    <label className="form-label"><i className="fas fa-user" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>联系人</label>
                    <input type="text" className="form-control" value={contactPerson} onChange={e => setContactPerson(e.target.value)} placeholder="例如：李经理" />
                  </div>
                  <div className="form-group-enhanced">
                    <label className="form-label"><i className="fas fa-phone" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>联系电话</label>
                    <input type="text" className="form-control" value={phone} onChange={e => setPhone(e.target.value)} placeholder="例如：13800138000" />
                  </div>
                  <div className="form-group-enhanced">
                    <label className="form-label"><i className="fas fa-map-marker-alt" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>地址</label>
                    <input type="text" className="form-control" value={address} onChange={e => setAddress(e.target.value)} placeholder="例如：广州市白云区" />
                  </div>
                  <div className="form-group-enhanced">
                    <label className="form-label"><i className="fas fa-sticky-note" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>备注</label>
                    <textarea className="form-control" rows={2} value={remark} onChange={e => setRemark(e.target.value)} placeholder="例如：长期合作供应商" />
                  </div>
                </div>
              </div>
              <button className="btn btn-primary btn-lg w-100 mt-4 btn-submit-enhanced" disabled={!name || createMutation.isPending} onClick={() => createMutation.mutate()}>
                <i className="fas fa-plus" style={{ marginRight: 8 }}></i>{createMutation.isPending ? "添加中..." : "添加供应商"}
              </button>
            </div>
          </div>

          <div className="col-xl-9 col-lg-8">
            <div className="card main-content-card">
              <div className="card-header">
                <div className="d-flex justify-content-between align-items-center flex-wrap gap-3">
                  <h6 className="mb-0 fw-bold"><i className="fas fa-list" style={{ marginRight: 8, color: "var(--plush-blue-text, #007bff)" }}></i>供应商列表</h6>
                  <div className="toolbar-wrapper">
                    <div className="search-box">
                      <i className="fas fa-search search-icon"></i>
                      <input type="text" className="form-control search-input" placeholder="搜索供应商名称..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
                    </div>
                  </div>
                </div>
              </div>
              <div className="card-body p-0">
                <div className="table-responsive" style={{ maxHeight: "calc(100vh - 280px)", overflowY: "auto" }}>
                  <table className="table table-hover mb-0">
                    <thead className="sticky-top">
                      <tr>
                        <th style={{ width: 180 }}>供应商名称</th>
                        <th style={{ width: 120 }}>联系人</th>
                        <th style={{ width: 140 }}>联系电话</th>
                        <th>地址</th>
                        <th style={{ width: 160 }}>创建时间</th>
                        <th style={{ width: 120 }}>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {isLoading ? (
                        <tr><td colSpan={6} className="text-center py-5">加载中...</td></tr>
                      ) : suppliers.length === 0 ? (
                        <tr><td colSpan={6} className="text-center py-5"><div className="empty-state"><i className="fas fa-truck" style={{ fontSize: 48, color: "#ccc", marginBottom: 16 }}></i><p className="text-muted">暂无供应商，请先添加</p></div></td></tr>
                      ) : suppliers.map((s, idx) => (
                        <tr key={s.id} className="table-row-animate" style={{ animationDelay: `${Math.min(idx * 0.05, 0.25)}s` }}>
                          <td><span className="supplier-name"><i className="fas fa-truck" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>{s.name}</span></td>
                          <td><span className="contact-text">{s.contact_person || "-"}</span></td>
                          <td><span className="phone-text">{s.phone || "-"}</span></td>
                          <td><span className="address-text">{s.address || "-"}</span></td>
                          <td><span className="time-text">{s.created_at ? s.created_at.split("T")[0] : "-"}</span></td>
                          <td>
                            <div className="action-buttons">
                              <a href={`/supplier/${s.id}`} className="btn btn-sm btn-outline-primary" title="编辑"><i className="fas fa-edit"></i></a>
                              <button className="btn btn-sm btn-outline-danger" title="删除" onClick={() => { if (confirm(`确定要删除供应商"${s.name}"吗？如果该供应商已关联BOM或采购订单，将无法删除。`)) deleteMutation.mutate(s.id); }}><i className="fas fa-trash"></i></button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                  </div>
                </div>
              </div>
          </div>
        </div>
      </div>

      <style jsx global>{`
        .sp-page-root .container-fluid { padding: 0 16px; }
        .sp-page-root .page-header-wrapper { margin-bottom: 32px; padding-bottom: 24px; border-bottom: 3px solid var(--plush-blue-light, #e0e0e0); }
        .sp-page-root .page-title { color: var(--plush-text, #2d3748); font-size: 24px; font-weight: 400; margin-bottom: 8px; letter-spacing: -0.5px; }
        .sp-page-root .page-subtitle { color: var(--plush-text-light, #718096); font-size: 18px; margin: 0; }
        .sp-page-root .sidebar-panel { position: sticky; top: 120px; }
        .sp-page-root .form-group-enhanced { margin-bottom: 24px; }
        .sp-page-root .form-group-enhanced .form-label { display: flex; align-items: center; font-weight: 400; color: var(--plush-text, #2d3748); font-size: 14px; margin-bottom: 8px; }
        .sp-page-root .btn-submit-enhanced { font-size: 16px; padding: 16px 32px; border-radius: 16px; box-shadow: 0 4px 16px var(--plush-shadow-soft, rgba(176,224,230,0.25)); min-height: 48px; }
        .sp-page-root .btn-submit-enhanced:hover:not(:disabled) { transform: translateY(-3px) scale(1.02); box-shadow: 0 8px 24px var(--plush-shadow-medium, rgba(135,206,235,0.35)); }
        .sp-page-root .main-content-card { min-height: calc(100vh - 200px); }
        .sp-page-root .toolbar-wrapper { flex: 1; max-width: 500px; }
        .sp-page-root .search-box { position: relative; flex: 1; min-width: 200px; }
        .sp-page-root .search-icon { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); color: var(--plush-text-light, #718096); font-size: 14px; pointer-events: none; }
        .sp-page-root .search-input { padding-left: 40px !important; border-radius: var(--radius-button, 12px) !important; min-height: 44px; }
        .sp-page-root .supplier-name { font-weight: 500; color: var(--plush-text, #2d3748); font-size: 14px; line-height: 1.5; }
        .sp-page-root .contact-text, .sp-page-root .phone-text, .sp-page-root .address-text, .sp-page-root .time-text { font-size: 14px; color: var(--plush-text-light, #718096); line-height: 1.5; }
        .sp-page-root .action-buttons { display: flex; gap: 8px; }
        .sp-page-root .action-buttons .btn { width: 44px; height: 44px; padding: 0; display: flex; align-items: center; justify-content: center; border-radius: 12px; min-height: 44px; min-width: 44px; }
        .sp-page-root .action-buttons .btn:focus-visible { outline: 2px solid var(--plush-blue-text, #007bff); outline-offset: 2px; }
        .sp-page-root .empty-state { padding: 64px 40px; }
        .sp-page-root .table { margin-bottom: 0; }
        .sp-page-root .table thead th { padding: 16px 24px; font-weight: 400; font-size: 14px; letter-spacing: 0.3px; border-bottom: 2px solid var(--plush-blue-light, #e0e0e0); background: var(--plush-white, #fff); line-height: 1.5; }
        .sp-page-root .table tbody tr { animation: fadeIn 0.3s ease forwards; transition: all 0.2s ease; }
        .sp-page-root .table tbody tr:hover, .sp-page-root .table tbody tr:focus-within { background: linear-gradient(135deg, rgba(176, 224, 230, 0.1) 0%, rgba(212, 241, 244, 0.15) 100%); }
        .sp-page-root .table tbody td { padding: 16px 24px; vertical-align: middle; border-bottom: 1px solid var(--plush-blue-light, #e0e0e0); font-size: 14px; font-weight: 400; line-height: 1.5; }
        .sp-page-root .table-row-animate { opacity: 0; }
        .sp-page-root .card-header { padding: 24px; }
        .sp-page-root .card-body { padding: 24px; }
        .sp-page-root .form-control { border: 2px solid var(--plush-blue-light, #e0e0e0); border-radius: var(--radius-input, 12px); transition: all 0.3s ease; min-height: 44px; line-height: 1.5; }
        .sp-page-root .form-control:focus { border-color: var(--plush-blue-text, #007bff); box-shadow: 0 0 0 .2rem rgba(135,206,235,0.25); outline: none; }
        .sp-page-root .btn-sm { padding: 8px 16px; font-size: 14px; border-radius: 12px; min-height: 44px; display: inline-flex; align-items: center; justify-content: center; }
        .sp-page-root .btn-outline-primary { color: #0d6efd; border: 2px solid #0d6efd; background: transparent; }
        .sp-page-root .btn-outline-primary:hover { background: #0d6efd; color: #fff; }
        .sp-page-root .btn-outline-danger { background: transparent; color: #dc3545; border: 2px solid #dc3545; }
        .sp-page-root .btn-outline-danger:hover { background: #dc3545; color: white; }
        .sp-page-root .row { display: flex; flex-wrap: wrap; margin: 0 -16px; }
        .sp-page-root .col-xl-3 { flex: 0 0 25%; max-width: 25%; padding: 0 16px; }
        .sp-page-root .col-xl-9 { flex: 0 0 75%; max-width: 75%; padding: 0 16px; }
        .sp-page-root .col-lg-4 { padding: 0 16px; }
        .sp-page-root .col-lg-8 { padding: 0 16px; }
        .sp-page-root .g-5 { gap: 3rem; }
        .sp-page-root .btn-lg { padding: .5rem 1rem; font-size: 1.25rem; border-radius: .5rem; }
        .sp-page-root .table-responsive { overflow-x: auto; }
        .sp-page-root .sticky-top { position: sticky; top: 0; z-index: 10; }
        .sp-page-root .collapse-trigger { cursor: pointer; }
        .sp-page-root .collapse-trigger:hover { background: rgba(176,224,230,0.05); }
        .sp-page-root .collapse-content { overflow: hidden; transition: max-height 0.3s ease; }
        .sp-page-root .collapse-content.show { max-height: 800px; }
        .sp-page-root .collapse-content:not(.show) { max-height: 0; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @media (max-width: 1200px) { .sp-page-root .sidebar-panel { position: static; } .sp-page-root .col-xl-3 { flex: 0 0 33.333%; max-width: 33.333%; } .sp-page-root .col-xl-9 { flex: 0 0 66.666%; max-width: 66.666%; } }
        @media (max-width: 992px) { .sp-page-root .col-xl-3, .sp-page-root .col-lg-4 { flex: 0 0 100%; max-width: 100%; } .sp-page-root .col-xl-9, .sp-page-root .col-lg-8 { flex: 0 0 100%; max-width: 100%; } .sp-page-root .toolbar-wrapper { max-width: 100%; width: 100%; } .sp-page-root .search-box { min-width: 152px; } }
        @media (max-width: 768px) { .sp-page-root .page-header-wrapper { margin-bottom: 16px; padding-bottom: 16px; } .sp-page-root .page-title { font-size: 20px; } .sp-page-root .card-header { padding: 16px; } .sp-page-root .toolbar-wrapper { flex-direction: column; } .sp-page-root .search-box { width: 100%; } .sp-page-root .action-buttons .btn { width: 44px; height: 44px; font-size: 12px; } }
      `}</style>
    </div>
  );
}
