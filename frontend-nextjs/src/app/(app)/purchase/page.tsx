import { Suspense } from "react";
import { PurchaseContent } from "./purchase-content";
import { Skeleton } from "@/components/ui/skeleton";

function PurchaseSkeleton() {
  return (
    <div className="pc-root">
      {/* Page Header */}
      <div className="pc-header">
        <div className="pc-header-content">
          <div className="pc-header-left">
            <Skeleton className="h-7 w-32" />
            <Skeleton className="h-5 w-48 mt-2" />
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="pc-body">
        <div className="pc-tabs">
          <Skeleton className="h-10 w-32 rounded-b-none" />
          <Skeleton className="h-10 w-32 rounded-b-none" />
        </div>

        {/* Pending Orders Card */}
        <div className="pc-card pc-pending-section">
          <div className="pc-card-header">
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-8 w-32" />
          </div>
          <div className="pc-card-body">
            <Skeleton className="h-48 w-full rounded-xl" />
          </div>
        </div>

        {/* Divider */}
        <div className="pc-section-divider"></div>

        {/* Orders Card */}
        <div className="pc-card">
          <div className="pc-card-header">
            <Skeleton className="h-5 w-28" />
            <div className="flex gap-2">
              <Skeleton className="h-8 w-28" />
              <Skeleton className="h-8 w-32" />
              <Skeleton className="h-6 w-20 rounded-full" />
            </div>
          </div>
          <div className="pc-card-body">
            {/* Filter Bar */}
            <div className="pc-filter-bar">
              <Skeleton className="h-9 w-56" />
              <div className="flex gap-1">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-7 w-14 rounded-xl" />
                ))}
              </div>
            </div>
            {/* Order Cards Skeleton */}
            <div className="pc-order-cards">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-48 w-full rounded-xl" />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PurchasePage() {
  return (
    <Suspense fallback={<PurchaseSkeleton />}>
      <PurchaseContent />
    </Suspense>
  );
}
