import React, { useState, useEffect } from "react";
import { getAlerts } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const AlertsPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState("active");
  const [alerts, setAlerts] = useState<any[]>([]);
  const auth = useAuth();

  useEffect(() => {
    if (!auth.token) return;
    getAlerts().then(setAlerts).catch(console.error);
  }, [auth.token]);

  return (
    <div className="space-y-8 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h1 className="text-2xl font-black text-text-strong tracking-tight">Security & Alerts</h1>
          <p className="text-text-muted text-sm mt-1 font-medium">Critical system events and incident response management</p>
        </div>
        <div className="flex items-center bg-surface-bright/20 p-1 rounded-xl border border-outline-variant/20 shadow-inner">
           <button 
             onClick={() => setActiveTab("active")}
             className={`px-6 py-2 text-[10px] font-black uppercase tracking-[0.2em] rounded-lg transition-all ${
               activeTab === "active" ? "bg-error-red text-primary-on shadow-lg shadow-error-red/20" : "text-text-muted hover:text-text-strong"
             }`}
           >
             Active Incidents
           </button>
           <button 
             onClick={() => setActiveTab("resolved")}
             className={`px-6 py-2 text-[10px] font-black uppercase tracking-[0.2em] rounded-lg transition-all ${
               activeTab === "resolved" ? "bg-primary text-primary-on shadow-lg shadow-white/10" : "text-text-muted hover:text-text-strong"
             }`}
           >
             Resolution Log
           </button>
        </div>
      </div>

      <div className="grid gap-4">
        {alerts
          .map(a => ({
            id: a.id,
            severity: a.level.toLowerCase(),
            target: "System",
            issue: a.title,
            duration: new Date(a.timestamp * 1000).toLocaleString(),
            status: a.resolved_at ? "resolved" : "active",
            desc: a.body
          }))
          .filter(a => a.status === activeTab)
          .map((alert) => (
          <div key={alert.id} className="group relative bg-surface-container-low rounded-2xl border border-outline-variant/20 p-8 hover:border-primary/30 transition-all duration-300 flex flex-col lg:flex-row lg:items-center justify-between gap-8 shadow-sm">
            <div className={`absolute left-0 top-0 bottom-0 w-1.5 rounded-l-2xl ${alert.severity === 'critical' ? 'bg-error-red shadow-[4px_0_12px_rgba(248,113,113,0.3)]' : alert.severity === 'warning' ? 'bg-warning-amber' : 'bg-primary'}`}></div>
            
            <div className="flex items-start space-x-6">
              <div className={`mt-1.5 w-3 h-3 rounded-full shrink-0 ${alert.severity === 'critical' ? 'bg-error-red animate-pulse' : 'bg-warning-amber'}`}></div>
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  <h3 className="text-base font-black text-text-strong uppercase tracking-wide">{alert.issue}</h3>
                  <span className="px-2 py-1 rounded bg-surface-bright/50 text-[10px] font-black text-text-muted border border-outline-variant/30 uppercase tracking-widest">{alert.target}</span>
                  {alert.severity === 'critical' && <span className="px-2 py-1 rounded bg-error-red/10 text-[9px] font-black text-error-red border border-error-red/20 uppercase tracking-widest">Priority 1</span>}
                </div>
                <p className="text-xs text-text-muted font-medium max-w-2xl leading-relaxed">{alert.desc}</p>
              </div>
            </div>
            
            <div className="flex flex-row lg:flex-col items-center lg:items-end justify-between lg:justify-center gap-6 border-t lg:border-t-0 border-outline-variant/10 pt-6 lg:pt-0">
               <div className="flex flex-col lg:items-end">
                 <span className="text-[10px] text-text-muted uppercase font-black tracking-[0.2em]">Active Duration</span>
                 <span className="text-sm font-black font-mono text-text-strong tabular-nums">{alert.duration}</span>
               </div>
               <div className="flex items-center space-x-3">
                 {activeTab === 'active' ? (
                   <>
                     <button className="px-5 py-2.5 bg-surface-bright/50 text-text-strong hover:bg-surface-bright transition-all text-[10px] font-black uppercase tracking-widest rounded-lg border border-outline-variant/30">Suppress</button>
                     <button className="px-5 py-2.5 bg-primary text-primary-on hover:scale-105 transition-all text-[10px] font-black uppercase tracking-widest rounded-lg shadow-lg shadow-white/5">Resolve Fix</button>
                   </>
                 ) : (
                   <button className="px-5 py-2.5 bg-surface-bright/50 text-text-strong hover:bg-surface-bright transition-all text-[10px] font-black uppercase tracking-widest rounded-lg border border-outline-variant/30">Review Incident</button>
                 )}
               </div>
            </div>
          </div>
        ))}

        {alerts.filter(a => a.status === activeTab).length === 0 && (
          <div className="py-32 text-center bg-surface-container-low/50 rounded-2xl border border-dashed border-outline-variant/30">
             <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-surface-bright/50 mb-6">
                <svg className="w-6 h-6 text-text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
             </div>
             <p className="text-xs text-text-muted uppercase font-black tracking-[0.3em]">No {activeTab} incidents recorded</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default AlertsPage;
