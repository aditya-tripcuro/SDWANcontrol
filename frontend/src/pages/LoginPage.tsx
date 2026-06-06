import React, { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const LoginPage: React.FC = () => {
  const auth = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  
  const successMessage = location.state?.message;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await auth.login(username, password);
      nav("/", { replace: true });
    } catch (err) {
      setError("Invalid credentials. Please verify your access tokens.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex flex-col items-center justify-center p-8 text-text-strong font-sans relative overflow-hidden">
      {/* Background decoration */}
      <div className="absolute top-0 left-0 w-full h-full opacity-5 pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary rounded-full blur-[128px]"></div>
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-secondary rounded-full blur-[128px]"></div>
      </div>

      <div className="w-full max-w-md space-y-12 relative z-10">
        <div className="text-center space-y-6">
          <div className="inline-flex items-center justify-center w-20 h-20 bg-primary text-primary-on rounded-2xl shadow-2xl shadow-white/5 mb-2 group hover:scale-105 transition-transform duration-500">
            <span className="text-3xl font-black tracking-tighter">WC</span>
          </div>
          <div className="space-y-2">
            <h1 className="text-3xl font-black tracking-tight uppercase text-text-strong">Terminal Access</h1>
            <p className="text-[10px] text-text-muted font-black uppercase tracking-[0.3em]">WANControl v2.0 Enterprise</p>
          </div>
        </div>

        <form onSubmit={submit} className="bg-surface-container-low p-10 rounded-3xl border border-outline-variant/20 shadow-2xl space-y-8 backdrop-blur-md">
          {successMessage && (
            <div className="bg-success-green/10 border border-success-green/20 p-4 rounded-xl flex items-start space-x-3 animate-in fade-in zoom-in duration-300">
              <svg className="w-4 h-4 text-success-green mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
              <span className="text-[11px] font-bold text-success-green">{successMessage}</span>
            </div>
          )}

          {error && (
            <div className="bg-error-red/10 border border-error-red/20 p-4 rounded-xl flex items-start space-x-3 animate-in fade-in zoom-in duration-300">
              <svg className="w-4 h-4 text-error-red mt-0.5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              <span className="text-[11px] font-bold text-error-red">{error}</span>
            </div>
          )}

          <div className="space-y-6">
            <div className="space-y-2.5 group">
              <label htmlFor="username" className="text-[10px] font-black text-text-muted group-focus-within:text-primary uppercase tracking-[0.2em] transition-colors">Username</label>
              <div className="relative">
                <input 
                  id="username"
                  value={username} 
                  onChange={(e)=>setUsername(e.target.value)} 
                  className="w-full bg-canvas/50 border border-outline-variant/30 rounded-xl px-5 py-4 text-sm text-text-strong focus:outline-none focus:border-primary/50 focus:ring-4 focus:ring-primary/5 transition-all placeholder:text-text-muted/30"
                  placeholder="admin_id_01"
                />
              </div>
            </div>
            <div className="space-y-2.5 group">
              <label htmlFor="password" className="text-[10px] font-black text-text-muted group-focus-within:text-primary uppercase tracking-[0.2em] transition-colors">Password</label>
              <div className="relative">
                <input 
                  id="password"
                  type="password" 
                  value={password} 
                  onChange={(e)=>setPassword(e.target.value)} 
                  className="w-full bg-canvas/50 border border-outline-variant/30 rounded-xl px-5 py-4 text-sm text-text-strong focus:outline-none focus:border-primary/50 focus:ring-4 focus:ring-primary/5 transition-all placeholder:text-text-muted/30"
                  placeholder="••••••••••••"
                />
              </div>
            </div>
          </div>

          <button 
            disabled={loading}
            className={`w-full bg-primary text-primary-on py-4 rounded-xl text-[11px] font-black uppercase tracking-[0.3em] hover:scale-[1.02] active:scale-[0.98] transition-all shadow-xl shadow-white/5 relative overflow-hidden group ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            <div className="absolute inset-0 bg-white/10 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000"></div>
            <span className="relative z-10">{loading ? "Synchronizing..." : "Sign in"}</span>
          </button>
        </form>

        <div className="text-center space-y-4">
           <p className="text-[10px] text-text-muted uppercase tracking-[0.2em] font-bold">Secure encryption active (AES-256)</p>
           <div className="h-px w-12 bg-outline-variant/30 mx-auto"></div>
           <p className="text-[9px] text-text-muted/50 uppercase tracking-tighter">© 2026 WANCONTROL INDUSTRIAL SYSTEMS</p>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
