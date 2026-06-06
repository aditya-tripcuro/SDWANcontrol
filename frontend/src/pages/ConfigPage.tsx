import React, { useState, useEffect } from "react";
import {
  discoverInterfaces,
  getInterfacesStatus,
  getStatus,
  putConfigInterfaces,
  putWanMode,
} from "../api/client";
import { useTimezone, TIMEZONE_LIST } from "../context/TimezoneContext";

interface IfaceForm {
  name: string;
  label: string;
  gateway: string;
  expected_speed_mbps: number | string;
  routing_table_id: number | string;
}

const EMPTY_FORM: IfaceForm = {
  name: "",
  label: "",
  gateway: "",
  expected_speed_mbps: "",
  routing_table_id: "",
};

const ConfigPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState("general");
  const [interfaces, setInterfaces] = useState<any[]>([]);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<IfaceForm>(EMPTY_FORM);
  const [addingNew, setAddingNew] = useState(false);
  const [newForm, setNewForm] = useState<IfaceForm>(EMPTY_FORM);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [wanMode, setWanMode] = useState<string | null>(null);
  const [modeSaving, setModeSaving] = useState(false);
  const [discovered, setDiscovered] = useState<any[]>([]);
  const [suggestedConfig, setSuggestedConfig] = useState<any[]>([]);
  const [discovering, setDiscovering] = useState(false);

  const { timezone, setTimezone } = useTimezone();

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getInterfacesStatus().catch(() => []),
      getStatus().catch(() => null),
      discoverInterfaces().catch(() => ({ interfaces: [], suggested_config: [] })),
    ]).then(([ifaces, status, discoveredResult]) => {
      setInterfaces(
        ifaces.map((i: any) => ({
          name: i.name,
          label: i.label,
          gateway: i.gateway,
          expected_speed_mbps: i.expected_speed_mbps,
          routing_table_id: i.routing_table_id,
        }))
      );
      if (status?.wan_mode) setWanMode(status.wan_mode);
      setDiscovered(discoveredResult.interfaces || []);
      setSuggestedConfig(discoveredResult.suggested_config || []);
      setLoading(false);
    });
  }, []);

  const refreshDiscovery = async () => {
    setDiscovering(true);
    setSaveError(null);
    try {
      const result = await discoverInterfaces();
      setDiscovered(result.interfaces || []);
      setSuggestedConfig(result.suggested_config || []);
    } catch (e: any) {
      setSaveError(e.message || "Failed to discover interfaces.");
    } finally {
      setDiscovering(false);
    }
  };

  const useSuggestedConfig = () => {
    if (suggestedConfig.length < 2) {
      setSaveError("At least 2 WAN candidates are required for load balancing.");
      return;
    }
    setInterfaces(suggestedConfig);
    setSaveError(null);
    setSaveSuccess("Discovered WAN candidates copied into the editable configuration. Save to apply.");
  };

  const addDiscoveredInterface = (iface: any) => {
    if (interfaces.some((existing) => existing.name === iface.name)) {
      setSaveError(`${iface.name} is already configured.`);
      return;
    }
    const nextTableId = Math.max(99, ...interfaces.map((i) => Number(i.routing_table_id) || 99)) + 1;
    setInterfaces((prev) => [
      ...prev,
      {
        name: iface.name,
        label: iface.label && iface.is_wan_candidate ? iface.label : iface.name,
        gateway: iface.gateway || "",
        expected_speed_mbps: iface.speed_mbps > 0 ? iface.speed_mbps : 100,
        routing_table_id: iface.suggested_routing_table_id || nextTableId,
      },
    ]);
    setSaveError(null);
    setSaveSuccess(`${iface.name} added to the editable configuration. Save to apply.`);
  };

  const saveWanMode = async () => {
    if (wanMode !== "failover" && wanMode !== "load_balance") return;
    setModeSaving(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      const result = await putWanMode(wanMode);
      setWanMode(result.wan_mode);
      setSaveSuccess("WAN mode saved and applied.");
    } catch (e: any) {
      setSaveError(e.message || "Failed to save WAN mode.");
    } finally {
      setModeSaving(false);
    }
  };

  const startEdit = (idx: number) => {
    const iface = interfaces[idx];
    setEditForm({
      name: iface.name,
      label: iface.label,
      gateway: iface.gateway,
      expected_speed_mbps: iface.expected_speed_mbps,
      routing_table_id: iface.routing_table_id,
    });
    setEditingIdx(idx);
    setAddingNew(false);
    setSaveError(null);
    setSaveSuccess(null);
  };

  const cancelEdit = () => {
    setEditingIdx(null);
  };

  const applyEdit = () => {
    if (editingIdx === null) return;
    setInterfaces((prev) =>
      prev.map((iface, i) =>
        i === editingIdx
          ? {
              name: editForm.name.trim(),
              label: editForm.label.trim(),
              gateway: editForm.gateway.trim(),
              expected_speed_mbps: Number(editForm.expected_speed_mbps),
              routing_table_id: Number(editForm.routing_table_id),
            }
          : iface
      )
    );
    setEditingIdx(null);
  };

  const deleteInterface = (idx: number) => {
    setInterfaces((prev) => prev.filter((_, i) => i !== idx));
    if (editingIdx === idx) setEditingIdx(null);
    setSaveError(null);
    setSaveSuccess(null);
  };

  const applyNew = () => {
    setInterfaces((prev) => [
      ...prev,
      {
        name: newForm.name.trim(),
        label: newForm.label.trim(),
        gateway: newForm.gateway.trim(),
        expected_speed_mbps: Number(newForm.expected_speed_mbps),
        routing_table_id: Number(newForm.routing_table_id),
      },
    ]);
    setNewForm(EMPTY_FORM);
    setAddingNew(false);
  };

  const saveAll = async () => {
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      await putConfigInterfaces(interfaces);
      setSaveSuccess("Configuration saved and reloaded successfully.");
      // Refresh from server
      const fresh = await getInterfacesStatus();
      setInterfaces(
        fresh.map((i: any) => ({
          name: i.name,
          label: i.label,
          gateway: i.gateway,
          expected_speed_mbps: i.expected_speed_mbps,
          routing_table_id: i.routing_table_id,
        }))
      );
    } catch (e: any) {
      setSaveError(e.message || "Failed to save configuration.");
    } finally {
      setSaving(false);
    }
  };

  const IfaceFormFields = ({
    form,
    onChange,
  }: {
    form: IfaceForm;
    onChange: (f: IfaceForm) => void;
  }) => (
    <div className="space-y-4 pt-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">
            Interface Name *
          </label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => onChange({ ...form, name: e.target.value })}
            placeholder="e.g. wan0, eth0"
            className="w-full bg-canvas/40 border border-outline-variant/20 rounded-xl px-4 py-2.5 text-xs text-text-strong focus:outline-none focus:border-primary/40 font-mono"
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">
            Display Label *
          </label>
          <input
            type="text"
            value={form.label}
            onChange={(e) => onChange({ ...form, label: e.target.value })}
            placeholder="e.g. Fiber WAN, LTE Backup"
            className="w-full bg-canvas/40 border border-outline-variant/20 rounded-xl px-4 py-2.5 text-xs text-text-strong focus:outline-none focus:border-primary/40"
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">
            Gateway IP *
          </label>
          <input
            type="text"
            value={form.gateway}
            onChange={(e) => onChange({ ...form, gateway: e.target.value })}
            placeholder="e.g. 192.168.1.1"
            className="w-full bg-canvas/40 border border-outline-variant/20 rounded-xl px-4 py-2.5 text-xs text-text-strong focus:outline-none focus:border-primary/40 font-mono"
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">
            Expected Speed (Mbps) *
          </label>
          <input
            type="number"
            min={1}
            value={form.expected_speed_mbps}
            onChange={(e) => onChange({ ...form, expected_speed_mbps: e.target.value })}
            placeholder="e.g. 100"
            className="w-full bg-canvas/40 border border-outline-variant/20 rounded-xl px-4 py-2.5 text-xs text-text-strong focus:outline-none focus:border-primary/40"
          />
        </div>
        <div className="space-y-2">
          <label className="text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">
            Routing Table ID (1–252) *
          </label>
          <input
            type="number"
            min={1}
            max={252}
            value={form.routing_table_id}
            onChange={(e) => onChange({ ...form, routing_table_id: e.target.value })}
            placeholder="e.g. 100"
            className="w-full bg-canvas/40 border border-outline-variant/20 rounded-xl px-4 py-2.5 text-xs text-text-strong focus:outline-none focus:border-primary/40"
          />
        </div>
      </div>
    </div>
  );

  return (
    <div className="max-w-5xl space-y-10 pb-12 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <h1 className="sr-only">Config</h1>
      {/* Tab bar */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 border-b border-outline-variant/10">
        <div className="flex items-center space-x-8">
          {["general", "interfaces", "routing", "monitoring"].map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`pb-5 text-[10px] font-black uppercase tracking-[0.2em] transition-all relative ${
                activeTab === tab ? "text-text-strong" : "text-text-muted hover:text-text-strong"
              }`}
            >
              {tab}
              {activeTab === tab && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary shadow-[0_-4px_8px_rgba(255,255,255,0.2)]"></div>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-8">
        {/* ── General Tab ── */}
        {activeTab === "general" && (
          <div className="space-y-8 animate-in fade-in slide-in-from-left-4 duration-500">
            {/* Timezone */}
            <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 overflow-hidden shadow-sm">
              <div className="px-8 py-5 border-b border-outline-variant/20 bg-surface-bright/5">
                <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Display Settings</h3>
                <p className="text-[10px] text-text-muted mt-1 font-bold">Configure how timestamps are shown in the UI.</p>
              </div>
              <div className="p-8">
                <div className="space-y-2.5 group max-w-sm">
                  <label className="text-[10px] font-black text-text-muted group-focus-within:text-primary uppercase tracking-[0.2em] transition-colors">
                    Display Timezone
                  </label>
                  <select
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    className="w-full bg-canvas/40 border border-outline-variant/20 rounded-xl px-5 py-3 text-xs text-text-strong focus:outline-none focus:border-primary/40 focus:ring-4 focus:ring-primary/5 transition-all font-medium"
                  >
                    {TIMEZONE_LIST.map((tz) => (
                      <option key={tz.value} value={tz.value}>
                        {tz.label}
                      </option>
                    ))}
                  </select>
                  <p className="text-[10px] text-text-muted">
                    All timestamps in the UI will display in <strong className="text-text-strong">{timezone}</strong>.
                    Saved to your browser.
                  </p>
                </div>
              </div>
            </div>

            {/* WAN Mode (read-only) */}
            <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 overflow-hidden shadow-sm">
              <div className="px-8 py-5 border-b border-outline-variant/20 bg-surface-bright/5">
                <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Controller Settings</h3>
                <p className="text-[10px] text-text-muted mt-1 font-bold">Read from config.yaml — edit the file directly to change these.</p>
              </div>
              <div className="p-8">
                <div className="space-y-2.5 max-w-sm">
                  <label className="text-[10px] font-black text-text-muted uppercase tracking-[0.2em]">WAN Mode</label>
                  <select
                    value={wanMode ?? "load_balance"}
                    onChange={(e) => setWanMode(e.target.value)}
                    className="w-full bg-canvas/40 border border-outline-variant/20 rounded-xl px-5 py-3 text-xs text-text-strong focus:outline-none focus:border-primary/40 font-medium"
                  >
                    <option value="load_balance">load_balance</option>
                    <option value="failover">failover</option>
                  </select>
                  <p className="text-[10px] text-text-muted">
                    <code className="font-mono">failover</code> — switches to backup when primary fails. <code className="font-mono">load_balance</code> — distributes across all links.
                  </p>
                  <button
                    onClick={saveWanMode}
                    disabled={modeSaving}
                    className="px-6 py-2.5 bg-primary text-primary-on text-[10px] font-black uppercase tracking-widest rounded-xl hover:scale-105 transition-all shadow-lg disabled:opacity-40"
                  >
                    {modeSaving ? "Saving…" : "Save Mode"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Interfaces Tab ── */}
        {activeTab === "interfaces" && (
          <div className="animate-in fade-in slide-in-from-right-4 duration-500">
            <div className="bg-surface-container-low rounded-2xl border border-outline-variant/20 overflow-hidden shadow-sm">
              <div className="px-8 py-5 border-b border-outline-variant/20 bg-surface-bright/5 flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Interface Management</h3>
                  <p className="text-[10px] text-text-muted mt-1 font-bold">
                    Configure WAN interfaces. At least 2 required. Changes are written to config.yaml and reloaded live.
                  </p>
                </div>
                {loading && (
                  <span className="text-[9px] font-black text-text-muted uppercase tracking-widest animate-pulse">Loading…</span>
                )}
              </div>

              <div className="p-8 space-y-4">
                {/* Notification banners */}
                {saveError && (
                  <div className="p-4 bg-error-red/10 border border-error-red/30 rounded-xl text-xs text-error-red font-bold">
                    {saveError}
                  </div>
                )}
                {saveSuccess && (
                  <div className="p-4 bg-success-green/10 border border-success-green/30 rounded-xl text-xs text-success-green font-bold">
                    {saveSuccess}
                  </div>
                )}

                <div className="p-6 bg-canvas/30 rounded-2xl border border-outline-variant/10 space-y-4">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                      <h4 className="text-xs font-black text-text-strong uppercase tracking-[0.2em]">Available Interfaces</h4>
                      <p className="text-[10px] text-text-muted mt-1 font-bold">
                        Interfaces discovered from the Linux host. WAN candidates have an IP, gateway, link-up state, and probe reachability.
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={refreshDiscovery}
                        disabled={discovering}
                        className="px-5 py-2.5 border border-outline-variant/30 rounded-xl text-[10px] font-black uppercase tracking-widest text-text-strong hover:bg-surface-bright transition-all disabled:opacity-40"
                      >
                        {discovering ? "Scanning…" : "Rescan"}
                      </button>
                      <button
                        onClick={useSuggestedConfig}
                        disabled={suggestedConfig.length < 2}
                        className="px-5 py-2.5 bg-primary text-primary-on rounded-xl text-[10px] font-black uppercase tracking-widest hover:scale-105 transition-all disabled:opacity-40 disabled:hover:scale-100"
                      >
                        Use WAN Candidates
                      </button>
                    </div>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-[10px]">
                      <thead className="text-text-muted uppercase tracking-widest">
                        <tr>
                          <th className="py-3 pr-4">Name</th>
                          <th className="py-3 pr-4">IP</th>
                          <th className="py-3 pr-4">Gateway</th>
                          <th className="py-3 pr-4">Speed</th>
                          <th className="py-3 pr-4">State</th>
                          <th className="py-3 pr-4">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-outline-variant/10">
                        {discovered.length === 0 && (
                          <tr>
                            <td className="py-4 text-text-muted font-bold" colSpan={6}>
                              No interfaces discovered yet.
                            </td>
                          </tr>
                        )}
                        {discovered.map((iface) => (
                          <tr key={iface.name} className="text-text-strong">
                            <td className="py-3 pr-4 font-mono font-black">{iface.name}</td>
                            <td className="py-3 pr-4 font-mono text-text-muted">
                              {iface.ip ? `${iface.ip}/${iface.prefix_len}` : "-"}
                            </td>
                            <td className="py-3 pr-4 font-mono text-text-muted">{iface.gateway || "-"}</td>
                            <td className="py-3 pr-4 text-text-muted">
                              {iface.speed_mbps > 0 ? `${iface.speed_mbps} Mbps` : "unknown"}
                            </td>
                            <td className="py-3 pr-4">
                              <span className={`font-black ${iface.is_wan_candidate ? "text-success-green" : "text-text-muted"}`}>
                                {iface.is_wan_candidate ? "WAN candidate" : iface.skip_reason || "not usable"}
                              </span>
                            </td>
                            <td className="py-3 pr-4">
                              <button
                                onClick={() => addDiscoveredInterface(iface)}
                                className="px-3 py-2 border border-outline-variant/30 rounded-lg text-[9px] font-black uppercase tracking-widest hover:bg-surface-bright transition-all"
                              >
                                Add
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Existing interfaces */}
                {interfaces.map((iface, idx) => (
                  <div
                    key={idx}
                    className="p-6 bg-canvas/30 rounded-2xl border border-outline-variant/10 hover:border-primary/20 transition-all group"
                  >
                    {editingIdx === idx ? (
                      <>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-[10px] font-black text-primary uppercase tracking-widest">
                            Editing Interface {idx + 1}
                          </span>
                          <button
                            onClick={cancelEdit}
                            className="text-[9px] font-black text-text-muted uppercase tracking-widest hover:text-error-red transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                        <IfaceFormFields form={editForm} onChange={setEditForm} />
                        <div className="flex items-center space-x-3 mt-4">
                          <button
                            onClick={applyEdit}
                            className="px-6 py-2.5 bg-primary text-primary-on text-[10px] font-black uppercase tracking-widest rounded-xl hover:scale-105 transition-all shadow-lg"
                          >
                            Apply Changes
                          </button>
                        </div>
                      </>
                    ) : (
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-6">
                          <div className="w-14 h-14 rounded-2xl bg-surface-bright flex items-center justify-center font-black text-sm text-text-strong border border-outline-variant/20 shadow-sm group-hover:bg-primary group-hover:text-primary-on transition-all font-mono">
                            {idx + 1}
                          </div>
                          <div>
                            <h4 className="text-sm font-black text-text-strong">
                              {iface.label}{" "}
                              <span className="font-mono text-text-muted text-xs">({iface.name})</span>
                            </h4>
                            <p className="text-[10px] text-text-muted mt-1 font-bold uppercase tracking-tight">
                              GW: {iface.gateway} · {iface.expected_speed_mbps} Mbps · Table: {iface.routing_table_id}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center space-x-3">
                          <button
                            onClick={() => startEdit(idx)}
                            className="text-[10px] font-black text-text-strong uppercase tracking-widest border border-outline-variant/30 px-5 py-2.5 rounded-xl hover:bg-surface-bright transition-all"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => deleteInterface(idx)}
                            disabled={interfaces.length <= 2}
                            className="text-[10px] font-black uppercase tracking-widest border px-4 py-2.5 rounded-xl transition-all disabled:opacity-30 disabled:cursor-not-allowed border-error-red/30 text-error-red hover:bg-error-red/10"
                            title={interfaces.length <= 2 ? "At least 2 interfaces required" : "Remove interface"}
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}

                {/* Add new interface form */}
                {addingNew ? (
                  <div className="p-6 bg-canvas/30 rounded-2xl border border-primary/20 transition-all">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] font-black text-primary uppercase tracking-widest">
                        New Interface
                      </span>
                      <button
                        onClick={() => { setAddingNew(false); setNewForm(EMPTY_FORM); }}
                        className="text-[9px] font-black text-text-muted uppercase tracking-widest hover:text-error-red transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                    <IfaceFormFields form={newForm} onChange={setNewForm} />
                    <div className="flex items-center space-x-3 mt-4">
                      <button
                        onClick={applyNew}
                        disabled={!newForm.name.trim() || !newForm.label.trim() || !newForm.gateway.trim()}
                        className="px-6 py-2.5 bg-primary text-primary-on text-[10px] font-black uppercase tracking-widest rounded-xl hover:scale-105 transition-all shadow-lg disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        Add Interface
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => { setAddingNew(true); setSaveError(null); setSaveSuccess(null); }}
                    className="w-full py-6 border-2 border-dashed border-outline-variant/20 rounded-2xl text-[10px] font-black text-text-muted uppercase tracking-[0.3em] hover:border-primary/30 hover:text-text-strong transition-all mt-2"
                  >
                    + Add Interface
                  </button>
                )}
              </div>

              {/* Save footer */}
              <div className="px-8 py-5 border-t border-outline-variant/10 flex items-center justify-between bg-surface-bright/5">
                <span className="text-[9px] font-black text-text-muted uppercase tracking-tight">
                  {interfaces.length} interface{interfaces.length !== 1 ? "s" : ""} configured
                </span>
                <button
                  onClick={saveAll}
                  disabled={saving || interfaces.length < 2}
                  className="px-8 py-3 bg-primary text-primary-on text-[10px] font-black uppercase tracking-[0.2em] rounded-xl hover:scale-105 transition-all shadow-xl shadow-white/5 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
                >
                  {saving ? "Saving…" : "Save & Apply"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Routing / Monitoring — config file only ── */}
        {(activeTab === "routing" || activeTab === "monitoring") && (
          <div className="flex flex-col items-center justify-center py-32 text-center space-y-8 animate-in zoom-in-95 duration-500">
            <div className="w-20 h-20 bg-surface-container-low rounded-3xl border border-outline-variant/20 flex items-center justify-center text-text-muted shadow-lg">
              <svg className="w-10 h-10 opacity-20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
              </svg>
            </div>
            <div className="space-y-3">
              <h3 className="text-sm font-black text-text-strong uppercase tracking-[0.3em]">Edit config.yaml</h3>
              <p className="text-xs text-text-muted font-medium max-w-sm mx-auto leading-relaxed">
                {activeTab === "routing" ? "Routing" : "Monitoring"} parameters are configured in{" "}
                <code className="font-mono text-text-strong">/etc/wancontrol/config.yaml</code>. Hot-reload after saving with the button below.
              </p>
            </div>
            <button
              onClick={async () => {
                try {
                  await import("../api/client").then(({ reloadConfig }) => reloadConfig());
                  alert("Configuration reloaded.");
                } catch (e: any) {
                  alert("Reload failed: " + e.message);
                }
              }}
              className="px-8 py-3 bg-surface-bright text-text-strong text-[10px] font-black uppercase tracking-widest rounded-xl border border-outline-variant/30 hover:scale-105 transition-transform"
            >
              Reload Config
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default ConfigPage;
