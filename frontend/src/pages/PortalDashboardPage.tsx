import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type DeviceRecord,
  type PortalMe,
  type PortalScanRow,
  type ScanPatchBody,
  type StaffCreateBody,
  type StaffMember,
  type StaffPatchBody,
} from "../api/client";
import PortalOpNotesPanel from "../components/PortalOpNotesPanel";
import PortalUsersPanel from "../components/PortalUsersPanel";
import { fmtCalendarDateMdY, fmtDateTimeEt } from "../dates";

type Tab = "scans" | "staff" | "devices" | "opnotes" | "settings";

const fmt$ = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

/** Physicians first, then other roles; then last / first name. */
function sortStaffMembers(a: StaffMember, b: StaffMember): number {
  const rank = (t: string | null | undefined) => (t?.toLowerCase() === "physician" ? 0 : 1);
  const dr = rank(a.staff_type) - rank(b.staff_type);
  if (dr !== 0) return dr;
  const ln = a.last_name.localeCompare(b.last_name);
  if (ln !== 0) return ln;
  return a.first_name.localeCompare(b.first_name);
}

function Spinner({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card flex-1 min-w-[130px] px-5 py-4">
      <div className="label mb-1.5">{label}</div>
      <div className="text-2xl font-black text-ink tracking-tight">{value}</div>
      {sub && <div className="text-xs text-ink-secondary mt-0.5">{sub}</div>}
    </div>
  );
}

// ── Table shared styles ────────────────────────────────────────────────────────
const TH = "px-3 py-2.5 text-[10px] font-bold uppercase tracking-wide text-ink-secondary whitespace-nowrap border-b-2 border-brand-border bg-surface-soft text-left";
const TD = "px-3 py-2.5 text-sm border-b border-brand-border/60 align-top";

type LineItem = {
  cpt?: string;
  procedure_name?: string;
  provider_name?: string;
  provider_role?: string;
  modifier?: string;
  modifier_code?: string;
  modifier_factor?: number;
  modifier_desc?: string;
  is_assist?: boolean;
  work_rvu?: number;
  pe_rvu?: number;
  mp_rvu?: number;
  total_rvu?: number;
  work_payment?: number;
  pe_payment?: number;
  mp_payment?: number;
  payment?: number;
};

function parseLineItems(scan: PortalScanRow): LineItem[] {
  const raw = (scan.line_items as unknown) ?? scan.cpts ?? [];
  if (Array.isArray(raw)) return raw as LineItem[];
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw) as unknown;
      return Array.isArray(parsed) ? (parsed as LineItem[]) : [];
    } catch {
      return [];
    }
  }
  return [];
}

function financialBreakdown(scan: PortalScanRow) {
  const items = parseLineItems(scan);
  const surgeonItems = items.filter((li) => !li.is_assist && !/\bAS\b/i.test(li.modifier ?? ""));
  const workRvu = surgeonItems.reduce((a, li) => a + Number(li.work_rvu ?? 0), 0);
  const cf = Number(scan.cf ?? 32.3465);
  // Use stored work_payment if available (post-modifier, post-GPCI); fallback to wRVU×CF for old records
  const hasWorkPayment = surgeonItems.some((li) => li.work_payment != null);
  const surgeonValue = hasWorkPayment
    ? surgeonItems.reduce((a, li) => a + Number(li.work_payment ?? 0), 0)
    : workRvu * cf;
  const totalPayment = Number(scan.total_payment ?? 0);
  const facilityShare = totalPayment - surgeonValue;
  const assistCount = items.filter((li) => Boolean(li.is_assist) || /\bAS\b/i.test(li.modifier ?? "")).length;
  return {
    items,
    workRvu,
    surgeonValue,
    facilityShare,
    totalPayment,
    assistCount,
  };
}

// ── Inline edit row ────────────────────────────────────────────────────────────
interface EditRowProps {
  scan: PortalScanRow;
  draft: ScanPatchBody;
  setDraft: (d: ScanPatchBody) => void;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
  colCount: number;
}

