import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type DeviceRecord,
  type PortalMe,
  type PortalDashboardDrilldownResponse,
  type PortalDashboardResponse,
  type PortalDashboardProvider,
  type ModifierRule,
  type PortalScanAiRun,
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
const SCAN_PAGE_SIZE = 100;

const fmt$ = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

/** Physicians first, then other roles; then last / first name. */
function sortStaffMembers(a: StaffMember, b: StaffMember): number {
  const rank = (t: string | null | undefined) => {
    const value = t?.toLowerCase();
    if (value === "physician") return 0;
    if (value === "pa" || value === "physician_assistant") return 1;
    return 2;
  };
  const dr = rank(a.staff_type) - rank(b.staff_type);
  if (dr !== 0) return dr;
  const ln = a.last_name.localeCompare(b.last_name);
  if (ln !== 0) return ln;
  return a.first_name.localeCompare(b.first_name);
}

const STAFF_ROLE_OPTIONS = [
  { value: "physician", label: "Physician" },
  { value: "pa", label: "PA-C" },
  { value: "staff", label: "Admin Staff" },
] as const;

function staffRoleLabel(value: string | null | undefined): string {
  const normalized = value?.trim().toLowerCase();
  return STAFF_ROLE_OPTIONS.find((option) => option.value === normalized)?.label ?? (value || "—");
}

function formatUsPhone(value: string | null | undefined): string {
  const digits = String(value ?? "").replace(/\D/g, "").slice(0, 10);
  if (digits.length <= 3) return digits;
  if (digits.length <= 6) return `(${digits.slice(0, 3)}) ${digits.slice(3)}`;
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

function Spinner({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function DetailMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-brand-border bg-surface-soft px-3 py-2">
      <div className="text-[10px] font-bold uppercase tracking-wide text-ink-secondary">{label}</div>
      <div className="mt-1 text-sm font-black text-ink tabular-nums">{value}</div>
    </div>
  );
}

// ── Table shared styles ────────────────────────────────────────────────────────
const TH = "px-3 py-2.5 text-[10px] font-bold uppercase tracking-wide text-ink-secondary whitespace-nowrap border-b-2 border-brand-border bg-surface-soft text-left";
const TD = "px-3 py-2.5 text-sm border-b border-brand-border/60 align-top";
const GROUP_TD = "px-3 py-2 text-[10px] font-black uppercase tracking-wide text-ink-secondary bg-surface-soft border-y border-brand-border";

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
  if (Array.isArray(raw)) return raw.filter((item): item is LineItem => typeof item === "object" && item !== null);
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw) as unknown;
      return Array.isArray(parsed)
        ? parsed.filter((item): item is LineItem => typeof item === "object" && item !== null)
        : [];
    } catch {
      return [];
    }
  }
  return [];
}

function financialBreakdown(scan: PortalScanRow) {
  const items = parseLineItems(scan);
  if (!items.length) {
    return {
      items,
      workRvu: Number(scan.work_rvu ?? 0),
      surgeonValue: Number(scan.surgeon_value ?? 0),
      facilityShare: Number(scan.facility_share ?? 0),
      totalPayment: Number(scan.total_payment ?? 0),
      assistCount: Number(scan.assist_count ?? 0),
      cptCount: Number(scan.cpt_count ?? 0),
    };
  }
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
    cptCount: items.length,
  };
}

function listFinancialSummary(scan: PortalScanRow): ReturnType<typeof financialBreakdown> {
  return {
    items: [],
    workRvu: Number(scan.work_rvu ?? 0),
    surgeonValue: Number(scan.surgeon_value ?? 0),
    facilityShare: Number(scan.facility_share ?? 0),
    totalPayment: Number(scan.total_payment ?? 0),
    assistCount: Number(scan.assist_count ?? 0),
    cptCount: Number(scan.cpt_count ?? 0),
  };
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

function isPrimaryOcrRun(run: PortalScanAiRun): boolean {
  return run.stage === "vision_primary" || run.stage === "text_primary";
}

function providerRoleRank(role: string | null | undefined): number {
  const value = role?.trim().toLowerCase();
  if (value === "physician" || value === "surgeon") return 0;
  if (value === "pa" || value === "pa-c" || value === "physician_assistant" || value === "physician assistant") return 1;
  return 2;
}

function providerGroupLabel(role: string | null | undefined): string {
  const rank = providerRoleRank(role);
  if (rank === 0) return "Surgeons";
  if (rank === 1) return "PA-C";
  return "Other Staff";
}

function etDateKey(value: string | null | undefined): string {
  if (!value) return "";
  const directEt = value.match(/^(\d{4}-\d{2}-\d{2})T/);
  if (directEt && (value.includes("-04:00") || value.includes("-05:00"))) return directEt[1];
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function weekEndingLabel(periodKey: string, fallback: string): string {
  const match = periodKey.match(/^(\d{4})-W(\d{2})$/);
  if (!match) return fallback;
  const year = Number(match[1]);
  const week = Number(match[2]);
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Day = jan4.getUTCDay() || 7;
  const weekOneMonday = new Date(jan4);
  weekOneMonday.setUTCDate(jan4.getUTCDate() - jan4Day + 1);
  const weekEnd = new Date(weekOneMonday);
  weekEnd.setUTCDate(weekOneMonday.getUTCDate() + (week - 1) * 7 + 6);
  return weekEnd.toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "2-digit",
    day: "2-digit",
    year: "2-digit",
  });
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
  mode?: "edit" | "add";
}

