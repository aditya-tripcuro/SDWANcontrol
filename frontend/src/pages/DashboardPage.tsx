import React, { useEffect, useState } from "react";
import { sseManager } from "../api/sse";
import { useAlertCount } from "../context/AlertCountContext";
import { useAuth } from "../auth/AuthContext";

const DashboardPage: React.FC = () => {
  const [status, setStatus] = useState<any>(null);
  const [metrics, setMetrics] = useState<Record<string, any>>({});
  const alertCtx = useAlertCount();
  const auth = useAuth();

  useEffect(() => {
    if (!auth.token) return;
    const onStatus = (d: unknown) => setStatus(d as any);
    const onMetric = (d: unknown) => setMetrics(d as any);
    const onAlert = (d: unknown) => { alertCtx.increment(); };
    sseManager.on("status", onStatus);
    sseManager.on("metric", onMetric);
    sseManager.on("alert", onAlert);
    return () => {
      sseManager.off("status", onStatus);
      sseManager.off("metric", onMetric);
      sseManager.off("alert", onAlert);
    };
  }, [auth.token]);

  return (
    <div className="p-6">
      <h2 className="text-xl font-bold mb-4">Dashboard</h2>
      <pre className="bg-slate-800 p-4 rounded max-h-96 overflow-auto">{JSON.stringify({status, metrics}, null, 2)}</pre>
    </div>
  );
};

export default DashboardPage;
