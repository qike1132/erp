"use client";

import { useQuery } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { get } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import {
  FileTextIcon,
  WarehouseIcon,
  TruckIcon,
  DollarSignIcon,
  BarChart3Icon,
  UsersIcon,
  ShieldIcon,
  SettingsIcon,
  ShoppingCartIcon,
  FactoryIcon,
  ClipboardListIcon,
  FileIcon,
  CalculatorIcon,
  PackageIcon,
  ScanLineIcon,
  UserCheckIcon,
  BoxesIcon,
  HeartIcon,
  type LucideIcon,
} from "lucide-react";

interface NavItem {
  name: string;
  code: string;
  icon: string | null;
  url: string;
  permission_codes: string[];
}

interface NavSection {
  name: string;
  items: NavItem[];
}

const ICON_MAP: Record<string, LucideIcon> = {
  "fa-box": PackageIcon,
  "fa-file-invoice": FileTextIcon,
  "fa-warehouse": WarehouseIcon,
  "fa-truck": TruckIcon,
  "fa-money-bill": DollarSignIcon,
  "fa-chart-bar": BarChart3Icon,
  "fa-users": UsersIcon,
  "fa-shield": ShieldIcon,
  "fa-cogs": SettingsIcon,
  "fa-shopping-cart": ShoppingCartIcon,
  "fa-industry": FactoryIcon,
  "fa-clipboard": ClipboardListIcon,
  "fa-file-alt": FileIcon,
  "fa-calculator": CalculatorIcon,
  "fa-boxes": BoxesIcon,
  "fa-scan": ScanLineIcon,
  "fa-user-check": UserCheckIcon,
};

function getIconComponent(icon: string | null): LucideIcon {
  if (!icon) return FileIcon;
  const Component = ICON_MAP[icon];
  return Component ?? FileIcon;
}

const SECTION_ORDER = ["purchase", "purchase_tools", "core", "finance", "data", "system"];

export function AppSidebar() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const pathname = usePathname();

  const { data: userInfo } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () =>
      get<{
        user_id: number;
        username: string;
        is_super: boolean;
        permissions: string[];
      }>("/auth/me"),
    staleTime: 5 * 60 * 1000,
    enabled: !user,
  });

  const { data: navData } = useQuery({
    queryKey: ["dashboard", "nav-sections"],
    queryFn: () => get<Record<string, NavSection>>("/dashboard/nav-sections"),
    staleTime: 5 * 60 * 1000,
  });

  const permissions = user?.permissions ?? [];
  const isSuper = user?.isSuper ?? false;

  const sections: NavSection[] = (() => {
    if (!navData) return [];
    const sorted = Object.entries(navData).sort(([a], [b]) => {
      const ai = SECTION_ORDER.indexOf(a);
      const bi = SECTION_ORDER.indexOf(b);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });
    return sorted.map(([, v]) => v);
  })();

  return (
    <div className="app-sidebar-root flex h-full flex-col overflow-y-auto overflow-x-hidden scrollbar-thin">
      <div className="sidebar-header-area">
        <div className="flex items-center gap-3.5 mb-3">
          <Image
            src="/static/logo_plush.png"
            alt="滨发玩具"
            width={56}
            height={56}
            className="sidebar-logo-img"
          />
          <div>
            <div className="sidebar-title-text">滨发协同系统</div>
            <div className="sidebar-subtitle-text">毛绒玩具全流程管理</div>
          </div>
        </div>
      </div>

      <nav className="sidebar-nav-area">
        {sections.map((section) => {
          const visibleItems = section.items.filter((item) => {
            if (isSuper) return true;
            return item.permission_codes.some((c) => permissions.includes(c));
          });
          if (visibleItems.length === 0) return null;

          return (
            <div key={section.name} className="nav-section-block">
              <p className="nav-section-label">{section.name}</p>
              {visibleItems.map((item) => {
                const IconComp = getIconComponent(item.icon);
                const isActive = pathname === item.url;
                return (
                  <Link
                    key={item.code}
                    href={item.url}
                    className={`nav-item-btn ${isActive ? "active" : ""}`}
                  >
                    <IconComp className="nav-item-icon h-[18px] w-[18px]" />
                    <span>{item.name}</span>
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>

      <div className="sidebar-footer-area">
        <div className="text-center text-[11px] opacity-70" style={{ color: "#595959" }}>
          <HeartIcon className="inline-block h-3 w-3 mr-1" style={{ color: "#EF9A9A" }} />
          滨发协同系统 v2.0
        </div>
      </div>
    </div>
  );
}
