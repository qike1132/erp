import { Suspense } from "react";
import { MaterialContent } from "./material-content";
import { Skeleton } from "@/components/ui/skeleton";

function MaterialSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-7 w-32" />
      <div className="flex gap-2">
        <Skeleton className="h-8 w-16" />
        <Skeleton className="h-8 w-16" />
        <Skeleton className="h-8 w-16" />
        <Skeleton className="h-8 w-16" />
      </div>
      <div className="space-y-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    </div>
  );
}

export default function MaterialPage() {
  return (
    <Suspense fallback={<MaterialSkeleton />}>
      <MaterialContent />
    </Suspense>
  );
}
