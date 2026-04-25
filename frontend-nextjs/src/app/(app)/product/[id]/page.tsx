import { Suspense } from "react";
import { ProductEditContent } from "../product-edit-content";
import { Skeleton } from "@/components/ui/skeleton";

function ProductEditSkeleton() {
  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="rounded-md border p-6 space-y-6">
        <Skeleton className="h-7 w-32" />
        <div className="space-y-4">
          <div className="flex items-start gap-4">
            <Skeleton className="h-24 w-24" />
            <div className="space-y-2">
              <Skeleton className="h-9 w-48" />
              <Skeleton className="h-4 w-48" />
            </div>
          </div>
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

export default function ProductEditPage() {
  return (
    <Suspense fallback={<ProductEditSkeleton />}>
      <ProductEditContent />
    </Suspense>
  );
}
