"use client";

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import Image from "next/image";
import Link from "next/link";
import {
  ShoppingCartIcon,
  PackagePlusIcon,
  TruckIcon,
  ClipboardCheckIcon,
  InboxIcon,
  BellIcon,
  ActivityIcon,
  ChevronRightIcon,
  ArrowUpIcon,
  ArrowDownIcon,
  ArrowRightIcon,
  AlertCircleIcon,
  CheckCircleIcon,
} from "lucide-react";

/* ===== Types ===== */
interface DashboardStats {
  order_today: number;
  order_yesterday: number;
  stockin_today: number;
  stockin_yesterday: number;
  stockout_today: number;
  stockout_yesterday: number;
  pending_approvals: number;
  low_stock_count: number;
  pending_purchases: number;
  pending_materials: number;
}

interface Activity {
  type: string;
  time: string;
  status: string;
  title: string;
  desc: string;
}

/* ===== Hero Section (includes KPI grid, matches Jinja2 structure) ===== */
function HeroBanner({ username, stats }: { username?: string; stats: DashboardStats | undefined }) {
  const [dateStr, setDateStr] = useState("");

  useEffect(() => {
    const weekDays = ["日", "一", "二", "三", "四", "五", "六"];
    const now = new Date();
    const ds = `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 星期${weekDays[now.getDay()]}`;
    setDateStr(ds);
  }, []);

  return (
    <div className="home-hero">
      <div className="hero-welcome">
        <h1>
          <Image
            src="/static/logo_plush.png"
            alt="滨发玩具"
            width={72}
            height={72}
            className="hero-logo"
          />
          欢迎回来，{username || "用户"}
        </h1>
      </div>
      <p className="hero-greeting" id="heroGreeting">
        今天是 {dateStr}。系统运行正常，以下是今日业务概览。
      </p>
      <KPIGrid stats={stats} />
    </div>
  );
}

/* ===== KPI Cards ===== */
function KPIGrid({ stats }: { stats: DashboardStats | undefined }) {
  const s = stats;

  return (
    <div className="kpi-grid">
      <Link href="/order" className="kpi-card kpi-order">
        <div className="kpi-header">
          <div className="kpi-icon kpi-order-icon"><ShoppingCartIcon className="h-5 w-5" /></div>
          <span className="kpi-arrow"><ArrowRightIcon className="h-3 w-3" /></span>
        </div>
        <div className="kpi-value">{s?.order_today ?? 0}</div>
        <div className="kpi-label">今日订单</div>
        <KpiTrend today={s?.order_today ?? 0} yesterday={s?.order_yesterday ?? 0} />
      </Link>

      <Link href="/stock" className="kpi-card kpi-stockin">
        <div className="kpi-header">
          <div className="kpi-icon kpi-stockin-icon"><PackagePlusIcon className="h-5 w-5" /></div>
          <span className="kpi-arrow"><ArrowRightIcon className="h-3 w-3" /></span>
        </div>
        <div className="kpi-value">{s?.stockin_today ?? 0}</div>
        <div className="kpi-label">今日备货</div>
        <KpiTrend today={s?.stockin_today ?? 0} yesterday={s?.stockin_yesterday ?? 0} />
      </Link>

      <Link href="/stock" className="kpi-card kpi-stockout">
        <div className="kpi-header">
          <div className="kpi-icon kpi-stockout-icon"><TruckIcon className="h-5 w-5" /></div>
          <span className="kpi-arrow"><ArrowRightIcon className="h-3 w-3" /></span>
        </div>
        <div className="kpi-value">{s?.stockout_today ?? 0}</div>
        <div className="kpi-label">今日出货</div>
        <KpiTrend today={s?.stockout_today ?? 0} yesterday={s?.stockout_yesterday ?? 0} />
      </Link>

      <Link href="/approval" className="kpi-card kpi-approval">
        <div className="kpi-header">
          <div className="kpi-icon kpi-approval-icon"><ClipboardCheckIcon className="h-5 w-5" /></div>
          <span className="kpi-arrow"><ArrowRightIcon className="h-3 w-3" /></span>
        </div>
        <div className="kpi-value">{s?.pending_approvals ?? 0}</div>
        <div className="kpi-label">待审批</div>
        {(s?.pending_approvals ?? 0) > 0 ? (
          <div className="kpi-trend trend-warn"><AlertCircleIcon className="h-3 w-3" /> 需处理</div>
        ) : (
          <div className="kpi-trend trend-up"><CheckCircleIcon className="h-3 w-3" /> 无待办</div>
        )}
      </Link>
    </div>
  );
}

function KpiTrend({ today, yesterday }: { today: number; yesterday: number }) {
  const diff = today - yesterday;
  const isUp = diff >= 0;
  return (
    <div className={`kpi-trend ${isUp ? "trend-up" : "trend-warn"}`}>
      {isUp ? <ArrowUpIcon className="h-3 w-3" /> : <ArrowDownIcon className="h-3 w-3" />}
      较昨日 {isUp ? "+" : ""}{diff}
    </div>
  );
}

