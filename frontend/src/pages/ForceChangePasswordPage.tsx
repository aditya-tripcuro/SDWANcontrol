import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { changePassword } from "../api/client";

const ForceChangePasswordPage: React.FC = () => {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const auth = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match");
      return;
    }
    if (newPassword.length < 12) {
      setError("Password must be at least 12 characters long");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      await changePassword(oldPassword, newPassword);
      // Re-login or refresh token to clear the flag
      // For now, we just logout and let them log in with new password
      // Or we could have the backend return a new token in changePassword
      auth.logout();
      navigate("/login", { state: { message: "Password changed successfully. Please log in again." } });
    } catch (err: any) {
      setError(err.message || "Failed to change password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-canvas flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-md animate-in fade-in zoom-in duration-500">
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 border border-primary/20 mb-6 shadow-2xl shadow-primary/10">
            <svg className="w-8 h-8 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <h1 className="text-3xl font-black text-text-strong tracking-tighter uppercase italic">Security Update</h1>
          <p className="text-text-muted mt-2 font-bold text-sm tracking-wide uppercase">First-run password reset required</p>
        </div>

        <div className="bg-surface-container p-8 rounded-3xl border border-outline-variant/30 shadow-2xl backdrop-blur-xl relative overflow-hidden">
          <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-transparent via-primary/50 to-transparent"></div>
          
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-[10px] font-black text-text-muted uppercase tracking-[0.2em] mb-2 px-1">Initial Password</label>
              <input
                type="password"
                required
                className="w-full bg-surface-container-lowest border border-outline-variant/40 rounded-xl px-4 py-3.5 text-text-strong focus:outline-none focus:border-primary/50 focus:ring-4 focus:ring-primary/5 transition-all font-mono"
                placeholder="••••••••••••"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
              />
            </div>

            <div className="pt-2 border-t border-outline-variant/10">
              <label className="block text-[10px] font-black text-text-muted uppercase tracking-[0.2em] mb-2 px-1">New Secure Password</label>
              <input
                type="password"
                required
                className="w-full bg-surface-container-lowest border border-outline-variant/40 rounded-xl px-4 py-3.5 text-text-strong focus:outline-none focus:border-primary/50 focus:ring-4 focus:ring-primary/5 transition-all font-mono"
                placeholder="Min. 12 characters"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </div>

            <div>
              <label className="block text-[10px] font-black text-text-muted uppercase tracking-[0.2em] mb-2 px-1">Confirm New Password</label>
              <input
                type="password"
                required
                className="w-full bg-surface-container-lowest border border-outline-variant/40 rounded-xl px-4 py-3.5 text-text-strong focus:outline-none focus:border-primary/50 focus:ring-4 focus:ring-primary/5 transition-all font-mono"
                placeholder="••••••••••••"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>

            {error && (
              <div className="bg-error-red/10 border border-error-red/20 text-error-red text-[11px] font-black px-4 py-3 rounded-xl flex items-center space-x-2 animate-in fade-in slide-in-from-top-1">
                <svg className="w-4 h-4 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary text-primary-on font-black py-4 rounded-xl hover:scale-[1.02] active:scale-[0.98] transition-all shadow-xl shadow-primary/20 disabled:opacity-50 disabled:scale-100 flex items-center justify-center space-x-2 uppercase tracking-widest text-xs"
            >
              {loading ? (
                <svg className="animate-spin h-5 w-5 text-current" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
              ) : (
                <span>Initialize Identity</span>
              )}
            </button>
          </form>
        </div>
        
        <p className="text-center mt-8 text-[10px] font-black text-text-muted uppercase tracking-[0.3em]">
          WANControl v2 &bull; Industrial Precision
        </p>
      </div>
    </div>
  );
};

export default ForceChangePasswordPage;
