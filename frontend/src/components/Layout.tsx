import React, { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAlertCount } from "../context/AlertCountContext";
import { sseManager } from "../api/sse";
import { getAuthConfig } from "../api/client";

interface LayoutProps {
  children: React.ReactNode;
}

function formatUptime(startTime: number): string {
  const secs = Math.floor(Date.now() / 1000 - startTime);
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation();
  const { unresolved } = useAlertCount();
  const [startTime, setStartTime] = useState<number | null>(null);
  const [authEnabled, setAuthEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    const onStatus = (d: any) => {
      if (d?.start_time) setStartTime(d.start_time);
    };
    sseManager.on("status", onStatus);
    return () => sseManager.off("status", onStatus);
  }, []);

  useEffect(() => {
    getAuthConfig()
      .then((cfg) => setAuthEnabled(cfg.auth_enabled))
      .catch(() => setAuthEnabled(true));
  }, []);

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
        {unresolved > 0 && <span className="absolute -top-1 -right-1 flex h-2 w-2 rounded-full bg-error-red"></span>}
      </div>
    )},
    { name: "Config", path: "/config", icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
    )},
    ...(authEnabled ? [{ name: "Users", path: "/users", icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a4 4 0 00-4-4h-1M9 20H4v-2a4 4 0 014-4h1m6-4a4 4 0 11-8 0 4 4 0 018 0zm6 2a3 3 0 10-6 0" /></svg>
    )}] : []),
  ];

  return (
    <div className="flex min-h-screen bg-canvas text-on-surface font-sans selection:bg-primary/20">
      {/* Desktop Sidebar */}
      <aside className="hidden md:flex flex-col w-64 bg-surface-dim border-r border-outline-variant/30 fixed inset-y-0">
        <div className="p-6 flex items-center space-x-3 border-b border-outline-variant/20">
          <div className="w-10 h-10 bg-primary text-primary-on rounded-lg flex items-center justify-center font-black text-lg shadow-lg shadow-white/5">WC</div>
          <div className="flex flex-col">
            <h1 className="font-bold tracking-tight text-text-strong leading-none">WANControl</h1>
            <span className="text-[10px] text-text-muted font-bold uppercase tracking-[0.2em] mt-1">v2.0 Enterprise</span>
          </div>
        </div>
        <nav className="flex-1 p-4 space-y-2 mt-4">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center space-x-3 px-4 py-3 rounded-md transition-all duration-200 group ${
                location.pathname === item.path
                  ? "bg-surface-bright/20 text-text-strong border border-white/10 shadow-sm"
                  : "text-text-muted hover:bg-surface-bright/10 hover:text-text-strong border border-transparent"
              }`}
            >
              <div className={`${location.pathname === item.path ? "text-primary" : "group-hover:text-text-strong"} transition-colors`}>
                {item.icon}
              </div>
              <span className="text-sm font-semibold tracking-wide">{item.name}</span>
              {location.pathname === item.path && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-primary shadow-[0_0_8px_rgba(255,255,255,0.5)]"></div>
              )}
            </Link>
          ))}
        </nav>
        <div className="p-6 border-t border-outline-variant/20">
          <div className="flex items-center space-x-4 p-3 rounded-lg bg-surface-container-low border border-outline-variant/20">
            <div className="relative">
              <div className="w-3 h-3 rounded-full bg-success-green shadow-[0_0_8px_rgba(74,222,128,0.5)]"></div>
              <div className="absolute inset-0 w-3 h-3 rounded-full bg-success-green animate-ping opacity-75"></div>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-black uppercase tracking-widest text-text-strong">Operational</span>
              <span className="text-[9px] text-text-muted font-medium">
                {startTime ? `Uptime: ${formatUptime(startTime)}` : "Connecting..."}
              </span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 md:ml-64 flex flex-col min-h-screen">
        {/* Header */}
        <header className="h-16 flex items-center justify-between px-8 bg-canvas/60 backdrop-blur-xl sticky top-0 z-10 border-b border-outline-variant/20">
          <div className="md:hidden flex items-center space-x-3">
             <div className="w-8 h-8 bg-primary text-primary-on rounded flex items-center justify-center font-black text-xs">WC</div>
             <span className="font-bold text-sm tracking-tight">WANControl</span>
          </div>
          <div className="hidden md:flex items-center space-x-2">
            <span className="text-xs font-bold text-text-muted uppercase tracking-widest">Network Ops</span>
            <span className="text-text-muted/30">/</span>
            <h2 className="text-sm font-black text-text-strong uppercase tracking-widest">
              {navItems.find(i => i.path === location.pathname)?.name || "Page"}
            </h2>
          </div>
          <div className="flex items-center space-x-6">
             <button className="relative p-2 text-text-muted hover:text-text-strong transition-all group">
               <svg className="w-5 h-5 group-hover:scale-110 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
             </button>
             <div className="h-8 w-px bg-outline-variant/30"></div>
             <div className="flex items-center space-x-3">
               <div className="flex flex-col items-end hidden sm:flex">
                 <span className="text-xs font-bold text-text-strong">Aditya Malpani</span>
                 <span className="text-[10px] text-primary font-bold uppercase tracking-tighter">System Admin</span>
               </div>
               <div className="w-9 h-9 rounded-xl bg-surface-bright border border-outline-variant/40 flex items-center justify-center overflow-hidden shadow-inner group cursor-pointer hover:border-primary/50 transition-colors">
                 <span className="text-xs font-black group-hover:scale-110 transition-transform">AD</span>
               </div>
             </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 p-6 overflow-x-hidden">
          <div className="max-w-[1600px] mx-auto">
            {children}
          </div>
        </main>

        {/* Mobile Bottom Nav */}
        <nav className="md:hidden flex bg-surface-dim/95 backdrop-blur-lg border-t border-outline-variant/30 fixed bottom-0 inset-x-0 h-16 safe-area-bottom z-50">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`flex-1 flex flex-col items-center justify-center space-y-1 transition-all ${
                location.pathname === item.path
                  ? "text-primary"
                  : "text-text-muted hover:text-text-strong"
              }`}
            >
              {item.icon}
              <span className="text-[9px] font-black uppercase tracking-widest leading-none">{item.name}</span>
            </Link>
          ))}
        </nav>
        <div className="md:hidden h-16"></div> {/* Spacer for bottom nav */}
      </div>
    </div>
  );
};

export default Layout;
