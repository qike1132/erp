"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/lib/api-client";
import { useSearchParams } from "next/navigation";

// ============ Types ============

interface PermissionItem {
  id: number; name: string; code: string; parent_id: number | null;
  section_name: string; is_nav: boolean; children?: PermissionItem[];
}

interface UserPermissionResult {
  success: boolean; user_id: number; user_permission_ids: number[]; permissions: PermissionItem[];
}

interface UserItem {
  id: number; username: string; is_super: boolean; status: number; create_time: string;
}

// ============ Component ============

export function PermissionContent() {
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const [selectedUserId, setSelectedUserId] = useState<number | null>(() => {
    const uid = searchParams.get("userId");
    return uid ? Number(uid) : null;
  });
  const [selectedPermIds, setSelectedPermIds] = useState<number[]>([]);
  const [initialized, setInitialized] = useState(false);

  // Get users list for the dropdown
  const { data: usersData } = useQuery({
    queryKey: ["users"],
    queryFn: () => get<{ success: boolean; users: UserItem[] }>("/users/list"),
  });
  const users = usersData?.users ?? [];

  // Get user permissions
  const { data: permData, isLoading: permLoading } = useQuery({
    queryKey: ["user-permissions", selectedUserId],
    queryFn: () => get<UserPermissionResult>(`/users/permission/${selectedUserId}`),
    enabled: !!selectedUserId,
  });

  // Initialize selectedPermIds when data loads
  if (permData && !initialized) {
    setSelectedPermIds(permData.user_permission_ids);
    setInitialized(true);
  }

  const currentPermIds = permData?.user_permission_ids ?? [];
  const effectivePermIds = selectedPermIds.length > 0 || !permData ? selectedPermIds : currentPermIds;

  const savePermMut = useMutation({
    mutationFn: ({ id, ids }: { id: number; ids: number[] }) => post<Record<string, unknown>>(`/users/permission/${id}`, { permission_ids: ids }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["user-permissions", selectedUserId] }); setInitialized(false); },
  });

  const togglePerm = (id: number) => setSelectedPermIds(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);

  const toggleSection = (sectionIds: number[]) => {
    setSelectedPermIds(prev => {
      const allSelected = sectionIds.every(id => prev.includes(id));
      return allSelected ? prev.filter(id => !sectionIds.includes(id)) : [...new Set([...prev, ...sectionIds])];
    });
  };

  const selectedUser = users.find(u => u.id === selectedUserId);

  return (
    <div className="pm-page-root">
      <h2 className="pm-page-title">权限设置{selectedUser ? ` - ${selectedUser.username}` : ""}</h2>

      <div className="pm-card">
        <div className="pm-card-header">
          <span>权限分配</span>
          <span className="pm-badge-info">已选择 {effectivePermIds.length} 个权限</span>
        </div>
        <div className="pm-card-body">
          {/* User selector if no userId in URL */}
          {!searchParams.get("userId") && (
            <div style={{ marginBottom: 20 }}>
              <label className="pm-form-label">选择用户</label>
              <select className="pm-form-select" value={selectedUserId ?? ""} onChange={e => { setSelectedUserId(Number(e.target.value) || null); setSelectedPermIds([]); setInitialized(false); }}>
                <option value="">请选择用户</option>
                {users.filter(u => !u.is_super).map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
              </select>
            </div>
          )}

          {!selectedUserId ? (
            <div className="pm-empty"><i className="fas fa-shield-alt" style={{ fontSize: 48, opacity: 0.25 }}></i><p>请选择用户查看权限</p></div>
          ) : permLoading ? (
            <div className="pm-empty"><i className="fas fa-spinner fa-spin" style={{ fontSize: 32 }}></i><p>加载中...</p></div>
          ) : (
            <>
              <h5 style={{ marginBottom: 4, fontSize: 16 }}>功能模块</h5>
              <p style={{ color: "#6c757d", fontSize: 13, marginBottom: 16 }}>勾选功能模块将自动授予该模块下的所有操作权限</p>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
                {permData?.permissions.map(section => {
                  const sectionIds = [section.id, ...(section.children?.map(c => c.id) ?? [])];
                  const allSelected = sectionIds.every(id => effectivePermIds.includes(id));
                  return (
                    <div key={section.id} className={`pm-perm-card ${allSelected ? "pm-perm-checked" : ""}`} onClick={() => toggleSection(sectionIds)}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontWeight: 600, fontSize: 14 }} onClick={e => e.stopPropagation()}>
                          <input type="checkbox" checked={allSelected} onChange={() => toggleSection(sectionIds)} className="pm-checkbox" />
                          {section.section_name || section.name}
                        </label>
                        <i className={`fas fa-check-circle pm-check-icon ${allSelected ? "pm-check-visible" : "pm-check-hidden"}`}></i>
                      </div>
                      <div style={{ marginTop: 8 }}>
                        {section.children?.map(child => (
                          <span key={child.id} className="pm-perm-badge">{child.name}</span>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {(!permData?.permissions || permData.permissions.length === 0) && (
                <div className="pm-empty" style={{ marginTop: 24 }}><i className="fas fa-shield-alt" style={{ fontSize: 48, opacity: 0.25 }}></i><p>暂无可分配的权限模块</p></div>
              )}

              <div style={{ display: "flex", gap: 8, marginTop: 24 }}>
                <button className="pm-btn pm-btn-primary" onClick={() => savePermMut.mutate({ id: selectedUserId!, ids: effectivePermIds })} disabled={savePermMut.isPending}>
                  <i className="fas fa-save" style={{ marginRight: 4 }}></i>{savePermMut.isPending ? "保存中..." : "保存权限"}
                </button>
                <button className="pm-btn pm-btn-secondary" onClick={() => window.history.back()}>
                  <i className="fas fa-arrow-left" style={{ marginRight: 4 }}></i>返回列表
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      <style jsx global>{`
        .pm-page-root { padding: 16px 24px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; font-size: 14px; color: #333; }
        .pm-page-title { font-size: 22px; font-weight: 600; margin-bottom: 16px; }

        .pm-card { background: #fff; border: 1px solid #dee2e6; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
        .pm-card-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; background: #f8f9fa; border-bottom: 1px solid #dee2e6; font-weight: 600; font-size: 15px; }
        .pm-card-body { padding: 16px; }

        .pm-badge-info { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: #fff; background: #17a2b8; }
        .pm-form-label { display: block; margin-bottom: 4px; font-size: 13px; font-weight: 500; color: #495057; }
        .pm-form-select { width: 100%; max-width: 300px; padding: 6px 10px; border: 1px solid #ced4da; border-radius: 6px; font-size: 13px; }
        .pm-form-select:focus { border-color: #80bdff; outline: none; box-shadow: 0 0 0 3px rgba(0,123,255,0.15); }

        .pm-btn { display: inline-flex; align-items: center; padding: 8px 16px; border-radius: 6px; font-size: 14px; font-weight: 500; cursor: pointer; border: 1px solid transparent; transition: all 0.15s; }
        .pm-btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .pm-btn-primary { background: #007bff; color: #fff; }
        .pm-btn-primary:hover:not(:disabled) { background: #0069d9; }
        .pm-btn-secondary { background: #6c757d; color: #fff; }
        .pm-btn-secondary:hover:not(:disabled) { background: #5a6268; }

        .pm-perm-card { border: 2px solid #dee2e6; border-radius: 12px; padding: 12px; transition: all 0.3s; cursor: pointer; }
        .pm-perm-card:hover { border-color: #87CEEB; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(135,206,235,0.3); }
        .pm-perm-checked { border-color: #198754 !important; background: rgba(25,135,84,0.05); }

        .pm-checkbox { width: 1.2em; height: 1.2em; accent-color: #198754; }
        .pm-check-icon { font-size: 16px; transition: opacity 0.3s; }
        .pm-check-visible { color: #198754; opacity: 1; }
        .pm-check-hidden { color: #198754; opacity: 0; }
        .pm-perm-badge { display: inline-block; padding: 2px 8px; border: 1px solid #dee2e6; border-radius: 4px; font-size: 12px; font-weight: 400; color: #495057; background: #f8f9fa; margin: 2px; }

        .pm-empty { text-align: center; padding: 40px 20px; color: #6c757d; }
        .pm-empty p { margin: 8px 0 0; font-size: 14px; }

        @media (max-width: 768px) {
          .pm-page-root { padding: 8px 12px; }
        }
      `}</style>
    </div>
  );
}
