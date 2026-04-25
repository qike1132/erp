"use client";

import { PlusIcon, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface PageHeaderProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  action?: {
    label: string;
    onClick: () => void;
    icon?: LucideIcon;
  };
  badge?: {
    label: string;
    variant?: "default" | "secondary" | "destructive" | "outline";
  };
}

export function PageHeader({ title, description, icon: Icon, action, badge }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-3">
        {Icon && (
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-plush-blue-deep to-plush-blue shadow-sm">
            <Icon className="h-5 w-5 text-white" />
          </div>
        )}
        <div>
          <div className="flex items-center gap-2">
            <h1 className="plush-section-title !mb-0 !text-2xl">{title}</h1>
            {badge && <Badge variant={badge.variant}>{badge.label}</Badge>}
          </div>
          {description && (
            <p className="text-sm text-muted-foreground mt-0.5">{description}</p>
          )}
        </div>
      </div>
      {action && (
        <Button onClick={action.onClick} className="plush-btn bg-gradient-to-r from-plush-blue-deep to-plush-blue text-white shadow-sm hover:shadow-md">
          {action.icon ? <action.icon className="mr-2 h-4 w-4" /> : <PlusIcon className="mr-2 h-4 w-4" />}
          {action.label}
        </Button>
      )}
    </div>
  );
}
