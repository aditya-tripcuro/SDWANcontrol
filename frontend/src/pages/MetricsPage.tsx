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

const MetricsPage: React.FC = () => {
  const [metrics, setMetrics] = useState<any>(null);
  const auth = useAuth();

  useEffect(() => {
    if (!auth.token) return;
    const onMetric = (d: unknown) => setMetrics(d as any);
    sseManager.on("metric", onMetric);
    return () => {
      sseManager.off("metric", onMetric);
    };
  }, [auth.token]);

  const throughputData = [
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-text-strong">Network Metrics</h2>
          <p className="text-sm text-text-muted">Detailed performance analysis across all interfaces</p>
        </div>
        <div className="flex space-x-2">
           <button className="px-3 py-1.5 bg-white/5 border border-white/10 rounded-sm text-xs font-medium hover:bg-white/10 transition-colors">Last 24 Hours</button>
           <button className="px-3 py-1.5 bg-brand-primary text-white rounded-sm text-xs font-medium hover:bg-brand-primary/90 transition-colors">Export PDF</button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Throughput Area Chart */}
        <div className="bg-surface p-6 rounded-base border border-white/5">
          <h3 className="text-sm font-bold text-text-strong uppercase tracking-wider mb-8">Interface Throughput (Mbps)</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={throughputData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 10}} />
                <YAxis axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 10}} />
                <Tooltip 
                  contentStyle={{backgroundColor: '#1e293b', border: 'none', borderRadius: '4px', fontSize: '12px'}}
                  itemStyle={{color: '#f8fafc'}}
                />
                <Legend iconType="circle" wrapperStyle={{fontSize: '10px', textTransform: 'uppercase', fontWeight: 'bold', paddingTop: '20px'}} />
                <Area type="monotone" dataKey="wan1" stroke="#38bdf8" fill="#38bdf8" fillOpacity={0.1} strokeWidth={2} name="WAN 1 (Primary)" />
                <Area type="monotone" dataKey="wan2" stroke="#818cf8" fill="#818cf8" fillOpacity={0.1} strokeWidth={2} name="WAN 2 (Backup)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Latency Distribution Bar Chart */}
        <div className="bg-surface p-6 rounded-base border border-white/5">
          <h3 className="text-sm font-bold text-text-strong uppercase tracking-wider mb-8">Latency Distribution</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={latencyDistribution}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="range" axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 10}} />
                <YAxis axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 10}} />
                <Tooltip 
                  cursor={{fill: 'rgba(255,255,255,0.05)'}}
                  contentStyle={{backgroundColor: '#1e293b', border: 'none', borderRadius: '4px', fontSize: '12px'}}
                  itemStyle={{color: '#f8fafc'}}
                />
                <Bar dataKey="count" fill="#334155" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Interface Health Table */}
      <div className="bg-surface rounded-base border border-white/5 overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5">
          <h3 className="text-sm font-bold text-text-strong uppercase tracking-wider">Interface Health Summary</h3>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="bg-white/5">
              <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest">Interface</th>
              <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest text-center">Uptime</th>
              <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest text-center">Stability</th>
              <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest text-right">Error Rate</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {[
              { name: "WAN 1 (eth0)", uptime: "99.98%", stability: "High", errors: "0.001%" },
              { name: "WAN 2 (eth1)", uptime: "99.92%", stability: "Medium", errors: "0.015%" },
              { name: "LAN (br0)", uptime: "100.00%", stability: "High", errors: "0.000%" },
            ].map((iface, idx) => (
              <tr key={idx} className="hover:bg-white/[0.02] transition-colors">
                <td className="px-6 py-4">
                  <div className="flex flex-col">
                    <span className="text-xs font-bold text-text-strong">{iface.name}</span>
                    <span className="text-[10px] text-text-muted">Active / Connected</span>
                  </div>
                </td>
                <td className="px-6 py-4 text-xs text-center font-medium text-text-strong">{iface.uptime}</td>
                <td className="px-6 py-4 text-center">
                   <span className={`inline-block px-2 py-0.5 rounded-sm text-[10px] font-bold uppercase ${iface.stability === 'High' ? 'bg-green-500/10 text-green-400' : 'bg-yellow-500/10 text-yellow-400'}`}>
                     {iface.stability}
                   </span>
                </td>
                <td className="px-6 py-4 text-xs text-right font-medium text-text-muted">{iface.errors}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default MetricsPage;
