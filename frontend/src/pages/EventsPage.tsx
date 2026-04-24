import React, { useState } from "react";

const EventsPage: React.FC = () => {
  const [filter, setFilter] = useState("all");

  const events = [
    { id: 1, time: "2026-04-24 19:45:12", type: "system", message: "Interface WAN1 switched to eth0 (Fiber)", severity: "info" },
    { id: 2, time: "2026-04-24 19:40:05", type: "network", message: "Latency spike detected on eth1 (LTE): 450ms", severity: "warning" },
    { id: 3, time: "2026-04-24 19:35:00", type: "auth", message: "Successful login from admin (192.168.1.50)", severity: "info" },
    { id: 4, time: "2026-04-24 19:30:22", type: "system", message: "Core controller service restarted", severity: "success" },
    { id: 5, time: "2026-04-24 19:25:10", type: "network", message: "VPN Tunnel 'Office-Primary' disconnected", severity: "error" },
    { id: 6, time: "2026-04-24 19:20:00", type: "system", message: "New firmware update available: v2.1.4", severity: "info" },
  ];

  const getSeverityStyles = (severity: string) => {
    switch (severity) {
      case "error": return "bg-red-500/10 text-red-400 border-red-500/20";
      case "warning": return "bg-yellow-500/10 text-yellow-400 border-yellow-500/20";
      case "success": return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      default: return "bg-sky-500/10 text-sky-400 border-sky-500/20";
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-text-strong">System Events</h2>
          <p className="text-sm text-text-muted">Audit logs and network state transitions</p>
        </div>
        <div className="flex items-center space-x-2 bg-surface p-1 rounded-sm border border-white/5">
           {["all", "info", "warning", "error"].map((f) => (
             <button
               key={f}
               onClick={() => setFilter(f)}
               className={`px-3 py-1 text-[10px] font-bold uppercase tracking-widest rounded-sm transition-all ${
                 filter === f ? "bg-brand-primary text-white" : "text-text-muted hover:text-white"
               }`}
             >
               {f}
             </button>
           ))}
        </div>
      </div>

      <div className="bg-surface rounded-base border border-white/5 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-white/5">
                <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest">Timestamp</th>
                <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest">Type</th>
                <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest">Message</th>
                <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest text-right">Severity</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {events
                .filter(e => filter === "all" || e.severity === filter)
                .map((event) => (
                <tr key={event.id} className="hover:bg-white/[0.02] transition-colors group">
                  <td className="px-6 py-4 text-xs font-mono text-text-muted">{event.time}</td>
                  <td className="px-6 py-4 text-xs">
                    <span className="text-text-strong font-medium uppercase tracking-tighter text-[10px]">{event.type}</span>
                  </td>
                  <td className="px-6 py-4 text-xs text-text-strong">{event.message}</td>
                  <td className="px-6 py-4 text-right">
                    <span className={`inline-block px-2 py-0.5 rounded-sm text-[9px] font-black uppercase border ${getSeverityStyles(event.severity)}`}>
                      {event.severity}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-6 py-4 bg-white/5 border-t border-white/5 flex items-center justify-between">
          <span className="text-[10px] text-text-muted uppercase font-bold tracking-widest">Showing 6 of 1,245 events</span>
          <div className="flex space-x-2">
             <button className="p-1 text-text-muted hover:text-white transition-colors">
               <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
             </button>
             <button className="p-1 text-text-muted hover:text-white transition-colors">
               <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
             </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default EventsPage;
