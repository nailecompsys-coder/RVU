// ── localStorage token (fallback for iOS cookie isolation) ───────────────────
const LS_KEY = "rvu_surgeon_token";
const getLocalToken = (): string | null => {
  try { return localStorage.getItem(LS_KEY); } catch { return null; }
};
const setLocalToken = (t: string): void => {
  try { localStorage.setItem(LS_KEY, t); } catch { /* ignore */ }
};

/** True if this browser already stored a staff JWT (PWA / iOS home screen). */
export function hasStaffSession(): boolean {
  return Boolean(getLocalToken());
}

// Returns Authorization header if we have a local token stored
const authHeaders = (): Record<string, string> => {
  const t = getLocalToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
};

const json = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const r = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers as Record<string, string>),
    },
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || r.statusText);
  }
  return r.json() as Promise<T>;
};

export const api = {
  register: async (token: string) => {
    const r = await json<{ ok: boolean; token?: string; surgeon: Record<string, unknown> }>(
      "/api/v1/auth/register",
      { method: "POST", body: JSON.stringify({ token }) }
    );
    // Persist JWT to localStorage so it survives iOS cookie isolation
    if (r.token) setLocalToken(r.token);
    return r;
  },
  meStaff: () => json<StaffMe>("/api/v1/auth/me"),
  mePortal: () => json<PortalMe>("/api/v1/auth/portal/me"),
  portalLogin: (username: string, password: string) =>
    json<{ ok: boolean }>("/api/v1/auth/portal/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  portalLogout: () => json<{ ok: boolean }>("/api/v1/auth/portal/logout", { method: "POST" }),
  staffLogout: () => json<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" }),
  localities: () => json<LocalitiesResponse>("/api/v1/rvu/localities"),
  getVisionConfig: () => json<{ provider: string; vision_model: string; text_model: string }>("/api/v1/rvu/vision-config"),
  getStaffDevVisionConfig: () => json<{ provider: string; vision_model: string; text_model: string; openai_key_set?: string; anthropic_key_set?: string }>("/api/v1/rvu/dev/vision-config"),
  patchStaffDevVisionConfig: (body: { provider?: string; vision_model?: string; openai_api_key?: string; anthropic_api_key?: string }) =>
    json<{ provider: string; vision_model: string; text_model: string; openai_key_set?: string; anthropic_key_set?: string }>("/api/v1/rvu/dev/vision-config", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  history: () => json<{ scans: ScanRow[] }>("/api/v1/rvu/history"),
  portalScans: (limit = 100, offset = 0, options?: { scannedOn?: string }) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (options?.scannedOn) params.set("scanned_on", options.scannedOn);
    return json<PortalScansResponse>(`/api/v1/portal/rvu/scans?${params.toString()}`);
  },
  portalDashboard: (range = "month", groupBy = "week", providerId?: number | null) => {
    const qs = new URLSearchParams({ range, group_by: groupBy });
    if (providerId != null) qs.set("provider_id", String(providerId));
    return json<PortalDashboardResponse>(`/api/v1/portal/rvu/dashboard?${qs.toString()}`);
  },
  portalDashboardDrilldown: (params: { range?: string; groupBy?: string; providerId?: number; periodKey?: string; day?: string; limit?: number }) => {
    const qs = new URLSearchParams({
      range: params.range ?? "month",
      group_by: params.groupBy ?? "week",
      limit: String(params.limit ?? 250),
    });
    if (params.providerId != null) qs.set("provider_id", String(params.providerId));
    if (params.periodKey) qs.set("period_key", params.periodKey);
    if (params.day) qs.set("day", params.day);
    return json<PortalDashboardDrilldownResponse>(`/api/v1/portal/rvu/dashboard/drilldown?${qs.toString()}`);
  },
  portalScanDetail: (id: number) =>
    json<PortalScanRow>(`/api/v1/portal/rvu/scans/${id}`),
  portalScanAiRuns: (id: number) =>
    json<{ scan_id: number; ai_runs: PortalScanAiRun[] }>(`/api/v1/portal/rvu/scans/${id}/ai-runs`),
  adminStaff: (includeInactive = false) =>
    json<{ staff: StaffMember[] }>(`/api/v1/auth/admin/staff${includeInactive ? "?include_inactive=true" : ""}`),
  createStaff: (body: StaffCreateBody) =>
    json<StaffMember>("/api/v1/auth/admin/staff", { method: "POST", body: JSON.stringify(body) }),
  patchStaff: (id: number, body: StaffPatchBody) =>
    json<StaffMember>(`/api/v1/auth/admin/staff/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  listDevices: () => json<{ devices: DeviceRecord[] }>("/api/v1/auth/admin/devices"),
  patchDevice: (id: number, body: { is_active: boolean }) =>
    json<DeviceRecord>(`/api/v1/auth/admin/devices/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  patchScan: (id: number, body: ScanPatchBody) =>
    json<PortalScanRow>(`/api/v1/portal/rvu/scans/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteScan: async (id: number) => {
    const r = await fetch(`/api/v1/portal/rvu/scans/${id}`, {
      method: "DELETE",
      credentials: "include",
      headers: authHeaders(),
    });
    if (!r.ok && r.status !== 204) {
      const err = await r.json().catch(() => ({}));
      throw new Error((err as { detail?: string }).detail || r.statusText);
    }
  },
  listPortalUsers: () => json<{ users: PortalUserRecord[] }>("/api/v1/auth/portal/users"),
  createPortalUser: (body: PortalUserCreateBody) =>
    json<PortalUserRecord>("/api/v1/auth/portal/users", { method: "POST", body: JSON.stringify(body) }),
  patchPortalUser: (id: number, body: PortalUserPatchBody) =>
    json<PortalUserRecord>(`/api/v1/auth/portal/users/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deletePortalUser: async (id: number) => {
    const r = await fetch(`/api/v1/auth/portal/users/${id}`, {
      method: "DELETE",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...authHeaders() },
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error((err as { detail?: string }).detail || r.statusText);
    }
    return r.json() as Promise<{ ok: boolean }>;
  },
  listPortalOpNotes: () => json<{ notes: OpNoteRow[] }>("/api/v1/portal/rvu/op-notes"),
  getDevVisionConfig: () => json<{ provider: string; vision_model: string; text_model: string; openai_key_set?: string; anthropic_key_set?: string }>("/api/v1/portal/rvu/dev/vision-config"),
  patchDevVisionConfig: (body: { provider?: string; vision_model?: string; openai_api_key?: string; anthropic_api_key?: string }) =>
    json<{ provider: string; vision_model: string; text_model: string; openai_key_set?: string; anthropic_key_set?: string }>("/api/v1/portal/rvu/dev/vision-config", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  portalModifierRules: () => json<{ modifiers: ModifierRule[] }>("/api/v1/portal/rvu/modifier-rules"),
  patchPortalModifierRule: (code: string, body: { desc?: string; factor?: number; needs_review?: boolean }) =>
    json<ModifierRule>(`/api/v1/portal/rvu/modifier-rules/${encodeURIComponent(code)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deletePortalOpNote: async (id: number) => {
    const r = await fetch(`/api/v1/portal/rvu/op-notes/${id}`, {
      method: "DELETE",
      credentials: "include",
      headers: authHeaders(),
    });
    if (!r.ok && r.status !== 204) {
      const err = await r.json().catch(() => ({}));
      throw new Error((err as { detail?: string }).detail || r.statusText);
    }
  },
  uploadOpNote: async (blob: Blob) => {
    const fd = new FormData();
    fd.append("image", blob, "opnote.jpg");
    const r = await fetch("/api/v1/rvu/op-note", {
      method: "POST",
      credentials: "include",
      headers: authHeaders(),
      body: fd,
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error((err as { detail?: string }).detail || r.statusText);
    }
    return r.json() as Promise<{
      ok: boolean;
      id: number;
      extracted_text: string;
      image_kb: number;
      elapsed_secs: number;
      ai_model: string;
    }>;
  },
  lookup: (body: LookupBody) =>
    json<LookupResponse>("/api/v1/rvu/lookup", { method: "POST", body: JSON.stringify(body) }),
  preview: (body: LookupBody) =>
    json<LookupResponse>("/api/v1/rvu/preview", { method: "POST", body: JSON.stringify(body) }),
  commit: async (body: CommitBody, imageBlob?: Blob): Promise<CommitResponse> => {
    const fd = new FormData();
    fd.append("cpts", JSON.stringify(body.cpts));
    fd.append("locality", body.locality);
    fd.append("facility", String(body.facility));
    fd.append("cf", String(body.cf));
    if (body.service_date) fd.append("service_date", body.service_date);
    if (body.mrn) fd.append("mrn", body.mrn);
    fd.append("lines", JSON.stringify(body.lines ?? []));
    fd.append("ai_model", body.ai_model ?? "vision");
    fd.append("image_kb", String(body.image_kb ?? 0));
    fd.append("elapsed_secs", String(body.elapsed_secs ?? 0));
    if (imageBlob) fd.append("image", imageBlob, "scan.jpg");
    const r = await fetch("/api/v1/rvu/commit", { method: "POST", credentials: "include", headers: authHeaders(), body: fd });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error((err as { detail?: string }).detail || r.statusText);
    }
    return r.json() as Promise<CommitResponse>;
  },
  consumeRvuSse: async (
    url: string,
    init: RequestInit,
    handlers: { onToken?: (t: string) => void; onStatus?: (msg: string) => void; onError?: (msg: string) => void }
  ): Promise<RvuStreamDone | null> => {
    const r = await fetch(url, { ...init, credentials: "include", headers: { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) } });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error((err as { detail?: string }).detail || r.statusText);
    }
    const reader = r.body?.getReader();
    if (!reader) return null;
    const dec = new TextDecoder();
    let buf = "";
    let donePayload: RvuStreamDone | null = null;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const block of parts) {
        const parsed = parseSseBlock(block);
        if (!parsed) continue;
        if (parsed.event === "token" && handlers.onToken) {
          try {
            const j = JSON.parse(parsed.data) as { t?: string };
            if (j.t) handlers.onToken(j.t);
          } catch {
            /* ignore */
          }
        }
        if (parsed.event === "status") {
          try {
            const j = JSON.parse(parsed.data) as { msg?: string };
            if (j.msg) handlers.onStatus?.(j.msg);
          } catch {
            /* ignore */
          }
        }
        if (parsed.event === "error") {
          try {
            const j = JSON.parse(parsed.data) as { msg?: string };
            handlers.onError?.(j.msg || "Stream error");
          } catch {
            handlers.onError?.("Stream error");
          }
          return null;
        }
        if (parsed.event === "done") {
          try {
            donePayload = JSON.parse(parsed.data) as RvuStreamDone;
          } catch {
            /* ignore */
          }
        }
      }
    }
    return donePayload;
  },
};

function parseSseBlock(block: string): { event: string; data: string } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

export type StaffMe = {
  id: number;
  full_name: string;
  staff_type: string;
  email: string | null;
  suffix: string | null;
};

export type PortalMe = { id: number; username: string; email: string; role: string };

export type ModifierRule = {
  code: string;
  desc: string;
  factor: number;
  source?: string;
  needs_review?: boolean;
  added_by_staff_id?: number;
  added_by_staff_name?: string;
  added_at?: string;
};

export type PortalUserRecord = {
  id: number;
  username: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string | null;
};

export type PortalUserCreateBody = {
  username: string;
  email: string;
  password: string;
  role?: string;
};

export type PortalUserPatchBody = {
  email?: string;
  password?: string;
  role?: string;
  is_active?: boolean;
};

export type OpNoteRow = {
  id: number;
  surgeon_id: number;
  surgeon_name: string | null;
  scanned_at: string | null;
  image_kb: number;
  extracted_text: string;
  ai_model: string | null;
  elapsed_secs: number | null;
  has_image: boolean;
};

export type LocalitiesResponse = {
  localities: { locality_num: string; locality_name: string; state: string }[];
  cf: number;
};

export type CaptureLine = {
  cpt: string;
  procedure_name: string;
  provider_name?: string;
  provider_role?: string;
  modifier?: string;
  is_assist?: boolean;
};

export type ScanRow = {
  id: number;
  scanned_at: string | null;
  /** ISO UTC instant from API (preferred when present) */
  scanned_at_et?: string | null;
  scanned_at_label?: string | null;
  service_date?: string | null;
  patient_name?: string | null;
  mrn?: string | null;
  line_items?: unknown;
  /** Legacy JSON string of CPT list from API; parsed LineItem[] in UI */
  cpts?: unknown;
  total_rvu: number;
  total_payment: number;
  cf?: number;
  locality_num?: string | null;
  locality_name: string | null;
  facility: boolean;
  ai_model: string | null;
  has_image?: boolean;
  scan_status?: string | null;
  status_label?: string | null;
  main_cpt?: string | null;
  main_cpt_status?: string | null;
  review_reason?: string | null;
  elapsed_secs?: number | null;
  ocr_elapsed_label?: string | null;
  surgeon_name?: string | null;
  staff_type?: string | null;
  cpt_count?: number;
  work_rvu?: number;
  surgeon_value?: number;
  facility_share?: number;
  assist_count?: number;
};

export type PortalScanRow = ScanRow & {
  surgeon_id: number;
  surgeon_name: string | null;
  staff_type: string | null;
};

export type PortalScansResponse = {
  scans: PortalScanRow[];
  limit: number;
  offset: number;
  total_count: number;
  has_more: boolean;
};

export type PortalDashboardMetric = {
  patients: number;
  scans: number;
  verified_scans: number;
  case_count: number;
  cpt_lines: number;
  wrvu: number;
  est_payment: number;
  avg_wrvu_per_patient: number;
  avg_wrvu_per_case: number;
  avg_payment_per_case: number;
  annualized_wrvu_run_rate: number;
  annualized_est_payment_run_rate: number;
  rolling_7_day_avg_wrvu: number;
  rolling_30_day_avg_wrvu: number;
  best_day: PortalDashboardBestDay | null;
  active_scanners: number;
  pending_review: number;
  missing_mrn: number;
  missing_service_date: number;
};

export type PortalDashboardBestDay = {
  date: string;
  wrvu: number;
  est_payment: number;
  case_count: number;
  scans: number;
};

export type PortalDashboardProvider = PortalDashboardMetric & {
  provider_id: number;
  provider_name: string;
  role: string | null;
  is_active: boolean;
  last_scan: string | null;
  top_cpt: string | null;
};

export type PortalDashboardPeriod = PortalDashboardMetric & {
  period_key: string;
  period_label: string;
};

export type PortalDashboardProviderPeriod = PortalDashboardPeriod & {
  provider_id: number;
  provider_name: string;
};

export type PortalDashboardCpt = {
  cpt: string;
  count: number;
  patients: number;
  wrvu: number;
  est_payment: number;
  providers: number;
};

export type PortalDashboardProviderOption = {
  provider_id: number;
  provider_name: string;
  role: string | null;
  is_active: boolean;
};

export type PortalDashboardResponse = {
  range: { key: string; start: string; end: string; group_by: string };
  selected_provider_id: number | null;
  practice: PortalDashboardMetric & { inactive_scanners: number };
  provider_options: PortalDashboardProviderOption[];
  providers: PortalDashboardProvider[];
  periods: PortalDashboardPeriod[];
  provider_periods: PortalDashboardProviderPeriod[];
  cpt_mix: PortalDashboardCpt[];
};

export type PortalDashboardDayCptMix = {
  day: string;
  day_label: string;
  cpt_mix: PortalDashboardCpt[];
};

export type PortalDashboardDrilldownResponse = {
  range: { key: string; start: string; end: string; group_by: string };
  provider_id: number | null;
  period_key: string | null;
  period_label: string | null;
  metrics: PortalDashboardMetric;
  scans: PortalScanRow[];
  cpt_mix: PortalDashboardCpt[];
  day_cpt_mix: PortalDashboardDayCptMix[];
  limit: number;
  has_more: boolean;
};

export type PortalScanAiRun = {
  id: number;
  scan_id: number;
  sequence_num: number;
  stage: string;
  provider: string | null;
  model: string | null;
  raw_response: string | null;
  parsed_json: Record<string, unknown> | unknown[] | null;
  error_text: string | null;
  created_at: string | null;
  created_at_et: string | null;
};

export type ScanPatchBody = {
  service_date?: string | null;
  mrn?: string | null;
  locality_num?: string;
  locality_name?: string;
  facility?: boolean;
  cpts?: string[];
};

export type StaffMember = {
  id: number;
  first_name: string;
  last_name: string;
  full_name: string;
  staff_type: string | null;
  email: string | null;
  phone: string | null;
  suffix: string | null;
  is_active: boolean;
};

export type StaffPatchBody = {
  first_name?: string;
  last_name?: string;
  suffix?: string;
  staff_type?: string;
  email?: string;
  phone?: string;
  is_active?: boolean;
};

export type DeviceRecord = {
  id: number;
  surgeon_id: number;
  surgeon_name: string;
  device_name: string;
  user_agent: string | null;
  registered_at: string | null;
  last_seen: string | null;
  is_active: boolean;
};

export type StaffCreateBody = {
  first_name: string;
  last_name: string;
  suffix?: string;
  staff_type?: string;
  email?: string;
  phone?: string;
};

export type LookupBody = {
  cpts: string[];
  locality: string;
  facility: boolean;
  cf: number;
};

export type LookupResponse = { cpts: string[]; rows: unknown[]; total_payment: number };

export type CommitBody = {
  cpts: string[];
  locality: string;
  facility: boolean;
  cf: number;
  service_date?: string | null;
  mrn?: string | null;
  lines: CaptureLine[];
  ai_model: string;
  image_kb: number;
  elapsed_secs: number;
};

export type CommitResponse = LookupResponse & { line_items: unknown[] };

export type RvuStreamDone = LookupResponse & {
  service_date?: string | null;
  mrn?: string | null;
  surgeon_name?: string | null;
  lines?: CaptureLine[];
  doc_type_guess?: "charge_sheet" | "op_note" | "unknown";
  elapsed_secs?: number;
  persisted?: boolean;
  ai_model?: string;
};
