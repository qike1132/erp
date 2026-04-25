import { Suspense } from "react";
import { cookies } from "next/headers";
import { UserContent } from "./user-content";
import { serverGet } from "@/lib/server-api";
import type { UserListResult } from "./user-content";

function UserSkeleton() {
  return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
      <p style={{ marginTop: 12 }}>加载中...</p>
    </div>
  );
}

export default async function UserPage() {
  let initialData: UserListResult | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    initialData = await serverGet<UserListResult>("/users/list", cookieHeader);
  } catch {
    // SSR fetch failed — client will retry
  }

  return (
    <Suspense fallback={<UserSkeleton />}>
      <UserContent initialData={initialData} />
    </Suspense>
  );
}
