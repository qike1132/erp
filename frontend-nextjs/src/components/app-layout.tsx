import { AppSidebar } from "./app-sidebar";
import { AppHeader } from "./app-header";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen overflow-hidden">
      {/* Sidebar - matches Jinja2 .sidebar */}
      <aside className="hidden md:block">
        <AppSidebar />
      </aside>
      {/* Main content - matches Jinja2 .main-content */}
      <div className="app-main-content">
        <AppHeader />
        <main className="flex-1 overflow-y-auto scrollbar-thin">
          <div className="content-container">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
