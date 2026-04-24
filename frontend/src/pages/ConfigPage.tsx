import React, { useState } from "react";

const ConfigPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState("general");

  const Section = ({ title, description, children }: any) => (
    <div className="bg-surface rounded-base border border-white/5 overflow-hidden">
      <div className="px-6 py-4 border-b border-white/5">
        <h3 className="text-sm font-bold text-text-strong uppercase tracking-wider">{title}</h3>
        <p className="text-xs text-text-muted mt-1">{description}</p>
      </div>
      <div className="p-6 space-y-6">
        {children}
      </div>
    </div>
  );

  const InputField = ({ label, type = "text", placeholder, value }: any) => (
    <div className="space-y-2">
      <label className="text-[10px] font-bold text-text-muted uppercase tracking-widest">{label}</label>
      <input 
        type={type} 
        defaultValue={value}
        placeholder={placeholder}
        className="w-full bg-canvas border border-white/10 rounded-sm px-4 py-2 text-xs text-text-strong focus:outline-none focus:border-brand-primary transition-colors"
      />
    </div>
  );

  const Toggle = ({ label, description, defaultChecked }: any) => (
    <div className="flex items-center justify-between p-4 bg-white/5 rounded-sm border border-white/5">
      <div>
        <h4 className="text-xs font-bold text-text-strong">{label}</h4>
        <p className="text-[10px] text-text-muted mt-0.5">{description}</p>
      </div>
      <label className="relative inline-flex items-center cursor-pointer">
        <input type="checkbox" className="sr-only peer" defaultChecked={defaultChecked} />
        <div className="w-9 h-5 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-text-muted peer-checked:after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-brand-primary"></div>
      </label>
    </div>
  );

  return (
    <div className="max-w-4xl space-y-8">
      <div className="flex items-center space-x-8 border-b border-white/5 pb-1">
        {["general", "interfaces", "routing", "monitoring"].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`pb-4 text-[10px] font-bold uppercase tracking-[0.2em] transition-all relative ${
              activeTab === tab ? "text-white" : "text-text-muted hover:text-white"
            }`}
          >
            {tab}
            {activeTab === tab && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand-primary"></div>
            )}
          </button>
        ))}
      </div>

      <div className="space-y-6">
        {activeTab === "general" && (
          <>
            <Section title="System Information" description="Basic identity and localization settings for this node.">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <InputField label="Hostname" value="wancontrol-primary" />
                <InputField label="Admin Email" placeholder="admin@example.com" />
                <InputField label="Timezone" value="UTC (Greenwich Mean Time)" />
                <InputField label="SSH Port" value="22" />
              </div>
            </Section>
            
            <Section title="Security & Access" description="Control how the system is accessed and secured.">
              <div className="space-y-4">
                <Toggle label="Enable Two-Factor Authentication" description="Require a TOTP code for all administrator logins." defaultChecked={true} />
                <Toggle label="Restrict SSH Access" description="Only allow SSH connections from the local network." defaultChecked={false} />
                <Toggle label="Automatic Updates" description="Check for and apply security patches automatically at 03:00." defaultChecked={true} />
              </div>
            </Section>
          </>
        )}

        {activeTab === "interfaces" && (
          <Section title="Interface Configuration" description="Configure physical and virtual network interfaces.">
             <div className="space-y-6">
               <div className="p-4 bg-white/5 rounded-sm border border-white/5 flex items-center justify-between">
                  <div className="flex items-center space-x-4">
                    <div className="w-10 h-10 rounded-sm bg-brand-primary/20 flex items-center justify-center text-brand-primary font-bold">W1</div>
                    <div>
                      <h4 className="text-xs font-bold text-text-strong">WAN 1 (eth0)</h4>
                      <p className="text-[10px] text-text-muted mt-0.5">Primary Fiber Connection - 1Gbps</p>
                    </div>
                  </div>
                  <button className="text-[10px] font-bold text-brand-primary uppercase tracking-widest border border-brand-primary/20 px-3 py-1.5 rounded-sm hover:bg-brand-primary/10 transition-all">Configure</button>
               </div>
               <div className="p-4 bg-white/5 rounded-sm border border-white/5 flex items-center justify-between opacity-60 hover:opacity-100 transition-all">
                  <div className="flex items-center space-x-4">
                    <div className="w-10 h-10 rounded-sm bg-purple-500/20 flex items-center justify-center text-purple-400 font-bold">W2</div>
                    <div>
                      <h4 className="text-xs font-bold text-text-strong">WAN 2 (eth1)</h4>
                      <p className="text-[10px] text-text-muted mt-0.5">Secondary LTE Backup - 100Mbps</p>
                    </div>
                  </div>
                  <button className="text-[10px] font-bold text-text-muted uppercase tracking-widest border border-white/10 px-3 py-1.5 rounded-sm hover:text-white transition-all">Configure</button>
               </div>
             </div>
          </Section>
        )}

        {/* Other tabs can be implemented similarly */}
        {(activeTab === "routing" || activeTab === "monitoring") && (
           <div className="flex flex-col items-center justify-center py-20 text-center space-y-4">
              <div className="w-12 h-12 bg-white/5 rounded-full flex items-center justify-center text-text-muted">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" /></svg>
              </div>
              <div>
                <h3 className="text-sm font-bold text-text-strong uppercase tracking-widest">Under Construction</h3>
                <p className="text-xs text-text-muted mt-2">The {activeTab} module is currently being migrated to v2.</p>
              </div>
           </div>
        )}
      </div>

      <div className="pt-8 border-t border-white/5 flex justify-end space-x-4">
         <button className="px-6 py-2.5 text-[10px] font-bold text-text-muted uppercase tracking-[0.2em] hover:text-white transition-colors">Discard Changes</button>
         <button className="px-8 py-2.5 bg-brand-primary text-white text-[10px] font-bold uppercase tracking-[0.2em] rounded-sm hover:shadow-lg hover:shadow-brand-primary/10 transition-all">Apply Configuration</button>
      </div>
    </div>
  );
};

export default ConfigPage;
