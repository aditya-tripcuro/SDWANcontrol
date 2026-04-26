import React, { useState } from "react";

const ConfigPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState("general");

  const Section = ({ title, description, children }: any) => (
    <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 overflow-hidden shadow-sm">
      <div className="px-8 py-5 border-b border-outline-variant/20 bg-surface-bright/5">
        <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">{title}</h3>
        <p className="text-[10px] text-text-muted mt-1 font-bold">{description}</p>
      </div>
      <div className="p-8 space-y-8">
        {children}
      </div>
    </div>
  );

  const InputField = ({ label, type = "text", placeholder, value }: any) => (
    <div className="space-y-2.5 group">
      <label className="text-[10px] font-black text-text-muted group-focus-within:text-primary uppercase tracking-[0.2em] transition-colors">{label}</label>
      <input 
        type={type} 
        defaultValue={value}
        placeholder={placeholder}
        className="w-full bg-canvas/40 border border-outline-variant/20 rounded-xl px-5 py-3 text-xs text-text-strong focus:outline-none focus:border-primary/40 focus:ring-4 focus:ring-primary/5 transition-all font-medium"
      />
    </div>
  );

  const Toggle = ({ label, description, defaultChecked }: any) => (
    <div className="flex items-center justify-between p-5 bg-canvas/30 rounded-2xl border border-outline-variant/10 group hover:border-outline-variant/30 transition-all">
      <div>
        <h4 className="text-xs font-black text-text-strong uppercase tracking-tight">{label}</h4>
        <p className="text-[10px] text-text-muted mt-1 font-medium">{description}</p>
      </div>
      <label className="relative inline-flex items-center cursor-pointer">
        <input type="checkbox" className="sr-only peer" defaultChecked={defaultChecked} />
        <div className="w-11 h-6 bg-surface-bright/50 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-text-muted peer-checked:after:bg-primary-on after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary"></div>
      </label>
    </div>
  );

  return (
    <div className="max-w-5xl space-y-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 border-b border-outline-variant/10">
        <div className="flex items-center space-x-10">
          {["general", "interfaces", "routing", "monitoring"].map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`pb-5 text-[10px] font-black uppercase tracking-[0.2em] transition-all relative ${
                activeTab === tab ? "text-text-strong" : "text-text-muted hover:text-text-strong"
              }`}
            >
              {tab}
              {activeTab === tab && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary shadow-[0_-4px_8px_rgba(255,255,255,0.2)]"></div>
              )}
            </button>
          ))}
        </div>
        <div className="pb-4">
           <span className="text-[9px] font-black text-text-muted uppercase tracking-widest bg-surface-bright/50 px-3 py-1 rounded-full border border-outline-variant/20">Config v1.0.4-stable</span>
        </div>
      </div>

      <div className="space-y-8">
        {activeTab === "general" && (
          <div className="grid grid-cols-1 gap-8 animate-in fade-in slide-in-from-left-4 duration-500">
            <Section title="System Node Parameters" description="Core identity and regional configuration for this controller.">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <InputField label="Nodename / Host" value="wancontrol-alpha-01" />
                <InputField label="Administrative Uplink" placeholder="ops@wancontrol.net" />
                <InputField label="Temporal Zone" value="UTC (Greenwich Mean Time)" />
                <InputField label="Access Port" value="5000" />
              </div>
            </Section>
            
            <Section title="Operational Protocols" description="Security enforcement and automated maintenance policies.">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Toggle label="Multi-Factor Auth" description="Enforce TOTP handshake for all administrative sessions." defaultChecked={true} />
                <Toggle label="Hardened SSH" description="Restrict remote terminal access to encrypted local tunnels." defaultChecked={false} />
                <Toggle label="Automated Patching" description="Synchronize and apply security updates during low-traffic windows." defaultChecked={true} />
                <Toggle label="Verbose Telemetry" description="Record high-density probe data for deeper forensic analysis." defaultChecked={false} />
              </div>
            </Section>
          </div>
        )}

        {activeTab === "interfaces" && (
          <div className="animate-in fade-in slide-in-from-right-4 duration-500">
            <Section title="Interface Management" description="Physical port mapping and software-defined link parameters.">
               <div className="grid gap-4">
                 {[
                   { name: "Fiber Trunk", id: "eth0", label: "WAN 1", speed: "1000 Mbps", status: "Primary" },
                   { name: "LTE Gateway", id: "eth1", label: "WAN 2", speed: "150 Mbps", status: "Backup" }
                 ].map((iface, idx) => (
                   <div key={idx} className="p-6 bg-canvas/30 rounded-2xl border border-outline-variant/10 flex items-center justify-between group hover:border-primary/20 transition-all">
                      <div className="flex items-center space-x-6">
                        <div className="w-14 h-14 rounded-2xl bg-surface-bright flex items-center justify-center font-black text-sm text-text-strong border border-outline-variant/20 shadow-sm group-hover:bg-primary group-hover:text-primary-on transition-all">{iface.label.split(' ')[1]}</div>
                        <div>
                          <h4 className="text-sm font-black text-text-strong">{iface.name} ({iface.id})</h4>
                          <p className="text-[10px] text-text-muted mt-1 font-bold uppercase tracking-tight">{iface.speed} • {iface.status} Active</p>
                        </div>
                      </div>
                      <button className="text-[10px] font-black text-text-strong uppercase tracking-widest border border-outline-variant/30 px-6 py-3 rounded-xl hover:bg-surface-bright transition-all">Modify Link</button>
                   </div>
                 ))}
                 <button className="w-full py-6 border-2 border-dashed border-outline-variant/20 rounded-2xl text-[10px] font-black text-text-muted uppercase tracking-[0.3em] hover:border-primary/30 hover:text-text-strong transition-all mt-4">+ Provision New Interface</button>
               </div>
            </Section>
          </div>
        )}

        {(activeTab === "routing" || activeTab === "monitoring") && (
           <div className="flex flex-col items-center justify-center py-32 text-center space-y-8 animate-in zoom-in-95 duration-500">
              <div className="w-20 h-20 bg-surface-container-low rounded-3xl border border-outline-variant/20 flex items-center justify-center text-text-muted shadow-lg">
                <svg className="w-10 h-10 opacity-20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" /></svg>
              </div>
              <div className="space-y-3">
                <h3 className="text-sm font-black text-text-strong uppercase tracking-[0.3em]">Module Encrypted</h3>
                <p className="text-xs text-text-muted font-medium max-w-sm mx-auto leading-relaxed">The {activeTab} engine is currently restricted to local terminal configuration during the v2.0 deployment phase.</p>
              </div>
              <button className="px-8 py-3 bg-surface-bright text-text-strong text-[10px] font-black uppercase tracking-widest rounded-xl border border-outline-variant/30 hover:scale-105 transition-transform">Access Docs</button>
           </div>
        )}
      </div>

      <div className="pt-10 border-t border-outline-variant/10 flex items-center justify-between">
         <div className="flex items-center space-x-2">
            <div className="w-2 h-2 rounded-full bg-warning-amber animate-pulse"></div>
            <span className="text-[10px] font-black text-text-muted uppercase tracking-tight">Unsaved changes detected in scratchpad</span>
         </div>
         <div className="flex items-center space-x-6">
            <button className="text-[10px] font-black text-text-muted uppercase tracking-widest hover:text-error-red transition-colors">Abort Changes</button>
            <button className="px-10 py-4 bg-primary text-primary-on text-[11px] font-black uppercase tracking-[0.2em] rounded-xl hover:scale-105 transition-all shadow-xl shadow-white/5">Commit Config</button>
         </div>
      </div>
    </div>
  );
};

export default ConfigPage;
