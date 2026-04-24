import React, { useState } from "react";

const AlertsPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState("active");

  const alerts = [
    { id: 1, severity: "critical", target: "WAN 1", issue: "Complete Link Failure", duration: "12m 45s", status: "active" },
    { id: 2, severity: "warning", target: "VPN Tunnel", issue: "Packet Loss > 5%", duration: "1h 22m", status: "active" },
    { id: 3, severity: "info", target: "System", issue: "Backup power engaged", duration: "4h 10m", status: "resolved" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-text-strong">Network Alerts</h2>
          <p className="text-sm text-text-muted">Manage active incidents and historical resolutions</p>
        </div>
        <div className="flex items-center space-x-2">
           <button 
             onClick={() => setActiveTab("active")}
             className={`px-4 py-2 text-[10px] font-bold uppercase tracking-widest rounded-sm transition-all border ${
               activeTab === "active" ? "bg-status-error/10 text-status-error border-status-error/20" : "text-text-muted border-white/5 hover:text-white"
             }`}
           >
             Active
           </button>
           <button 
             onClick={() => setActiveTab("resolved")}
             className={`px-4 py-2 text-[10px] font-bold uppercase tracking-widest rounded-sm transition-all border ${
               activeTab === "resolved" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : "text-text-muted border-white/5 hover:text-white"
             }`}
           >
             Resolved
           </button>
        </div>
      </div>

      <div className="space-y-4">
        {alerts
          .filter(a => a.status === activeTab)
          .map((alert) => (
          <div key={alert.id} className="bg-surface rounded-base border border-white/5 p-6 hover:border-white/10 transition-all flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="flex items-start space-x-4">
              <div className={`mt-1 w-2 h-2 rounded-full shrink-0 ${alert.severity === 'critical' ? 'bg-status-error animate-pulse' : 'bg-yellow-500'}`}></div>
              <div className="space-y-1">
                <div className="flex items-center space-x-3">
                  <h3 className="text-sm font-bold text-text-strong uppercase tracking-wider">{alert.issue}</h3>
                  <span className="px-1.5 py-0.5 rounded-sm bg-white/5 text-[10px] font-bold text-text-muted border border-white/5 uppercase tracking-tighter">{alert.target}</span>
                </div>
                <p className="text-xs text-text-muted">Detected across {alert.target} primary gateway. Performance degraded below 40% threshold.</p>
              </div>
            </div>
            
            <div className="flex flex-row md:flex-col items-center md:items-end justify-between md:justify-center gap-4 border-t md:border-t-0 border-white/5 pt-4 md:pt-0">
               <div className="flex flex-col md:items-end">
                 <span className="text-[10px] text-text-muted uppercase font-bold tracking-widest">Duration</span>
                 <span className="text-xs font-mono text-text-strong">{alert.duration}</span>
               </div>
               <div className="flex space-x-2">
                 {activeTab === 'active' ? (
                   <>
                     <button className="px-3 py-1.5 bg-white/5 text-text-muted hover:text-white transition-colors text-[10px] font-bold uppercase rounded-sm border border-white/10">Ignore</button>
                     <button className="px-3 py-1.5 bg-status-error text-white hover:bg-status-error/90 transition-colors text-[10px] font-bold uppercase rounded-sm shadow-lg shadow-status-error/10">Acknowledge</button>
                   </>
                 ) : (
                   <button className="px-3 py-1.5 bg-white/5 text-text-muted hover:text-white transition-colors text-[10px] font-bold uppercase rounded-sm border border-white/10">View Report</button>
                 )}
               </div>
            </div>
          </div>
        ))}

        {alerts.filter(a => a.status === activeTab).length === 0 && (
          <div className="py-20 text-center bg-surface rounded-base border border-dashed border-white/10">
             <p className="text-xs text-text-muted uppercase font-bold tracking-[0.2em]">No {activeTab} alerts at this time</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default AlertsPage;
