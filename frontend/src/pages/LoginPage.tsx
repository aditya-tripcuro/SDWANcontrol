import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const LoginPage: React.FC = () => {
  const auth = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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
    <div className="min-h-screen bg-canvas flex flex-col items-center justify-center p-6 text-text-strong font-sans">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center space-y-4">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-brand-primary rounded-base shadow-2xl shadow-brand-primary/20 mb-4">
            <span className="text-2xl font-bold">WC</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight uppercase">WANControl v2</h1>
          <p className="text-sm text-text-muted">Network Operations Management System</p>
        </div>

        <form onSubmit={submit} className="bg-surface p-8 rounded-base border border-white/5 shadow-2xl space-y-6">
          {error && (
            <div className="bg-status-error/10 border border-status-error/20 p-4 rounded-sm flex items-start space-x-3">
              <svg className="w-4 h-4 text-status-error mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              <span className="text-xs font-medium text-status-error">{error}</span>
            </div>
          )}

          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-text-muted uppercase tracking-widest">Username / Identifier</label>
              <input 
                value={username} 
                onChange={(e)=>setUsername(e.target.value)} 
                className="w-full bg-canvas border border-white/10 rounded-sm px-4 py-3 text-xs text-text-strong focus:outline-none focus:border-brand-primary transition-colors"
                placeholder="system-admin"
              />
            </div>
            <div className="space-y-2">
              <label className="text-[10px] font-bold text-text-muted uppercase tracking-widest">Access Key / Password</label>
              <input 
                type="password" 
                value={password} 
                onChange={(e)=>setPassword(e.target.value)} 
                className="w-full bg-canvas border border-white/10 rounded-sm px-4 py-3 text-xs text-text-strong focus:outline-none focus:border-brand-primary transition-colors"
                placeholder="••••••••"
              />
            </div>
          </div>

          <button 
            disabled={loading}
            className={`w-full bg-brand-primary py-3 rounded-sm text-[10px] font-bold uppercase tracking-[0.2em] hover:shadow-lg hover:shadow-brand-primary/10 transition-all ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {loading ? "Authenticating..." : "Establish Session"}
          </button>
        </form>

        <div className="text-center">
           <p className="text-[10px] text-text-muted uppercase tracking-widest">Authorized Personnel Only</p>
        </div>
      </div>
    </div>
  );
};

export default LoginPage;
