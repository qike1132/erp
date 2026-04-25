import { Suspense } from "react";
import { OcrImportContent } from "./ocr-import-content";
import { Skeleton } from "@/components/ui/skeleton";

function OcrImportSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <Skeleton className="h-7 w-52" />
        <Skeleton className="h-5 w-36" />
      </div>
      <div className="rounded-lg border bg-card p-6">
        <Skeleton className="h-5 w-48 mb-4" />
        <Skeleton className="h-10 w-full mb-2" />
        <Skeleton className="h-4 w-64" />
      </div>
    </div>
  );
}

export default function OcrImportPage() {
  return (
    <Suspense fallback={<OcrImportSkeleton />}>
      <OcrImportContent />
    </Suspense>
  );
}
