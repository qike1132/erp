"use client";

import { useState, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { AppSidebar } from "./app-sidebar";
import { HomeIcon, LogOutIcon, MenuIcon, ClockIcon } from "lucide-react";

export function AppHeader() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [currentTime, setCurrentTime] = useState("");
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const router = useRouter();
  const pathname = usePathname();
  const isHome = pathname === "/dashboard";

  useEffect(() => {
    function updateTime() {
      const now = new Date();
      const timeStr =
        now.getFullYear() +
        "-" +
        String(now.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(now.getDate()).padStart(2, "0") +
        " " +
        String(now.getHours()).padStart(2, "0") +
        ":" +
        String(now.getMinutes()).padStart(2, "0");
      setCurrentTime(timeStr);
    }
    updateTime();
    const interval = setInterval(updateTime, 60000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  return (
    <header className="app-top-header flex items-center justify-between">
      <div className="header-left flex items-center gap-4">
        <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
          <SheetTrigger className="md:hidden inline-flex items-center justify-center rounded-[14px] text-[#5A4A4A] hover:bg-[#D4F1F4] h-11 w-11 transition-colors border-2 border-[#B0E0E6] shadow-[0_2px_8px_rgba(176,224,230,0.25)]">
            <MenuIcon className="h-5 w-5" />
          </SheetTrigger>
          <SheetContent side="left" className="w-[280px] p-0">
            <AppSidebar />
          </SheetContent>
        </Sheet>
        {!isHome && (
          <button
            onClick={() => router.push("/dashboard")}
            className="home-btn-header"
          >
            <HomeIcon className="h-4 w-4" />
            <span className="hidden sm:inline">返回首页</span>
          </button>
        )}
      </div>

      <div className="header-right flex items-center gap-5">
        <span className="hidden sm:flex items-center gap-1.5 text-[13px] font-medium" style={{ color: "#595959" }}>
          <ClockIcon className="h-3.5 w-3.5" />
          <span>{currentTime}</span>
        </span>

        {user && (
          <>
            <div className="user-info-header">
              <div className="user-avatar-header">
                {user.username.slice(0, 1).toUpperCase()}
              </div>
              <div className="user-info-details hidden sm:block">
                <div className="user-name-header">{user.username}</div>
                <div className="user-role-header">{user.isSuper ? "超级管理员" : "普通用户"}</div>
              </div>
            </div>

            <button
              onClick={logout}
              className="logout-btn-header"
              title="退出登录"
            >
              <LogOutIcon className="h-4 w-4" />
              <span className="hidden sm:inline">退出</span>
            </button>
          </>
        )}
      </div>
    </header>
  );
}