function EditRow({ scan, draft, setDraft, saving, onSave, onCancel, colCount }: EditRowProps) {
  const rawCpts = (() => {
    try { return (JSON.parse(scan.cpts as string ?? "[]") as string[]).join(", "); }
    catch { return ""; }
  })();
  const [cptsText, setCptsText] = useState(draft.cpts ? draft.cpts.join(", ") : rawCpts);

  return (
    <tr className="bg-brand-muted/60">
      <td colSpan={colCount} className="px-4 py-3">
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex-1 min-w-[110px]">
            <label className="label">DOS</label>
            <input type="date" className="input text-xs"
              value={draft.service_date ?? scan.service_date ?? ""}
              onChange={(e) => setDraft({ ...draft, service_date: e.target.value || null })}
            />
          </div>
          <div className="flex-1 min-w-[100px]">
            <label className="label">MRN</label>
            <input type="text" className="input text-xs" placeholder="—"
              value={draft.mrn ?? scan.mrn ?? ""}
              onChange={(e) => setDraft({ ...draft, mrn: e.target.value || null })}
            />
          </div>
          <div className="flex-none">
            <label className="label">Setting</label>
            <select className="input text-xs w-auto"
              value={draft.facility !== undefined ? String(draft.facility) : String(scan.facility ?? false)}
              onChange={(e) => setDraft({ ...draft, facility: e.target.value === "true" })}
            >
              <option value="false">Non-Facility</option>
              <option value="true">Facility</option>
            </select>
          </div>
          <div className="flex-[2_1_200px] min-w-[160px]">
            <label className="label">CPTs (comma-separated)</label>
            <input type="text" className="input text-xs" placeholder="e.g. 27447, 00400"
              value={cptsText}
              onChange={(e) => {
                setCptsText(e.target.value);
                const codes = e.target.value.split(",").map((c) => c.trim()).filter(Boolean);
                setDraft({ ...draft, cpts: codes.length ? codes : undefined });
              }}
            />
          </div>
          <div className="flex gap-2 items-center pb-0.5">
            <button onClick={onSave} disabled={saving} className="btn-primary text-xs px-4 py-2">
              {saving ? <><Spinner className="w-3 h-3" /> Saving…</> : "Save"}
            </button>
            <button onClick={onCancel} disabled={saving} className="btn-secondary text-xs px-3 py-2">Cancel</button>
          </div>
        </div>
      </td>
    </tr>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function PortalDashboardPage() {
  const nav = useNavigate();
  const [admin, setAdmin] = useState<PortalMe | null>(null);
  const [scans, setScans] = useState<PortalScanRow[]>([]);
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [tab, setTab] = useState<Tab>("scans");

  const [filterSurgeon, setFilterSurgeon] = useState("all");
  const [filterFrom, setFilterFrom] = useState("");
  const [filterTo, setFilterTo] = useState("");
  const [filterFacility, setFilterFacility] = useState("all");

  const [imageModal, setImageModal] = useState<number | null>(null);
  const [detailScan, setDetailScan] = useState<PortalScanRow | null>(null);
  const [togglingDevice, setTogglingDevice] = useState<number | null>(null);

  const [editId, setEditId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<ScanPatchBody>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const [sending, setSending] = useState<number | null>(null);
  const [sendErr, setSendErr] = useState<Record<number, string>>({});
  type QrResult = { surgeon: string; email: string | null; magic_url: string; qr_b64: string; emailed: boolean };
  const [qrModal, setQrModal] = useState<QrResult | null>(null);
  const [copied, setCopied] = useState(false);

  const [staffEditId, setStaffEditId] = useState<number | null>(null);
  const [staffDraft, setStaffDraft] = useState<StaffPatchBody>({});
  const [staffSaving, setStaffSaving] = useState(false);
  const [staffErr, setStaffErr] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [addDraft, setAddDraft] = useState<StaffCreateBody>({ first_name: "", last_name: "" });
  const [addErr, setAddErr] = useState<string | null>(null);
  const [addSaving, setAddSaving] = useState(false);
  const [devCfg, setDevCfg] = useState<{ provider: string; vision_model: string; text_model: string; openai_key_set?: string; anthropic_key_set?: string } | null>(null);
  const [devProvider, setDevProvider] = useState("ollama");
  const [devModel, setDevModel] = useState("");
  const [devOpenAiKey, setDevOpenAiKey] = useState("");
  const [devAnthropicKey, setDevAnthropicKey] = useState("");
  const [devSaving, setDevSaving] = useState(false);
  const [devErr, setDevErr] = useState<string | null>(null);
  const defaultModelForProvider = (p: string) =>
    p === "openai" ? "gpt-4o-mini" : p === "anthropic" ? "claude-3-5-sonnet-latest" : p === "paddle" ? "paddleocr" : "qwen2.5vl:7b";

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.mePortal(), api.portalScans(), api.adminStaff(), api.listDevices()])
      .then(([a, s, st, dv]) => {
        if (cancelled) return;
        setAdmin(a);
        setScans(s.scans);
        setStaff(st.staff.slice().sort(sortStaffMembers));
        setDevices(dv.devices);
      })
      .catch(() => { if (!cancelled) nav("/portal/login"); });
    return () => { cancelled = true; };
  }, [nav]);

  useEffect(() => {
    if (!admin || admin.role !== "superadmin") return;
    api.getDevVisionConfig()
      .then((cfg) => {
        setDevCfg(cfg);
        setDevProvider(cfg.provider);
        setDevModel(cfg.vision_model);
      })
      .catch(() => {});
  }, [admin]);

  const logout = async () => {
    await api.portalLogout();
    nav("/portal/login");
  };

  const startEdit = (s: PortalScanRow) => { setDeleteConfirmId(null); setEditId(s.id); setEditDraft({}); };
  const cancelEdit = () => { setEditId(null); setEditDraft({}); };

  const saveEdit = async (id: number) => {
    if (!Object.keys(editDraft).length) { cancelEdit(); return; }
    setSavingId(id);
    try {
      const updated = await api.patchScan(id, editDraft);
      setScans((prev) => prev.map((s) => (s.id === id ? { ...s, ...updated } : s)));
      setEditId(null); setEditDraft({});
    } catch (e: unknown) {
      alert("Save failed: " + (e instanceof Error ? e.message : "unknown error"));
    } finally { setSavingId(null); }
  };

  const doDelete = async (id: number) => {
    setDeletingId(id);
    try {
      await api.deleteScan(id);
      setScans((prev) => prev.filter((s) => s.id !== id));
      setDeleteConfirmId(null);
    } catch (e: unknown) {
      alert("Delete failed: " + (e instanceof Error ? e.message : "unknown error"));
    } finally { setDeletingId(null); }
  };

  const filtered = useMemo(() => scans.filter((s) => {
    if (filterSurgeon !== "all" && String(s.surgeon_id) !== filterSurgeon) return false;
    const dateKey = s.service_date ?? s.scanned_at?.slice(0, 10) ?? "";
    if (filterFrom && dateKey < filterFrom) return false;
    if (filterTo   && dateKey > filterTo)   return false;
    if (filterFacility === "fac"    && !s.facility) return false;
    if (filterFacility === "nonfac" &&  s.facility) return false;
    return true;
  }), [scans, filterSurgeon, filterFrom, filterTo, filterFacility]);

  const totalRvu = filtered.reduce((a, s) => a + (s.total_rvu ?? 0), 0);
  const totalPay = filtered.reduce((a, s) => a + (s.total_payment ?? 0), 0);
  const totalWorkRvu = filtered.reduce((a, s) => a + financialBreakdown(s).workRvu, 0);
  const totalSurgeonValue = filtered.reduce((a, s) => a + financialBreakdown(s).surgeonValue, 0);
  const totalFacilityValue = filtered.reduce((a, s) => a + financialBreakdown(s).facilityShare, 0);
  const uniqueStaff = new Set(filtered.map((s) => s.surgeon_id)).size;

  const downloadScanReport = () => {
    const head = ["Scanned", "DOS", "Staff", "Role", "Setting", "CPT Count", "Total RVU", "wRVU", "Value$", "Facility$", "Total Payment", "AS Assist Lines"];
    const rows = filtered.map((s) => {
      const fin = financialBreakdown(s);
      const cptCount = (() => {
        return fin.items.length;
      })();
      return [
        fmtDateTimeEt(s.scanned_at),
        fmtCalendarDateMdY(s.service_date),
        s.surgeon_name ?? "",
        s.staff_type ?? "",
        s.facility ? "Facility" : "Non-Facility",
        String(cptCount),
        (s.total_rvu ?? 0).toFixed(2),
        fin.workRvu.toFixed(2),
        fin.surgeonValue.toFixed(2),
        fin.facilityShare.toFixed(2),
        fin.totalPayment.toFixed(2),
        String(fin.assistCount),
      ];
    });
    const csv = [head, ...rows]
      .map((r) =>
        r
          .map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`)
          .join(",")
      )
      .join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const from = filterFrom || "start";
    const to = filterTo || "today";
    a.href = url;
    a.download = `rvu-scan-report-${from}-to-${to}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const uniqueSurgeons = useMemo(() => {
    const seen = new Map<number, string>();
    scans.forEach((s) => { if (s.surgeon_id) seen.set(s.surgeon_id, s.surgeon_name ?? String(s.surgeon_id)); });
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [scans]);

  const sendLink = async (id: number) => {
    setSending(id);
    setSendErr((p) => { const n = { ...p }; delete n[id]; return n; });
    try {
      const r = await api.sendMagicLink(id);
      setQrModal(r); setCopied(false);
    } catch (e: unknown) {
      setSendErr((p) => ({ ...p, [id]: e instanceof Error ? e.message : "Failed" }));
    } finally { setSending(null); }
  };

  const copyLink = () => {
    if (!qrModal) return;
    void navigator.clipboard.writeText(qrModal.magic_url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  };

  const startStaffEdit = (s: StaffMember) => {
    setShowAddForm(false); setStaffEditId(s.id);
    setStaffDraft({ first_name: s.first_name, last_name: s.last_name, suffix: s.suffix ?? "", staff_type: s.staff_type ?? "physician", email: s.email ?? "", is_active: s.is_active });
    setStaffErr(null);
  };

  const saveStaffEdit = async () => {
    if (staffEditId === null) return;
    setStaffSaving(true); setStaffErr(null);
    try {
      const updated = await api.patchStaff(staffEditId, staffDraft);
      setStaff((prev) =>
        prev.map((s) => (s.id === staffEditId ? { ...s, ...updated } : s)).sort(sortStaffMembers)
      );
      setStaffEditId(null);
    } catch (e: unknown) {
      setStaffErr(e instanceof Error ? e.message : "Save failed");
    } finally { setStaffSaving(false); }
  };

  const submitAddStaff = async () => {
    if (!addDraft.first_name.trim() || !addDraft.last_name.trim()) { setAddErr("First and last name are required."); return; }
    setAddSaving(true); setAddErr(null);
    try {
      const created = await api.createStaff(addDraft);
      setStaff((prev) => [...prev, created].sort(sortStaffMembers));
      setShowAddForm(false); setAddDraft({ first_name: "", last_name: "" });
    } catch (e: unknown) {
      setAddErr(e instanceof Error ? e.message : "Failed to add staff");
    } finally { setAddSaving(false); }
  };

  const toggleDevice = async (id: number, active: boolean) => {
    setTogglingDevice(id);
    try {
      const updated = await api.patchDevice(id, { is_active: active });
      setDevices((prev) => prev.map((d) => d.id === id ? { ...d, ...updated } : d));
    } catch { /* ignore */ } finally { setTogglingDevice(null); }
  };

  if (!admin) return null;

  const COL_COUNT = 12;

  const navItems: { id: Tab; label: string }[] = [
    { id: "scans", label: "Scans" },
    { id: "staff", label: "Staff" },
    { id: "devices", label: "Devices" },
    { id: "opnotes", label: "OP notes" },
    { id: "settings", label: "Settings" },
  ];

  return (
    <div className="min-h-dvh bg-surface-soft font-sans flex flex-col">

      {/* ── Header ── */}
      <header className="bg-ink sticky top-0 z-20 flex items-center gap-4 h-14 px-4 sm:px-6 shrink-0">
        <div className="w-7 h-7 bg-brand-gradient rounded-lg flex items-center justify-center flex-shrink-0">
          <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
        </div>
        <span className="font-bold text-white text-base flex-1 truncate">RVU Insight Portal</span>
        <span className="text-white/50 text-sm hidden sm:block truncate max-w-[140px]">{admin.username}</span>
        <button
          onClick={() => void logout()}
          className="text-white/60 hover:text-white text-xs font-semibold border border-white/10 rounded-lg px-3 py-1.5 transition-colors hover:border-white/30 shrink-0"
        >Log out</button>
      </header>

      <div className="flex flex-1 min-h-0 flex-col sm:flex-row">
        {/* ── Sidebar (desktop) ── */}
        <aside className="w-52 shrink-0 border-r border-brand-border bg-surface overflow-y-auto hidden sm:block">
          <nav className="p-3 space-y-0.5">
            {navItems.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`w-full text-left px-3 py-2.5 rounded-xl text-sm font-semibold transition-colors ${
                  tab === id ? "bg-brand-muted text-ink shadow-card" : "text-ink-secondary hover:bg-surface-soft"
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
        </aside>

        <div className="flex flex-col flex-1 min-w-0 min-h-0">
          {/* Mobile nav */}
          <div className="sm:hidden border-b border-brand-border bg-surface px-2 py-2 overflow-x-auto flex gap-1 shrink-0">
            {navItems.map(({ id, label }) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`whitespace-nowrap px-3 py-2 rounded-lg text-xs font-semibold shrink-0 ${
                  tab === id ? "bg-brand-muted text-ink" : "text-ink-secondary bg-surface-soft"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <main className="flex-1 overflow-y-auto min-w-0 max-w-screen-xl mx-auto w-full px-4 py-6">

        {/* ── Stat cards (scans only) ── */}
        {tab === "scans" && (
        <div className="flex flex-wrap gap-3 mb-6">
          <StatCard label="Scans shown" value={String(filtered.length)} sub={`of ${scans.length} total`} />
          <StatCard label="Total RVU" value={totalRvu.toFixed(2)} />
          <StatCard label="wRVU (doctor)" value={totalWorkRvu.toFixed(2)} />
          <StatCard label="Value$ (doctor)" value={fmt$(totalSurgeonValue)} />
          <StatCard label="Facility share" value={fmt$(totalFacilityValue)} />
          <StatCard label="Total payment" value={fmt$(totalPay)} />
          <StatCard label="Staff" value={String(uniqueStaff)} sub="with scans shown" />
        </div>
        )}

        {/* ══════════════ SCANS TAB ══════════════ */}
        {tab === "scans" && (
          <>
            {/* Filters */}
            <div className="card px-4 py-3.5 mb-4 flex flex-wrap gap-4 items-end">
              {[
                { label: "Staff", content: (
                  <select className="input text-xs w-auto" value={filterSurgeon} onChange={(e) => setFilterSurgeon(e.target.value)}>
                    <option value="all">All staff</option>
                    {uniqueSurgeons.map(([id, name]) => <option key={id} value={String(id)}>{name}</option>)}
                  </select>
                )},
                { label: "From", content: <input type="date" className="input text-xs w-auto" value={filterFrom} onChange={(e) => setFilterFrom(e.target.value)} /> },
                { label: "To",   content: <input type="date" className="input text-xs w-auto" value={filterTo}   onChange={(e) => setFilterTo(e.target.value)} /> },
                { label: "Setting", content: (
                  <select className="input text-xs w-auto" value={filterFacility} onChange={(e) => setFilterFacility(e.target.value)}>
                    <option value="all">All</option>
                    <option value="nonfac">Non-Facility</option>
                    <option value="fac">Facility</option>
                  </select>
                )},
              ].map(({ label, content }) => (
                <div key={label}>
                  <label className="label">{label}</label>
                  {content}
                </div>
              ))}
              {(filterSurgeon !== "all" || filterFrom || filterTo || filterFacility !== "all") && (
                <button
                  onClick={() => { setFilterSurgeon("all"); setFilterFrom(""); setFilterTo(""); setFilterFacility("all"); }}
                  className="btn-secondary text-xs px-3 py-2"
                >Clear filters</button>
              )}
              <button onClick={downloadScanReport} className="btn-primary text-xs px-3 py-2">Export report</button>
            </div>

            {/* Scans table */}
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full border-collapse" style={{ minWidth: 1040 }}>
                  <thead>
                    <tr>
                      {["", "Scanned", "DOS", "MRN", "Staff", "Type", "Setting", "CPTs", "Total RVU", "Facility$", "Payment", ""].map((h, i) => (
                        <th key={i} className={`${TH} ${i >= 8 && i < 11 ? "text-right" : "text-left"}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={COL_COUNT} className="px-4 py-10 text-center text-ink-secondary text-sm">
                          No scans match the current filters.
                        </td>
                      </tr>
                    )}
                    {filtered.map((s) => {
                      const fin = financialBreakdown(s);
                      const cptCount = fin.items.length;
                      const isEditing = editId === s.id;
                      const isDeleteConfirm = deleteConfirmId === s.id;
                      const isDeleting = deletingId === s.id;

                      return [
                        <tr
                          key={`row-${s.id}`}
                          className={`transition-colors ${isEditing ? "bg-brand-muted/60" : isDeleteConfirm ? "bg-red-50" : "hover:bg-surface-soft"}`}
                        >
                          {/* Thumbnail */}
                          <td className="px-2 py-2 w-11">
                            {s.has_image ? (
                              <img
                                src={`/api/v1/portal/rvu/scans/${s.id}/image`}
                                alt="scan"
                                onClick={() => setImageModal(s.id)}
                                className="w-9 h-9 object-cover rounded-lg cursor-zoom-in border border-brand-border"
                              />
                            ) : (
                              <div className="w-9 h-9 rounded-lg bg-surface-soft border border-brand-border flex items-center justify-center">
                                <svg className="w-4 h-4 text-brand-border" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                                  <path strokeLinecap="round" strokeLinejoin="round"
                                    d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                                </svg>
                              </div>
                            )}
                          </td>
                          <td className={TD}><span className="text-xs text-ink-secondary">{fmtDateTimeEt(s.scanned_at)}</span></td>
                          <td className={TD}><span className="text-xs">{fmtCalendarDateMdY(s.service_date)}</span></td>
                          <td className={`${TD} font-mono text-xs`}>{s.mrn || "—"}</td>
                          <td className={`${TD} font-semibold text-sm`}>{s.surgeon_name || "—"}</td>
                          <td className={TD}>
                            {s.staff_type ? <span className="badge bg-indigo-50 text-indigo-600 border border-indigo-200">{s.staff_type}</span> : "—"}
                          </td>
                          <td className={TD}>
                            {s.facility
                              ? <span className="badge-blue">Facility</span>
                              : <span className="badge-green">Non-Fac</span>}
                          </td>
                          <td className={`${TD} text-xs text-ink-secondary`}>{cptCount}</td>
                          <td className={`${TD} text-right font-mono tabular-nums text-sm`}>{(s.total_rvu ?? 0).toFixed(2)}</td>
                          <td className={`${TD} text-right font-mono tabular-nums text-sm`}>{fmt$(fin.facilityShare)}</td>
                          <td className={`${TD} text-right font-bold text-green-700 font-mono tabular-nums text-sm`}>{fmt$(s.total_payment ?? 0)}</td>
                          {/* Actions */}
                          <td className={`${TD} text-right whitespace-nowrap`}>
                            {isEditing ? null : isDeleteConfirm ? (
                              <span className="inline-flex items-center gap-2">
                                <span className="text-xs font-bold text-red-600">Delete?</span>
                                <button
                                  onClick={() => void doDelete(s.id)}
                                  disabled={isDeleting}
                                  className="btn-danger text-xs px-3 py-1.5"
                                >{isDeleting ? <Spinner className="w-3 h-3" /> : "Yes"}</button>
                                <button
                                  onClick={() => setDeleteConfirmId(null)}
                                  className="btn-secondary text-xs px-2 py-1.5"
                                >No</button>
                              </span>
                            ) : (
                              <span className="inline-flex gap-2">
                                <button onClick={() => setDetailScan(s)} className="text-ink text-xs font-semibold border border-brand-border rounded-lg px-2.5 py-1 hover:bg-surface-soft transition-colors">
                                  Details
                                </button>
                                <button onClick={() => startEdit(s)} className="text-indigo-600 text-xs font-semibold border border-indigo-200 rounded-lg px-2.5 py-1 hover:bg-indigo-50 transition-colors">
                                  Edit
                                </button>
                                <button onClick={() => { cancelEdit(); setDeleteConfirmId(s.id); }} className="text-red-600 text-xs font-semibold border border-red-200 rounded-lg px-2.5 py-1 hover:bg-red-50 transition-colors">
                                  Del
                                </button>
                              </span>
                            )}
                          </td>
                        </tr>,

                        isEditing && (
                          <EditRow
                            key={`edit-${s.id}`}
                            scan={s}
                            draft={editDraft}
                            setDraft={setEditDraft}
                            saving={savingId === s.id}
                            onSave={() => void saveEdit(s.id)}
                            onCancel={cancelEdit}
                            colCount={COL_COUNT}
                          />
                        ),
                      ];
                    })}
                  </tbody>
                  {filtered.length > 0 && (
                    <tfoot>
                      <tr className="bg-surface-soft">
                        <td colSpan={8} className="px-3 py-3 font-bold text-xs text-ink-secondary border-t-2 border-ink">
                          Totals ({filtered.length} scan{filtered.length !== 1 ? "s" : ""})
                        </td>
                        <td className="px-3 py-3 text-right font-black font-mono tabular-nums text-sm border-t-2 border-ink">{totalRvu.toFixed(2)}</td>
                        <td className="px-3 py-3 text-right font-black text-ink font-mono tabular-nums text-sm border-t-2 border-ink">{fmt$(totalFacilityValue)}</td>
                        <td className="px-3 py-3 text-right font-black text-green-700 font-mono tabular-nums text-sm border-t-2 border-ink">{fmt$(totalPay)}</td>
                        <td className="border-t-2 border-ink" />
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            </div>
          </>
        )}

        {/* ══════════════ STAFF TAB ══════════════ */}
        {tab === "staff" && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <p className="text-sm text-ink-secondary">Manage staff — edit names, emails, and roles, or add new members.</p>
              <button
                onClick={() => { setShowAddForm((v) => !v); setStaffEditId(null); setAddErr(null); }}
                className={showAddForm ? "btn-secondary" : "btn-primary"}
              >
                {showAddForm ? "Cancel" : "+ Add Staff"}
              </button>
            </div>

            {/* Add form */}
            {showAddForm && (
              <div className="card border-2 border-brand-blue/30 p-5 mb-4">
                <p className="label text-brand-blue mb-4">New Staff Member</p>
                <div className="grid grid-cols-2 gap-3 mb-3">
                  {[
                    { label: "First Name *", key: "first_name" as const, placeholder: "John" },
                    { label: "Last Name *",  key: "last_name"  as const, placeholder: "Smith" },
                    { label: "Suffix",       key: "suffix"     as const, placeholder: "MD, DO, PA-C…" },
                    { label: "Email",        key: "email"      as const, placeholder: "jsmith@example.com", type: "email" },
                  ].map(({ label, key, placeholder, type }) => (
                    <div key={key}>
                      <label className="label">{label}</label>
                      <input
                        type={type ?? "text"}
                        placeholder={placeholder}
                        value={(addDraft[key] as string) ?? ""}
                        onChange={(e) => setAddDraft((d) => ({ ...d, [key]: e.target.value }))}
                        className="input text-sm"
                      />
                    </div>
                  ))}
                </div>
                <div className="mb-4">
                  <label className="label">Role</label>
                  <select className="input text-sm w-auto"
                    value={addDraft.staff_type ?? "physician"}
                    onChange={(e) => setAddDraft((d) => ({ ...d, staff_type: e.target.value }))}
                  >
                    <option value="physician">Physician</option>
                    <option value="staff">Staff (PA/NP/etc.)</option>
                  </select>
                </div>
                {addErr && <p className="text-red-600 text-xs mb-3">{addErr}</p>}
                <button onClick={() => void submitAddStaff()} disabled={addSaving} className="btn-primary">
                  {addSaving ? <><Spinner /> Adding…</> : "Add Staff Member"}
                </button>
              </div>
            )}

            {/* Staff table */}
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full border-collapse" style={{ minWidth: 620 }}>
                  <thead>
                    <tr>
                      {["Name", "Role", "Email", "Status", "Actions"].map((h, i) => (
                        <th key={h} className={`${TH} ${i === 4 ? "text-right" : "text-left"}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {staff.length === 0 && (
                      <tr><td colSpan={5} className="px-4 py-10 text-center text-ink-secondary text-sm">No staff found.</td></tr>
                    )}
                    {staff.map((s) => {
                      const isEditing = staffEditId === s.id;
                      return [
                        <tr key={`staff-${s.id}`} className={`transition-colors ${isEditing ? "bg-brand-muted/60" : "hover:bg-surface-soft"}`}>
                          <td className={`${TD} font-semibold`}>
                            {s.full_name}
                            {s.suffix && <span className="text-xs text-ink-secondary ml-2">{s.suffix}</span>}
                          </td>
                          <td className={TD}>
                            {s.staff_type
                              ? <span className="badge bg-indigo-50 text-indigo-600 border border-indigo-200">{s.staff_type}</span>
                              : <span className="text-ink-secondary">—</span>}
                          </td>
                          <td className={`${TD} text-xs`}>
                            {s.email
                              ? <a href={`mailto:${s.email}`} className="text-brand-blue hover:underline">{s.email}</a>
                              : <span className="badge-yellow">⚠ No email</span>}
                          </td>
                          <td className={TD}>
                            {s.is_active ? <span className="badge-green">Active</span> : <span className="badge-gray">Inactive</span>}
                          </td>
                          <td className={`${TD} text-right`}>
                            <span className="inline-flex gap-2">
                              <button
                                onClick={() => isEditing ? setStaffEditId(null) : startStaffEdit(s)}
                                className={`text-xs font-semibold border rounded-lg px-2.5 py-1 transition-colors ${isEditing ? "bg-indigo-600 text-white border-indigo-600" : "text-indigo-600 border-indigo-200 hover:bg-indigo-50"}`}
                              >{isEditing ? "Cancel" : "Edit"}</button>
                              {sendErr[s.id] && <span className="text-xs text-red-600">{sendErr[s.id]}</span>}
                              <button
                                disabled={sending === s.id}
                                onClick={() => void sendLink(s.id)}
                                className="btn-primary text-xs px-2.5 py-1"
                              >
                                {sending === s.id ? <Spinner className="w-3 h-3" /> : (s.email ? "Email + QR" : "QR Link")}
                              </button>
                            </span>
                          </td>
                        </tr>,

                        isEditing && (
                          <tr key={`staff-edit-${s.id}`} className="bg-brand-muted/60">
                            <td colSpan={5} className="px-4 py-3">
                              <div className="flex flex-wrap gap-3 items-end">
                                {[
                                  { label: "First Name", key: "first_name" as const },
                                  { label: "Last Name",  key: "last_name"  as const },
                                  { label: "Suffix",     key: "suffix"     as const, placeholder: "MD, PA-C…" },
                                  { label: "Email",      key: "email"      as const, type: "email" },
                                ].map(({ label, key, placeholder, type }) => (
                                  <div key={key} className="flex-1 min-w-[110px]">
                                    <label className="label">{label}</label>
                                    <input
                                      type={type ?? "text"}
                                      placeholder={placeholder}
                                      value={(staffDraft[key] as string) ?? ""}
                                      onChange={(e) => setStaffDraft((d) => ({ ...d, [key]: e.target.value }))}
                                      className="input text-xs"
                                    />
                                  </div>
                                ))}
                                <div className="flex-none">
                                  <label className="label">Role</label>
                                  <select className="input text-xs w-auto"
                                    value={staffDraft.staff_type ?? "physician"}
                                    onChange={(e) => setStaffDraft((d) => ({ ...d, staff_type: e.target.value }))}
                                  >
                                    <option value="physician">Physician</option>
                                    <option value="staff">Staff (PA/NP/etc.)</option>
                                  </select>
                                </div>
                                <div className="flex-none">
                                  <label className="label">Status</label>
                                  <select className="input text-xs w-auto"
                                    value={staffDraft.is_active ? "active" : "inactive"}
                                    onChange={(e) => setStaffDraft((d) => ({ ...d, is_active: e.target.value === "active" }))}
                                  >
                                    <option value="active">Active</option>
                                    <option value="inactive">Inactive</option>
                                  </select>
                                </div>
                                <div className="flex gap-2 items-end pb-0.5">
                                  <button onClick={() => void saveStaffEdit()} disabled={staffSaving} className="btn-primary text-xs px-4 py-2">
                                    {staffSaving ? <><Spinner className="w-3 h-3" /> Saving…</> : "Save"}
                                  </button>
                                </div>
                              </div>
                              {staffErr && <p className="text-red-600 text-xs mt-2">{staffErr}</p>}
                            </td>
                          </tr>
                        ),
                      ];
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ══════════════ DEVICES TAB ══════════════ */}
        {tab === "opnotes" && <PortalOpNotesPanel />}

        {tab === "settings" && (
          <div>
            <h2 className="text-lg font-bold text-ink mb-1">Settings</h2>
            <p className="text-sm text-ink-secondary mb-6">Portal accounts for office staff (username and password).</p>
            <PortalUsersPanel admin={admin} />
            {admin.role === "superadmin" && (
              <div className="card mt-6 p-5 border-2 border-brand-blue/25">
                <p className="label text-brand-blue mb-2">Developer AI engine (you only)</p>
                <p className="text-xs text-ink-secondary mb-4">
                  Switch scanner vision provider for testing. Hidden from non-developer admins.
                </p>
                <div className="flex flex-wrap gap-3 items-end">
                  <div>
                    <label className="label">Provider</label>
                    <select
                      className="input text-sm w-auto"
                      value={devProvider}
                      onChange={(e) => {
                        const p = e.target.value;
                        setDevProvider(p);
                        setDevModel(defaultModelForProvider(p));
                      }}
                    >
                      <option value="ollama">Ollama (local)</option>
                      <option value="paddle">PaddleOCR (local GPU)</option>
                      <option value="openai">OpenAI</option>
                      <option value="anthropic">Claude (Anthropic)</option>
                    </select>
                  </div>
                  <div className="min-w-[260px] flex-1">
                    <label className="label">Vision model</label>
                    <input className="input text-sm" value={devModel} onChange={(e) => setDevModel(e.target.value)} placeholder="e.g. gpt-4o-mini or qwen2.5vl:7b" />
                  </div>
                  <div className="min-w-[260px] flex-1">
                    <label className="label">OpenAI API key (optional)</label>
                    <input className="input text-sm" type="password" value={devOpenAiKey} onChange={(e) => setDevOpenAiKey(e.target.value)} placeholder="Paste only if updating" />
                  </div>
                  <div className="min-w-[260px] flex-1">
                    <label className="label">Anthropic API key (optional)</label>
                    <input className="input text-sm" type="password" value={devAnthropicKey} onChange={(e) => setDevAnthropicKey(e.target.value)} placeholder="Paste only if updating" />
                  </div>
                  <button
                    className="btn-primary"
                    disabled={devSaving}
                    onClick={() => {
                      if (!devModel || devModel.includes("@") || /\s/.test(devModel)) {
                        setDevErr("Vision model is invalid (do not use email/spaces).");
                        return;
                      }
                      setDevSaving(true);
                      setDevErr(null);
                      void api.patchDevVisionConfig({
                        provider: devProvider,
                        vision_model: devModel,
                        openai_api_key: devOpenAiKey || undefined,
                        anthropic_api_key: devAnthropicKey || undefined,
                      })
                        .then((cfg) => {
                          setDevCfg(cfg);
                          setDevOpenAiKey("");
                          setDevAnthropicKey("");
                        })
                        .catch((e: unknown) => setDevErr(e instanceof Error ? e.message : "Failed"))
                        .finally(() => setDevSaving(false));
                    }}
                  >
                    {devSaving ? "Saving..." : "Save engine"}
                  </button>
                </div>
                {devCfg && (
                  <p className="text-xs text-ink-secondary mt-3">
                    Active now: <span className="font-semibold text-ink">{devCfg.provider}</span> · <span className="font-mono">{devCfg.vision_model}</span>
                  </p>
                )}
                {devCfg && (
                  <p className="text-xs text-ink-secondary">
                    Keys: OpenAI {devCfg.openai_key_set === "yes" ? "set" : "not set"} · Claude {devCfg.anthropic_key_set === "yes" ? "set" : "not set"}
                  </p>
                )}
                {devErr && <p className="text-xs text-red-600 mt-2">{devErr}</p>}
              </div>
            )}
          </div>
        )}

        {tab === "devices" && (
          <div>
            <p className="text-sm text-ink-secondary mb-4">
              <strong className="text-ink">One row per staff member</strong> — the most recently used phone or browser.{" "}
              <strong className="text-ink">Deactivate</strong> revokes access until they use a new registration link.
            </p>
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full border-collapse" style={{ minWidth: 580 }}>
                  <thead>
                    <tr>
                      {["Staff", "Device", "Registered", "Last Seen", "Status", ""].map((h, i) => (
                        <th key={i} className={`${TH} ${i === 5 ? "text-right" : "text-left"}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {devices.length === 0 && (
                      <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-secondary text-sm">No devices registered yet.</td></tr>
                    )}
                    {devices.map((d) => {
                      const isBusy = togglingDevice === d.id;
                      return (
                        <tr key={d.id} className={`transition-opacity hover:bg-surface-soft ${d.is_active ? "" : "opacity-50"}`}>
                          <td className={`${TD} font-semibold`}>{d.surgeon_name}</td>
                          <td className={`${TD} max-w-[200px]`}>
                            <div className="font-semibold text-ink text-sm">{d.device_name}</div>
                            {d.user_agent && (
                              <div className="text-[10px] text-ink-secondary truncate mt-0.5" title={d.user_agent}>{d.user_agent}</div>
                            )}
                          </td>
                          <td className={`${TD} text-xs text-ink-secondary whitespace-nowrap`}>{fmtDateTimeEt(d.registered_at)}</td>
                          <td className={`${TD} text-xs text-ink-secondary whitespace-nowrap`}>{d.last_seen ? fmtDateTimeEt(d.last_seen) : "Never"}</td>
                          <td className={TD}>
                            {d.is_active
                              ? <span className="badge-green">Active</span>
                              : <span className="badge-red">Revoked</span>}
                          </td>
                          <td className={`${TD} text-right`}>
                            {d.is_active ? (
                              <button
                                disabled={isBusy}
                                onClick={() => void toggleDevice(d.id, false)}
                                className="btn-danger text-xs px-3 py-1.5"
                              >{isBusy ? <Spinner className="w-3 h-3" /> : "Deactivate"}</button>
                            ) : (
                              <button
                                disabled={isBusy}
                                onClick={() => void toggleDevice(d.id, true)}
                                className="text-xs font-semibold text-green-700 border border-green-300 rounded-lg px-3 py-1.5 hover:bg-green-50 transition-colors disabled:opacity-50"
                              >{isBusy ? <Spinner className="w-3 h-3" /> : "Reactivate"}</button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
          </main>
        </div>
      </div>

      {/* ══════════════ IMAGE LIGHTBOX ══════════════ */}
      {imageModal !== null && (
        <div
          onClick={() => setImageModal(null)}
          className="fixed inset-0 z-[200] bg-black/85 backdrop-blur-md flex items-center justify-center p-4 cursor-zoom-out"
        >
          <div className="max-w-full max-h-[90dvh] flex flex-col items-center gap-3" onClick={(e) => e.stopPropagation()}>
            <img
              src={`/api/v1/portal/rvu/scans/${imageModal}/image`}
              alt="Scan photo"
              className="max-w-full max-h-[78dvh] rounded-2xl shadow-modal"
            />
            <button onClick={() => setImageModal(null)} className="btn-secondary px-4 py-2 text-sm">Back to scans</button>
          </div>
          <button
            onClick={() => setImageModal(null)}
            className="fixed top-5 right-5 w-9 h-9 rounded-full bg-white/15 hover:bg-white/25 text-white text-xl flex items-center justify-center transition-colors"
          >×</button>
        </div>
      )}

      {detailScan && (
        <div onClick={() => setDetailScan(null)} className="fixed inset-0 z-[210] bg-black/45 backdrop-blur-sm flex items-center justify-center p-4">
          <div onClick={(e) => e.stopPropagation()} className="bg-surface rounded-2xl w-full max-w-5xl max-h-[90dvh] overflow-auto shadow-modal border border-brand-border">
            <div className="px-5 py-4 border-b border-brand-border flex items-center gap-3">
              <h3 className="text-base font-bold text-ink">Case details</h3>
              <span className="text-xs text-ink-secondary">{detailScan.surgeon_name || "—"}</span>
              <span className="text-xs text-ink-secondary">Scanned: {fmtDateTimeEt(detailScan.scanned_at)}</span>
              <button onClick={() => setDetailScan(null)} className="ml-auto btn-secondary text-xs px-3 py-1.5">Close</button>
            </div>
            {(() => {
              const fin = financialBreakdown(detailScan);
              return (
                <div className="p-5 space-y-4">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <StatCard label="Total RVU" value={(detailScan.total_rvu ?? 0).toFixed(2)} />
                    <StatCard label="wRVU (doctor)" value={fin.workRvu.toFixed(2)} />
                    <StatCard label="Value$ (doctor)" value={fmt$(fin.surgeonValue)} />
                    <StatCard label="Facility share" value={fmt$(fin.facilityShare)} />
                  </div>
                  <div className="text-xs text-ink-secondary">
                    Total payment: <span className="font-semibold text-ink">{fmt$(fin.totalPayment)}</span>{" "}
                    · AS assist lines: <span className="font-semibold text-ink">{fin.assistCount}</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse min-w-[860px]">
                      <thead>
                        <tr>
                          {["CPT", "Procedure / Provider", "Modifier", "wRVU", "PE RVU", "MP RVU", "Total RVU", "Work $", "PE $", "MP $", "Payment", "AS"].map((h, i) => (
                            <th key={h} className={`${TH} ${i >= 3 && i <= 10 ? "text-right" : "text-left"}`}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {fin.items.map((li, idx) => {
                          const isAs = Boolean(li.is_assist) || /\bAS\b/i.test(li.modifier ?? "");
                          const hasMod = Boolean(li.modifier_code);
                          return (
                            <tr key={`${li.cpt ?? "row"}-${idx}`} className={isAs ? "bg-amber-50/40" : ""}>
                              <td className={`${TD} font-mono text-xs font-bold`}>{li.cpt ?? "—"}</td>
                              <td className={`${TD} text-xs`}>
                                <div>{li.procedure_name || "—"}</div>
                                {(li.provider_name || li.provider_role) && (
                                  <div className="text-[10px] text-ink-secondary">
                                    {li.provider_name || "Unknown"} · {li.provider_role || "unknown"}
                                  </div>
                                )}
                              </td>
                              <td className={`${TD} text-xs`}>
                                {hasMod ? (
                                  <span className="inline-flex flex-col gap-0.5">
                                    <span className="inline-block bg-yellow-50 text-yellow-800 border border-yellow-200 rounded px-1.5 py-0.5 font-bold text-[10px]">
                                      -{li.modifier_code}
                                    </span>
                                    {li.modifier_desc && <span className="text-[10px] text-ink-secondary">{li.modifier_desc}</span>}
                                    {li.modifier_factor != null && li.modifier_factor !== 1 && (
                                      <span className="text-[10px] text-ink-secondary">×{li.modifier_factor}</span>
                                    )}
                                  </span>
                                ) : li.modifier ? (
                                  <span className="text-[10px] text-ink-secondary">{li.modifier}</span>
                                ) : "—"}
                              </td>
                              <td className={`${TD} text-right font-mono tabular-nums text-xs`}>{Number(li.work_rvu ?? 0).toFixed(2)}</td>
                              <td className={`${TD} text-right font-mono tabular-nums text-xs text-ink-secondary`}>{Number(li.pe_rvu ?? 0).toFixed(2)}</td>
                              <td className={`${TD} text-right font-mono tabular-nums text-xs text-ink-secondary`}>{Number(li.mp_rvu ?? 0).toFixed(2)}</td>
                              <td className={`${TD} text-right font-mono tabular-nums text-xs font-semibold`}>{Number(li.total_rvu ?? 0).toFixed(2)}</td>
                              <td className={`${TD} text-right font-mono tabular-nums text-xs text-green-700 font-semibold`}>
                                {li.work_payment != null ? fmt$(Number(li.work_payment)) : "—"}
                              </td>
                              <td className={`${TD} text-right font-mono tabular-nums text-xs text-ink-secondary`}>
                                {li.pe_payment != null ? fmt$(Number(li.pe_payment)) : "—"}
                              </td>
                              <td className={`${TD} text-right font-mono tabular-nums text-xs text-ink-secondary`}>
                                {li.mp_payment != null ? fmt$(Number(li.mp_payment)) : "—"}
                              </td>
                              <td className={`${TD} text-right font-mono tabular-nums text-xs font-bold`}>{fmt$(Number(li.payment ?? 0))}</td>
                              <td className={TD}>{isAs ? <span className="badge bg-amber-50 text-amber-700 border border-amber-200">AS</span> : "—"}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      )}

      {/* ══════════════ QR MODAL ══════════════ */}
      {qrModal && (
        <div
          onClick={(e) => { if (e.target === e.currentTarget) setQrModal(null); }}
          className="fixed inset-0 z-[100] bg-black/55 backdrop-blur flex items-center justify-center p-4"
        >
          <div className="bg-surface rounded-3xl shadow-modal w-full max-w-sm p-8 text-center relative">
            <button
              onClick={() => setQrModal(null)}
              className="absolute top-4 right-4 w-8 h-8 rounded-full bg-surface-soft hover:bg-brand-border text-ink-secondary flex items-center justify-center text-lg transition-colors"
            >×</button>

            <p className="label mb-1">Staff registration link</p>
            <h2 className="text-xl font-black text-ink mb-2">{qrModal.surgeon}</h2>
            <p className={`text-xs font-semibold mb-5 ${qrModal.emailed ? "text-green-700" : "text-amber-600"}`}>
              {qrModal.emailed ? `✓ Email sent to ${qrModal.email}` : "⚠ No email on file — share the link below"}
            </p>

            <div className="inline-block p-3 bg-surface border-2 border-brand-border rounded-2xl mb-5 shadow-card">
              <img
                src={`data:image/png;base64,${qrModal.qr_b64}`}
                alt="Registration link QR code"
                className="block w-48 h-48 rounded-lg"
              />
            </div>

            <div className="flex items-center gap-2 bg-surface-soft border border-brand-border rounded-xl px-3 py-2.5 mb-4">
              <span className="flex-1 text-[11px] font-mono text-ink-secondary truncate text-left">{qrModal.magic_url}</span>
              <button
                onClick={copyLink}
                className={`flex-shrink-0 text-xs font-bold px-3 py-1.5 rounded-lg transition-colors ${copied ? "bg-green-700 text-white" : "bg-ink text-white hover:bg-ink/90"}`}
              >{copied ? "✓ Copied" : "Copy"}</button>
            </div>

            <p className="text-xs text-ink-secondary mb-5">Link expires in 7 days. Scanning or clicking it registers the device.</p>

            <button
              onClick={() => setQrModal(null)}
              className="btn-secondary w-full py-3"
            >Done</button>
          </div>
        </div>
      )}
    </div>
  );
}
