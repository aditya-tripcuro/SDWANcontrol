import React from "react";

const UsersPage: React.FC = () => {
  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-text-strong tracking-tight">Users</h1>
          <p className="text-text-muted text-sm mt-1 font-medium">Manage node administrators and terminal access tokens</p>
        </div>
        <button className="px-6 py-3 bg-primary text-primary-on rounded-xl text-[10px] font-black uppercase tracking-[0.2em] hover:scale-105 transition-all shadow-xl shadow-white/5">Provision Admin</button>
      </div>

      <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 p-12 flex flex-col items-center justify-center text-center space-y-8 border-dashed">
         <div className="w-20 h-20 bg-surface-bright rounded-3xl flex items-center justify-center border border-outline-variant/20">
            <svg className="w-10 h-10 text-text-muted opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" /></svg>
         </div>
         <div className="space-y-3">
           <h3 className="text-sm font-black text-text-strong uppercase tracking-[0.3em]">Access Management Restricted</h3>
           <p className="text-xs text-text-muted font-medium max-w-sm mx-auto leading-relaxed">Identity controls are currently managed via the <code className="text-primary font-mono">/etc/wancontrol/users.db</code> manifest for security enforcement.</p>
         </div>
         <div className="grid grid-cols-1 md:grid-cols-2 gap-4 w-full max-w-lg">
            <div className="p-4 bg-canvas/30 rounded-xl border border-outline-variant/10 text-left">
               <span className="text-[9px] font-black text-text-muted uppercase tracking-widest block mb-1">Active Admins</span>
               <span className="text-xl font-black text-text-strong tabular-nums">04</span>
            </div>
            <div className="p-4 bg-canvas/30 rounded-xl border border-outline-variant/10 text-left">
               <span className="text-[9px] font-black text-text-muted uppercase tracking-widest block mb-1">Session Tokens</span>
               <span className="text-xl font-black text-text-strong tabular-nums">12</span>
            </div>
         </div>
      </div>
    </div>
  );
};

export default UsersPage;
