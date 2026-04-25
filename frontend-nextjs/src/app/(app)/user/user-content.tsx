"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, put, del } from "@/lib/api-client";

// ============ Types ============

interface UserItem {
  id: number; username: string; is_super: boolean; status: number; create_time: string;
}

export interface UserListResult {
  success: boolean; users: UserItem[]; total: number;
}

interface PermissionItem {
  id: number; name: string; code: string; parent_id: number | null;
  section_name: string; is_nav: boolean; children?: PermissionItem[];
}

interface UserPermissionResult {
  success: boolean; user_id: number; user_permission_ids: number[]; permissions: PermissionItem[];
}

// ============ Component ============

interface UserContentProps {
  initialData?: UserListResult;
}

export function UserContent({ initialData }: UserContentProps) {
  const qc = useQueryClient();
  const [createForm, setCreateForm] = useState({ username: "", password: "", is_super: false });
  const [editOpen, setEditOpen] = useState(false);
  const [permOpen, setPermOpen] = useState(false);
  const [selectedUser, setSelectedUser] = useState<UserItem | null>(null);
  const [editForm, setEditForm] = useState({ password: "", is_super: false });
  const [selectedPermIds, setSelectedPermIds] = useState<number[]>([]);

  // Queries
  const { data, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: () => get<UserListResult>("/users/list"),
    initialData,
  });
  const users = useMemo(() => data?.users ?? [], [data]);

  const { data: permData, isLoading: permLoading } = useQuery({
    queryKey: ["user-permissions", selectedUser?.id],
    queryFn: () => get<UserPermissionResult>(`/users/permission/${selectedUser!.id}`),
    enabled: !!selectedUser && permOpen,
  });

  // Mutations
  const createMut = useMutation({
    mutationFn: (body: typeof createForm) => post<Record<string, unknown>>("/users/create", body),
    onSuccess: () => { setCreateForm({ username: "", password: "", is_super: false }); qc.invalidateQueries({ queryKey: ["users"] }); },
  });

  const editMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: typeof editForm }) => put<Record<string, unknown>>(`/users/edit/${id}`, body),
    onSuccess: () => { setEditOpen(false); qc.invalidateQueries({ queryKey: ["users"] }); },
  });

  const toggleMut = useMutation({
    mutationFn: (id: number) => post<Record<string, unknown>>(`/users/toggle/${id}`, {}),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => del<Record<string, unknown>>(`/users/delete/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); },
  });

  const savePermMut = useMutation({
    mutationFn: ({ id, ids }: { id: number; ids: number[] }) => post<Record<string, unknown>>(`/users/permission/${id}`, { permission_ids: ids }),
    onSuccess: () => { setPermOpen(false); qc.invalidateQueries({ queryKey: ["users"] }); },
  });

  // Handlers
  const openEdit = (u: UserItem) => { setSelectedUser(u); setEditForm({ password: "", is_super: u.is_super }); setEditOpen(true); };
  const openPerm = (u: UserItem) => { setSelectedUser(u); setSelectedPermIds([]); setPermOpen(true); };
  const togglePerm = (id: number) => setSelectedPermIds(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);
  const toggleSection = (sectionIds: number[]) => {
    setSelectedPermIds(prev => {
      const allSelected = sectionIds.every(id => prev.includes(id));
      return allSelected ? prev.filter(id => !sectionIds.includes(id)) : [...new Set([...prev, ...sectionIds])];
    });
  };

  const currentPermIds = permData?.user_permission_ids ?? [];
  const effectivePermIds = permLoading ? [] : (selectedPermIds.length > 0 || !permData ? selectedPermIds : currentPermIds);

  return (
    <div className="us-page-root">
      <h2 className="us-page-title">用户管理</h2>

      {/* Add user */}
      <div className="us-card">
        <div className="us-card-header">添加新用户</div>
        <div className="us-card-body">
          <div className="us-row" style={{ gap: 16, marginBottom: 16 }}>
            <div style={{ flex: 1 }}>
              <label className="us-form-label">用户名</label>
              <input type="text" className="us-form-control" placeholder="请输入用户名" value={createForm.username} onChange={e => setCreateForm({ ...createForm, username: e.target.value })} />
            </div>
            <div style={{ flex: 1 }}>
              <label className="us-form-label">密码</label>
              <input type="password" className="us-form-control" placeholder="请输入密码" value={createForm.password} onChange={e => setCreateForm({ ...createForm, password: e.target.value })} />
            </div>
            <div style={{ flex: "0 0 auto", display: "flex", alignItems: "flex-end", gap: 8 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 14 }}>
                <input type="checkbox" checked={createForm.is_super} onChange={e => setCreateForm({ ...createForm, is_super: e.target.checked })} />
                超级用户
              </label>
            </div>
          </div>
          <button className="us-btn us-btn-primary" onClick={() => createMut.mutate(createForm)} disabled={createMut.isPending || !createForm.username || !createForm.password}>
            {createMut.isPending ? "添加中..." : "添加用户"}
          </button>
        </div>
      </div>

      {/* User list */}
      <div className="us-card" style={{ marginTop: 24 }}>
        <div className="us-card-header">用户列表</div>
        <div className="us-card-body" style={{ padding: 0 }}>
          {isLoading ? (
            <div className="us-empty"><i className="fas fa-spinner fa-spin" style={{ fontSize: 32 }}></i><p>加载中...</p></div>
          ) : users.length === 0 ? (
            <div className="us-empty"><p>暂无用户</p></div>
          ) : (
            <table className="us-table">
              <thead><tr><th>用户名</th><th>是否超级用户</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.id}>
                    <td>{u.username}</td>
                    <td>{u.is_super ? "是" : "否"}</td>
                    <td><span className={`us-badge ${u.status ? "us-badge-success" : "us-badge-secondary"}`}>{u.status ? "启用" : "禁用"}</span></td>
                    <td>{u.create_time || "-"}</td>
                    <td>
                      <button className="us-btn us-btn-sm us-btn-outline-primary" onClick={() => openEdit(u)} title="编辑"><i className="fas fa-edit"></i></button>
                      <button className="us-btn us-btn-sm us-btn-outline-info" onClick={() => openPerm(u)} title="权限设置"><i className="fas fa-key"></i></button>
                      <button className={`us-btn us-btn-sm ${u.status ? "us-btn-outline-danger" : "us-btn-outline-success"}`} onClick={() => toggleMut.mutate(u.id)} title={u.status ? "禁用" : "启用"}>
                        <i className={`fas fa-${u.status ? "ban" : "check"}`}></i>
                      </button>
                      {!u.is_super && (
                        <button className="us-btn us-btn-sm us-btn-outline-danger" onClick={() => { if (confirm("确定要删除该用户吗？")) deleteMut.mutate(u.id); }} title="删除"><i className="fas fa-trash"></i></button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Edit modal */}
      {editOpen && selectedUser && (
        <div className="us-modal-overlay" onClick={() => setEditOpen(false)}>
          <div className="us-modal" onClick={e => e.stopPropagation()}>
            <div className="us-modal-header">
              <h5>编辑用户 - {selectedUser.username}</h5>
              <button className="us-modal-close" onClick={() => setEditOpen(false)}>&times;</button>
            </div>
            <div className="us-modal-body">
              <div className="us-mb3">
                <label className="us-form-label">新密码（留空则不修改）</label>
                <input type="password" className="us-form-control" value={editForm.password} onChange={e => setEditForm({ ...editForm, password: e.target.value })} />
              </div>
              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 14 }}>
                <input type="checkbox" checked={editForm.is_super} onChange={e => setEditForm({ ...editForm, is_super: e.target.checked })} />
                超级管理员
              </label>
            </div>
            <div className="us-modal-footer">
              <button className="us-btn us-btn-secondary" onClick={() => setEditOpen(false)}>取消</button>
              <button className="us-btn us-btn-primary" onClick={() => editMut.mutate({ id: selectedUser.id, body: editForm })} disabled={editMut.isPending}>保存</button>
            </div>
          </div>
        </div>
      )}

      {/* Permission modal */}
      {permOpen && selectedUser && (
        <div className="us-modal-overlay" onClick={() => setPermOpen(false)}>
          <div className="us-modal" style={{ maxWidth: 640 }} onClick={e => e.stopPropagation()}>
            <div className="us-modal-header">
              <h5>权限设置 - {selectedUser.username}</h5>
              <button className="us-modal-close" onClick={() => setPermOpen(false)}>&times;</button>
            </div>
            <div className="us-modal-body" style={{ maxHeight: "60vh", overflowY: "auto" }}>
              {permLoading ? (
                <div className="us-empty"><i className="fas fa-spinner fa-spin"></i><p>加载中...</p></div>
              ) : (
                <div>
                  <h5 style={{ marginBottom: 4 }}>功能模块</h5>
                  <p style={{ color: "#6c757d", fontSize: 13, marginBottom: 16 }}>勾选功能模块将自动授予该模块下的所有操作权限</p>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
                    {permData?.permissions.map(section => {
                      const sectionIds = [section.id, ...(section.children?.map(c => c.id) ?? [])];
                      const allSelected = sectionIds.every(id => effectivePermIds.includes(id));
                      return (
                        <div key={section.id} className={`us-perm-card ${allSelected ? "us-perm-checked" : ""}`} onClick={() => toggleSection(sectionIds)}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontWeight: 600, fontSize: 14 }} onClick={e => e.stopPropagation()}>
                              <input type="checkbox" checked={allSelected} onChange={() => toggleSection(sectionIds)} />
                              {section.section_name || section.name}
                            </label>
                            {allSelected && <i className="fas fa-check-circle" style={{ color: "#198754" }}></i>}
                          </div>
                          <div style={{ marginTop: 6 }}>
                            {section.children?.map(child => (
                              <span key={child.id} className="us-perm-badge" onClick={e => { e.stopPropagation(); togglePerm(child.id); }} style={{ cursor: "pointer", opacity: effectivePermIds.includes(child.id) ? 1 : 0.5 }}>
                                {child.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
            <div className="us-modal-footer">
              <button className="us-btn us-btn-secondary" onClick={() => setPermOpen(false)}>取消</button>
              <button className="us-btn us-btn-primary" onClick={() => savePermMut.mutate({ id: selectedUser.id, ids: effectivePermIds })} disabled={savePermMut.isPending}>保存权限</button>
            </div>
          </div>
        </div>
      )}

      {/* CSS */}
      <style jsx global>{`
        .us-page-root { padding: 16px 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; font-size: 14px; color: #333; }
        .us-page-title { font-size: 22px; font-weight: 600; margin-bottom: 16px; }

        .us-card { background: #fff; border: 1px solid #dee2e6; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
        .us-card-header { padding: 10px 16px; background: #f8f9fa; border-bottom: 1px solid #dee2e6; font-weight: 600; font-size: 15px; }
        .us-card-body { padding: 16px; }

        .us-row { display: flex; flex-wrap: wrap; }

        .us-form-label { display: block; margin-bottom: 4px; font-size: 13px; font-weight: 500; color: #495057; }
        .us-form-control { width: 100%; padding: 6px 10px; border: 1px solid #ced4da; border-radius: 6px; font-size: 13px; box-sizing: border-box; }
        .us-form-control:focus { border-color: #80bdff; outline: none; box-shadow: 0 0 0 3px rgba(0,123,255,0.15); }

        .us-btn { display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; border: 1px solid transparent; transition: all 0.15s; }
        .us-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .us-btn-primary { background: #007bff; color: #fff; border-color: #007bff; }
        .us-btn-primary:hover:not(:disabled) { background: #0069d9; }
        .us-btn-secondary { background: #6c757d; color: #fff; border-color: #6c757d; }
        .us-btn-secondary:hover:not(:disabled) { background: #5a6268; }
        .us-btn-outline-primary { background: transparent; color: #007bff; border-color: #007bff; }
        .us-btn-outline-primary:hover:not(:disabled) { background: #007bff; color: #fff; }
        .us-btn-outline-info { background: transparent; color: #17a2b8; border-color: #17a2b8; }
        .us-btn-outline-info:hover:not(:disabled) { background: #17a2b8; color: #fff; }
        .us-btn-outline-danger { background: transparent; color: #dc3545; border-color: #dc3545; }
        .us-btn-outline-danger:hover:not(:disabled) { background: #dc3545; color: #fff; }
        .us-btn-outline-success { background: transparent; color: #28a745; border-color: #28a745; }
        .us-btn-outline-success:hover:not(:disabled) { background: #28a745; color: #fff; }
        .us-btn-sm { padding: 3px 8px; font-size: 12px; }

        .us-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: #fff; }
        .us-badge-success { background: #28a745; }
        .us-badge-secondary { background: #6c757d; }

        .us-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .us-table th { padding: 8px 12px; background: #f8f9fa; border-bottom: 2px solid #dee2e6; font-weight: 600; text-align: left; }
        .us-table td { padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: middle; }
        .us-table tbody tr:hover { background: #f8f9fa; }

        .us-empty { text-align: center; padding: 24px; color: #6c757d; }
        .us-empty p { margin: 8px 0 0; font-size: 14px; }
        .us-mb3 { margin-bottom: 12px; }

        .us-perm-card { border: 2px solid #dee2e6; border-radius: 12px; padding: 12px; transition: all 0.2s; cursor: pointer; }
        .us-perm-card:hover { border-color: #87CEEB; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(135,206,235,0.3); }
        .us-perm-checked { border-color: #198754 !important; background: rgba(25,135,84,0.05); }
        .us-perm-badge { display: inline-block; padding: 2px 6px; border: 1px solid #dee2e6; border-radius: 4px; font-size: 11px; color: #495057; background: #f8f9fa; margin: 1px 2px; }

        .us-modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 1050; }
        .us-modal { background: #fff; border-radius: 12px; width: 480px; max-width: 90vw; max-height: 90vh; overflow-y: auto; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
        .us-modal-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid #dee2e6; }
        .us-modal-header h5 { margin: 0; font-size: 16px; font-weight: 600; }
        .us-modal-close { background: none; border: none; font-size: 22px; cursor: pointer; color: #6c757d; }
        .us-modal-close:hover { color: #333; }
        .us-modal-body { padding: 20px; }
        .us-modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid #dee2e6; }

        @media (max-width: 768px) {
          .us-row { flex-direction: column; }
          .us-page-root { padding: 8px 12px; }
        }
      `}</style>
    </div>
  );
}
