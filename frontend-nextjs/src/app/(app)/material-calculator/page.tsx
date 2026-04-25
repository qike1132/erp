import { Suspense } from "react";
import { MaterialCalculatorContent } from "./material-calculator-content";
import { Skeleton } from "@/components/ui/skeleton";

function MaterialCalculatorSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-7 w-28" />
      <div className="flex items-end gap-3">
        <div className="flex-1 max-w-md space-y-1.5">
          <Skeleton className="h-4 w-16" />
          <div className="flex gap-2">
            <Skeleton className="h-9 flex-1" />
            <Skeleton className="h-9 w-16" />
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MaterialCalculatorPage() {
  return (
    <Suspense fallback={<MaterialCalculatorSkeleton />}>
      <MaterialCalculatorContent />
    </Suspense>
  );
}
