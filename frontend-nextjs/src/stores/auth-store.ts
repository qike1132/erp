/**
 * 认证状态管理
 *
 * 使用Zustand管理用户认证状态，替代window全局变量模式（修复P1-03）
 * 配合TanStack Query缓存用户数据，避免每个页面重复请求
 */

import { create } from "zustand";

interface User {
  id: number;
  username: string;
  isSuper: boolean;
  permissions: string[];
}

interface AuthState {
  user: User | null;
  setUser: (user: User | null) => void;
  hasPermission: (code: string) => boolean;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,

  setUser: (user) => set({ user }),

  hasPermission: (code) => {
    const { user } = get();
    if (!user) return false;
    if (user.isSuper) return true;
    return user.permissions.includes(code);
  },

  logout: () => {
    set({ user: null });
    // 调用后端清除 httpOnly cookie，再跳转登录页
    fetch("/api/v1/auth/logout", { method: "POST", credentials: "include" })
      .catch(() => {})
      .finally(() => {
        window.location.href = "/login";
      });
  },
}));
