import React, { useEffect, useState } from "react";
import { sseManager } from "../api/sse";
import { useAuth } from "../auth/AuthContext";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  AreaChart,
  Area,
} from "recharts";

import { getMetrics } from "../api/client";

const MetricsPage: React.FC = () => {
  const [metrics, setMetrics] = useState<any>(null);
  const [historicalMetrics, setHistoricalMetrics] = useState<any[]>([]);
  const auth = useAuth();

  useEffect(() => {
    if (!auth.token) return;
    getMetrics({ limit: 100 }).then(setHistoricalMetrics).catch(console.error);

    const onMetric = (d: unknown) => setMetrics(d as any);
    sseManager.on("metric", onMetric);
    return () => {
      sseManager.off("metric", onMetric);
    };
  }, [auth.token]);

  // Group historical metrics by time for the chart
  const throughputData = historicalMetrics.length > 0
    ? Object.values(historicalMetrics.reduce((acc, m) => {
        const time = new Date(m.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        if (!acc[time]) acc[time] = { time, wan1: 0, wan2: 0 };
        if (m.interface.includes("1") || m.interface.includes("2s0")) acc[time].wan1 = m.score;
        else acc[time].wan2 = m.score;
        return acc;
      }, {} as Record<string, any>)).reverse()
    : [
    { time: "10:00", wan1: 45, wan2: 32 },
    { time: "10:05", wan1: 52, wan2: 28 },
    { time: "10:10", wan1: 48, wan2: 35 },
    { time: "10:15", wan1: 61, wan2: 42 },
    { time: "10:20", wan1: 55, wan2: 38 },
    { time: "10:25", wan1: 65, wan2: 45 },
  ];

  const latencyDistribution = [
    { range: "<10ms", count: 450 },
    { range: "10-20ms", count: 820 },
    { range: "20-50ms", count: 310 },
    { range: "50-100ms", count: 85 },
    { range: ">100ms", count: 12 },
  ];

  return (
    <div className="space-y-8 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div>
          <h1 className="text-2xl font-black text-text-strong tracking-tight">Analytical Metrics</h1>
          <p className="text-text-muted text-sm mt-1 font-medium">Deep telemetry data and interface health diagnostics</p>
        </div>
        <div className="flex items-center space-x-3">
           <div className="flex bg-surface-bright/20 p-1 rounded-lg border border-outline-variant/20">
             <button className="px-4 py-1.5 text-[10px] font-black uppercase tracking-widest text-text-strong bg-surface-bright rounded-md shadow-sm">24h</button>
             <button className="px-4 py-1.5 text-[10px] font-black uppercase tracking-widest text-text-muted hover:text-text-strong transition-colors">7d</button>
             <button className="px-4 py-1.5 text-[10px] font-black uppercase tracking-widest text-text-muted hover:text-text-strong transition-colors">30d</button>
           </div>
           <button className="px-5 py-2 bg-primary text-primary-on rounded-lg text-[10px] font-black uppercase tracking-widest hover:scale-105 transition-transform shadow-lg shadow-white/5">Export Dataset</button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Throughput Area Chart */}
        <div className="bg-surface-container-low p-8 rounded-2xl border border-outline-variant/20 shadow-sm group">
          <div className="flex items-center justify-between mb-10">
            <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Bandwidth Utilization</h3>
            <span className="text-[10px] font-black text-success-green uppercase">Live Feed</span>
          </div>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={throughputData}>
                <defs>
                  <linearGradient id="colorWan1" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ffffff" stopOpacity={0.1}/>
                    <stop offset="95%" stopColor="#ffffff" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorWan2" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.1}/>
                    <stop offset="95%" stopColor="#38bdf8" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.2} />
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{fill: '#94a3b8', fontSize: 10, fontWeight: 700}} />
                <YAxis axisLine={false} tickLine={false} tick={{fill: '#94a3b8', fontSize: 10, fontWeight: 700}} />
                <Tooltip 
                  contentStyle={{backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px', fontSize: '11px'}}
                  itemStyle={{fontWeight: 700}}
                />
                <Legend verticalAlign="top" align="right" height={36} iconType="rect" wrapperStyle={{fontSize: '9px', fontWeight: 900, textTransform: 'uppercase', letterSpacing: '0.1em'}} />
                <Area type="monotone" dataKey="wan1" stroke="#ffffff" fill="url(#colorWan1)" strokeWidth={3} name="Primary Trunk" />
                <Area type="monotone" dataKey="wan2" stroke="#38bdf8" fill="url(#colorWan2)" strokeWidth={2} name="Secondary Path" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Latency Distribution Bar Chart */}
        <div className="bg-surface-container-low p-8 rounded-2xl border border-outline-variant/20 shadow-sm group">
          <div className="flex items-center justify-between mb-10">
            <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Response Time Histogram</h3>
            <span className="text-[10px] font-black text-text-muted uppercase">Sample: 1.6k Packets</span>
          </div>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={latencyDistribution}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.2} />
                <XAxis dataKey="range" axisLine={false} tickLine={false} tick={{fill: '#94a3b8', fontSize: 10, fontWeight: 700}} />
                <YAxis axisLine={false} tickLine={false} tick={{fill: '#94a3b8', fontSize: 10, fontWeight: 700}} />
                <Tooltip 
                  cursor={{fill: 'rgba(255,255,255,0.03)'}}
                  contentStyle={{backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px', fontSize: '11px'}}
                />
                <Bar dataKey="count" fill="#334155" radius={[6, 6, 0, 0]} className="hover:fill-primary transition-colors cursor-pointer" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Interface Health Table */}
      <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 shadow-sm overflow-hidden">
        <div className="px-8 py-6 border-b border-outline-variant/20 bg-surface-bright/5">
          <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Hardware Interface Health Diagnostics</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-canvas/40">
                <th className="px-8 py-4 text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">Interface Identifier</th>
                <th className="px-8 py-4 text-[10px] font-black text-text-muted uppercase tracking-[0.2em] text-center">Availability</th>
                <th className="px-8 py-4 text-[10px] font-black text-text-muted uppercase tracking-[0.2em] text-center">Stability Index</th>
                <th className="px-8 py-4 text-[10px] font-black text-text-muted uppercase tracking-[0.2em] text-right">Integrity Loss</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/10">
              {[
                { name: "WAN 1", id: "eth0", uptime: "99.98%", stability: "Robust", errors: "0.001%" },
                { name: "WAN 2", id: "eth1", uptime: "99.92%", stability: "Nominal", errors: "0.015%" },
                { name: "LAN Local", id: "br0", uptime: "100.00%", stability: "Robust", errors: "0.000%" },
              ].map((iface, idx) => (
                <tr key={idx} className="hover:bg-primary/[0.01] transition-colors group">
                  <td className="px-8 py-5">
                    <div className="flex items-center space-x-4">
                      <div className="w-10 h-10 rounded-xl bg-surface-bright border border-outline-variant/20 flex items-center justify-center font-black text-xs text-text-strong group-hover:border-primary/40 transition-colors uppercase">{iface.id}</div>
                      <div className="flex flex-col">
                        <span className="text-sm font-black text-text-strong">{iface.name}</span>
                        <span className="text-[10px] text-success-green font-bold uppercase tracking-tighter">Operational • Full Duplex</span>
                      </div>
                    </div>
                  </td>
                  <td className="px-8 py-5 text-sm text-center font-black text-text-strong tabular-nums">{iface.uptime}</td>
                  <td className="px-8 py-5 text-center">
                     <span className={`inline-flex items-center px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-widest ${iface.stability === 'Robust' ? 'bg-success-green/10 text-success-green border border-success-green/20' : 'bg-warning-amber/10 text-warning-amber border border-warning-amber/20'}`}>
                       {iface.stability}
                     </span>
                  </td>
                  <td className="px-8 py-5 text-sm text-right font-bold text-text-muted tabular-nums">{iface.errors}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default MetricsPage;