/* ===== Todo List ===== */
function TodoList({ stats }: { stats: DashboardStats | undefined }) {
  const s = stats;
  const todos = [
    { count: s?.pending_approvals ?? 0, title: "笔订单待审批", href: "/approval", level: "urgent", label: "紧急", source: "采购中心", action: "去审批" },
    { count: s?.low_stock_count ?? 0, title: "个产品低库存预警", href: "/stock", level: "warning", label: "注意", source: "库存管理", action: "查看库存" },
    { count: s?.pending_purchases ?? 0, title: "笔采购单待确认", href: "/purchase", level: "info", label: "一般", source: "采购管理", action: "去处理" },
    { count: s?.pending_materials ?? 0, title: "笔来料待接收", href: "/material", level: "secondary", label: "提示", source: "来料登记", action: "查看详情" },
  ].filter(t => t.count > 0);

  const totalCount = todos.reduce((sum, t) => sum + t.count, 0);

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-header-title">
          <BellIcon className="h-4 w-4" /> 待办事项
        </div>
        <span className="todo-badge">{totalCount}</span>
      </div>
      <div className="card-body">
        <div className="todo-list" role="list">
          {totalCount === 0 ? (
            <div className="todo-empty">
              <InboxIcon className="h-12 w-12 opacity-20 mx-auto mb-3 block" />
              <p>暂无待办，一切正常</p>
            </div>
          ) : (
            todos.map((t, i) => (
              <Link key={i} href={t.href} className={`todo-item todo-${t.level}`} role="listitem">
                <div className="todo-dot" />
                <div className="todo-content">
                  <div className="todo-title">{t.count} {t.title}</div>
                  <div className="todo-meta">
                    <span className="todo-priority">{t.label}</span>
                    <span>· {t.source}</span>
                  </div>
                </div>
                <div className="todo-action"><span>{t.action}</span> <ChevronRightIcon className="h-3 w-3" /></div>
              </Link>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

/* ===== Timeline ===== */
const DOT_TYPE_MAP: Record<string, string> = {
  stockin: "dot-stockin",
  stockout: "dot-stockout",
  order: "dot-order",
  approval: "dot-approval",
  material: "dot-material",
};

const TAG_TYPE_MAP: Record<string, string> = {
  stockin: "tag-stockin",
  stockout: "tag-stockout",
  order: "tag-order",
  approval: "tag-approval",
  material: "tag-material",
};

function ActivityTimeline({ activities }: { activities: Activity[] | undefined }) {
  if (!activities || activities.length === 0) {
    return (
      <div className="card">
        <div className="card-header">
          <div className="card-header-title">
            <ActivityIcon className="h-4 w-4" /> 最近动态
          </div>
        </div>
        <div className="card-body">
          <div className="todo-empty">
            <ActivityIcon className="h-12 w-12 opacity-20 mx-auto mb-3 block" />
            <p>暂无动态</p>
          </div>
        </div>
      </div>
    );
  }

  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);

  const groups: { date: string; items: Activity[] }[] = [];
  let currentDate = "";
  for (const act of activities) {
    const actDate = act.time ? act.time.slice(0, 10) : "";
    if (actDate !== currentDate) {
      groups.push({ date: actDate, items: [act] });
      currentDate = actDate;
    } else {
      groups[groups.length - 1].items.push(act);
    }
  }

  function formatGroupDate(d: string) {
    if (d === today) return "今天";
    if (d === yesterday) return "昨天";
    return d;
  }

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-header-title">
          <ActivityIcon className="h-4 w-4" /> 最近动态
        </div>
        <Link href="/report" className="view-all-btn">查看全部 <ArrowRightIcon className="h-3 w-3" /></Link>
      </div>
      <div className="card-body">
        <div className="timeline">
          {groups.map((group, gi) => (
            <div key={gi} className="timeline-date-group">
              <div className="timeline-date">{formatGroupDate(group.date)}</div>
              {group.items.map((act, ai) => (
                <div key={ai} className="timeline-item" tabIndex={0}>
                  <div className="timeline-line">
                    <div className={`timeline-dot ${DOT_TYPE_MAP[act.type] || ""}`} />
                    <div className="timeline-connector" />
                  </div>
                  <div className="timeline-content">
                    {act.time && (
                      <div className="timeline-time">{act.time.slice(11, 16)}</div>
                    )}
                    <div className="timeline-title">
                      {act.status && (
                        <span className={`timeline-tag ${TAG_TYPE_MAP[act.type] || ""}`}>
                          {act.status}
                        </span>
                      )}
                      {act.title}
                    </div>
                    {act.desc && (
                      <div className="timeline-desc">{act.desc}</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ===== Dashboard Page ===== */
export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);

  const { data: stats } = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: () => get<DashboardStats>("/dashboard/stats"),
    staleTime: 5 * 60 * 1000,
  });

  const { data: activities } = useQuery({
    queryKey: ["dashboard", "activities"],
    queryFn: () => get<Activity[]>("/dashboard/activities"),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <>
      {/* Section 1+2: Hero + KPI (nested inside home-hero, matches Jinja2) */}
      <HeroBanner username={user?.username} stats={stats} />

      {/* Section 3+4: Todo + Timeline */}
      <div className="dashboard-row">
        <TodoList stats={stats} />
        <ActivityTimeline activities={activities} />
      </div>
    </>
  );
}
