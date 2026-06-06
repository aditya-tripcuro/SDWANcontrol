import React, { useEffect, useState, useMemo } from "react";
import { sseManager } from "../api/sse";
import { useTimezone } from "../context/TimezoneContext";
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
import { getMetrics, getInterfacesStatus } from "../api/client";
import type { InterfaceStatus, MetricRow } from "../api/types";

const IFACE_COLORS = ["#ffffff", "#38bdf8", "#4ade80", "#fbbf24", "#f87171", "#a78bfa"];

const MetricsPage: React.FC = () => {
  const [liveMetrics, setLiveMetrics] = useState<Record<string, MetricRow | null>>({});
  const [historicalMetrics, setHistoricalMetrics] = useState<MetricRow[]>([]);
  const [ifaceStatus, setIfaceStatus] = useState<InterfaceStatus[]>([]);
  const { timezone } = useTimezone();

  useEffect(() => {
    getMetrics({ limit: 500 }).then(setHistoricalMetrics).catch(console.error);
    getInterfacesStatus().then(setIfaceStatus).catch(console.error);

    const onMetric = (d: unknown) => setLiveMetrics(d as Record<string, MetricRow | null>);
    sseManager.on("metric", onMetric);
    return () => sseManager.off("metric", onMetric);
  }, []);

  // Per-interface historical averages
  const ifaceStats = useMemo(() => {
    const stats: Record<string, { latSum: number; jitSum: number; lossSum: number; n: number }> = {};
    historicalMetrics.forEach((m) => {
      if (!stats[m.interface]) stats[m.interface] = { latSum: 0, jitSum: 0, lossSum: 0, n: 0 };
      stats[m.interface].latSum += m.latency_ms;
      stats[m.interface].jitSum += m.jitter_ms;
      stats[m.interface].lossSum += m.loss_pct;
      stats[m.interface].n++;
    });
    return stats;
  }, [historicalMetrics]);

  // Score-over-time chart: one area per interface, bucketed by minute
  const scoreChartData = useMemo(() => {
    if (historicalMetrics.length === 0) return [];
    const sorted = [...historicalMetrics].reverse();
    const buckets: Record<string, any> = {};
    sorted.forEach((m) => {
      const time = new Intl.DateTimeFormat("en-US", {
        timeZone: timezone,
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(m.timestamp * 1000));
      if (!buckets[time]) buckets[time] = { time };
      buckets[time][m.interface] = m.score;
    });
    return Object.values(buckets);
  }, [historicalMetrics, timezone]);

  const ifaceNamesInHistory = useMemo(
    () => [...new Set(historicalMetrics.map((m) => m.interface))],
    [historicalMetrics]
  );

  // Latency distribution computed from real historical data
  const latencyDistribution = useMemo(() => {
    const b = [0, 0, 0, 0, 0];
    historicalMetrics.forEach((m) => {
      if (m.latency_ms < 10) b[0]++;
      else if (m.latency_ms < 20) b[1]++;
      else if (m.latency_ms < 50) b[2]++;
      else if (m.latency_ms < 100) b[3]++;
      else b[4]++;
    });
    return [
      { range: "<10ms", count: b[0] },
      { range: "10-20ms", count: b[1] },
      { range: "20-50ms", count: b[2] },
      { range: "50-100ms", count: b[3] },
      { range: ">100ms", count: b[4] },
    ];
  }, [historicalMetrics]);

  const totalSamples = historicalMetrics.length;

  // Merged per-interface data for the table
  const perIfaceData = useMemo(
    () =>
      ifaceStatus.map((iface) => {
        const hist = ifaceStats[iface.name];
        const live = liveMetrics[iface.name];
        return {
          name: iface.name,
          label: iface.label,
          wan_state: iface.wan_state,
          expected_speed_mbps: iface.expected_speed_mbps,
          gateway: iface.gateway,
          latency: live?.latency_ms ?? (hist ? hist.latSum / hist.n : null),
          jitter: live?.jitter_ms ?? (hist ? hist.jitSum / hist.n : null),
          loss: live?.loss_pct ?? (hist ? hist.lossSum / hist.n : null),
          score: live?.score ?? iface.score,
          dns_ok: live?.dns_ok,
          http_ok: live?.http_ok,
          samples: hist?.n ?? 0,
        };
      }),
    [ifaceStatus, ifaceStats, liveMetrics]
  );

  return (
    <div className="space-y-6 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 bg-surface-container-low/50 p-6 rounded-2xl border border-outline-variant/20 backdrop-blur-sm">
        <div className="flex items-center space-x-4">
          <div className="w-12 h-12 rounded-2xl bg-secondary text-secondary-on flex items-center justify-center shadow-lg shadow-secondary/10">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-black text-text-strong tracking-tight leading-none uppercase">
              Interface Metrics
            </h1>
            <p className="text-text-muted text-[10px] mt-1.5 font-bold uppercase tracking-[0.2em]">
              {totalSamples > 0 ? `${totalSamples} samples · ` : ""}Real-time probe telemetry
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Interface Score Over Time */}
        <div className="bg-surface-container-low p-6 rounded-2xl border border-outline-variant/20 shadow-sm group">
          <div className="flex items-center justify-between mb-8">
            <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">
              Interface Score Over Time
            </h3>
            <div className="flex items-center space-x-2">
              <span className="w-1.5 h-1.5 rounded-full bg-success-green animate-pulse"></span>
              <span className="text-[9px] font-black text-text-muted uppercase tracking-widest">Live Sampling</span>
            </div>
          </div>
          <div className="h-80">
            {scoreChartData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-xs font-bold uppercase tracking-widest">
                No data yet
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={scoreChartData}>
                  <defs>
                    {ifaceNamesInHistory.map((name, i) => (
                      <linearGradient key={name} id={`grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={IFACE_COLORS[i % IFACE_COLORS.length]} stopOpacity={0.15} />
                        <stop offset="95%" stopColor={IFACE_COLORS[i % IFACE_COLORS.length]} stopOpacity={0} />
                      </linearGradient>
                    ))}
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.1} />
                  <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} />
                  <YAxis domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} unit="%" />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "12px", fontSize: "10px", padding: "12px" }}
                    itemStyle={{ fontWeight: 900, textTransform: "uppercase" }}
                  />
                  <Legend verticalAlign="top" align="right" height={36} iconType="rect" wrapperStyle={{ fontSize: "9px", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.15em", paddingBottom: "20px" }} />
                  {ifaceNamesInHistory.map((name, i) => {
                    const iface = ifaceStatus.find((s) => s.name === name);
                    return (
                      <Area
                        key={name}
                        type="monotone"
                        dataKey={name}
                        name={iface?.label || name}
                        stroke={IFACE_COLORS[i % IFACE_COLORS.length]}
                        fill={`url(#grad-${i})`}
                        strokeWidth={i === 0 ? 3 : 2}
                        dot={{ r: 0 }}
                      />
                    );
                  })}
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Latency Distribution — computed from real historical data */}
        <div className="bg-surface-container-low p-6 rounded-2xl border border-outline-variant/20 shadow-sm group">
          <div className="flex items-center justify-between mb-8">
            <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">
              Latency Distribution
            </h3>
            <span className="text-[9px] font-black text-text-muted uppercase tracking-widest">
              N={totalSamples} samples
            </span>
          </div>
          <div className="h-80">
            {totalSamples === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-xs font-bold uppercase tracking-widest">
                No data yet
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={latencyDistribution}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.1} />
                  <XAxis dataKey="range" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} />
                  <Tooltip
                    cursor={{ fill: "rgba(255,255,255,0.02)" }}
                    contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "12px", fontSize: "10px" }}
                  />
                  <Bar dataKey="count" name="Samples" fill="#1e293b" radius={[4, 4, 0, 0]} className="hover:fill-primary transition-colors cursor-pointer" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      {/* Per-Interface Performance Table — real data */}
      <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 shadow-sm overflow-hidden">
        <div className="px-6 py-5 border-b border-outline-variant/20 bg-surface-bright/5 flex items-center justify-between">
          <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">
            Per-Interface Performance
          </h3>
          <span className="text-[9px] font-black text-text-muted uppercase tracking-widest">
            Live + historical average
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-canvas/20">
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Interface</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-center">State</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-right">Latency</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-right">Jitter</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-right">Loss</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-center">DNS</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-center">HTTP</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-right">Score</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/10">
              {perIfaceData.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-6 py-12 text-center text-text-muted text-xs font-bold uppercase tracking-widest">
                    Loading…
                  </td>
                </tr>
              ) : (
                perIfaceData.map((iface, i) => (
                  <tr key={iface.name} className="hover:bg-primary/[0.01] transition-colors group">
                    <td className="px-6 py-5">
                      <div className="flex items-center space-x-4">
                        <div
                          className="w-2 h-8 rounded-full"
                          style={{ backgroundColor: IFACE_COLORS[i % IFACE_COLORS.length] }}
                        ></div>
                        <div className="flex flex-col">
                          <span className="text-xs font-black text-text-strong uppercase tracking-wider">
                            {iface.label}
                          </span>
                          <span className="text-[9px] font-mono text-text-muted">
                            {iface.name} · {iface.expected_speed_mbps} Mbps · GW {iface.gateway}
                          </span>
                          {iface.samples > 0 && (
                            <span className="text-[8px] text-text-muted font-bold">{iface.samples} samples</span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-5 text-center">
                      <span
                        className={`inline-flex items-center px-2 py-1 rounded text-[8px] font-black uppercase tracking-widest ${
                          iface.wan_state === "STABLE"
                            ? "bg-success-green/10 text-success-green border border-success-green/20"
                            : iface.wan_state === "DEGRADED"
                            ? "bg-warning-amber/10 text-warning-amber border border-warning-amber/20"
                            : iface.wan_state === "FAILED"
                            ? "bg-error-red/10 text-error-red border border-error-red/20"
                            : "bg-surface-bright/50 text-text-muted border border-outline-variant/20"
                        }`}
                      >
                        {iface.wan_state ?? "—"}
                      </span>
                    </td>
                    <td className="px-6 py-5 text-right font-black text-sm text-text-strong tabular-nums">
                      {iface.latency != null ? `${iface.latency.toFixed(1)} ms` : "—"}
                    </td>
                    <td className="px-6 py-5 text-right font-bold text-sm text-text-muted tabular-nums">
                      {iface.jitter != null ? `${iface.jitter.toFixed(1)} ms` : "—"}
                    </td>
                    <td className="px-6 py-5 text-right font-bold text-sm text-text-muted tabular-nums">
                      {iface.loss != null ? `${iface.loss.toFixed(2)}%` : "—"}
                    </td>
                    <td className="px-6 py-5 text-center">
                      {iface.dns_ok == null ? (
                        <span className="text-text-muted text-xs">—</span>
                      ) : (
                        <span className={`text-xs font-black ${iface.dns_ok ? "text-success-green" : "text-error-red"}`}>
                          {iface.dns_ok ? "OK" : "FAIL"}
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-5 text-center">
                      {iface.http_ok == null ? (
                        <span className="text-text-muted text-xs">—</span>
                      ) : (
                        <span className={`text-xs font-black ${iface.http_ok ? "text-success-green" : "text-error-red"}`}>
                          {iface.http_ok ? "OK" : "FAIL"}
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-5 text-right">
                      <span
                        className={`text-sm font-black tabular-nums ${
                          (iface.score ?? 0) > 80
                            ? "text-success-green"
                            : (iface.score ?? 0) > 50
                            ? "text-warning-amber"
                            : "text-error-red"
                        }`}
                      >
                        {iface.score?.toFixed(1) ?? "—"}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default MetricsPage;
