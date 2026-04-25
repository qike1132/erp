import { Suspense } from "react";
import { PurchasePlanContent } from "./purchase-plan-content";
import { Skeleton } from "@/components/ui/skeleton";

function PurchasePlanSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-7 w-32" />
      <div className="flex items-center gap-2">
        <Skeleton className="h-9 w-24" />
        <Skeleton className="h-4 w-8" />
        <Skeleton className="h-9 w-20" />
        <Skeleton className="h-4 w-8" />
      </div>
      <div className="space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    </div>
  );
}

export default function PurchasePlanPage() {
  return (
    <Suspense fallback={<PurchasePlanSkeleton />}>
      <PurchasePlanContent />
    </Suspense>
  );
}
