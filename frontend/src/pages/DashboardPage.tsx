import React, { useEffect, useState } from "react";
import { sseManager } from "../api/sse";
import { useAlertCount } from "../context/AlertCountContext";
import { useAuth } from "../auth/AuthContext";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
} from "recharts";

import { getStatus, getMetrics } from "../api/client";

const DashboardPage: React.FC = () => {
  const [status, setStatus] = useState<any>(null);
  const [metrics, setMetrics] = useState<Record<string, any>>({});
  const [historicalMetrics, setHistoricalMetrics] = useState<any[]>([]);
  const alertCtx = useAlertCount();
  const auth = useAuth();

  useEffect(() => {
    if (!auth.token) return;

    // Fetch initial data
    getStatus().then(setStatus).catch(console.error);
    getMetrics({ limit: 50 }).then(setHistoricalMetrics).catch(console.error);

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
  }, [auth.token, alertCtx]);

  // Map real data for charts, fallback to mock if empty
  const performanceData = historicalMetrics.length > 0 
    ? historicalMetrics.map(m => ({
        time: new Date(m.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        latency: m.latency_ms,
        jitter: m.jitter_ms
      })).reverse()
    : [
    { time: "00:00", latency: 25, jitter: 2 },
    { time: "04:00", latency: 28, jitter: 3 },
    { time: "08:00", latency: 45, jitter: 12 },
    { time: "12:00", latency: 30, jitter: 4 },
    { time: "16:00", latency: 35, jitter: 6 },
    { time: "20:00", latency: 22, jitter: 2 },
  ];

  const trafficData = [
    { name: "HTTP/S", value: 450, color: "#ffffff" },
    { name: "Streaming", value: 300, color: "#b7c8e1" },
    { name: "VPN", value: 150, color: "#f87171" },
    { name: "Other", value: 100, color: "#444749" },
  ];

  const MetricCard = ({ title, value, unit, trend, colorClass }: any) => (
    <div className="bg-surface-container-low p-6 rounded-xl border border-outline-variant/20 hover:border-primary/30 transition-all duration-300 group shadow-sm hover:shadow-primary/5">
      <div className="flex justify-between items-start mb-6">
        <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-text-muted group-hover:text-primary transition-colors">{title}</h3>
        <div className={`p-2 rounded-lg bg-surface-bright/50 border border-outline-variant/30 text-text-strong group-hover:border-primary/50 transition-all`}>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>
        </div>
      </div>
      <div className="flex items-baseline space-x-2">
        <span className="text-3xl font-black text-text-strong tracking-tighter tabular-nums">{value}</span>
        <span className="text-xs font-bold text-text-muted uppercase">{unit}</span>
      </div>
      <div className="mt-6 pt-4 border-t border-outline-variant/10 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <span className={`text-[10px] font-black px-1.5 py-0.5 rounded ${trend.startsWith('-') ? 'bg-success-green/10 text-success-green' : 'bg-error-red/10 text-error-red'}`}>
            {trend}
          </span>
          <span className="text-[9px] text-text-muted font-bold uppercase tracking-tight">vs last hour</span>
        </div>
        <div className="w-12 h-6 opacity-30 group-hover:opacity-100 transition-opacity">
           {/* Mini Sparkline placeholder */}
           <svg viewBox="0 0 48 24" className="w-full h-full"><path d="M0 20 L8 15 L16 18 L24 10 L32 12 L40 5 L48 8" fill="none" stroke="currentColor" strokeWidth="2" className={trend.startsWith('-') ? 'text-success-green' : 'text-error-red'} /></svg>
        </div>
      </div>
    </div>
  );

  return (
    <div className="space-y-8 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
      {/* Welcome Section */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-text-strong tracking-tight">Network Overview</h1>
          <p className="text-text-muted text-sm mt-1 font-medium">Real-time health monitoring for <span className="text-primary">wan-cluster-alpha</span></p>
        </div>
        <div className="flex items-center space-x-3 text-[10px] font-black uppercase tracking-widest text-text-muted bg-surface-container-low px-4 py-2 rounded-full border border-outline-variant/20">
           <span className="flex h-2 w-2 rounded-full bg-success-green"></span>
           <span>Last synced: {new Date().toLocaleTimeString()}</span>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard title="System Latency" value={metrics.latency || "24.5"} unit="ms" trend="-2.4%" />
        <MetricCard title="Jitter Variance" value={metrics.jitter || "3.2"} unit="ms" trend="+0.5%" />
        <MetricCard title="Packet Integrity" value={metrics.packet_loss ? (100 - metrics.packet_loss).toFixed(2) : "99.98"} unit="%" trend="+0.01%" />
        <MetricCard title="Peak Throughput" value={metrics.throughput || "842"} unit="Mbps" trend="+12.3%" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Performance Chart */}
        <div className="lg:col-span-2 bg-surface-container-low p-8 rounded-2xl border border-outline-variant/20 shadow-sm relative overflow-hidden group">
          <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity pointer-events-none">
             <svg className="w-32 h-32" fill="currentColor" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14.5v-9l6 4.5-6 4.5z"/></svg>
          </div>
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-10 gap-4">
            <div>
              <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Network Performance Matrix</h3>
              <p className="text-[11px] text-text-muted mt-1 font-bold">Deep packet inspection & jitter correlation</p>
            </div>
            <div className="flex items-center bg-canvas/50 p-1.5 rounded-lg border border-outline-variant/20">
               <button className="px-3 py-1 text-[9px] font-black uppercase tracking-widest text-text-strong bg-surface-bright rounded-md shadow-sm">Real-time</button>
               <button className="px-3 py-1 text-[9px] font-black uppercase tracking-widest text-text-muted hover:text-text-strong transition-colors">Historical</button>
            </div>
          </div>
          <div className="h-[320px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={performanceData}>
                <defs>
                  <linearGradient id="colorLat" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ffffff" stopOpacity={0.15}/>
                    <stop offset="95%" stopColor="#ffffff" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.2} />
                <XAxis 
                  dataKey="time" 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{fill: '#94a3b8', fontSize: 10, fontWeight: 700}} 
                  dy={10}
                />
                <YAxis 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{fill: '#94a3b8', fontSize: 10, fontWeight: 700}} 
                />
                <Tooltip 
                  contentStyle={{backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px', fontSize: '11px', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)'}}
                  itemStyle={{color: '#f8fafc', fontWeight: 700}}
                />
                <Area type="monotone" dataKey="latency" stroke="#ffffff" strokeWidth={3} fillOpacity={1} fill="url(#colorLat)" />
                <Line type="monotone" dataKey="jitter" stroke="#38bdf8" strokeWidth={2} dot={{r: 4, fill: '#38bdf8', strokeWidth: 2, stroke: '#0f172a'}} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Traffic Distribution */}
        <div className="bg-surface-container-low p-8 rounded-2xl border border-outline-variant/20 shadow-sm flex flex-col">
          <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em] mb-10">Application Load</h3>
          <div className="flex-1 flex items-center justify-center relative">
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={trafficData}
                  cx="50%"
                  cy="50%"
                  innerRadius={75}
                  outerRadius={100}
                  paddingAngle={8}
                  dataKey="value"
                  stroke="none"
                >
                  {trafficData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-4xl font-black text-text-strong tracking-tighter">1.2</span>
              <span className="text-[10px] text-text-muted uppercase font-black tracking-widest">Gbps Total</span>
            </div>
          </div>
          <div className="mt-10 grid grid-cols-2 gap-4">
            {trafficData.map((item) => (
              <div key={item.name} className="p-3 rounded-xl bg-canvas/40 border border-outline-variant/10 flex flex-col gap-1">
                <div className="flex items-center space-x-2">
                  <div className="w-2 h-2 rounded-full" style={{backgroundColor: item.color}}></div>
                  <span className="text-[10px] font-black uppercase tracking-tight text-text-muted">{item.name}</span>
                </div>
                <span className="text-sm font-black text-text-strong">{Math.round((item.value / 1000) * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Connection Table */}
      <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 shadow-sm overflow-hidden">
        <div className="px-8 py-6 border-b border-outline-variant/20 flex items-center justify-between bg-surface-bright/5">
          <div>
            <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Live Traffic Analysis</h3>
            <p className="text-[10px] text-text-muted mt-1 font-bold">Active interface peering & bandwidth allocation</p>
          </div>
          <button className="px-4 py-2 bg-surface-bright/50 border border-outline-variant/30 text-[10px] font-black text-text-strong hover:bg-primary hover:text-primary-on transition-all rounded-lg uppercase tracking-widest">View All Nodes</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-canvas/40">
                <th className="px-8 py-4 text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">Source Node</th>
                <th className="px-8 py-4 text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">Interface</th>
                <th className="px-8 py-4 text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">State</th>
                <th className="px-8 py-4 text-[10px] font-black text-text-muted uppercase tracking-[0.2em] text-right">Throughput</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/10">
              {[
                { ip: "192.168.1.105", iface: "WAN1", status: "Active", speed: "12.4 Mbps", load: "High" },
                { ip: "192.168.1.12", iface: "WAN1", status: "Active", speed: "4.8 Mbps", load: "Med" },
                { ip: "10.0.0.45", iface: "WAN2", status: "Active", speed: "256 Kbps", load: "Low" },
                { ip: "192.168.1.201", iface: "WAN1", status: "Idle", speed: "0 Mbps", load: "None" },
              ].map((conn, idx) => (
                <tr key={idx} className="hover:bg-primary/[0.02] transition-colors group">
                  <td className="px-8 py-5">
                    <div className="flex items-center space-x-3">
                       <div className="w-8 h-8 rounded-lg bg-surface-bright flex items-center justify-center font-mono text-[10px] font-bold text-text-muted border border-outline-variant/20 group-hover:border-primary/30 transition-colors">IP</div>
                       <span className="text-xs font-black font-mono text-text-strong">{conn.ip}</span>
                    </div>
                  </td>
                  <td className="px-8 py-5">
                    <span className="px-2.5 py-1 rounded-md bg-surface-bright/50 border border-outline-variant/30 text-text-strong text-[9px] font-black uppercase tracking-widest">{conn.iface}</span>
                  </td>
                  <td className="px-8 py-5">
                    <div className="flex items-center space-x-2">
                       <div className={`w-2 h-2 rounded-full ${conn.status === 'Active' ? 'bg-success-green shadow-[0_0_8px_rgba(74,222,128,0.4)]' : 'bg-outline-variant'}`}></div>
                       <span className="text-[10px] font-black uppercase tracking-wider text-text-muted">{conn.status}</span>
                    </div>
                  </td>
                  <td className="px-8 py-5 text-right">
                    <div className="flex flex-col items-end">
                      <span className="text-xs font-black text-text-strong tracking-tight tabular-nums">{conn.speed}</span>
                      <div className="w-16 h-1 bg-outline-variant/20 rounded-full mt-1.5 overflow-hidden">
                         <div className={`h-full rounded-full ${conn.load === 'High' ? 'bg-error-red w-3/4' : conn.load === 'Med' ? 'bg-warning-amber w-1/2' : 'bg-success-green w-1/4'}`}></div>
                      </div>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default DashboardPage;
