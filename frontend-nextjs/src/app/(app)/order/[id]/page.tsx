import { Suspense } from "react";
import { OrderEditContent } from "../order-edit-content";
import { Skeleton } from "@/components/ui/skeleton";

function OrderEditSkeleton() {
  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="rounded-md border p-6 space-y-6">
        <Skeleton className="h-7 w-32" />
        <div className="space-y-4">
          <div className="space-y-2">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-9 w-full" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-9 w-full" />
          </div>
          <div className="space-y-2">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-9 w-full" />
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-9 w-20" />
            <Skeleton className="h-9 w-16" />
          </div>
        </div>
      </div>
    </div>
  );
}

export default function OrderEditPage() {
  return (
    <Suspense fallback={<OrderEditSkeleton />}>
      <OrderEditContent />
    </Suspense>
  );
}
