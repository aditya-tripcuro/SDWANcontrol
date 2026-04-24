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

  // Mock data for charts - in a real app these would come from the API
  const performanceData = [
    { time: "00:00", latency: 25, jitter: 2 },
    { time: "04:00", latency: 28, jitter: 3 },
    { time: "08:00", latency: 45, jitter: 12 },
    { time: "12:00", latency: 30, jitter: 4 },
    { time: "16:00", latency: 35, jitter: 6 },
    { time: "20:00", latency: 22, jitter: 2 },
  ];

  const trafficData = [
    { name: "HTTP/S", value: 450, color: "#38bdf8" },
    { name: "Streaming", value: 300, color: "#818cf8" },
    { name: "VPN", value: 150, color: "#fb7185" },
    { name: "Other", value: 100, color: "#94a3b8" },
  ];

  const MetricCard = ({ title, value, unit, trend, color }: any) => (
    <div className="bg-surface p-6 rounded-base border border-white/5 hover:border-white/10 transition-all group">
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">{title}</h3>
        <div className={`p-1.5 rounded-sm bg-${color}/10 text-${color}`}>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>
        </div>
      </div>
      <div className="flex items-baseline space-x-1">
        <span className="text-2xl font-bold text-text-strong tracking-tight">{value}</span>
        <span className="text-sm font-medium text-text-muted">{unit}</span>
      </div>
      <div className="mt-4 flex items-center space-x-2">
        <span className="text-xs font-medium text-green-400">{trend}</span>
        <span className="text-[10px] text-text-muted uppercase tracking-tighter">vs last hour</span>
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard title="Avg Latency" value={metrics.latency || "24.5"} unit="ms" trend="-2.4%" color="blue-400" />
        <MetricCard title="Jitter" value={metrics.jitter || "3.2"} unit="ms" trend="+0.5%" color="purple-400" />
        <MetricCard title="Packet Loss" value={metrics.packet_loss || "0.02"} unit="%" trend="-0.01%" color="rose-400" />
        <MetricCard title="Throughput" value={metrics.throughput || "842"} unit="Mbps" trend="+12.3%" color="emerald-400" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Performance Chart */}
        <div className="lg:col-span-2 bg-surface p-6 rounded-base border border-white/5">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h3 className="text-sm font-bold text-text-strong uppercase tracking-wider">Network Performance</h3>
              <p className="text-xs text-text-muted mt-1">Real-time latency and jitter tracking</p>
            </div>
            <div className="flex items-center space-x-2">
               <div className="flex items-center space-x-1">
                 <div className="w-2 h-2 rounded-full bg-sky-400"></div>
                 <span className="text-[10px] uppercase font-semibold text-text-muted">Latency</span>
               </div>
               <div className="flex items-center space-x-1 pl-4">
                 <div className="w-2 h-2 rounded-full bg-indigo-400"></div>
                 <span className="text-[10px] uppercase font-semibold text-text-muted">Jitter</span>
               </div>
            </div>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={performanceData}>
                <defs>
                  <linearGradient id="colorLat" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#38bdf8" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis 
                  dataKey="time" 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{fill: '#64748b', fontSize: 10}} 
                  dy={10}
                />
                <YAxis 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{fill: '#64748b', fontSize: 10}} 
                />
                <Tooltip 
                  contentStyle={{backgroundColor: '#1e293b', border: 'none', borderRadius: '4px', fontSize: '12px'}}
                  itemStyle={{color: '#f8fafc'}}
                />
                <Area type="monotone" dataKey="latency" stroke="#38bdf8" strokeWidth={2} fillOpacity={1} fill="url(#colorLat)" />
                <Line type="monotone" dataKey="jitter" stroke="#818cf8" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Traffic Distribution */}
        <div className="bg-surface p-6 rounded-base border border-white/5 flex flex-col">
          <h3 className="text-sm font-bold text-text-strong uppercase tracking-wider mb-8">Traffic Distribution</h3>
          <div className="flex-1 flex items-center justify-center relative">
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={trafficData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {trafficData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-2xl font-bold text-text-strong">1.2</span>
              <span className="text-[10px] text-text-muted uppercase font-semibold">GB/s</span>
            </div>
          </div>
          <div className="mt-8 space-y-3">
            {trafficData.map((item) => (
              <div key={item.name} className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <div className="w-1.5 h-1.5 rounded-full" style={{backgroundColor: item.color}}></div>
                  <span className="text-xs font-medium text-text-muted">{item.name}</span>
                </div>
                <span className="text-xs font-bold text-text-strong">{Math.round((item.value / 1000) * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Connection Table */}
      <div className="bg-surface rounded-base border border-white/5 overflow-hidden">
        <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
          <h3 className="text-sm font-bold text-text-strong uppercase tracking-wider">Active Connections</h3>
          <button className="text-xs font-semibold text-sky-400 hover:text-sky-300 transition-colors uppercase tracking-widest">View All</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-white/5">
                <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest">Source IP</th>
                <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest">Interface</th>
                <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest">Status</th>
                <th className="px-6 py-3 text-[10px] font-bold text-text-muted uppercase tracking-widest text-right">Bandwidth</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {[
                { ip: "192.168.1.105", iface: "WAN1", status: "Active", speed: "12.4 Mbps" },
                { ip: "192.168.1.12", iface: "WAN1", status: "Active", speed: "4.8 Mbps" },
                { ip: "10.0.0.45", iface: "WAN2", status: "Active", speed: "256 Kbps" },
                { ip: "192.168.1.201", iface: "WAN1", status: "Idle", speed: "0 Mbps" },
              ].map((conn, idx) => (
                <tr key={idx} className="hover:bg-white/[0.02] transition-colors group">
                  <td className="px-6 py-4 text-xs font-medium font-mono text-text-strong">{conn.ip}</td>
                  <td className="px-6 py-4 text-xs">
                    <span className="px-2 py-1 rounded-sm bg-white/5 border border-white/5 text-text-muted text-[10px] font-bold uppercase">{conn.iface}</span>
                  </td>
                  <td className="px-6 py-4 text-xs">
                    <div className="flex items-center space-x-2">
                       <div className={`w-1.5 h-1.5 rounded-full ${conn.status === 'Active' ? 'bg-green-500' : 'bg-slate-500'}`}></div>
                       <span className="text-text-muted">{conn.status}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-xs text-right font-bold text-text-strong">{conn.speed}</td>
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
