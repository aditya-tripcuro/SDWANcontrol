import React, { useState, useEffect } from "react";
import { getSwitchEvents, getControllerEvents } from "../api/client";
import { useTimezone } from "../context/TimezoneContext";

const LEVEL_STYLES: Record<string, string> = {
  ERROR:    "bg-error-red/10 text-error-red border-error-red/20",
  WARNING:  "bg-warning-amber/10 text-warning-amber border-warning-amber/20",
  INFO:     "bg-sky-500/10 text-sky-400 border-sky-500/20",
  DEBUG:    "bg-surface-bright/50 text-text-muted border-outline-variant/20",
  CRITICAL: "bg-error-red/20 text-error-red border-error-red/40",
};

const EventsPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<"controller" | "switches">("controller");
  const [filter, setFilter] = useState("ALL");
  const [controllerEvents, setControllerEvents] = useState<any[]>([]);
  const [switchEvents, setSwitchEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const { formatTs } = useTimezone();

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getControllerEvents(200).catch(() => []),
      getSwitchEvents(100).catch(() => []),
    ]).then(([ctrl, sw]) => {
      setControllerEvents(ctrl);
      setSwitchEvents(sw);
      setLoading(false);
    });
  }, []);

  const filteredCtrl = controllerEvents.filter(
    (e) => filter === "ALL" || e.level === filter
  );

  return (
    <div className="space-y-6 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-black text-text-strong tracking-tight uppercase">System Events</h2>
          <p className="text-sm text-text-muted font-medium mt-1">
            Audit logs and WAN switching history
          </p>
        </div>

        {/* Tab toggle */}
        <div className="flex items-center space-x-2 bg-surface-bright/20 p-1 rounded-xl border border-outline-variant/20">
          <button
            onClick={() => setActiveTab("controller")}
            className={`px-5 py-2 text-[10px] font-black uppercase tracking-widest rounded-lg transition-all ${
              activeTab === "controller"
                ? "bg-primary text-primary-on shadow-lg"
                : "text-text-muted hover:text-text-strong"
            }`}
          >
            Controller Logs
          </button>
          <button
            onClick={() => setActiveTab("switches")}
            className={`px-5 py-2 text-[10px] font-black uppercase tracking-widest rounded-lg transition-all ${
              activeTab === "switches"
                ? "bg-primary text-primary-on shadow-lg"
                : "text-text-muted hover:text-text-strong"
            }`}
          >
            WAN Switches
          </button>
        </div>
      </div>

      {/* Level filter — only for controller tab */}
      {activeTab === "controller" && (
        <div className="flex items-center space-x-2 bg-canvas/30 p-1 rounded-xl border border-outline-variant/20 w-fit">
          {["ALL", "INFO", "WARNING", "ERROR", "CRITICAL", "DEBUG"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-4 py-1.5 text-[9px] font-black uppercase tracking-widest rounded-lg transition-all ${
                filter === f
                  ? "bg-surface-bright text-text-strong shadow-sm"
                  : "text-text-muted hover:text-text-strong"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <div className="py-24 text-center text-text-muted text-xs font-black uppercase tracking-widest">
          Loading events…
        </div>
      ) : activeTab === "controller" ? (
        /* Controller Events */
        <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="bg-canvas/20">
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Time</th>
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Level</th>
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Component</th>
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/10 font-mono text-xs">
                {filteredCtrl.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-6 py-16 text-center text-text-muted font-sans font-bold uppercase tracking-widest">
                      No events found
                    </td>
                  </tr>
                ) : (
                  filteredCtrl.map((ev) => (
                    <tr key={ev.id} className="hover:bg-primary/[0.01] transition-colors group">
                      <td className="px-6 py-3 text-text-muted whitespace-nowrap">
                        {formatTs(ev.timestamp, {
                          month: "2-digit",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                          hour12: false,
                        })}
                      </td>
                      <td className="px-6 py-3">
                        <span
                          className={`inline-flex px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-widest border font-sans ${
                            LEVEL_STYLES[ev.level] ?? LEVEL_STYLES.INFO
                          }`}
                        >
                          {ev.level}
                        </span>
                      </td>
                      <td className="px-6 py-3 text-text-muted">{ev.component}</td>
                      <td className="px-6 py-3 text-text-strong">{ev.message}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Switch Events */
        <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="bg-canvas/20">
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Time</th>
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">From</th>
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">To</th>
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Reason</th>
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-right">Score Before</th>
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em] text-right">Score After</th>
                  <th className="px-6 py-4 text-[9px] font-black text-text-muted uppercase tracking-[0.25em]">Triggered By</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/10 text-xs">
                {switchEvents.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-16 text-center text-text-muted font-bold uppercase tracking-widest">
                      No WAN switches recorded yet
                    </td>
                  </tr>
                ) : (
                  switchEvents.map((ev) => (
                    <tr key={ev.id} className="hover:bg-primary/[0.01] transition-colors group">
                      <td className="px-6 py-4 text-text-muted font-mono whitespace-nowrap">
                        {formatTs(ev.timestamp, {
                          month: "2-digit",
                          day: "2-digit",
                          hour: "2-digit",
                          minute: "2-digit",
                          second: "2-digit",
                          hour12: false,
                        })}
                      </td>
                      <td className="px-6 py-4">
                        <span className="px-2 py-1 rounded bg-error-red/10 text-error-red text-[9px] font-black uppercase tracking-widest border border-error-red/20 font-sans">
                          {ev.from_interface}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span className="px-2 py-1 rounded bg-success-green/10 text-success-green text-[9px] font-black uppercase tracking-widest border border-success-green/20 font-sans">
                          {ev.to_interface}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-text-muted">{ev.reason}</td>
                      <td className="px-6 py-4 text-right font-mono font-black text-text-muted">{ev.score_before?.toFixed(1)}</td>
                      <td className="px-6 py-4 text-right font-mono font-black text-text-strong">{ev.score_after?.toFixed(1)}</td>
                      <td className="px-6 py-4 text-text-muted">{ev.triggered_by}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default EventsPage;
