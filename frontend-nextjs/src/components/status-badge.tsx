"use client";

import { Badge } from "@/components/ui/badge";

type StatusVariant = "success" | "danger" | "primary" | "warning" | "info" | "secondary" | "outline";

const STATUS_STYLES: Record<StatusVariant, string> = {
  success: "bg-emerald-100 text-emerald-700 border-emerald-200",
  danger: "bg-red-100 text-red-700 border-red-200",
  primary: "bg-blue-100 text-blue-700 border-blue-200",
  warning: "bg-amber-100 text-amber-700 border-amber-200",
  info: "bg-cyan-100 text-cyan-700 border-cyan-200",
  secondary: "bg-gray-100 text-gray-700 border-gray-200",
  outline: "bg-white text-muted-foreground border-border",
};

interface StatusBadgeProps {
  label: string;
  variant?: StatusVariant;
}

const STATUS_MAP: Record<string, StatusVariant> = {
  "待备货": "outline",
  "部分备货": "info",
  "已备货": "primary",
  "已出货": "success",
  "已完成": "success",
  "待审批": "warning",
  "已通过": "success",
  "已拒绝": "danger",
  "pending": "warning",
  "approved": "success",
  "rejected": "danger",
  "active": "success",
  "inactive": "secondary",
};

export function StatusBadge({ label, variant }: StatusBadgeProps) {
  const resolvedVariant = variant ?? STATUS_MAP[label] ?? "outline";
  const style = STATUS_STYLES[resolvedVariant];

  return (
    <Badge
      variant="outline"
      className={`plush-badge border ${style}`}
    >
      {label}
    </Badge>
  );
}

export function getStatusVariant(status: string): StatusVariant {
  return STATUS_MAP[status] ?? "outline";
}
