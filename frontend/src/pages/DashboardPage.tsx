import React, { useEffect, useState, useMemo } from "react";
import { sseManager } from "../api/sse";
import { useAlertCount } from "../context/AlertCountContext";
import { useTimezone } from "../context/TimezoneContext";
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { getStatus, getMetrics, getInterfacesStatus, controlAction, type ControlAction } from "../api/client";
import type { InterfaceStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";

const IFACE_COLORS = ["#ffffff", "#38bdf8", "#4ade80", "#fbbf24", "#f87171", "#a78bfa"];

const CONTROL_MODE_STYLE: Record<string, string> = {
  RUNNING: "text-success-green",
  PAUSED: "text-warning-amber",
  STARTING: "text-warning-amber",
  STOPPED: "text-text-muted",
  KILLED: "text-error-red",
};

// Route-management controls (Start / Pause / Resume / Stop). Wired to the
// /api/control/* endpoints, which require operator role; viewers see state only.
const ControllerControls: React.FC<{ mode?: string; onStatus: (s: any) => void }> = ({ mode, onStatus }) => {
  const { user } = useAuth();
  const canControl = user?.role === "admin" || user?.role === "operator";
  const [busy, setBusy] = useState<ControlAction | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async (action: ControlAction) => {
    setBusy(action);
    setErr(null);
    try {
      onStatus(await controlAction(action));
    } catch (e: any) {
      setErr(e?.message || "Action failed");
    } finally {
      setBusy(null);
    }
  };

  const Btn: React.FC<{ action: ControlAction; label: string; intent: "primary" | "neutral" | "danger" }> = ({
    action,
    label,
    intent,
  }) => {
    const styles =
      intent === "primary"
        ? "bg-primary text-primary-on border-primary/50 hover:shadow-lg hover:shadow-white/10"
        : intent === "danger"
        ? "bg-error-red/10 text-error-red border-error-red/40 hover:bg-error-red/20"
        : "bg-surface-bright text-text-strong border-outline-variant/30 hover:border-primary/40";
    return (
      <button
        type="button"
        disabled={busy !== null}
        onClick={() => run(action)}
        className={`px-4 py-2 rounded-lg text-[10px] font-black uppercase tracking-widest border transition-all disabled:opacity-40 disabled:cursor-not-allowed ${styles}`}
      >
        {busy === action ? "…" : label}
      </button>
    );
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-black text-text-muted uppercase tracking-widest">Routing</span>
        <span className={`text-[10px] font-black uppercase tracking-widest ${CONTROL_MODE_STYLE[mode ?? ""] ?? "text-text-muted"}`}>
          {mode ?? "…"}
        </span>
      </div>
      {!canControl ? (
        <span className="text-[9px] font-bold text-text-muted uppercase tracking-wide">Operator role required</span>
      ) : mode === "STARTING" ? (
        <span className="text-[10px] font-black text-warning-amber uppercase tracking-widest animate-pulse">Starting…</span>
      ) : (
        <div className="flex items-center gap-2">
          {mode === "RUNNING" && (
            <>
              <Btn action="pause" label="Pause" intent="neutral" />
              <Btn action="stop" label="Stop" intent="danger" />
            </>
          )}
          {mode === "PAUSED" && (
            <>
              <Btn action="resume" label="Resume" intent="primary" />
              <Btn action="stop" label="Stop" intent="danger" />
            </>
          )}
          {(mode === undefined || mode === "STOPPED" || mode === "KILLED") && (
            <Btn action="start" label="Start" intent="primary" />
          )}
        </div>
      )}
      {err && <span className="text-[9px] font-bold text-error-red uppercase tracking-wide max-w-[14rem] text-right">{err}</span>}
    </div>
  );
};

const DashboardPage: React.FC = () => {
  const [status, setStatus] = useState<any>(null);
  const [liveMetrics, setLiveMetrics] = useState<Record<string, any>>({});
  const [ifaceStatus, setIfaceStatus] = useState<InterfaceStatus[]>([]);
  const [historicalMetrics, setHistoricalMetrics] = useState<any[]>([]);
  const alertCtx = useAlertCount();
  const { timezone, formatTs } = useTimezone();

  useEffect(() => {
    getStatus().then(setStatus).catch(console.error);
    getMetrics({ limit: 100 }).then(setHistoricalMetrics).catch(console.error);
    getInterfacesStatus().then(setIfaceStatus).catch(console.error);
    sseManager.connect();

    const onStatus = (d: any) => {
      setStatus(d);
      setIfaceStatus((prev) =>
        prev.map((iface) => ({
          ...iface,
          wan_state: d?.interfaces?.[iface.name]?.wan_state ?? iface.wan_state,
          score: d?.interfaces?.[iface.name]?.score ?? iface.score,
          in_pool: d?.interfaces?.[iface.name]?.in_pool ?? iface.in_pool,
        }))
      );
    };
    const onMetric = (d: unknown) => setLiveMetrics(d as Record<string, any>);
    const onAlert = () => alertCtx.increment();

    sseManager.on("status", onStatus);
    sseManager.on("metric", onMetric);
    sseManager.on("alert", onAlert);
    return () => {
      sseManager.off("status", onStatus);
      sseManager.off("metric", onMetric);
      sseManager.off("alert", onAlert);
    };
  }, []);

  // Compute averages across all interfaces from live SSE metric data
  const liveValues = Object.values(liveMetrics).filter(Boolean);
  const avgLatency =
    liveValues.length > 0
      ? (liveValues.reduce((s: number, m: any) => s + (m?.latency_ms ?? 0), 0) / liveValues.length).toFixed(1)
      : null;
  const avgJitter =
    liveValues.length > 0
      ? (liveValues.reduce((s: number, m: any) => s + (m?.jitter_ms ?? 0), 0) / liveValues.length).toFixed(1)
      : null;
  const avgLoss =
    liveValues.length > 0
      ? (liveValues.reduce((s: number, m: any) => s + (m?.loss_pct ?? 0), 0) / liveValues.length).toFixed(2)
      : null;
  const avgScore =
    liveValues.length > 0
      ? (liveValues.reduce((s: number, m: any) => s + (m?.score ?? 0), 0) / liveValues.length).toFixed(1)
      : null;

  // Build telemetry chart data: average latency + jitter per time bucket across all interfaces
  const telemetryData = useMemo(() => {
    if (historicalMetrics.length === 0) return [];
    const sorted = [...historicalMetrics].reverse();
    const buckets: Record<string, { time: string; latSum: number; jitSum: number; n: number }> = {};
    sorted.forEach((m) => {
      const time = new Intl.DateTimeFormat("en-US", {
        timeZone: timezone,
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(m.timestamp * 1000));
      if (!buckets[time]) buckets[time] = { time, latSum: 0, jitSum: 0, n: 0 };
      buckets[time].latSum += m.latency_ms;
      buckets[time].jitSum += m.jitter_ms;
      buckets[time].n++;
    });
    return Object.values(buckets).map((b) => ({
      time: b.time,
      latency: parseFloat((b.latSum / b.n).toFixed(2)),
      jitter: parseFloat((b.jitSum / b.n).toFixed(2)),
    }));
  }, [historicalMetrics, timezone]);

  // Interface score pie chart data
  const scorePieData = useMemo(
    () =>
      ifaceStatus.map((iface, i) => ({
        name: iface.label || iface.name,
        value: Math.max(0.5, iface.score ?? 0),
        color: IFACE_COLORS[i % IFACE_COLORS.length],
      })),
    [ifaceStatus]
  );

  const pieAvgScore =
    ifaceStatus.length > 0
      ? (ifaceStatus.reduce((s, i) => s + (i.score ?? 0), 0) / ifaceStatus.length).toFixed(1)
      : "—";

  const activeLinks = Object.values(status?.interfaces || {}).filter((i: any) => (i.score ?? 0) > 20).length;
  const totalLinks = Object.keys(status?.interfaces || {}).length;
  const globalScore = (
    Object.values(status?.interfaces || {}).reduce((acc: number, i: any) => acc + (i.score ?? 0), 0) /
    (Object.keys(status?.interfaces || {}).length || 1)
  ).toFixed(1);

  const MetricCard = ({ title, value, unit, icon }: any) => (
    <div className="bg-surface-container-low p-5 rounded-xl border border-outline-variant/20 hover:border-primary/30 transition-all duration-300 group shadow-sm hover:shadow-primary/5">
      <div className="flex justify-between items-start mb-4">
        <h3 className="text-[10px] font-black uppercase tracking-[0.2em] text-text-muted group-hover:text-primary transition-colors">
          {title}
        </h3>
        <div className="p-1.5 rounded bg-surface-bright/50 border border-outline-variant/30 text-text-strong group-hover:border-primary/50 transition-all">
          {icon}
        </div>
      </div>
      <div className="flex items-baseline space-x-1.5">
        <span className="text-2xl font-black text-text-strong tracking-tighter tabular-nums">
          {value ?? "—"}
        </span>
        {unit && <span className="text-[10px] font-bold text-text-muted uppercase">{unit}</span>}
      </div>
      {value === null && (
        <p className="mt-3 text-[9px] text-text-muted font-bold uppercase tracking-wide">Awaiting data</p>
      )}
    </div>
  );

  return (
    <div className="space-y-6 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
      {/* System Status Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 bg-surface-container-low/50 p-6 rounded-2xl border border-outline-variant/20 backdrop-blur-sm">
        <div className="flex items-center space-x-4">
          <div className="w-12 h-12 rounded-2xl bg-primary text-primary-on flex items-center justify-center shadow-lg shadow-white/10">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-black text-text-strong tracking-tight leading-none">
              WANControl Dashboard
            </h1>
            <p className="text-text-muted text-[11px] mt-1.5 font-bold uppercase tracking-widest flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-success-green animate-pulse"></span>
              <span>
                Mode:{" "}
                <span className="text-primary">{status?.wan_mode ?? "…"}</span>
                {status?.active_interface && (
                  <> · Active: <span className="text-primary">{status.active_interface}</span></>
                )}
              </span>
            </p>
          </div>
        </div>
        <div className="flex items-center space-x-6 h-full">
          <div className="flex flex-col items-end border-r border-outline-variant/30 pr-6">
            <span className="text-[10px] font-black text-text-muted uppercase tracking-widest">Active Links</span>
            <span className="text-lg font-black text-text-strong">
              {totalLinks > 0 ? `${activeLinks} / ${totalLinks}` : "—"}
            </span>
          </div>
          <div className="flex flex-col items-end border-r border-outline-variant/30 pr-6">
            <span className="text-[10px] font-black text-text-muted uppercase tracking-widest">Global Score</span>
            <span className={`text-lg font-black ${parseFloat(globalScore) > 80 ? "text-success-green" : parseFloat(globalScore) > 50 ? "text-warning-amber" : "text-error-red"}`}>
              {totalLinks > 0 ? globalScore : "—"}
            </span>
          </div>
          <ControllerControls mode={status?.mode} onStatus={setStatus} />
        </div>
      </div>

      {/* Primary Metrics Grid — real live data from SSE metric event */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Avg Latency"
          value={avgLatency}
          unit="ms"
          icon={<svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
        />
        <MetricCard
          title="Avg Jitter"
          value={avgJitter}
          unit="ms"
          icon={<svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>}
        />
        <MetricCard
          title="Avg Packet Loss"
          value={avgLoss}
          unit="%"
          icon={<svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z" /></svg>}
        />
        <MetricCard
          title="Avg Score"
          value={avgScore}
          unit="/ 100"
          icon={<svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Telemetry Chart — real historical metrics */}
        <div className="lg:col-span-2 bg-surface-container-low p-6 rounded-2xl border border-outline-variant/20 shadow-sm relative overflow-hidden group">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-8 gap-4">
            <div>
              <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">
                Interface Telemetry Stream
              </h3>
              <p className="text-[10px] text-text-muted mt-1 font-bold uppercase tracking-tight">
                Average latency &amp; jitter across all interfaces
              </p>
            </div>
            <div className="flex items-center space-x-2 bg-canvas/30 p-1 rounded-lg border border-outline-variant/20">
              <div className="flex items-center space-x-2 px-3 py-1 bg-surface-bright rounded text-[9px] font-black text-text-strong uppercase tracking-widest">
                <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></span>
                <span>Live</span>
              </div>
            </div>
          </div>
          <div className="h-[300px] w-full">
            {telemetryData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-text-muted text-xs font-bold uppercase tracking-widest">
                No data yet — awaiting first probe cycle
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={telemetryData}>
                  <defs>
                    <linearGradient id="colorLat" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ffffff" stopOpacity={0.15} />
                      <stop offset="95%" stopColor="#ffffff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} opacity={0.1} />
                  <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} dy={10} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 900 }} unit="ms" />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "12px", fontSize: "10px", boxShadow: "0 20px 25px -5px rgba(0,0,0,0.2)", padding: "12px" }}
                    itemStyle={{ color: "#f8fafc", fontWeight: 900, textTransform: "uppercase" }}
                    labelStyle={{ color: "#94a3b8", marginBottom: "8px", fontWeight: 900 }}
                  />
                  <Area type="monotone" dataKey="latency" name="Latency" stroke="#ffffff" strokeWidth={3} fillOpacity={1} fill="url(#colorLat)" dot={false} activeDot={{ r: 6, fill: "#ffffff", strokeWidth: 4, stroke: "#020617" }} />
                  <Line type="monotone" dataKey="jitter" name="Jitter" stroke="#38bdf8" strokeWidth={2} dot={false} activeDot={{ r: 4, fill: "#38bdf8" }} />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Interface Score Breakdown Pie */}
        <div className="bg-surface-container-low p-6 rounded-2xl border border-outline-variant/20 shadow-sm flex flex-col group">
          <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em] mb-8">
            Interface Score Breakdown
          </h3>
          <div className="flex-1 flex items-center justify-center relative">
            {scorePieData.length === 0 ? (
              <div className="text-text-muted text-xs font-bold uppercase tracking-widest text-center">
                No interfaces configured
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={scorePieData} cx="50%" cy="50%" innerRadius={70} outerRadius={90} paddingAngle={10} dataKey="value" stroke="none">
                    {scorePieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} className="hover:opacity-80 transition-opacity cursor-pointer" />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: "8px", fontSize: "10px" }}
                    formatter={(v: any) => [v.toFixed(1), "Score"]}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
            {scorePieData.length > 0 && (
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-3xl font-black text-text-strong tracking-tighter">{pieAvgScore}</span>
                <span className="text-[9px] text-text-muted uppercase font-black tracking-[0.2em]">Avg Score</span>
              </div>
            )}
          </div>
          <div className="mt-8 space-y-2">
            {scorePieData.map((item, i) => (
              <div key={item.name} className="p-2.5 rounded-xl bg-canvas/30 border border-outline-variant/10 flex items-center justify-between group/item hover:bg-canvas/50 transition-colors">
                <div className="flex items-center space-x-3">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }}></div>
                  <span className="text-[10px] font-black uppercase tracking-widest text-text-muted group-hover/item:text-text-strong transition-colors">
                    {item.name}
                  </span>
                </div>
                <span className={`text-xs font-black tabular-nums ${item.value > 80 ? "text-success-green" : item.value > 50 ? "text-warning-amber" : "text-error-red"}`}>
                  {item.value.toFixed(1)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Interface Health Table — real data from /api/status/interfaces */}
      <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 shadow-sm overflow-hidden">
        <div className="px-6 py-5 border-b border-outline-variant/20 flex items-center justify-between bg-surface-bright/5">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
              </svg>
            </div>
            <div>
              <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">WAN Interface Status</h3>
              <p className="text-[9px] text-text-muted mt-0.5 font-bold uppercase tracking-tight">
                Live state from controller
              </p>
            </div>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-canvas/20">
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Interface</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">State</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-center">Score</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Gateway</th>
                <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-right">Speed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/10">
              {ifaceStatus.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-text-muted text-xs font-bold uppercase tracking-widest">
                    Loading interface data…
                  </td>
                </tr>
              ) : (
                ifaceStatus.map((iface) => (
                  <tr key={iface.name} className="hover:bg-primary/[0.02] transition-colors group">
                    <td className="px-6 py-5">
                      <div className="flex items-center space-x-4">
                        <div className="w-9 h-9 rounded-xl bg-surface-bright flex items-center justify-center font-mono text-[10px] font-black text-text-muted border border-outline-variant/20 group-hover:border-primary/30 transition-colors uppercase">
                          {iface.name.slice(0, 4)}
                        </div>
                        <div className="flex flex-col">
                          <span className="text-xs font-black text-text-strong uppercase tracking-wide">
                            {iface.label}
                          </span>
                          <span className="text-[9px] font-mono text-text-muted">{iface.name}</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-5">
                      <div className="flex items-center space-x-2.5">
                        <div className={`w-2 h-2 rounded-full ${iface.wan_state === "STABLE" ? "bg-success-green shadow-[0_0_10px_rgba(74,222,128,0.5)]" : iface.wan_state === "DEGRADED" ? "bg-warning-amber" : "bg-error-red shadow-[0_0_10px_rgba(248,113,113,0.5)]"}`}></div>
                        <div className="flex flex-col">
                          <span className="text-[10px] font-black uppercase tracking-widest text-text-strong">
                            {iface.wan_state ?? "Unknown"}
                          </span>
                          <span className="text-[8px] font-bold text-text-muted uppercase">
                            {iface.in_pool ? "In Pool" : "Out of Pool"}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-5 text-center">
                      <span className={`text-sm font-black tabular-nums ${(iface.score ?? 0) > 80 ? "text-success-green" : (iface.score ?? 0) > 50 ? "text-warning-amber" : "text-error-red"}`}>
                        {iface.score?.toFixed(1) ?? "—"}
                      </span>
                    </td>
                    <td className="px-6 py-5">
                      <span className="text-xs font-mono text-text-muted">{iface.gateway}</span>
                    </td>
                    <td className="px-6 py-5 text-right">
                      <div className="flex flex-col items-end">
                        <span className="text-xs font-black text-text-strong tracking-tight tabular-nums">
                          {iface.expected_speed_mbps} Mbps
                        </span>
                        <div className="w-16 h-1 bg-outline-variant/10 rounded-full mt-2 overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-1000 ${(iface.score ?? 0) > 80 ? "bg-success-green w-full" : (iface.score ?? 0) > 50 ? "bg-warning-amber w-2/3" : "bg-error-red w-1/3"}`}
                          ></div>
                        </div>
                      </div>
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

export default DashboardPage;
