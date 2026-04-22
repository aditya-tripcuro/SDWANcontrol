import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const LoginPage: React.FC = () => {
  const auth = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await auth.login(username, password);
      nav("/", { replace: true });
    } catch (err) {
      setError("Invalid username or password");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center">
      <form onSubmit={submit} className="bg-slate-900 p-8 rounded-md w-full max-w-md">
        <h1 className="text-2xl font-bold mb-4">WANControl v2.0.0-dev</h1>
        {error && <div className="text-red-400 mb-2">{error}</div>}
        <label className="block mb-2">Username<input value={username} onChange={(e)=>setUsername(e.target.value)} className="w-full p-2 bg-slate-800 rounded mt-1"/></label>
        <label className="block mb-4">Password<input type="password" value={password} onChange={(e)=>setPassword(e.target.value)} className="w-full p-2 bg-slate-800 rounded mt-1"/></label>
        <button className="w-full bg-slate-700 py-2 rounded">Sign in</button>
      </form>
    </div>
  );
};

export default LoginPage;
