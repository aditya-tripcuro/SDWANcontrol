import React, { useEffect, useState, useMemo, useCallback } from "react";
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
  LineChart,
  Line,
} from "recharts";
import {
  getMetrics,
  getInterfacesStatus,
  getUsage,
  getSpeedtests,
  getLatestSpeedtests,
  getSpeedtestEnabled,
  setSpeedtestEnabled,
  runSpeedtest,
} from "../api/client";
import type {
  InterfaceStatus,
  MetricRow,
  UsageSample,
  SpeedtestResult,
} from "../api/types";

const IFACE_COLORS = ["#ffffff", "#38bdf8", "#4ade80", "#fbbf24", "#f87171", "#a78bfa"];

const MetricsPage: React.FC = () => {
  const [liveMetrics, setLiveMetrics] = useState<Record<string, MetricRow | null>>({});
  const [historicalMetrics, setHistoricalMetrics] = useState<MetricRow[]>([]);
  const [ifaceStatus, setIfaceStatus] = useState<InterfaceStatus[]>([]);
  const [usageSamples, setUsageSamples] = useState<UsageSample[]>([]);
  const [latestSpeedtests, setLatestSpeedtests] = useState<Record<string, SpeedtestResult | null>>({});
  const [historicalSpeedtests, setHistoricalSpeedtests] = useState<SpeedtestResult[]>([]);
  const [speedtestEnabled, setSpeedtestEnabledState] = useState<Record<string, boolean>>({});
  const [speedtestBusy, setSpeedtestBusy] = useState<Record<string, boolean>>({});
  const { timezone } = useTimezone();

  useEffect(() => {
    getMetrics({ limit: 500 }).then(setHistoricalMetrics).catch(console.error);
    getInterfacesStatus().then(setIfaceStatus).catch(console.error);
    getUsage({ limit: 720 }).then(setUsageSamples).catch(console.error);
    getLatestSpeedtests().then(setLatestSpeedtests).catch(console.error);
    getSpeedtests({ limit: 200 }).then(setHistoricalSpeedtests).catch(console.error);
    getSpeedtestEnabled().then(setSpeedtestEnabledState).catch(console.error);

    const onMetric = (d: unknown) => setLiveMetrics(d as Record<string, MetricRow | null>);
    const onUsage = (d: unknown) => {
      const next = d as Record<string, UsageSample | null>;
      // Push the latest sample for each interface onto the in-memory history
      // (sliding window of ~720 rows, matching the initial fetch).
      setUsageSamples((prev) => {
        const merged = [...prev];
        for (const [, s] of Object.entries(next)) {
          if (s) merged.push(s);
        }
        return merged.slice(-720);
      });
    };
    const onSpeedtest = (d: unknown) => {
      const row = d as SpeedtestResult;
      if (!row || !row.interface) return;
      setLatestSpeedtests((prev) => ({ ...prev, [row.interface]: row }));
      setHistoricalSpeedtests((prev) => [row, ...prev].slice(0, 200));
      setSpeedtestBusy((prev) => ({ ...prev, [row.interface]: false }));
    };
    sseManager.on("metric", onMetric);
    sseManager.on("usage", onUsage);
    sseManager.on("speedtest", onSpeedtest);
    return () => {
      sseManager.off("metric", onMetric);
      sseManager.off("usage", onUsage);
      sseManager.off("speedtest", onSpeedtest);
    };
  }, []);

  const toggleSpeedtest = useCallback(async (iface: string, on: boolean) => {
    try {
      const res = await setSpeedtestEnabled(iface, on);
      setSpeedtestEnabledState((prev) => ({ ...prev, [iface]: res.enabled }));
    } catch (e) {
      console.error("failed to toggle speedtest", e);
    }
  }, []);

  const triggerSpeedtest = useCallback(async (iface: string) => {
    setSpeedtestBusy((prev) => ({ ...prev, [iface]: true }));
    try {
      await runSpeedtest(iface);
    } catch (e) {
      console.error("failed to queue speedtest", e);
      setSpeedtestBusy((prev) => ({ ...prev, [iface]: false }));
    }
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

  // Bucket metrics by minute for latency/jitter time-series (mean over each minute,
  // one series per interface — same shape as scoreChartData so we can reuse
  // the Area chart pattern).
  const bucketByMinute = (
    rows: MetricRow[],
    field: "latency_ms" | "jitter_ms",
  ): any[] => {
    if (rows.length === 0) return [];
    const sorted = [...rows].reverse();
    const buckets: Record<string, any> = {};
    sorted.forEach((m) => {
      const time = new Intl.DateTimeFormat("en-US", {
        timeZone: timezone,
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(m.timestamp * 1000));
      if (!buckets[time]) buckets[time] = { time, _counts: {} };
      const cur = buckets[time][m.interface];
      const cnt = (buckets[time]._counts[m.interface] || 0) + 1;
      buckets[time]._counts[m.interface] = cnt;
      buckets[time][m.interface] = cur == null ? m[field] : (cur * (cnt - 1) + m[field]) / cnt;
    });
    return Object.values(buckets).map(({ _counts, ...rest }: any) => rest);
  };

  const latencyChartData = useMemo(
    () => bucketByMinute(historicalMetrics, "latency_ms"),
    [historicalMetrics, timezone]
  );
  const jitterChartData = useMemo(
    () => bucketByMinute(historicalMetrics, "jitter_ms"),
    [historicalMetrics, timezone]
  );

  // Network usage: separate chart per interface so rx/tx don't overlap with
  // other interfaces. Sample-by-sample (no minute-bucketing) to keep the live
  // "Task Manager" feel.
  const usageByIface = useMemo(() => {
    const groups: Record<string, UsageSample[]> = {};
    [...usageSamples]
      .sort((a, b) => a.timestamp - b.timestamp)
      .forEach((u) => {
        (groups[u.interface] ||= []).push(u);
      });
    return groups;
  }, [usageSamples]);

  const formatTime = (ts: number) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date(ts * 1000));

  // Speedtest history: bucket by interface for the download/upload chart.
  const speedtestDownloadData = useMemo(() => {
    if (historicalSpeedtests.length === 0) return [];
    const sorted = [...historicalSpeedtests].reverse();
    const buckets: Record<string, any> = {};
    sorted.forEach((s) => {
      const time = new Intl.DateTimeFormat("en-US", {
        timeZone: timezone,
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(s.timestamp * 1000));
      if (!buckets[time]) buckets[time] = { time };
      if (s.download_mbps != null) buckets[time][s.interface] = s.download_mbps;
    });
    return Object.values(buckets);
  }, [historicalSpeedtests, timezone]);

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

      {/* Latency + Jitter time-series — one Area per interface */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-surface-container-low p-6 rounded-2xl border border-outline-variant/20 shadow-sm">
          <div className="flex items-center justify-between mb-6">
            <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">
              Latency Over Time
            </h3>
            <span className="text-[9px] font-black text-text-muted uppercase tracking-widest">per interface · ms</span>
          </div>
          <div className="h-72">
            {latencyChartData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-xs font-bold uppercase tracking-widest">No data yet</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={latencyChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.1} />
                  <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} unit="ms" />
                  <Tooltip contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "12px", fontSize: "10px" }} />
                  <Legend verticalAlign="top" align="right" height={36} iconType="rect" wrapperStyle={{ fontSize: "9px", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.15em", paddingBottom: "20px" }} />
                  {ifaceNamesInHistory.map((name, i) => {
                    const iface = ifaceStatus.find((s) => s.name === name);
                    return (
                      <Line key={name} type="monotone" dataKey={name} name={iface?.label || name} stroke={IFACE_COLORS[i % IFACE_COLORS.length]} strokeWidth={2} dot={false} isAnimationActive={false} />
                    );
                  })}
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="bg-surface-container-low p-6 rounded-2xl border border-outline-variant/20 shadow-sm">
          <div className="flex items-center justify-between mb-6">
            <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">
              Jitter Over Time
            </h3>
            <span className="text-[9px] font-black text-text-muted uppercase tracking-widest">per interface · ms</span>
          </div>
          <div className="h-72">
            {jitterChartData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-xs font-bold uppercase tracking-widest">No data yet</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={jitterChartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.1} />
                  <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} unit="ms" />
                  <Tooltip contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "12px", fontSize: "10px" }} />
                  <Legend verticalAlign="top" align="right" height={36} iconType="rect" wrapperStyle={{ fontSize: "9px", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.15em", paddingBottom: "20px" }} />
                  {ifaceNamesInHistory.map((name, i) => {
                    const iface = ifaceStatus.find((s) => s.name === name);
                    return (
                      <Line key={name} type="monotone" dataKey={name} name={iface?.label || name} stroke={IFACE_COLORS[i % IFACE_COLORS.length]} strokeWidth={2} dot={false} isAnimationActive={false} />
                    );
                  })}
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>

      {/* Network Usage — one card per interface, rx + tx stacked, Task-Manager style */}
      <div className="bg-surface-container-low p-6 rounded-2xl border border-outline-variant/20 shadow-sm">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Network Usage</h3>
          <span className="text-[9px] font-black text-text-muted uppercase tracking-widest">RX / TX · Mbps</span>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {ifaceStatus.map((iface, i) => {
            const series = (usageByIface[iface.name] || []).map((s) => ({
              time: formatTime(s.timestamp),
              rx: s.rx_mbps,
              tx: s.tx_mbps,
            }));
            const color = IFACE_COLORS[i % IFACE_COLORS.length];
            return (
              <div key={iface.name} className="bg-canvas/30 rounded-xl border border-outline-variant/10 p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center space-x-2">
                    <div className="w-2 h-6 rounded-full" style={{ backgroundColor: color }} />
                    <span className="text-[10px] font-black text-text-strong uppercase tracking-widest">{iface.label}</span>
                  </div>
                  <span className="text-[9px] font-mono text-text-muted">{iface.name}</span>
                </div>
                <div className="h-48">
                  {series.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-text-muted text-[10px] font-bold uppercase tracking-widest">No samples yet</div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={series}>
                        <defs>
                          <linearGradient id={`rx-${i}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.4} />
                            <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
                          </linearGradient>
                          <linearGradient id={`tx-${i}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#4ade80" stopOpacity={0.4} />
                            <stop offset="95%" stopColor="#4ade80" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.1} />
                        <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} />
                        <YAxis axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} unit="" />
                        <Tooltip contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "12px", fontSize: "10px" }} formatter={(v: any) => `${(v as number).toFixed(2)} Mbps`} />
                        <Legend verticalAlign="top" align="right" height={28} iconType="rect" wrapperStyle={{ fontSize: "9px", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.15em" }} />
                        <Area type="monotone" dataKey="rx" name="RX" stroke="#38bdf8" fill={`url(#rx-${i})`} strokeWidth={2} dot={false} isAnimationActive={false} />
                        <Area type="monotone" dataKey="tx" name="TX" stroke="#4ade80" fill={`url(#tx-${i})`} strokeWidth={2} dot={false} isAnimationActive={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Speedtest panel: per-interface toggle + Run now + latest result, history chart */}
      <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 shadow-sm overflow-hidden">
        <div className="px-6 py-5 border-b border-outline-variant/20 bg-surface-bright/5 flex items-center justify-between">
          <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Speedtest (Ookla)</h3>
          <span className="text-[9px] font-black text-text-muted uppercase tracking-widest">Hourly per interface · opt-in</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-6">
          {ifaceStatus.map((iface, i) => {
            const latest = latestSpeedtests[iface.name];
            const enabled = !!speedtestEnabled[iface.name];
            const busy = !!speedtestBusy[iface.name];
            return (
              <div key={iface.name} className="bg-canvas/30 rounded-xl border border-outline-variant/10 p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <div className="w-2 h-6 rounded-full" style={{ backgroundColor: IFACE_COLORS[i % IFACE_COLORS.length] }} />
                    <span className="text-[10px] font-black text-text-strong uppercase tracking-widest">{iface.label}</span>
                  </div>
                  <label className="flex items-center space-x-2 cursor-pointer">
                    <input type="checkbox" className="accent-primary" checked={enabled} onChange={(e) => toggleSpeedtest(iface.name, e.target.checked)} />
                    <span className="text-[9px] font-black text-text-muted uppercase tracking-widest">Auto</span>
                  </label>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div>
                    <div className="text-[8px] font-black text-text-muted uppercase tracking-widest">Down</div>
                    <div className="text-sm font-black text-text-strong tabular-nums">{latest?.download_mbps != null ? `${latest.download_mbps.toFixed(1)}` : "—"}</div>
                    <div className="text-[8px] text-text-muted">Mbps</div>
                  </div>
                  <div>
                    <div className="text-[8px] font-black text-text-muted uppercase tracking-widest">Up</div>
                    <div className="text-sm font-black text-text-strong tabular-nums">{latest?.upload_mbps != null ? `${latest.upload_mbps.toFixed(1)}` : "—"}</div>
                    <div className="text-[8px] text-text-muted">Mbps</div>
                  </div>
                  <div>
                    <div className="text-[8px] font-black text-text-muted uppercase tracking-widest">Ping</div>
                    <div className="text-sm font-black text-text-strong tabular-nums">{latest?.ping_ms != null ? `${latest.ping_ms.toFixed(1)}` : "—"}</div>
                    <div className="text-[8px] text-text-muted">ms</div>
                  </div>
                </div>
                {latest?.error && (
                  <div className="text-[9px] font-bold text-error-red bg-error-red/5 border border-error-red/20 rounded px-2 py-1">
                    {latest.error}
                  </div>
                )}
                <div className="flex items-center justify-between pt-2 border-t border-outline-variant/10">
                  <span className="text-[8px] text-text-muted">
                    {latest ? new Date(latest.timestamp * 1000).toLocaleString() : "no run yet"}
                  </span>
                  <button
                    onClick={() => triggerSpeedtest(iface.name)}
                    disabled={busy}
                    className="px-3 py-1 text-[9px] font-black uppercase tracking-widest rounded bg-primary/10 text-primary hover:bg-primary/20 border border-primary/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    {busy ? "Running…" : "Run now"}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
        {historicalSpeedtests.length > 0 && (
          <div className="px-6 pb-6">
            <div className="text-[9px] font-black text-text-muted uppercase tracking-widest mb-3">Download history · Mbps</div>
            <div className="h-64 bg-canvas/30 rounded-xl border border-outline-variant/10 p-4">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={speedtestDownloadData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.1} />
                  <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} />
                  <Tooltip contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "12px", fontSize: "10px" }} formatter={(v: any) => `${(v as number).toFixed(1)} Mbps`} />
                  <Legend verticalAlign="top" align="right" height={28} iconType="rect" wrapperStyle={{ fontSize: "9px", fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.15em" }} />
                  {ifaceStatus.map((iface, i) => (
                    <Line key={iface.name} type="monotone" dataKey={iface.name} name={iface.label} stroke={IFACE_COLORS[i % IFACE_COLORS.length]} strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default MetricsPage;
