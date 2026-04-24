import React from "react";
import { Link, useLocation } from "react-router-dom";
import { useAlertCount } from "../context/AlertCountContext";

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation();
  const { unresolved } = useAlertCount();

  const navItems = [
    { name: "Dashboard", path: "/", icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" /></svg>
    )},
    { name: "Metrics", path: "/metrics", icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>
    )},
    { name: "Events", path: "/events", icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
    )},
    { name: "Alerts", path: "/alerts", icon: (
      <div className="relative">
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" /></svg>
        {unresolved > 0 && <span className="absolute -top-1 -right-1 flex h-2 w-2 rounded-full bg-status-error"></span>}
      </div>
    )},
    { name: "Config", path: "/config", icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
    )},
  ];

  return (
    <div className="flex min-h-screen bg-canvas text-text-strong font-sans">
      {/* Desktop Sidebar */}
      <aside className="hidden md:flex flex-col w-64 bg-surface border-r border-white/5 fixed inset-y-0">
        <div className="p-6 flex items-center space-x-3 border-b border-white/5">
          <div className="w-8 h-8 bg-brand-primary rounded flex items-center justify-center font-bold text-sm">WC</div>
          <h1 className="font-semibold tracking-tight">WANControl v2</h1>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center space-x-3 px-4 py-2.5 rounded-base transition-colors ${
                location.pathname === item.path
                  ? "bg-white/10 text-white"
                  : "text-text-muted hover:bg-white/5 hover:text-white"
              }`}
            >
              {item.icon}
              <span className="text-sm font-medium">{item.name}</span>
            </Link>
          ))}
        </nav>
        <div className="p-4 border-t border-white/5">
          <div className="flex items-center space-x-3 px-4 py-2 text-text-muted">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
            <span className="text-xs font-medium uppercase tracking-wider">System Online</span>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 md:ml-64 flex flex-col min-h-screen">
        {/* Header */}
        <header className="h-16 flex items-center justify-between px-6 bg-surface/80 backdrop-blur-md sticky top-0 z-10 border-b border-white/5">
          <div className="md:hidden flex items-center space-x-3">
             <div className="w-8 h-8 bg-brand-primary rounded flex items-center justify-center font-bold text-xs">WC</div>
             <span className="font-semibold text-sm">WANControl</span>
          </div>
          <div className="hidden md:block">
            <h2 className="text-sm font-medium text-text-muted">
              {navItems.find(i => i.path === location.pathname)?.name || "Page"}
            </h2>
          </div>
          <div className="flex items-center space-x-4">
             <button className="p-2 text-text-muted hover:text-white transition-colors">
               <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
             </button>
             <div className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center overflow-hidden border border-white/10">
               <span className="text-xs font-bold">AD</span>
             </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 p-page overflow-x-hidden">
          {children}
        </main>

        {/* Mobile Bottom Nav */}
        <nav className="md:hidden flex bg-surface border-t border-white/5 fixed bottom-0 inset-x-0 h-16 safe-area-bottom">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex-1 flex flex-col items-center justify-center space-y-1 transition-colors ${
                location.pathname === item.path
                  ? "text-white"
                  : "text-text-muted hover:text-white"
              }`}
            >
              {item.icon}
              <span className="text-[10px] font-medium uppercase tracking-widest">{item.name}</span>
            </Link>
          ))}
        </nav>
        <div className="md:hidden h-16"></div> {/* Spacer for bottom nav */}
      </div>
    </div>
  );
};

export default Layout;
