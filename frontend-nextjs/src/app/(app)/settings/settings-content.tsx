"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import {
  SettingsIcon,
  HeartPulseIcon,
  ActivityIcon,
  DatabaseIcon,
  GaugeIcon,
  ServerIcon,
  RefreshCwIcon,
  Trash2Icon,
  ExternalLinkIcon,
  Loader2Icon,
} from "lucide-react";

// ============ Types ============

interface SystemStats {
  cache?: {
    hit_rate?: number;
    hits?: number;
    misses?: number;
    size?: number;
  };
  performance?: {
    avg_response_time?: number;
    total_requests?: number;
    error_count?: number;
    queries?: {
      slow_count?: number;
      avg_time?: number;
      total?: number;
    };
  };
}

interface HealthCheck {
  status: string;
  database?: string;
  redis?: string;
  uptime_seconds?: number;
  version?: string;
}

// ============ Helpers ============

function getCsrfToken(): string | null {
  const match = document.cookie.match(/fastapi_csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const csrfToken = getCsrfToken();
  const res = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      ...options.headers,
      ...(csrfToken && options.method && options.method !== "GET"
        ? { "X-CSRF-Token": csrfToken }
        : {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || "请求失败");
  }
  return res.json();
}

function formatUptime(seconds: number | undefined): string {
  if (!seconds) return "-";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${d}天 ${h}小时 ${m}分钟`;
}

// ============ Stat Item ============

function StatItem({ label, value, variant }: { label: string; value: React.ReactNode; variant?: "default" | "success" | "danger" | "warning" }) {
  return (
    <div className={`stat-item stat-item-${variant || "default"}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}

// ============ Content ============

export function SettingsContent() {
  const healthQuery = useQuery({
    queryKey: ["system-health"],
    queryFn: () => apiFetch<HealthCheck>("/health"),
    refetchInterval: 10_000,
  });

  const statsQuery = useQuery({
    queryKey: ["system-stats"],
    queryFn: () => apiFetch<SystemStats>("/api/v1/system/stats"),
    refetchInterval: 15_000,
  });

  const clearCacheMutation = useMutation({
    mutationFn: () =>
      apiFetch<{ success: boolean }>("/api/v1/cache/clear", { method: "POST" }),
    onSuccess: () => {
      toast.success("缓存已清除");
      statsQuery.refetch();
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const health = healthQuery.data;
  const stats = statsQuery.data;

  return (
    <div className="settings-page-root">
      {/* Page Header */}
      <div className="page-header-wrapper">
        <h2 className="page-title">
          <SettingsIcon className="mr-2 inline-block h-5 w-5" />
          系统设置
        </h2>
        <p className="page-subtitle">查看系统健康状态、性能监控和管理操作</p>
      </div>

      {/* Health Check Card */}
      <div className="card main-content-card mb-4">
        <div className="card-header d-flex justify-content-between align-items-center">
          <h6 className="mb-0 fw-bold">
            <HeartPulseIcon className="mr-2 inline-block h-4 w-4" />
            系统健康状态
          </h6>
          <button className="btn-outline-primary btn-sm" onClick={() => healthQuery.refetch()} disabled={healthQuery.isFetching}>
            <RefreshCwIcon className={`mr-1 inline-block h-3.5 w-3.5 ${healthQuery.isFetching ? "animate-spin" : ""}`} />刷新
          </button>
        </div>
        <div className="card-body">
          {healthQuery.isLoading ? (
            <div className="text-center py-4"><Loader2Icon className="mx-auto h-6 w-6 animate-spin text-muted" /><p className="text-muted mt-2 mb-0 text-sm">加载中...</p></div>
          ) : healthQuery.isError ? (
            <div className="stat-item stat-item-danger"><span className="stat-label">健康检查失败</span></div>
          ) : (
            <div className="stat-grid">
              <StatItem label="整体状态" value={
                <span className={`health-badge ${health?.status === "ok" || health?.status === "healthy" ? "health-ok" : "health-error"}`}>
                  {health?.status || "unknown"}
                </span>
              } variant={health?.status === "ok" || health?.status === "healthy" ? "success" : "danger"} />
              <StatItem label="数据库" value={
                <span className={`health-badge ${health?.database === "ok" ? "health-ok" : "health-error"}`}>
                  {health?.database || "unknown"}
                </span>
              } variant={health?.database === "ok" ? "success" : "danger"} />
              <StatItem label="Redis" value={
                <span className={`health-badge ${health?.redis === "ok" ? "health-ok" : "health-error"}`}>
                  {health?.redis || "unknown"}
                </span>
              } variant={health?.redis === "ok" ? "success" : "danger"} />
              <StatItem label="版本" value={health?.version || "-"} />
              <StatItem label="运行时长" value={formatUptime(health?.uptime_seconds)} />
            </div>
          )}
        </div>
      </div>

      {/* Performance Stats Card */}
      <div className="card main-content-card mb-4">
        <div className="card-header d-flex justify-content-between align-items-center">
          <h6 className="mb-0 fw-bold">
            <ActivityIcon className="mr-2 inline-block h-4 w-4" />
            性能监控
          </h6>
          <button className="btn-outline-primary btn-sm" onClick={() => statsQuery.refetch()} disabled={statsQuery.isFetching}>
            <RefreshCwIcon className={`mr-1 inline-block h-3.5 w-3.5 ${statsQuery.isFetching ? "animate-spin" : ""}`} />刷新
          </button>
        </div>
        <div className="card-body">
          {statsQuery.isLoading ? (
            <div className="text-center py-4"><Loader2Icon className="mx-auto h-6 w-6 animate-spin text-muted" /><p className="text-muted mt-2 mb-0 text-sm">加载中...</p></div>
          ) : statsQuery.isError ? (
            <div className="stat-item stat-item-danger"><span className="stat-label">统计数据加载失败</span></div>
          ) : (
            <>
              {/* Request Stats */}
              <div className="stat-section">
                <div className="stat-section-title"><GaugeIcon className="mr-1 inline-block h-4 w-4" />请求统计</div>
                <div className="stat-grid">
                  <StatItem label="总请求数" value={stats?.performance?.total_requests ?? "-"} />
                  <StatItem label="平均响应时间" value={
                    stats?.performance?.avg_response_time != null
                      ? `${(stats.performance.avg_response_time * 1000).toFixed(1)} ms`
                      : "-"
                  } />
                  <StatItem label="错误数" value={stats?.performance?.error_count ?? 0} variant={stats?.performance?.error_count ? "danger" : "default"} />
                </div>
              </div>

              <div className="stat-divider" />

              {/* Database Queries */}
              <div className="stat-section">
                <div className="stat-section-title"><DatabaseIcon className="mr-1 inline-block h-4 w-4" />数据库查询</div>
                <div className="stat-grid">
                  <StatItem label="总查询数" value={stats?.performance?.queries?.total ?? "-"} />
                  <StatItem label="平均耗时" value={
                    stats?.performance?.queries?.avg_time != null
                      ? `${(stats.performance.queries.avg_time * 1000).toFixed(1)} ms`
                      : "-"
                  } />
                  <StatItem label="慢查询数" value={stats?.performance?.queries?.slow_count ?? 0} variant={stats?.performance?.queries?.slow_count ? "warning" : "default"} />
                </div>
              </div>

              <div className="stat-divider" />

              {/* Cache Stats */}
              <div className="stat-section">
                <div className="stat-section-title"><ServerIcon className="mr-1 inline-block h-4 w-4" />缓存</div>
                <div className="stat-grid">
                  <StatItem label="命中率" value={
                    stats?.cache?.hit_rate != null
                      ? `${(stats.cache.hit_rate * 100).toFixed(1)}%`
                      : "-"
                  } variant={stats?.cache?.hit_rate != null && stats.cache.hit_rate < 0.5 ? "warning" : "default"} />
                  <StatItem label="命中数" value={stats?.cache?.hits ?? "-"} />
                  <StatItem label="未命中" value={stats?.cache?.misses ?? "-"} />
                  <StatItem label="缓存项" value={stats?.cache?.size ?? "-"} />
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Admin Actions Card */}
      <div className="card main-content-card">
        <div className="card-header">
          <h6 className="mb-0 fw-bold">
            <SettingsIcon className="mr-2 inline-block h-4 w-4" />
            管理操作
          </h6>
        </div>
        <div className="card-body">
          <div className="admin-actions">
            <button
              className="admin-action-btn admin-action-danger"
              onClick={() => clearCacheMutation.mutate()}
              disabled={clearCacheMutation.isPending}
            >
              <Trash2Icon className="mr-2 h-4 w-4" />
              {clearCacheMutation.isPending ? "清除中..." : "清除 Redis 缓存"}
            </button>
            <button className="admin-action-btn" onClick={() => window.open("/api/v1/docs", "_blank")}>
              <ExternalLinkIcon className="mr-2 h-4 w-4" />API 文档
            </button>
            <button className="admin-action-btn" onClick={() => window.open("/metrics", "_blank")}>
              <ExternalLinkIcon className="mr-2 h-4 w-4" />Prometheus 指标
            </button>
          </div>
          <p className="admin-note">清除缓存会立即失效所有 Redis 键，可能短期内增加数据库负载。</p>
        </div>
      </div>

      <style jsx global>{`
        .settings-page-root {
          padding: 0;
        }

        /* Stat Grid */
        .stat-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
          gap: 12px;
        }
        .stat-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 10px 14px;
          border-radius: 10px;
          background: #f8f9fa;
          border: 1px solid #e8ecf0;
          font-size: 13px;
          transition: all 0.2s;
        }
        .stat-item:hover {
          background: #f1f5f9;
        }
        .stat-item-success { border-left: 3px solid #28C76F; }
        .stat-item-danger { border-left: 3px solid #EA5455; }
        .stat-item-warning { border-left: 3px solid #f59e0b; }
        .stat-label { color: #8e99a4; font-size: 12px; }
        .stat-value { font-weight: 600; color: #5A4A4A; }

        /* Health Badges */
        .health-badge {
          display: inline-block;
          padding: 2px 10px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 700;
        }
        .health-ok {
          background: linear-gradient(135deg, #28C76F 0%, #1E9E55 100%);
          color: #fff;
        }
        .health-error {
          background: linear-gradient(135deg, #EA5455 0%, #FF7675 100%);
          color: #fff;
        }

        /* Stat Section */
        .stat-section {
          margin-bottom: 8px;
        }
        .stat-section-title {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 13px;
          font-weight: 600;
          color: #8e99a4;
          margin-bottom: 10px;
        }
        .stat-divider {
          height: 1px;
          background: #e8ecf0;
          margin: 16px 0;
        }

        /* Admin Actions */
        .admin-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }
        .admin-action-btn {
          display: inline-flex;
          align-items: center;
          padding: 8px 18px;
          border-radius: 10px;
          border: 1px solid #e8ecf0;
          background: #fff;
          cursor: pointer;
          font-size: 13px;
          font-weight: 500;
          color: #5A4A4A;
          transition: all 0.2s;
        }
        .admin-action-btn:hover {
          background: #eef7fb;
          border-color: #87ceeb;
        }
        .admin-action-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .admin-action-danger {
          border-color: #ffcdd2;
          color: #e53935;
        }
        .admin-action-danger:hover {
          background: #ffebee;
          border-color: #e53935;
        }
        .admin-note {
          margin-top: 12px;
          font-size: 12px;
          color: #8e99a4;
        }
      `}</style>
    </div>
  );
}