function EditRow({ scan, draft, setDraft, saving, onSave, onCancel, colCount, mode = "edit" }: EditRowProps) {
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
            <label className="label">{mode === "add" ? "Add CPTs (comma-separated)" : "CPTs (comma-separated)"}</label>
            <input type="text" className="input text-xs" placeholder="e.g. 27447, 00400"
              autoFocus={mode === "add"}
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
  const [bootLoading, setBootLoading] = useState(true);
  const [scans, setScans] = useState<PortalScanRow[]>([]);
  const [hasMoreScans, setHasMoreScans] = useState(false);
  const [scansLoadingMore, setScansLoadingMore] = useState(false);
  const [scanLoadErr, setScanLoadErr] = useState<string | null>(null);
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [devices, setDevices] = useState<DeviceRecord[]>([]);
  const [staffLoaded, setStaffLoaded] = useState(false);
  const [devicesLoaded, setDevicesLoaded] = useState(false);
  const [tab, setTab] = useState<Tab>("scans");
  const [dashboardRange, setDashboardRange] = useState("month");
  const [dashboardGroupBy, setDashboardGroupBy] = useState("week");
  const [dashboard, setDashboard] = useState<PortalDashboardResponse | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardErr, setDashboardErr] = useState<string | null>(null);
  const [selectedProviderId, setSelectedProviderId] = useState<number | null>(null);
  const [selectedProviderPeriodKey, setSelectedProviderPeriodKey] = useState<string | null>(null);
  const [periodDrilldown, setPeriodDrilldown] = useState<PortalDashboardDrilldownResponse | null>(null);
  const [periodDrilldownLoading, setPeriodDrilldownLoading] = useState(false);
  const [periodDrilldownErr, setPeriodDrilldownErr] = useState<string | null>(null);

  const [imageModal, setImageModal] = useState<number | null>(null);
  const [imageLoading, setImageLoading] = useState(false);
  const [detailScan, setDetailScan] = useState<PortalScanRow | null>(null);
  const [detailLoadingId, setDetailLoadingId] = useState<number | null>(null);
  const [ocrReviewScan, setOcrReviewScan] = useState<PortalScanRow | null>(null);
  const [ocrReviewRuns, setOcrReviewRuns] = useState<PortalScanAiRun[]>([]);
  const [ocrReviewLoadingId, setOcrReviewLoadingId] = useState<number | null>(null);
  const [togglingDevice, setTogglingDevice] = useState<number | null>(null);

  const [editId, setEditId] = useState<number | null>(null);
  const [editMode, setEditMode] = useState<"edit" | "add">("edit");
  const [editDraft, setEditDraft] = useState<ScanPatchBody>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

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
  const [modifiers, setModifiers] = useState<ModifierRule[]>([]);
  const [modifiersLoaded, setModifiersLoaded] = useState(false);
  const [modifierSavingCode, setModifierSavingCode] = useState<string | null>(null);
  const defaultModelForProvider = (p: string) =>
    p === "openai" ? "gpt-4o-mini" : p === "anthropic" ? "claude-3-5-sonnet-latest" : p === "paddle" ? "paddleocr" : "qwen2.5vl:7b";
  const todayKey = useMemo(() => etDateKey(new Date().toISOString()), []);
  const pendingModifierRules = useMemo(
    () => modifiers.filter((rule) => rule.needs_review || rule.source === "mobile"),
    [modifiers],
  );

  const clearModifierReview = async (rule: ModifierRule) => {
    setModifierSavingCode(rule.code);
    try {
      const updated = await api.patchPortalModifierRule(rule.code, {
        desc: rule.desc,
        factor: rule.factor,
        needs_review: false,
      });
      setModifiers((prev) => prev.map((item) => (item.code === updated.code ? updated : item)));
    } finally {
      setModifierSavingCode(null);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setBootLoading(true);
    setScansLoadingMore(false);
    setScanLoadErr(null);
    Promise.all([api.mePortal(), api.portalScans(SCAN_PAGE_SIZE, 0, { scannedOn: todayKey })])
      .then(([a, firstPage]) => {
        if (cancelled) return;
        setAdmin(a);
        setScans(firstPage.scans);
        setHasMoreScans(firstPage.has_more);
        setBootLoading(false);
      })
      .catch(() => { if (!cancelled) nav("/portal/login"); })
      .finally(() => {
        if (!cancelled) setBootLoading(false);
      });
    return () => { cancelled = true; };
  }, [nav, todayKey]);

  const loadMoreScans = async () => {
    if (scansLoadingMore || !hasMoreScans) return;
    setScansLoadingMore(true);
    setScanLoadErr(null);
    try {
      const page = await api.portalScans(SCAN_PAGE_SIZE, scans.length, { scannedOn: todayKey });
      setHasMoreScans(page.has_more);
      setScans((prev) => {
        const seen = new Set(prev.map((scan) => scan.id));
        const newScans = page.scans.filter((scan) => !seen.has(scan.id));
        return newScans.length ? [...prev, ...newScans] : prev;
      });
    } catch (e: unknown) {
      setScanLoadErr(e instanceof Error ? e.message : "Could not load more scans.");
    } finally {
      setScansLoadingMore(false);
    }
  };

  useEffect(() => {
    if (!admin) return;
    if (tab === "staff" && !staffLoaded) {
      void api.adminStaff()
        .then((st) => {
          setStaff(st.staff.slice().sort(sortStaffMembers));
          setStaffLoaded(true);
        })
        .catch(() => {});
    }
    if (tab === "devices" && !devicesLoaded) {
      void api.listDevices()
        .then((dv) => {
          setDevices(dv.devices);
          setDevicesLoaded(true);
        })
        .catch(() => {});
    }
    if (tab === "settings" && !modifiersLoaded) {
      void api.portalModifierRules()
        .then((res) => {
          setModifiers(res.modifiers);
          setModifiersLoaded(true);
        })
        .catch(() => {});
    }
  }, [admin, tab, staffLoaded, devicesLoaded, modifiersLoaded]);

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

  useEffect(() => {
    if (!admin) return;
    let cancelled = false;
    setDashboardLoading(true);
    setDashboardErr(null);
    api.portalDashboard(dashboardRange, dashboardGroupBy)
      .then((payload) => {
        if (cancelled) return;
        setDashboard(payload);
        if (selectedProviderId && !payload.providers.some((provider) => provider.provider_id === selectedProviderId)) {
          setSelectedProviderId(null);
          setSelectedProviderPeriodKey(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setDashboardErr(e instanceof Error ? e.message : "Could not load dashboard.");
      })
      .finally(() => {
        if (!cancelled) setDashboardLoading(false);
      });
    return () => { cancelled = true; };
  }, [admin, dashboardRange, dashboardGroupBy]);

  useEffect(() => {
    if (!admin || selectedProviderId === null || !selectedProviderPeriodKey) {
      setPeriodDrilldown(null);
      setPeriodDrilldownErr(null);
      setPeriodDrilldownLoading(false);
      return;
    }
    let cancelled = false;
    setPeriodDrilldownLoading(true);
    setPeriodDrilldownErr(null);
    api.portalDashboardDrilldown({
      range: dashboardRange,
      groupBy: dashboardGroupBy,
      providerId: selectedProviderId,
      periodKey: selectedProviderPeriodKey,
      limit: 250,
    })
      .then((payload) => {
        if (!cancelled) setPeriodDrilldown(payload);
      })
      .catch((e: unknown) => {
        if (!cancelled) setPeriodDrilldownErr(e instanceof Error ? e.message : "Could not load period detail.");
      })
      .finally(() => {
        if (!cancelled) setPeriodDrilldownLoading(false);
      });
    return () => { cancelled = true; };
  }, [admin, dashboardRange, dashboardGroupBy, selectedProviderId, selectedProviderPeriodKey]);

  const logout = async () => {
    await api.portalLogout();
    nav("/portal/login");
  };

  const openScanImage = (id: number) => {
    setImageLoading(true);
    setImageModal(id);
  };

  const closeScanImage = () => {
    setImageModal(null);
    setImageLoading(false);
  };

  const openScanDetails = async (id: number) => {
    setDetailLoadingId(id);
    try {
      const detail = await api.portalScanDetail(id);
      setDetailScan(detail);
    } catch (e: unknown) {
      alert("Could not load scan details: " + (e instanceof Error ? e.message : "unknown error"));
    } finally {
      setDetailLoadingId(null);
    }
  };

  const openOcrReview = async (scan: PortalScanRow) => {
    setOcrReviewLoadingId(scan.id);
    try {
      const res = await api.portalScanAiRuns(scan.id);
      setOcrReviewScan(scan);
      setOcrReviewRuns(res.ai_runs);
    } catch (e: unknown) {
      alert("Could not load OCR results: " + (e instanceof Error ? e.message : "unknown error"));
    } finally {
      setOcrReviewLoadingId(null);
    }
  };

  const startEdit = (s: PortalScanRow) => { setDeleteConfirmId(null); setEditMode("edit"); setEditId(s.id); setEditDraft({}); };
  const startAdd = (s: PortalScanRow) => { setDeleteConfirmId(null); setEditMode("add"); setEditId(s.id); setEditDraft({}); };
  const cancelEdit = () => { setEditId(null); setEditMode("edit"); setEditDraft({}); };

  const saveEdit = async (id: number) => {
    if (!Object.keys(editDraft).length) { cancelEdit(); return; }
    setSavingId(id);
      try {
        const updated = await api.patchScan(id, editDraft);
        setScans((prev) => prev.map((s) => (s.id === id ? { ...s, ...updated } : s)));
        setPeriodDrilldown((prev) => prev ? { ...prev, scans: prev.scans.map((s) => (s.id === id ? { ...s, ...updated } : s)) } : prev);
      setEditId(null); setEditMode("edit"); setEditDraft({});
    } catch (e: unknown) {
      alert("Save failed: " + (e instanceof Error ? e.message : "unknown error"));
    } finally { setSavingId(null); }
  };

  const doDelete = async (id: number) => {
    setDeletingId(id);
    try {
      await api.deleteScan(id);
      setScans((prev) => prev.filter((s) => s.id !== id));
      setPeriodDrilldown((prev) => prev ? { ...prev, scans: prev.scans.filter((s) => s.id !== id) } : prev);
      setDeleteConfirmId(null);
    } catch (e: unknown) {
      alert("Delete failed: " + (e instanceof Error ? e.message : "unknown error"));
    } finally { setDeletingId(null); }
  };

  const todayScanSummary = useMemo(() => {
    const rows: { scan: PortalScanRow; fin: ReturnType<typeof financialBreakdown> }[] = [];
    let totalRvu = 0;
    let totalPay = 0;
    let totalFacilityValue = 0;

    for (const s of scans) {
      const scannedDay = s.scanned_at_et?.slice(0, 10) || etDateKey(s.scanned_at);
      if (scannedDay !== todayKey) continue;

      const fin = listFinancialSummary(s);
      rows.push({ scan: s, fin });
      totalRvu += s.total_rvu ?? 0;
      totalPay += s.total_payment ?? 0;
      totalFacilityValue += fin.facilityShare;
    }

    rows.sort((a, b) => String(b.scan.scanned_at ?? "").localeCompare(String(a.scan.scanned_at ?? "")));

    return {
      rows,
      scans: rows.map(({ scan }) => scan),
      totalRvu,
      totalPay,
      totalFacilityValue,
      dateKey: todayKey,
    };
  }, [scans, todayKey]);

  const {
    rows: todayScanRows,
    scans: todayScans,
    totalRvu,
    totalPay,
    totalFacilityValue,
    dateKey: todayScanDateKey,
  } = todayScanSummary;

  const groupedProviders = useMemo(() => {
    if (!dashboard) return [];
    const sorted = dashboard.providers.slice().sort((a, b) => {
      const roleDiff = providerRoleRank(a.role) - providerRoleRank(b.role);
      if (roleDiff !== 0) return roleDiff;
      const wrvuDiff = b.wrvu - a.wrvu;
      if (wrvuDiff !== 0) return wrvuDiff;
      return a.provider_name.localeCompare(b.provider_name);
    });
    const rows: Array<
      | { type: "group"; key: string; label: string }
      | { type: "provider"; key: string; provider: PortalDashboardProvider }
    > = [];
    let lastGroup = "";
    sorted.forEach((provider) => {
      const group = providerGroupLabel(provider.role);
      if (group !== lastGroup) {
        rows.push({ type: "group", key: `group-${group}`, label: group });
        lastGroup = group;
      }
      rows.push({ type: "provider", key: `provider-${provider.provider_id}`, provider });
    });
    return rows;
  }, [dashboard]);

  const selectedProviderPeriods = useMemo(() => {
    if (!dashboard || selectedProviderId === null) return [];
    return dashboard.provider_periods
      .filter((period) => period.provider_id === selectedProviderId)
      .slice()
      .sort((a, b) => b.period_key.localeCompare(a.period_key));
  }, [dashboard, selectedProviderId]);

  const selectedProvider = useMemo(() => {
    if (!dashboard || selectedProviderId === null) return null;
    return dashboard.providers.find((provider) => provider.provider_id === selectedProviderId) ?? null;
  }, [dashboard, selectedProviderId]);

  const selectedProviderPeriod = useMemo(
    () => selectedProviderPeriods.find((period) => period.period_key === selectedProviderPeriodKey) ?? selectedProviderPeriods[0] ?? null,
    [selectedProviderPeriods, selectedProviderPeriodKey],
  );

  useEffect(() => {
    if (selectedProviderId === null || selectedProviderPeriodKey || selectedProviderPeriods.length === 0) return;
    setSelectedProviderPeriodKey(selectedProviderPeriods[0].period_key);
  }, [selectedProviderId, selectedProviderPeriodKey, selectedProviderPeriods]);

  const openProviderDashboard = (provider: PortalDashboardProvider) => {
    if (!dashboard) return;
    if (dashboardGroupBy !== "week") {
      setDashboardGroupBy("week");
      setSelectedProviderId(provider.provider_id);
      setSelectedProviderPeriodKey(null);
      setPeriodDrilldown(null);
      return;
    }
    const periods = dashboard.provider_periods
      .filter((period) => period.provider_id === provider.provider_id)
      .slice()
      .sort((a, b) => b.period_key.localeCompare(a.period_key));
    setSelectedProviderId(provider.provider_id);
    setSelectedProviderPeriodKey(periods[0]?.period_key ?? null);
    setPeriodDrilldown(null);
  };

  const closeProviderDashboard = () => {
    setSelectedProviderId(null);
    setSelectedProviderPeriodKey(null);
    setPeriodDrilldown(null);
    setPeriodDrilldownErr(null);
    setEditId(null);
    setEditMode("edit");
    setEditDraft({});
    setDeleteConfirmId(null);
  };

  const startStaffEdit = (s: StaffMember) => {
    setShowAddForm(false); setStaffEditId(s.id);
    setStaffDraft({ first_name: s.first_name, last_name: s.last_name, suffix: s.suffix ?? "", staff_type: s.staff_type ?? "physician", email: s.email ?? "", phone: formatUsPhone(s.phone), is_active: s.is_active });
    setStaffErr(null);
  };

  const saveStaffEdit = async () => {
    if (staffEditId === null) return;
    setStaffSaving(true); setStaffErr(null);
    try {
      const updated = await api.patchStaff(staffEditId, { ...staffDraft, phone: formatUsPhone(staffDraft.phone) });
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
      const created = await api.createStaff({ ...addDraft, phone: formatUsPhone(addDraft.phone) });
      setStaff((prev) => [...prev, created].sort(sortStaffMembers));
      setShowAddForm(false); setAddDraft({ first_name: "", last_name: "", phone: "" });
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

  if (bootLoading || !admin) {
    return (
      <div className="min-h-dvh bg-surface-soft flex items-center justify-center">
        <div className="card px-5 py-4 flex items-center gap-3 text-sm text-ink-secondary">
          <Spinner />
          Loading portal scans...
        </div>
      </div>
    );
  }

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

        {/* ══════════════ SCANS TAB ══════════════ */}
        {tab === "scans" && (
          <div className="flex flex-col">
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_180px] mb-4">
              <div>
                <h1 className="text-xl font-black text-ink tracking-tight">Practice Dashboard</h1>
                {dashboard && (
                  <div className="text-xs text-ink-secondary mt-1">
                    {fmtCalendarDateMdY(dashboard.range.start)} - {fmtCalendarDateMdY(dashboard.range.end)}
                  </div>
                )}
              </div>
              <div>
                <label className="label">Range</label>
                <select className="input text-xs" value={dashboardRange} onChange={(e) => setDashboardRange(e.target.value)}>
                  <option value="today">Today</option>
                  <option value="7d">7 days</option>
                  <option value="30d">30 days</option>
                  <option value="month">Month</option>
                  <option value="quarter">Quarter</option>
                  <option value="ytd">YTD</option>
                </select>
              </div>
              <div>
                <label className="label">Group</label>
                <select className="input text-xs" value={dashboardGroupBy} onChange={(e) => setDashboardGroupBy(e.target.value)}>
                  <option value="day">Day</option>
                  <option value="week">Week</option>
                  <option value="month">Month</option>
                  <option value="quarter">Quarter</option>
                </select>
              </div>
            </div>

            {dashboardErr && (
              <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                <span><span className="font-bold">Dashboard failed.</span> {dashboardErr}</span>
              </div>
            )}

            {dashboardLoading && !dashboard && (
              <div className="card px-4 py-3 mb-4 inline-flex items-center gap-3 text-sm text-ink-secondary">
                <Spinner />
                Loading dashboard...
              </div>
            )}

            {dashboard && (
              <div className="space-y-4 mb-6 order-2">
                <div className="grid gap-4">
                  <div className="card overflow-hidden">
                    <div className="px-4 py-3 border-b border-brand-border">
                      <h2 className="text-sm font-black text-ink uppercase tracking-wide">Provider Production</h2>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full border-collapse" style={{ minWidth: 900 }}>
                        <thead>
                          <tr>
                            {["Provider", "Role", "Patients", "Scans", "CPTs", "wRVU", "Est. $", "Avg", "Last Scan"].map((h, i) => (
                              <th key={h} className={`${TH} ${i >= 2 && i <= 7 ? "text-right" : "text-left"}`}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {groupedProviders.map((row) => {
                            if (row.type === "group") {
                              return (
                                <tr key={row.key}>
                                  <td colSpan={9} className={GROUP_TD}>{row.label}</td>
                                </tr>
                              );
                            }
                            const { provider } = row;
                            return (
                              <tr
                                key={row.key}
                                onClick={() => openProviderDashboard(provider)}
                                className="cursor-pointer transition-colors hover:bg-surface-soft"
                              >
                                <td className={`${TD} font-bold`}>{provider.provider_name}</td>
                                <td className={TD}>{provider.role ? <span className="badge-blue">{staffRoleLabel(provider.role)}</span> : "—"}</td>
                                <td className={`${TD} text-right font-mono tabular-nums`}>{provider.patients}</td>
                                <td className={`${TD} text-right font-mono tabular-nums`}>{provider.scans}</td>
                                <td className={`${TD} text-right font-mono tabular-nums`}>{provider.cpt_lines}</td>
                                <td className={`${TD} text-right font-mono tabular-nums font-bold`}>{provider.wrvu.toFixed(2)}</td>
                                <td className={`${TD} text-right font-mono tabular-nums`}>{fmt$(provider.est_payment)}</td>
                                <td className={`${TD} text-right font-mono tabular-nums`}>{provider.avg_wrvu_per_patient.toFixed(2)}</td>
                                <td className={`${TD} text-xs text-ink-secondary whitespace-nowrap`}>{provider.last_scan ? fmtDateTimeEt(provider.last_scan) : "—"}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

              </div>
            )}

            {scanLoadErr && (
              <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                <span><span className="font-bold">Some scans did not load.</span> {scanLoadErr}</span>
              </div>
            )}

            <div className="order-1 mb-6">
            <div className="flex items-center justify-between gap-3 mb-3">
              <h2 className="text-sm font-black text-ink uppercase tracking-wide">Today's Scans</h2>
              <span className="text-xs font-semibold text-ink-secondary">{todayScanDateKey}</span>
            </div>

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
                    {todayScans.length === 0 && (
                      <tr>
                        <td colSpan={COL_COUNT} className="px-4 py-10 text-center text-ink-secondary text-sm">
                          No scans since midnight.
                        </td>
                      </tr>
                    )}
                    {todayScanRows.map(({ scan: s, fin }) => {
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
                              <button
                                type="button"
                                onClick={() => openScanImage(s.id)}
                                className="w-9 h-9 rounded-lg bg-surface-soft border border-brand-border flex items-center justify-center hover:bg-surface cursor-zoom-in"
                                title="Open scan image"
                              >
                                <svg className="w-4 h-4 text-brand-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                                  <path strokeLinecap="round" strokeLinejoin="round"
                                    d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                                </svg>
                              </button>
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
                            {s.staff_type ? <span className="badge bg-indigo-50 text-indigo-600 border border-indigo-200">{staffRoleLabel(s.staff_type)}</span> : "—"}
                          </td>
                          <td className={TD}>
                            {s.facility
                              ? <span className="badge-blue">Facility</span>
                              : <span className="badge-green">Non-Fac</span>}
                          </td>
                          <td className={`${TD} text-xs text-ink-secondary`}>{fin.cptCount}</td>
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
                              <div className="inline-flex flex-col items-end gap-2">
                                <span className="inline-flex gap-2">
                                  <button
                                    onClick={() => void openScanDetails(s.id)}
                                    disabled={detailLoadingId === s.id}
                                    className="text-ink text-xs font-semibold border border-brand-border rounded-lg px-2.5 py-1 hover:bg-surface-soft transition-colors disabled:opacity-60"
                                  >
                                    {detailLoadingId === s.id ? <Spinner className="w-3 h-3" /> : "Details"}
                                  </button>
                                  <button onClick={() => startAdd(s)} className="text-emerald-700 text-xs font-semibold border border-emerald-200 rounded-lg px-2.5 py-1 hover:bg-emerald-50 transition-colors">
                                    Add
                                  </button>
                                  <button onClick={() => startEdit(s)} className="text-indigo-600 text-xs font-semibold border border-indigo-200 rounded-lg px-2.5 py-1 hover:bg-indigo-50 transition-colors">
                                    Edit
                                  </button>
                                  <button onClick={() => { cancelEdit(); setDeleteConfirmId(s.id); }} className="text-red-600 text-xs font-semibold border border-red-200 rounded-lg px-2.5 py-1 hover:bg-red-50 transition-colors">
                                    Del
                                  </button>
                                </span>
                                <button
                                  onClick={() => void openOcrReview(s)}
                                  disabled={ocrReviewLoadingId === s.id}
                                  className="text-amber-700 text-xs font-semibold border border-amber-200 rounded-lg px-2.5 py-1 hover:bg-amber-50 transition-colors disabled:opacity-60"
                                >
                                  {ocrReviewLoadingId === s.id ? <Spinner className="w-3 h-3" /> : "Review OCR"}
                                </button>
                              </div>
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
                            mode={editMode}
                          />
                        ),
                      ];
                    })}
                  </tbody>
                  {todayScans.length > 0 && (
                    <tfoot>
                      <tr className="bg-surface-soft">
                        <td colSpan={8} className="px-3 py-3 font-bold text-xs text-ink-secondary border-t-2 border-ink">
                          Totals ({todayScans.length} scan{todayScans.length !== 1 ? "s" : ""})
                        </td>
                        <td className="px-3 py-3 text-right font-black font-mono tabular-nums text-sm border-t-2 border-ink">{totalRvu.toFixed(2)}</td>
                        <td className="px-3 py-3 text-right font-black text-ink font-mono tabular-nums text-sm border-t-2 border-ink">{fmt$(totalFacilityValue)}</td>
                        <td className="px-3 py-3 text-right font-black text-green-700 font-mono tabular-nums text-sm border-t-2 border-ink">{fmt$(totalPay)}</td>
                        <td colSpan={2} className="border-t-2 border-ink" />
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
              {hasMoreScans && (
                <div className="border-t border-brand-border bg-surface px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-ink-secondary">
                    Showing {scans.length} newest scans. More are available.
                  </p>
                  <button
                    type="button"
                    onClick={() => void loadMoreScans()}
                    disabled={scansLoadingMore}
                    className="btn-secondary text-xs px-3 py-2"
                  >
                    {scansLoadingMore ? <><Spinner className="w-3 h-3" /> Loading...</> : "Load more"}
                  </button>
                </div>
              )}
            </div>
            </div>
          </div>
        )}

        {/* ══════════════ STAFF TAB ══════════════ */}
        {tab === "staff" && (
          <div>
            {!staffLoaded && (
              <div className="card px-4 py-3 mb-4 inline-flex items-center gap-3 text-sm text-ink-secondary">
                <Spinner />
                Loading staff...
              </div>
            )}
            <div className="flex items-center justify-between mb-4">
              <p className="text-sm text-ink-secondary">Manage staff — edit names, email, phone, and roles, or add new members.</p>
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
                    { label: "Phone",        key: "phone"      as const, placeholder: "(555) 555-1212", type: "tel" },
                  ].map(({ label, key, placeholder, type }) => (
                    <div key={key}>
                      <label className="label">{label}</label>
                      <input
                        type={type ?? "text"}
                        placeholder={placeholder}
                        value={(addDraft[key] as string) ?? ""}
                        onChange={(e) => setAddDraft((d) => ({ ...d, [key]: key === "phone" ? formatUsPhone(e.target.value) : e.target.value }))}
                        className="input text-sm"
                        inputMode={key === "phone" ? "tel" : undefined}
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
                    {STAFF_ROLE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </div>
                {addErr && <p className="text-red-600 text-xs mb-3">{addErr}</p>}
                <button onClick={() => void submitAddStaff()} disabled={addSaving} className="btn-primary">
                  {addSaving ? <><Spinner /> Adding…</> : "Add Staff Member"}
                </button>
              </div>
            )}

            {/* Staff table */}
            {staffLoaded && (
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full border-collapse" style={{ minWidth: 760 }}>
                  <thead>
                    <tr>
                      {["Name", "Role", "Email", "Phone", "Status", "Actions"].map((h, i) => (
                        <th key={h} className={`${TH} ${i === 5 ? "text-right" : "text-left"}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {staff.length === 0 && (
                      <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-secondary text-sm">No staff found.</td></tr>
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
                              ? <span className="badge bg-indigo-50 text-indigo-600 border border-indigo-200">{staffRoleLabel(s.staff_type)}</span>
                              : <span className="text-ink-secondary">—</span>}
                          </td>
                          <td className={`${TD} text-xs`}>
                            {s.email
                              ? <a href={`mailto:${s.email}`} className="text-brand-blue hover:underline">{s.email}</a>
                              : <span className="badge-yellow">⚠ No email</span>}
                          </td>
                          <td className={`${TD} text-xs`}>
                            {s.phone
                              ? <a href={`tel:${String(s.phone).replace(/\D/g, "")}`} className="text-brand-blue hover:underline">{formatUsPhone(s.phone)}</a>
                              : <span className="badge-yellow">⚠ No phone</span>}
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
                            </span>
                          </td>
                        </tr>,

                        isEditing && (
                          <tr key={`staff-edit-${s.id}`} className="bg-brand-muted/60">
                            <td colSpan={6} className="px-4 py-3">
                              <div className="flex flex-wrap gap-3 items-end">
                                {[
                                  { label: "First Name", key: "first_name" as const },
                                  { label: "Last Name",  key: "last_name"  as const },
                                  { label: "Suffix",     key: "suffix"     as const, placeholder: "MD, PA-C…" },
                                  { label: "Email",      key: "email"      as const, type: "email" },
                                  { label: "Phone",      key: "phone"      as const, type: "tel", placeholder: "(555) 555-1212" },
                                ].map(({ label, key, placeholder, type }) => (
                                  <div key={key} className="flex-1 min-w-[110px]">
                                    <label className="label">{label}</label>
                                    <input
                                      type={type ?? "text"}
                                      placeholder={placeholder}
                                      value={(staffDraft[key] as string) ?? ""}
                                      onChange={(e) => setStaffDraft((d) => ({ ...d, [key]: key === "phone" ? formatUsPhone(e.target.value) : e.target.value }))}
                                      className="input text-xs"
                                      inputMode={key === "phone" ? "tel" : undefined}
                                    />
                                  </div>
                                ))}
                                <div className="flex-none">
                                  <label className="label">Role</label>
                                  <select className="input text-xs w-auto"
                                    value={staffDraft.staff_type ?? "physician"}
                                    onChange={(e) => setStaffDraft((d) => ({ ...d, staff_type: e.target.value }))}
                                  >
                                    {STAFF_ROLE_OPTIONS.map((option) => (
                                      <option key={option.value} value={option.value}>{option.label}</option>
                                    ))}
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
            )}
          </div>
        )}

        {/* ══════════════ DEVICES TAB ══════════════ */}
        {tab === "opnotes" && <PortalOpNotesPanel />}

        {tab === "settings" && (
          <div>
            <h2 className="text-lg font-bold text-ink mb-1">Settings</h2>
            <p className="text-sm text-ink-secondary mb-6">Portal accounts for office staff (username and password).</p>
            <PortalUsersPanel admin={admin} />
            <div className="card mt-6 p-5">
              <div className="flex items-start justify-between gap-4 mb-4">
                <div>
                  <h3 className="text-sm font-black text-ink uppercase tracking-wide">Mobile-added modifiers</h3>
                  <p className="text-xs text-ink-secondary mt-1">
                    Modifiers added from the iPhone appear here for admin review. They are already available to the picker wheel.
                  </p>
                </div>
                <button
                  className="btn-secondary text-xs px-3 py-2"
                  onClick={() => {
                    setModifiersLoaded(false);
                    void api.portalModifierRules().then((res) => {
                      setModifiers(res.modifiers);
                      setModifiersLoaded(true);
                    });
                  }}
                >
                  Refresh
                </button>
              </div>
              {!modifiersLoaded ? (
                <p className="text-sm text-ink-secondary">Loading modifier review...</p>
              ) : pendingModifierRules.length === 0 ? (
                <p className="text-sm text-ink-secondary">No mobile-added modifiers need review.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse" style={{ minWidth: 720 }}>
                    <thead>
                      <tr className="bg-surface-soft text-left">
                        {["Code", "Description", "Factor", "Added by", "Status", ""].map((h) => (
                          <th key={h} className="px-3 py-2 text-[11px] uppercase tracking-wide text-ink-secondary">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {pendingModifierRules.map((rule) => (
                        <tr key={rule.code} className="border-t border-border">
                          <td className="px-3 py-3 font-mono font-black text-ink">{rule.code}</td>
                          <td className="px-3 py-3 text-sm text-ink">{rule.desc || "No description"}</td>
                          <td className="px-3 py-3 text-sm font-mono">{Number(rule.factor ?? 1).toFixed(2)}x</td>
                          <td className="px-3 py-3 text-sm text-ink-secondary">{rule.added_by_staff_name || "Mobile user"}</td>
                          <td className="px-3 py-3">
                            <span className="badge-yellow">Needs review</span>
                          </td>
                          <td className="px-3 py-3 text-right">
                            <button
                              className="btn-secondary text-xs px-3 py-2"
                              disabled={modifierSavingCode === rule.code}
                              onClick={() => void clearModifierReview(rule)}
                            >
                              {modifierSavingCode === rule.code ? "Saving..." : "Mark reviewed"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
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
            {!devicesLoaded && (
              <div className="card px-4 py-3 mb-4 inline-flex items-center gap-3 text-sm text-ink-secondary">
                <Spinner />
                Loading devices...
              </div>
            )}
            <p className="text-sm text-ink-secondary mb-4">
              <strong className="text-ink">One row per staff member</strong> — the most recently used phone or browser.{" "}
              <strong className="text-ink">Deactivate</strong> revokes access until they use a new registration link.
            </p>
            {devicesLoaded && (
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
            )}
          </div>
        )}
          </main>
        </div>
      </div>

      {selectedProvider && (
        <div className="fixed inset-0 z-[190] bg-surface-soft flex flex-col">
          <div className="h-14 bg-ink text-white px-4 sm:px-6 flex items-center gap-4 shrink-0">
            <button onClick={closeProviderDashboard} className="btn-secondary text-xs px-3 py-1.5">Back</button>
            <div className="min-w-0 flex-1">
              <div className="text-base font-black truncate">{selectedProvider.provider_name}</div>
              <div className="text-[11px] text-white/60 truncate">
                {staffRoleLabel(selectedProvider.role)} · {selectedProvider.patients} patients · {selectedProvider.scans} scans · {selectedProvider.wrvu.toFixed(2)} wRVU · {fmt$(selectedProvider.est_payment)}
              </div>
            </div>
            <span className="text-xs text-white/60 hidden md:block">
              {dashboard && `${fmtCalendarDateMdY(dashboard.range.start)} - ${fmtCalendarDateMdY(dashboard.range.end)}`}
            </span>
          </div>

          <div className="grid flex-1 min-h-0 gap-4 p-4 lg:grid-cols-[220px_minmax(0,1fr)_300px]">
            <div className="card overflow-hidden min-h-0 flex flex-col">
              <div className="px-3 py-2.5 border-b border-brand-border">
                <h2 className="text-xs font-black uppercase tracking-wide text-ink">Weeks</h2>
              </div>
              <div className="overflow-auto">
                <table className="w-full border-collapse">
                  <tbody>
                    {selectedProviderPeriods.length === 0 && (
                      <tr><td className="px-3 py-4 text-sm text-ink-secondary">No weeks.</td></tr>
                    )}
                    {selectedProviderPeriods.map((period) => {
                      const selected = period.period_key === selectedProviderPeriodKey;
                      return (
                        <tr
                          key={period.period_key}
                          onClick={() => setSelectedProviderPeriodKey(period.period_key)}
                          className={`cursor-pointer border-b border-brand-border/60 ${selected ? "bg-brand-muted" : "hover:bg-surface-soft"}`}
                        >
                          <td className="px-3 py-2.5">
                            <div className="text-sm font-black text-ink">{period.period_label}</div>
                            <div className="text-[11px] text-ink-secondary">Ending {weekEndingLabel(period.period_key, period.period_label)}</div>
                            <div className="mt-1 text-[11px] text-ink-secondary font-mono">{period.scans} scans · {period.wrvu.toFixed(2)} wRVU</div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card overflow-hidden min-h-0 flex flex-col">
              <div className="px-4 py-3 border-b border-brand-border flex items-center gap-3">
                <h2 className="text-sm font-black uppercase tracking-wide text-ink flex-1">
                  {selectedProviderPeriod?.period_label ?? "Week Detail"}
                </h2>
                {selectedProviderPeriod && (
                  <span className="text-xs text-ink-secondary">
                    Ending {weekEndingLabel(selectedProviderPeriod.period_key, selectedProviderPeriod.period_label)}
                  </span>
                )}
              </div>
              <div className="overflow-auto">
                <table className="w-full border-collapse" style={{ minWidth: 900 }}>
                  <thead>
                    <tr>
                      {["Date/Time", "DOS", "Setting", "Total RVU", "Payment", ""].map((h, i) => (
                        <th key={h} className={`${TH} ${i >= 3 && i <= 4 ? "text-right" : "text-left"}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {periodDrilldownLoading && (
                      <tr><td colSpan={6} className="px-4 py-5 text-sm text-ink-secondary"><span className="inline-flex items-center gap-2"><Spinner /> Loading...</span></td></tr>
                    )}
                    {periodDrilldownErr && (
                      <tr><td colSpan={6} className="px-4 py-5 text-sm text-red-600">{periodDrilldownErr}</td></tr>
                    )}
                    {!periodDrilldownLoading && !periodDrilldownErr && periodDrilldown?.scans.length === 0 && (
                      <tr><td colSpan={6} className="px-4 py-5 text-sm text-ink-secondary">No entries.</td></tr>
                    )}
                    {!periodDrilldownLoading && !periodDrilldownErr && periodDrilldown?.scans.map((scan) => {
                      const isEditing = editId === scan.id;
                      const isDeleteConfirm = deleteConfirmId === scan.id;
                      const isDeleting = deletingId === scan.id;
                      const canMutate = admin.role === "superadmin";
                      return [
                        <tr key={`provider-scan-${scan.id}`} className={`${isEditing ? "bg-brand-muted/60" : isDeleteConfirm ? "bg-red-50" : "hover:bg-surface-soft"}`}>
                          <td className={`${TD} text-xs whitespace-nowrap`}>{fmtDateTimeEt(scan.scanned_at)}</td>
                          <td className={`${TD} text-xs whitespace-nowrap`}>{fmtCalendarDateMdY(scan.service_date)}</td>
                          <td className={TD}>{scan.facility ? <span className="badge-blue">Facility</span> : <span className="badge-green">Non-Fac</span>}</td>
                          <td className={`${TD} text-right font-mono tabular-nums font-bold`}>{(scan.total_rvu ?? 0).toFixed(2)}</td>
                          <td className={`${TD} text-right font-mono tabular-nums`}>{fmt$(scan.total_payment ?? 0)}</td>
                          <td className={`${TD} text-right whitespace-nowrap`}>
                            {isDeleteConfirm ? (
                              <span className="inline-flex items-center gap-2">
                                <span className="text-xs font-bold text-red-600">Delete?</span>
                                <button onClick={() => void doDelete(scan.id)} disabled={isDeleting} className="btn-danger text-xs px-3 py-1.5">
                                  {isDeleting ? <Spinner className="w-3 h-3" /> : "Yes"}
                                </button>
                                <button onClick={() => setDeleteConfirmId(null)} className="btn-secondary text-xs px-2 py-1.5">No</button>
                              </span>
                            ) : (
                              <span className="inline-flex flex-wrap justify-end gap-2">
                                <button onClick={() => void openScanDetails(scan.id)} disabled={detailLoadingId === scan.id} className="text-ink text-xs font-semibold border border-brand-border rounded-lg px-2.5 py-1 hover:bg-surface-soft transition-colors disabled:opacity-60">
                                  {detailLoadingId === scan.id ? <Spinner className="w-3 h-3" /> : "Details"}
                                </button>
                                <button onClick={() => void openOcrReview(scan)} disabled={ocrReviewLoadingId === scan.id} className="text-amber-700 text-xs font-semibold border border-amber-200 rounded-lg px-2.5 py-1 hover:bg-amber-50 transition-colors disabled:opacity-60">
                                  {ocrReviewLoadingId === scan.id ? <Spinner className="w-3 h-3" /> : "Review OCR"}
                                </button>
                                {canMutate && (
                                  <>
                                    <button onClick={() => startAdd(scan)} className="text-emerald-700 text-xs font-semibold border border-emerald-200 rounded-lg px-2.5 py-1 hover:bg-emerald-50 transition-colors">Add</button>
                                    <button onClick={() => startEdit(scan)} className="text-indigo-600 text-xs font-semibold border border-indigo-200 rounded-lg px-2.5 py-1 hover:bg-indigo-50 transition-colors">Edit</button>
                                    <button onClick={() => { cancelEdit(); setDeleteConfirmId(scan.id); }} className="text-red-600 text-xs font-semibold border border-red-200 rounded-lg px-2.5 py-1 hover:bg-red-50 transition-colors">Delete</button>
                                  </>
                                )}
                              </span>
                            )}
                          </td>
                        </tr>,
                        isEditing && (
                          <EditRow
                            key={`provider-edit-${scan.id}`}
                            scan={scan}
                            draft={editDraft}
                            setDraft={setEditDraft}
                            saving={savingId === scan.id}
                            onSave={() => void saveEdit(scan.id)}
                            onCancel={cancelEdit}
                            colCount={7}
                            mode={editMode}
                          />
                        ),
                      ];
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="card overflow-hidden min-h-0 flex flex-col">
              <div className="px-4 py-3 border-b border-brand-border">
                <h2 className="text-sm font-black uppercase tracking-wide text-ink">CPT Stats</h2>
              </div>
              <div className="overflow-auto">
                <table className="w-full border-collapse" style={{ minWidth: 300 }}>
                  <thead>
                    <tr>
                      {["CPT", "Count", "wRVU"].map((h, i) => (
                        <th key={h} className={`${TH} ${i > 0 ? "text-right" : "text-left"}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(periodDrilldown?.cpt_mix ?? []).length === 0 && !periodDrilldownLoading && (
                      <tr><td colSpan={3} className="px-4 py-5 text-sm text-ink-secondary">No CPTs.</td></tr>
                    )}
                    {(periodDrilldown?.cpt_mix ?? []).map((cpt) => (
                      <tr key={cpt.cpt} className="hover:bg-surface-soft">
                        <td className={`${TD} font-mono font-bold`}>{cpt.cpt}</td>
                        <td className={`${TD} text-right font-mono tabular-nums`}>{cpt.count}</td>
                        <td className={`${TD} text-right font-mono tabular-nums font-bold`}>{cpt.wrvu.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}

      {ocrReviewScan && (
        <div onClick={() => { setOcrReviewScan(null); setOcrReviewRuns([]); }} className="fixed inset-0 z-[205] bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
          <div onClick={(e) => e.stopPropagation()} className="bg-surface rounded-2xl w-full max-w-6xl max-h-[90dvh] overflow-auto shadow-modal border border-brand-border">
            {(() => {
              const primaryRun = ocrReviewRuns.find(isPrimaryOcrRun) ?? ocrReviewRuns[0] ?? null;
              const otherRuns = primaryRun ? ocrReviewRuns.filter((run) => run.id !== primaryRun.id) : ocrReviewRuns;
              return (
                <>
                  <div className="px-5 py-4 border-b border-brand-border flex items-center gap-3">
                    <div>
                      <h3 className="text-base font-bold text-ink">Raw OCR review</h3>
                      <div className="text-xs text-ink-secondary">
                        Scan #{ocrReviewScan.id} · {ocrReviewScan.surgeon_name || "—"} · {fmtDateTimeEt(ocrReviewScan.scanned_at)}
                      </div>
                    </div>
                    <button onClick={() => { setOcrReviewScan(null); setOcrReviewRuns([]); }} className="ml-auto btn-secondary text-xs px-3 py-1.5">Close</button>
                  </div>
                  <div className="p-5 space-y-5">
                    {!primaryRun && (
                      <div className="card px-4 py-4 text-sm text-ink-secondary">
                        No raw OCR audit rows were saved for this scan. Only newer captures have this trace.
                      </div>
                    )}
                    {primaryRun && (
                      <div className="space-y-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="badge bg-amber-50 text-amber-700 border border-amber-200">Primary OCR</span>
                          <span className="text-xs text-ink-secondary">Stage: <span className="font-semibold text-ink">{primaryRun.stage}</span></span>
                          <span className="text-xs text-ink-secondary">Provider: <span className="font-semibold text-ink">{primaryRun.provider || "—"}</span></span>
                          <span className="text-xs text-ink-secondary">Model: <span className="font-mono text-ink">{primaryRun.model || "—"}</span></span>
                        </div>
                        <div className="grid gap-4 lg:grid-cols-2">
                          <div className="card overflow-hidden">
                            <div className="px-4 py-3 border-b border-brand-border">
                              <div className="text-sm font-bold text-ink">Raw model response</div>
                              <div className="text-[11px] text-ink-secondary">Exact first-pass OCR output before enrichment or edits.</div>
                            </div>
                            <pre className="p-4 text-[11px] leading-5 whitespace-pre-wrap break-words bg-surface-soft text-ink overflow-x-auto">{primaryRun.raw_response || "—"}</pre>
                          </div>
                          <div className="card overflow-hidden">
                            <div className="px-4 py-3 border-b border-brand-border">
                              <div className="text-sm font-bold text-ink">Parsed JSON</div>
                              <div className="text-[11px] text-ink-secondary">What the backend parsed from that same first-pass response.</div>
                            </div>
                            <pre className="p-4 text-[11px] leading-5 whitespace-pre-wrap break-words bg-surface-soft text-ink overflow-x-auto">{prettyJson(primaryRun.parsed_json)}</pre>
                          </div>
                        </div>
                        {primaryRun.error_text && (
                          <div className="card px-4 py-3 border-red-200 bg-red-50/60 text-sm text-red-700">
                            Error: {primaryRun.error_text}
                          </div>
                        )}
                      </div>
                    )}
                    {otherRuns.length > 0 && (
                      <div className="space-y-3">
                        <div className="text-sm font-bold text-ink">Follow-up passes</div>
                        <div className="space-y-3">
                          {otherRuns.map((run) => (
                            <div key={run.id} className="card overflow-hidden">
                              <div className="px-4 py-3 border-b border-brand-border flex flex-wrap items-center gap-2">
                                <span className="badge bg-surface-soft text-ink border border-brand-border">{run.stage}</span>
                                <span className="text-xs text-ink-secondary">Provider: <span className="font-semibold text-ink">{run.provider || "—"}</span></span>
                                <span className="text-xs text-ink-secondary">Model: <span className="font-mono text-ink">{run.model || "—"}</span></span>
                              </div>
                              <div className="grid gap-px bg-brand-border lg:grid-cols-2">
                                <pre className="bg-surface p-4 text-[11px] leading-5 whitespace-pre-wrap break-words text-ink overflow-x-auto">{run.raw_response || "—"}</pre>
                                <pre className="bg-surface p-4 text-[11px] leading-5 whitespace-pre-wrap break-words text-ink overflow-x-auto">{prettyJson(run.parsed_json)}</pre>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      )}

      {/* ══════════════ IMAGE LIGHTBOX ══════════════ */}
      {imageModal !== null && (
        <div
          onClick={closeScanImage}
          className="fixed inset-0 z-[200] bg-black/85 backdrop-blur-md flex items-center justify-center p-4 cursor-zoom-out"
        >
          <div className="max-w-full max-h-[90dvh] flex flex-col items-center gap-3" onClick={(e) => e.stopPropagation()}>
            {imageLoading && (
              <div className="text-white/85 text-sm inline-flex items-center gap-3">
                <Spinner className="w-5 h-5" />
                Loading scan image...
              </div>
            )}
            <img
              src={`/api/v1/portal/rvu/scans/${imageModal}/image`}
              alt="Scan photo"
              onLoad={() => setImageLoading(false)}
              onError={() => setImageLoading(false)}
              className={`max-w-full max-h-[78dvh] rounded-2xl shadow-modal ${imageLoading ? "hidden" : "block"}`}
            />
            <button onClick={closeScanImage} className="btn-secondary px-4 py-2 text-sm">Back to scans</button>
          </div>
          <button
            onClick={closeScanImage}
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
	                    <DetailMetric label="Total RVU" value={(detailScan.total_rvu ?? 0).toFixed(2)} />
	                    <DetailMetric label="wRVU" value={fin.workRvu.toFixed(2)} />
	                    <DetailMetric label="Value" value={fmt$(fin.surgeonValue)} />
	                    <DetailMetric label="Facility" value={fmt$(fin.facilityShare)} />
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

    </div>
  );
}
