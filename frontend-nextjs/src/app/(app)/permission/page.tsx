import { Suspense } from "react";
import { PermissionContent } from "./permission-content";
import { Skeleton } from "@/components/ui/skeleton";

function PermissionSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-7 w-32" />
    </div>
  );
}

export default function PermissionPage() {
  return (
    <Suspense fallback={<PermissionSkeleton />}>
      <PermissionContent />
    </Suspense>
  );
}
