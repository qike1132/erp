import AppLayout from "@/components/app-layout";

/**
 * (app) 路由组共享布局 - Server Component
 *
 * 所有认证页面的共享布局外壳。AppLayout（侧边栏+头部）在此处渲染，
 * 页面导航时布局持久化，仅 {children} 区域重新渲染，实现 SPA 级路由切换。
 */
export default function AppGroupLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AppLayout>{children}</AppLayout>;
}
