"use client";

import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, del } from "@/lib/api-client";

interface Customer {
  id: number;
  name: string;
  contact: string;
  phone: string;
  address: string;
  note: string;
  status: string;
  create_time: string;
}

export interface CustomerListResult {
  success: boolean;
  customers: Customer[];
  total: number;
}

interface CustomerContentProps {
  initialData?: CustomerListResult;
}

export function CustomerContent({ initialData }: CustomerContentProps) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [panelOpen, setPanelOpen] = useState(true);

  const { data, isLoading } = useQuery({
    queryKey: ["customers-list"],
    queryFn: () => get<CustomerListResult>("/customers/list"),
    initialData,
  });

  const createMutation = useMutation({
    mutationFn: () => post<{ success: boolean; message?: string }>("/customers/create", { name, contact, phone, address, note }),
    onSuccess: (res) => { alert(res.message || "添加成功"); setName(""); setContact(""); setPhone(""); setAddress(""); setNote(""); qc.invalidateQueries({ queryKey: ["customers-list"] }); },
    onError: (err: Error) => alert(err.message),
  });

  const toggleMutation = useMutation({
    mutationFn: (id: number) => post<{ success: boolean; message?: string }>(`/customers/toggle-status/${id}`, {}),
    onSuccess: (res) => { alert(res.message || "操作成功"); qc.invalidateQueries({ queryKey: ["customers-list"] }); },
    onError: (err: Error) => alert(err.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => del<{ success: boolean; error?: string }>(`/customers/delete/${id}`),
    onSuccess: (res) => { if (res.success) { alert("删除成功"); qc.invalidateQueries({ queryKey: ["customers-list"] }); } else { alert(res.error || "删除失败"); } },
    onError: (err: Error) => alert(err.message),
  });

  const debouncedSearch = useMemo(() => {
    let timeout: ReturnType<typeof setTimeout>;
    return (value: string) => {
      clearTimeout(timeout);
      timeout = setTimeout(() => setSearchTerm(value), 300);
    };
  }, []);

  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    debouncedSearch(e.target.value);
  }, [debouncedSearch]);

  const allCustomers = data?.customers ?? [];

  const filtered = useMemo(() => {
    return allCustomers.filter((c) => {
      const matchesSearch = !searchTerm || c.name.toLowerCase().includes(searchTerm.toLowerCase());
      const matchesStatus = statusFilter === "all" || c.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [allCustomers, searchTerm, statusFilter]);

  return (
    <div className="cu-page-root">
      <div className="container-fluid">
        <div className="page-header-wrapper">
          <h2 className="page-title">客户管理</h2>
          <p className="page-subtitle">管理客户信息，支持添加、编辑、禁用客户</p>
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
                  aria-expanded={panelOpen}
                  onClick={() => setPanelOpen(!panelOpen)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPanelOpen(!panelOpen); } }}
                >
                  <h6 className="mb-0 fw-bold">
                    <i className="fas fa-user-plus" style={{ marginRight: 8, color: "var(--plush-blue-text, #007bff)" }}></i>添加新客户
                  </h6>
                  <i className={`fas fa-chevron-down collapse-arrow ${panelOpen ? "rotate-180" : ""}`}></i>
                </div>
                <div className={`collapse-content ${panelOpen ? "show" : ""}`}>
                  <div className="card-body">
                    <div className="form-group-enhanced">
                      <label className="form-label"><i className="fas fa-building" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>客户名称 <span className="text-danger">*</span></label>
                      <input type="text" className="form-control" value={name} onChange={e => setName(e.target.value)} placeholder="例如：MINISO 国际" />
                    </div>
                    <div className="form-group-enhanced">
                      <label className="form-label"><i className="fas fa-user" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>联系人</label>
                      <input type="text" className="form-control" value={contact} onChange={e => setContact(e.target.value)} placeholder="例如：张三" />
                    </div>
                    <div className="form-group-enhanced">
                      <label className="form-label"><i className="fas fa-phone" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>联系电话</label>
                      <input type="text" className="form-control" value={phone} onChange={e => setPhone(e.target.value)} placeholder="例如：13800138000" />
                    </div>
                    <div className="form-group-enhanced">
                      <label className="form-label"><i className="fas fa-map-marker-alt" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>地址</label>
                      <input type="text" className="form-control" value={address} onChange={e => setAddress(e.target.value)} placeholder="例如：北京市朝阳区" />
                    </div>
                    <div className="form-group-enhanced">
                      <label className="form-label"><i className="fas fa-sticky-note" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>备注</label>
                      <textarea className="form-control" rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder="例如：重要客户" />
                    </div>
                  </div>
                </div>
              </div>
              <button className="btn btn-primary btn-lg w-100 mt-4 btn-submit-enhanced" disabled={!name || createMutation.isPending} onClick={() => createMutation.mutate()}>
                <i className="fas fa-plus" style={{ marginRight: 8 }}></i>{createMutation.isPending ? "添加中..." : "添加客户"}
              </button>
            </div>
          </div>

          <div className="col-xl-9 col-lg-8">
            <div className="card main-content-card">
              <div className="card-header">
                <div className="d-flex justify-content-between align-items-center flex-wrap gap-3">
                  <h6 className="mb-0 fw-bold"><i className="fas fa-list" style={{ marginRight: 8, color: "var(--plush-blue-text, #007bff)" }}></i>客户列表</h6>
                  <div className="toolbar-wrapper d-flex gap-2 flex-wrap">
                    <div className="search-box">
                      <i className="fas fa-search search-icon"></i>
                      <input type="text" className="form-control search-input" placeholder="搜索客户名称..." aria-label="搜索客户" onChange={handleSearchChange} />
                    </div>
                    <select className="form-select sort-select" aria-label="客户状态筛选" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                      <option value="all">全部状态</option>
                      <option value="active">已启用</option>
                      <option value="inactive">已禁用</option>
                    </select>
                  </div>
                </div>
              </div>
              <div className="card-body p-0">
                <div className="table-responsive" style={{ maxHeight: "calc(100vh - 280px)", overflowY: "auto" }}>
                  <table className="table table-hover mb-0">
                    <thead className="sticky-top">
                      <tr>
                        <th style={{ width: 180 }}>客户名称</th>
                        <th style={{ width: 120 }}>联系人</th>
                        <th style={{ width: 140 }}>联系电话</th>
                        <th>地址</th>
                        <th style={{ width: 100 }}>状态</th>
                        <th style={{ width: 160 }}>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {isLoading ? (
                        <tr><td colSpan={6} className="text-center py-5">加载中...</td></tr>
                      ) : filtered.length === 0 ? (
                        <tr><td colSpan={6} className="text-center py-5"><div className="empty-state"><i className="fas fa-users" style={{ fontSize: 48, color: "#ccc", marginBottom: 16 }}></i><p className="text-muted mb-0">暂无客户，请先添加</p></div></td></tr>
                      ) : filtered.map(c => (
                        <tr key={c.id} data-name={c.name.toLowerCase()} data-status={c.status === "active" ? "active" : "inactive"}>
                          <td>
                            <span className="customer-name"><i className="fas fa-building" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>{c.name}</span>
                          </td>
                          <td><span className="contact-text">{c.contact || "-"}</span></td>
                          <td><span className="phone-text">{c.phone || "-"}</span></td>
                          <td><span className="address-text">{c.address || "-"}</span></td>
                          <td>
                            {c.status === "active" ? (
                              <span className="badge bg-success">已启用</span>
                            ) : (
                              <span className="badge bg-secondary">已禁用</span>
                            )}
                          </td>
                          <td>
                            <div className="action-buttons">
                              <a href={`/customer/${c.id}`} className="btn btn-sm btn-outline-primary" title="编辑"><i className="fas fa-edit"></i></a>
                              <button className={`btn btn-sm btn-outline-${c.status === "active" ? "warning" : "success"}`} title={c.status === "active" ? "禁用" : "启用"} onClick={() => { if (confirm("确定要切换该客户的状态吗？")) toggleMutation.mutate(c.id); }}>
                                <i className={`fas fa-${c.status === "active" ? "ban" : "check"}`}></i>
                              </button>
                              <button className="btn btn-sm btn-outline-danger" title="删除" onClick={() => { if (confirm("确定要删除该客户吗？")) deleteMutation.mutate(c.id); }}><i className="fas fa-trash"></i></button>
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

      <style jsx global>{`
        .cu-page-root .container-fluid { padding: 0 16px; }
        .cu-page-root .page-header-wrapper { margin-bottom: 32px; padding-bottom: 24px; border-bottom: 3px solid var(--plush-blue-light, #e0e0e0); }
        .cu-page-root .page-title { color: var(--plush-text, #2d3748); font-size: 24px; font-weight: 400; margin-bottom: 8px; letter-spacing: -0.5px; }
        .cu-page-root .page-subtitle { color: var(--plush-text-light, #718096); font-size: 18px; margin: 0; }
        .cu-page-root .sidebar-panel { position: sticky; top: 120px; }
        .cu-page-root .form-group-enhanced { margin-bottom: 24px; }
        .cu-page-root .form-group-enhanced .form-label { display: flex; align-items: center; font-weight: 400; color: var(--plush-text, #2d3748); font-size: 14px; margin-bottom: 8px; }
        .cu-page-root .btn-submit-enhanced { font-size: 16px; padding: 16px 32px; border-radius: 16px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); min-height: 48px; }
        .cu-page-root .btn-submit-enhanced:hover:not(:disabled) { transform: translateY(-3px) scale(1.02); box-shadow: 0 8px 24px rgba(0,0,0,0.12); }
        .cu-page-root .main-content-card { min-height: calc(100vh - 200px); }
        .cu-page-root .toolbar-wrapper { flex: 1; max-width: 500px; }
        .cu-page-root .search-box { position: relative; flex: 1; min-width: 200px; }
        .cu-page-root .search-icon { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); color: var(--plush-text-light, #718096); font-size: 14px; pointer-events: none; }
        .cu-page-root .search-input { padding-left: 40px !important; border-radius: 12px !important; min-height: 44px; }
        .cu-page-root .sort-select { width: auto; min-width: 136px; border-radius: 12px !important; min-height: 44px; padding: 8px 16px; border: 2px solid var(--plush-blue-light, #e0e0e0); font-size: 14px; }
        .cu-page-root .customer-name { font-weight: 500; color: var(--plush-text, #2d3748); font-size: 14px; }
        .cu-page-root .contact-text, .cu-page-root .phone-text, .cu-page-root .address-text { font-size: 14px; color: var(--plush-text-light, #718096); }
        .cu-page-root .action-buttons { display: flex; gap: 8px; }
        .cu-page-root .action-buttons .btn { width: 44px; height: 44px; padding: 0; display: flex; align-items: center; justify-content: center; border-radius: 12px; min-height: 44px; min-width: 44px; }
        .cu-page-root .action-buttons .btn:focus-visible { outline: 2px solid var(--plush-blue-text, #007bff); outline-offset: 2px; }
        .cu-page-root .empty-state { padding: 64px 40px; }
        .cu-page-root .table { margin-bottom: 0; }
        .cu-page-root .table thead th { padding: 16px 24px; font-weight: 400; font-size: 14px; letter-spacing: 0.3px; border-bottom: 2px solid var(--plush-blue-light, #e0e0e0); background: var(--plush-white, #fff); }
        .cu-page-root .table tbody tr { animation: fadeIn 0.3s ease forwards; transition: all 0.2s ease; }
        .cu-page-root .table tbody tr:hover, .cu-page-root .table tbody tr:focus-within { background: linear-gradient(135deg, rgba(176,224,230,0.1), rgba(212,241,244,0.15)); }
        .cu-page-root .table tbody td { padding: 16px 24px; vertical-align: middle; border-bottom: 1px solid var(--plush-blue-light, #e0e0e0); font-size: 14px; font-weight: 400; }
        .cu-page-root .table tbody tr:nth-child(1) { animation-delay: 0.05s; }
        .cu-page-root .table tbody tr:nth-child(2) { animation-delay: 0.1s; }
        .cu-page-root .table tbody tr:nth-child(3) { animation-delay: 0.15s; }
        .cu-page-root .table tbody tr:nth-child(4) { animation-delay: 0.2s; }
        .cu-page-root .table tbody tr:nth-child(5) { animation-delay: 0.25s; }
        .cu-page-root .card-header { padding: 24px; }
        .cu-page-root .card-body { padding: 24px; }
        .cu-page-root .form-control { padding: 8px 16px; border-radius: 8px; border: 2px solid var(--plush-blue-light, #e0e0e0); font-size: 14px; min-height: 44px; transition: all 0.3s ease; }
        .cu-page-root .form-control:focus { border-color: var(--plush-blue-text, #007bff); box-shadow: 0 0 0 .2rem rgba(135,206,235,0.25); outline: none; }
        .cu-page-root .btn-sm { padding: 8px 16px; font-size: 14px; border-radius: 12px; min-height: 44px; display: inline-flex; align-items: center; justify-content: center; }
        .cu-page-root .btn-outline-primary { color: #0d6efd; border: 2px solid #0d6efd; background: transparent; }
        .cu-page-root .btn-outline-primary:hover { background: #0d6efd; color: #fff; }
        .cu-page-root .btn-outline-danger { color: #dc3545; border: 2px solid #dc3545; background: transparent; }
        .cu-page-root .btn-outline-danger:hover { background: #dc3545; color: #fff; }
        .cu-page-root .btn-outline-success { background: transparent; color: #198754; border: 2px solid #198754; }
        .cu-page-root .btn-outline-success:hover { background: #198754; color: white; }
        .cu-page-root .btn-outline-warning { background: transparent; color: #ffc107; border: 2px solid #ffc107; }
        .cu-page-root .btn-outline-warning:hover { background: #ffc107; color: #212529; }
        .cu-page-root .badge { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .cu-page-root .bg-success { background: #28a745; color: #fff; }
        .cu-page-root .bg-secondary { background: #6c757d; color: #fff; }
        .cu-page-root .collapse-arrow { transition: transform 0.3s ease; }
        .cu-page-root .collapse-arrow.rotate-180 { transform: rotate(180deg); }
        .cu-page-root .collapse-content { max-height: 0; overflow: hidden; transition: max-height 0.35s ease; }
        .cu-page-root .collapse-content.show { max-height: 600px; }
        .cu-page-root .row { display: flex; flex-wrap: wrap; margin: 0 -16px; }
        .cu-page-root .col-xl-3 { flex: 0 0 25%; max-width: 25%; padding: 0 16px; }
        .cu-page-root .col-xl-9 { flex: 0 0 75%; max-width: 75%; padding: 0 16px; }
        .cu-page-root .col-lg-4 { padding: 0 16px; }
        .cu-page-root .col-lg-8 { padding: 0 16px; }
        .cu-page-root .card { background: #fff; border: 1px solid rgba(0,0,0,.125); border-radius: .375rem; }
        .cu-page-root .d-flex { display: flex; }
        .cu-page-root .justify-content-between { justify-content: space-between; }
        .cu-page-root .align-items-center { align-items: center; }
        .cu-page-root .flex-wrap { flex-wrap: wrap; }
        .cu-page-root .gap-2 { gap: .5rem; }
        .cu-page-root .gap-3 { gap: 1rem; }
        .cu-page-root .g-5 { gap: 3rem; }
        .cu-page-root .mt-4 { margin-top: 1.5rem; }
        .cu-page-root .mb-0 { margin-bottom: 0; }
        .cu-page-root .p-0 { padding: 0; }
        .cu-page-root .fw-bold { font-weight: 700; }
        .cu-page-root .text-center { text-align: center; }
        .cu-page-root .text-muted { color: #6c757d; }
        .cu-page-root .text-danger { color: #dc3545; }
        .cu-page-root .py-5 { padding-top: 3rem; padding-bottom: 3rem; }
        .cu-page-root .w-100 { width: 100%; }
        .cu-page-root .btn-primary { color: #fff; background-color: #0d6efd; border-color: #0d6efd; }
        .cu-page-root .btn-primary:disabled { opacity: .65; cursor: not-allowed; }
        .cu-page-root .btn-lg { padding: .5rem 1rem; font-size: 1.25rem; border-radius: .5rem; }
        .cu-page-root .table-responsive { overflow-x: auto; }
        .cu-page-root .sticky-top { position: sticky; top: 0; z-index: 10; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @media (max-width: 1200px) { .cu-page-root .sidebar-panel { position: static; } .cu-page-root .col-xl-3 { flex: 0 0 33.333%; max-width: 33.333%; } .cu-page-root .col-xl-9 { flex: 0 0 66.666%; max-width: 66.666%; } }
        @media (max-width: 992px) { .cu-page-root .col-xl-3, .cu-page-root .col-lg-4 { flex: 0 0 100%; max-width: 100%; } .cu-page-root .col-xl-9, .cu-page-root .col-lg-8 { flex: 0 0 100%; max-width: 100%; } .cu-page-root .toolbar-wrapper { max-width: 100%; width: 100%; } .cu-page-root .search-box { min-width: 152px; } }
        @media (max-width: 768px) { .cu-page-root .page-header-wrapper { margin-bottom: 16px; padding-bottom: 16px; } .cu-page-root .page-title { font-size: 20px; } .cu-page-root .card-header { padding: 16px; } .cu-page-root .toolbar-wrapper { flex-direction: column; } .cu-page-root .search-box { width: 100%; } .cu-page-root .sort-select { width: 100%; } }
      `}</style>
    </div>
  );
}
