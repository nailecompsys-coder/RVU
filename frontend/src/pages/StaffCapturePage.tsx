import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type CommitBody, type LocalitiesResponse, type RvuStreamDone } from "../api/client";

// ── Types ─────────────────────────────────────────────────────────────────────
type Locality = { locality_num: string; locality_name: string; state: string };
type PayRow = {
  CPT?: string; cpt?: string; desc?: string;
  work_rvu?: number; pe_rvu?: number; pe_nonfac_rvu?: number; pe_fac_rvu?: number;
  mp_rvu?: number; total_rvu?: number; payment?: number;
};
type PillState = "hidden" | "loading" | "ok" | "err";

// ── Spinner SVG ───────────────────────────────────────────────────────────────
function Spinner({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function StaffCapturePage() {
  const nav = useNavigate();
  const FIXED_CF = 41.0;
  const [locData, setLocData] = useState<LocalitiesResponse | null>(null);
  const [locality, setLocality] = useState("99");
  const [facility, setFacility] = useState(true);
  const [cf] = useState(FIXED_CF);

  const [pill, setPill] = useState<{ state: PillState; msg: string }>({ state: "hidden", msg: "" });
  const [elapsed, setElapsed] = useState("");
  const [thinkText, setThinkText] = useState("");
  const [showThink, setShowThink] = useState(false);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [rows, setRows] = useState<PayRow[]>([]);
  const [aiModel, setAiModel] = useState("");
  const [showResults, setShowResults] = useState(false);

  const [approvalCpts, setApprovalCpts] = useState<string[]>([]);
  const [approvalDos, setApprovalDos] = useState("");
  const [approvalMrn, setApprovalMrn] = useState("");
  const [parsedSurgeonName, setParsedSurgeonName] = useState("");
  const [approvalLines, setApprovalLines] = useState<CommitBody["lines"]>([]);
  const [approvalElapsed, setApprovalElapsed] = useState(0);
  const [capturedBlob, setCapturedBlob] = useState<Blob | null>(null);
  const [newCptInput, setNewCptInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [workMode, setWorkMode] = useState<"rvu" | "opnote">("rvu");
  const [scanMode, setScanMode] = useState<"fast" | "balanced" | "thorough">("balanced");
  const [manualCptQuick, setManualCptQuick] = useState("");
  const [opNoteBusy, setOpNoteBusy] = useState(false);
  const [opNotePreviewSrc, setOpNotePreviewSrc] = useState<string | null>(null);
  const [opNoteBlob, setOpNoteBlob] = useState<Blob | null>(null);
  const [devCfg, setDevCfg] = useState<{ provider: string; vision_model: string; text_model: string } | null>({
    provider: "ollama",
    vision_model: "default",
    text_model: "default",
  });
  const [devCanEdit, setDevCanEdit] = useState(false);
  const [devProvider, setDevProvider] = useState("ollama");
  const [devModel, setDevModel] = useState("");
  const [devOpenAiKey, setDevOpenAiKey] = useState("");
  const [devAnthropicKey, setDevAnthropicKey] = useState("");
  const [devSaving, setDevSaving] = useState(false);
  const [devErr, setDevErr] = useState<string | null>(null);
  const defaultModelForProvider = (p: string) =>
    p === "openai" ? "gpt-4o-mini" : p === "anthropic" ? "claude-3-5-sonnet-latest" : p === "paddle" ? "paddleocr" : "qwen2.5vl:7b";

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const t0Ref = useRef(0);
  const thinkRef = useRef<HTMLDivElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const opNoteCameraRef = useRef<HTMLInputElement>(null);
  const opNoteFileRef = useRef<HTMLInputElement>(null);
  const approvalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.meStaff()
      .then(async () => {
        // Read-only active engine badge for all staff users.
        try {
          const cfg = await api.getVisionConfig();
          setDevCfg(cfg);
          setDevProvider(cfg.provider);
          setDevModel(cfg.vision_model);
        } catch {
          /* ignore */
        }
        // Edit controls only for configured developer staff account(s).
        try {
          const cfg = await api.getStaffDevVisionConfig();
          setDevCfg(cfg);
          setDevProvider(cfg.provider);
          setDevModel(cfg.vision_model);
          setDevCanEdit(true);
        } catch {
          setDevCanEdit(false);
        }
      })
      .catch(() => nav("/register", { replace: true }));
    api.localities().then((d) => {
      setLocData(d);
      const restOfFl = d.localities.find((l) => l.locality_num === "99");
      const firstFl  = d.localities.find((l) => l.state === "FL");
      const target = restOfFl ?? firstFl;
      if (target) setLocality(target.locality_num);
    }).catch(() => {});
  }, [nav]);

  // ── Pill helpers ──────────────────────────────────────────────────────────
  const pillSet = (msg: string, state: PillState = "loading") => {
    setPill({ state, msg });
    if (timerRef.current) clearInterval(timerRef.current);
    if (state === "loading") {
      t0Ref.current = Date.now();
      setElapsed("0s");
      timerRef.current = setInterval(() => {
        setElapsed(((Date.now() - t0Ref.current) / 1000).toFixed(0) + "s");
      }, 500);
    } else {
      setElapsed("");
    }
  };
  const pillHide = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    setPill({ state: "hidden", msg: "" });
    setElapsed("");
  };

  const getLocObj = (): Locality =>
    locData?.localities.find((l) => l.locality_num === locality) ||
    { locality_num: "00", locality_name: "", state: "" };

  const recalc = (rawRows: PayRow[]): PayRow[] =>
    rawRows.map((r) => {
      const pe = facility ? (r.pe_fac_rvu ?? 0) : (r.pe_nonfac_rvu ?? r.pe_rvu ?? 0);
      return { ...r, pe_rvu: pe };
    });

  const resizeImage = (file: File, maxDim = 1536, quality = 0.88): Promise<Blob> =>
    new Promise((resolve, reject) => {
      const fallback = () => resolve(new Blob([file], { type: "image/jpeg" }));
      const img = new window.Image();
      const url = URL.createObjectURL(file);
      const timer = setTimeout(() => { URL.revokeObjectURL(url); fallback(); }, 8000);
      img.onerror = () => { clearTimeout(timer); URL.revokeObjectURL(url); fallback(); };
      img.onload = () => {
        clearTimeout(timer);
        URL.revokeObjectURL(url);
        try {
          const { naturalWidth: w, naturalHeight: h } = img;
          const scale = Math.min(1, maxDim / Math.max(w, h));
          const canvas = document.createElement("canvas");
          canvas.width = Math.round(w * scale) || 800;
          canvas.height = Math.round(h * scale) || 600;
          canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
          canvas.toBlob((b) => { if (b) resolve(b); else fallback(); }, "image/jpeg", quality);
        } catch { fallback(); }
      };
      img.src = url;
      void Promise.resolve().then(() => { if (!img.src) reject(new Error("Could not load image")); });
    });

  const loadApproval = (done: RvuStreamDone) => {
    setApprovalCpts(done.cpts ?? []);
    setApprovalDos(done.service_date ?? "");
    setApprovalMrn(done.mrn ?? "");
    setParsedSurgeonName(done.surgeon_name ?? "");
    setApprovalLines(
      (done.lines ?? []).map((l) => ({
        cpt: l.cpt ?? "",
        procedure_name: l.procedure_name ?? "",
        provider_name: l.provider_name ?? "",
        provider_role: l.provider_role ?? "unknown",
        modifier: l.modifier ?? "",
        is_assist: Boolean(l.is_assist),
      }))
    );
    setApprovalElapsed(done.elapsed_secs ?? 0);
  };

  const sendVision = async (file: File) => {
    setPreviewSrc(URL.createObjectURL(file));
    setBusy(true);
    setShowThink(true);
    setThinkText("");
    setShowResults(false);
    setCapturedBlob(null);
    pillSet("Resizing image…");
    try {
      const small = await resizeImage(file);
      setCapturedBlob(small);
      pillSet(`Uploading ${Math.round(small.size / 1024)} KB to AI…`);
      const fd = new FormData();
      fd.append("image", small, "photo.jpg");
      fd.append("locality", locality);
      fd.append("facility", String(facility));
      fd.append("cf", String(cf));
      fd.append("scan_mode", scanMode);
      const done: RvuStreamDone | null = await api.consumeRvuSse(
        "/api/v1/rvu/vision-stream", { method: "POST", body: fd },
        {
          onStatus: (msg) => pillSet(msg),
          onToken: (t) => {
            setThinkText((s) => s + t);
            if (thinkRef.current) thinkRef.current.scrollTop = thinkRef.current.scrollHeight;
          },
          onError: (msg) => { pillSet(msg, "err"); setBusy(false); },
        }
      );
      setBusy(false);
      if (!done) return;
      const t = ((Date.now() - t0Ref.current) / 1000).toFixed(1);
      let opNoteAutoSaved = false;
      if (done.doc_type_guess === "op_note") {
        try {
          const op = await api.uploadOpNote(small);
          if (opNotePreviewSrc) URL.revokeObjectURL(opNotePreviewSrc);
          setOpNotePreviewSrc(URL.createObjectURL(file));
          setOpNoteBlob(new File([small], "opnote.jpg", { type: small.type || "image/jpeg" }));
          opNoteAutoSaved = true;
          pillSet(`Detected OP note and saved (${op.image_kb} KB) ✓`, "ok");
        } catch {
          // Keep RVU flow even if OP note save fails.
        }
      }
      if (!(done.rows ?? []).length) {
        pillSet(
          opNoteAutoSaved
            ? "Detected OP note — saved to portal"
            : "No CPT codes found — try a clearer photo",
          opNoteAutoSaved ? "ok" : "err"
        );
      } else {
        pillSet(
          `${done.cpts?.length ?? 0} CPT code(s) found in ${t}s — review below${opNoteAutoSaved ? " · OP note also saved" : ""}`,
          "ok"
        );
        setAiModel(done.ai_model ?? "");
        setRows(done.rows as PayRow[]);
        setShowResults(true);
        loadApproval(done);
        setTimeout(() => approvalRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
      }
    } catch (err: unknown) {
      setBusy(false);
      setShowThink(false);
      pillSet(err instanceof Error ? err.message : "Scan failed — check connection", "err");
    }
  };

  const sendText = async () => {
    if (!pasteText.trim()) { pillSet("Paste some text first", "err"); return; }
    setBusy(true);
    setShowThink(true);
    setThinkText("");
    setShowResults(false);
    setPreviewSrc(null);
    setCapturedBlob(null);
    pillSet("Sending to local AI…");
    try {
      const done: RvuStreamDone | null = await api.consumeRvuSse(
        "/api/v1/rvu/text-stream",
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ raw_text: pasteText, locality, facility, cf }) },
        {
          onStatus: (msg) => pillSet(msg),
          onToken: (t) => {
            setThinkText((s) => s + t);
            if (thinkRef.current) thinkRef.current.scrollTop = thinkRef.current.scrollHeight;
          },
          onError: (msg) => { pillSet(msg, "err"); setBusy(false); },
        }
      );
      setBusy(false);
      setShowThink(false);
      if (!done) return;
      const t = ((Date.now() - t0Ref.current) / 1000).toFixed(1);
      if (!(done.rows ?? []).length) {
        pillSet("No CPT codes found", "err");
      } else {
        pillSet(`${done.cpts?.length ?? 0} CPT code(s) found in ${t}s — review below`, "ok");
        setAiModel(done.ai_model ?? "");
        setRows(done.rows as PayRow[]);
        setShowResults(true);
        loadApproval(done);
        setTimeout(() => approvalRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
      }
    } catch (err: unknown) {
      setBusy(false);
      setShowThink(false);
      pillSet(err instanceof Error ? err.message : "Extract failed", "err");
    }
  };

  const commitScan = async () => {
    if (!approvalCpts.length) return;
    setSaving(true);
    try {
      await api.commit({
        cpts: approvalCpts, locality, facility, cf,
        service_date: approvalDos || null, mrn: approvalMrn || null,
        lines: approvalLines ?? [], ai_model: aiModel || "vision",
        image_kb: capturedBlob ? Math.round(capturedBlob.size / 1024) : 0,
        elapsed_secs: approvalElapsed,
      }, capturedBlob ?? undefined);
      pillSet("Saved ✓ — ready for next", "ok");
      window.setTimeout(() => {
        clearResults();
        pillHide();
      }, 900);
    } catch (err: unknown) {
      pillSet(err instanceof Error ? err.message : "Save failed", "err");
    } finally {
      setSaving(false);
    }
  };

  const removeCpt = (code: string) => {
    setApprovalCpts((prev) => prev.filter((c) => c !== code));
    setApprovalLines((prev) => (prev ?? []).filter((l) => l.cpt !== code));
    setRows((prev) => prev.filter((r) => (r.CPT ?? r.cpt) !== code));
  };

  const addCpt = () => {
    const code = newCptInput.trim().replace(/\D/g, "").slice(0, 5);
    if (!code || approvalCpts.includes(code)) { setNewCptInput(""); return; }
    setApprovalCpts((prev) => [...prev, code]);
    setNewCptInput("");
  };

  const clearResults = () => {
    setShowResults(false); setRows([]); setPreviewSrc(null); setThinkText(""); setShowThink(false);
    setApprovalCpts([]); setApprovalDos(""); setApprovalMrn(""); setCapturedBlob(null);
    setParsedSurgeonName("");
    pillHide(); setBusy(false);
    if (cameraRef.current) cameraRef.current.value = "";
    if (fileRef.current) fileRef.current.value = "";
  };

  const loadManualCpts = async () => {
    const codes = manualCptQuick
      .split(/[\s,;]+/)
      .map((c) => c.replace(/\D/g, "").slice(0, 5))
      .filter((c) => c.length === 5);
    const uniq = [...new Set(codes)];
    if (!uniq.length) {
      pillSet("Enter valid 5-digit CPT codes", "err");
      return;
    }
    setBusy(true);
    pillSet("Loading fee schedule…");
    try {
      const p = await api.preview({ cpts: uniq, locality, facility, cf });
      setBusy(false);
      pillHide();
      if (!(p.rows as PayRow[]).length) {
        pillSet("No matching CPT rows", "err");
        return;
      }
      setAiModel("manual");
      setRows(p.rows as PayRow[]);
      setShowResults(true);
      setApprovalCpts(p.cpts ?? uniq);
      setApprovalDos("");
      setApprovalMrn("");
      setApprovalLines((p.cpts ?? uniq).map((cpt) => ({ cpt, procedure_name: "" })));
      setApprovalElapsed(0);
      setCapturedBlob(null);
      setPreviewSrc(null);
      setThinkText("");
      setShowThink(false);
      setManualCptQuick("");
      setTimeout(() => approvalRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 100);
    } catch (err: unknown) {
      setBusy(false);
      pillSet(err instanceof Error ? err.message : "Lookup failed", "err");
    }
  };

  const sendOpNotePhoto = async (file: File) => {
    setOpNoteBusy(true);
    pillSet("Uploading OP note…");
    try {
      const small = await resizeImage(file, 1600, 0.85);
      pillSet("Reading document (local AI)…");
      const r = await api.uploadOpNote(small);
      setOpNoteBusy(false);
      pillSet(`OP note saved (${r.image_kb} KB) ✓`, "ok");
      window.setTimeout(() => {
        pillHide();
        if (opNotePreviewSrc) URL.revokeObjectURL(opNotePreviewSrc);
        setOpNotePreviewSrc(null);
        setOpNoteBlob(null);
        if (opNoteCameraRef.current) opNoteCameraRef.current.value = "";
        if (opNoteFileRef.current) opNoteFileRef.current.value = "";
      }, 1200);
    } catch (err: unknown) {
      setOpNoteBusy(false);
      pillSet(err instanceof Error ? err.message : "Upload failed", "err");
    }
  };

  const stageOpNotePhoto = (file: File) => {
    if (opNotePreviewSrc) URL.revokeObjectURL(opNotePreviewSrc);
    setOpNotePreviewSrc(URL.createObjectURL(file));
    setOpNoteBlob(file);
    pillSet("Photo captured — review then save", "ok");
  };

  const clearOpNoteDraft = () => {
    if (opNotePreviewSrc) URL.revokeObjectURL(opNotePreviewSrc);
    setOpNotePreviewSrc(null);
    setOpNoteBlob(null);
    if (opNoteCameraRef.current) opNoteCameraRef.current.value = "";
    if (opNoteFileRef.current) opNoteFileRef.current.value = "";
    pillHide();
  };

  const displayRows = recalc(rows);
  const sumPay = displayRows.reduce((a, r) => a + (r.payment ?? 0), 0);
  const sumRvu = displayRows.reduce((a, r) => a + (r.total_rvu ?? 0), 0);
  const sumWorkRvu = displayRows.reduce((a, r) => a + (r.work_rvu ?? 0), 0);
  const surgeonValue = sumWorkRvu * cf;
  const assistLines = approvalLines.filter((l) => Boolean(l.is_assist) || (l.provider_role ?? "").toLowerCase() === "pa" || (l.modifier ?? "").toUpperCase().includes("AS"));
  const loc = getLocObj();

  const pillColors = {
    hidden: "",
    loading: "bg-surface border-brand-border text-ink",
    ok:     "bg-green-50 border-green-200 text-green-700",
    err:    "bg-red-50 border-red-200 text-red-600",
  };

  return (
    <div className="min-h-dvh bg-surface-soft text-ink pb-10 font-sans">
      <div className="max-w-2xl mx-auto px-4 pt-4">

        {/* ── Header ── */}
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-brand-border">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 bg-brand-gradient rounded-xl flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <span className="font-bold text-sm">RVU Estimator</span>
            <span className="badge badge-blue text-[10px]">β 1.2</span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              to="/done"
              className="btn-secondary px-4 py-2.5 text-sm font-bold"
            >
              Done
            </Link>
            <Link
              to="/history"
              className="text-xs font-semibold text-brand-blue hover:opacity-80 transition-opacity"
            >
              History
            </Link>
          </div>
        </div>

        {/* ── Work mode ── */}
        <div className="grid grid-cols-2 gap-2 mb-3">
          <button
            type="button"
            onClick={() => { setWorkMode("rvu"); pillHide(); }}
            className={`py-3 rounded-xl text-sm font-bold transition-colors ${workMode === "rvu" ? "bg-brand-gradient text-white shadow-card" : "bg-surface border border-brand-border text-ink-secondary"}`}
          >
            RVU (charges)
          </button>
          <button
            type="button"
            onClick={() => { setWorkMode("opnote"); clearResults(); pillHide(); }}
            className={`py-3 rounded-xl text-sm font-bold transition-colors ${workMode === "opnote" ? "bg-brand-gradient text-white shadow-card" : "bg-surface border border-brand-border text-ink-secondary"}`}
          >
            OP note photo
          </button>
        </div>

        {workMode === "opnote" ? (
          <div className="card p-4 mb-3">
            <p className="label mb-1">Operative note</p>
            <p className="text-xs text-ink-secondary mb-3">
              Photo is stored in the portal; text is extracted on the server with local AI (no separate OCR step on the phone).
            </p>
            <input
              ref={opNoteCameraRef}
              id="opnote-camera-input"
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (opNoteCameraRef.current) opNoteCameraRef.current.value = "";
                if (f) stageOpNotePhoto(f);
              }}
            />
            <label
              htmlFor={opNoteBusy ? "" : "opnote-camera-input"}
              className={`flex flex-col items-center justify-center gap-1.5 w-full h-24 rounded-2xl border-2 border-dashed transition-all select-none mb-2
                ${opNoteBusy ? "border-brand-blue/40 bg-brand-muted cursor-not-allowed" : "border-brand-border bg-surface-soft hover:border-brand-blue/50 cursor-pointer"}`}
            >
              {opNoteBusy ? (
                <>
                  <Spinner className="w-6 h-6 text-brand-blue" />
                  <span className="text-xs font-semibold text-brand-blue">Working…</span>
                </>
              ) : (
                <>
                  <svg className="w-7 h-7 text-brand-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round"
                      d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                  <span className="text-sm font-semibold text-brand-blue">Snap OP note</span>
                </>
              )}
            </label>
            <label className="flex items-center justify-center gap-2 w-full text-xs text-brand-blue font-semibold cursor-pointer py-2">
              <input
                ref={opNoteFileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) stageOpNotePhoto(f);
                }}
              />
              Or choose from gallery
            </label>
            {opNotePreviewSrc && (
              <div className="mt-3 rounded-xl border border-brand-blue/30 bg-brand-muted/40 p-2">
                <p className="text-[10px] font-bold uppercase tracking-wide text-brand-blue mb-1.5">OP note preview</p>
                <img
                  src={opNotePreviewSrc}
                  alt="OP note capture preview"
                  className="w-full max-h-40 object-contain rounded-lg border border-brand-border bg-ink/5 mx-auto"
                />
                <div className="grid grid-cols-2 gap-2 mt-2">
                  <button
                    type="button"
                    className="btn-secondary py-2 text-sm"
                    onClick={clearOpNoteDraft}
                    disabled={opNoteBusy}
                  >
                    Retake
                  </button>
                  <button
                    type="button"
                    className="btn-primary py-2 text-sm"
                    onClick={() => {
                      if (opNoteBlob) void sendOpNotePhoto(new File([opNoteBlob], "opnote.jpg", { type: opNoteBlob.type || "image/jpeg" }));
                    }}
                    disabled={opNoteBusy || !opNoteBlob}
                  >
                    {opNoteBusy ? "Saving..." : "Save"}
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <>
            <details className="card mb-3 group overflow-hidden">
              <summary className="px-4 py-3 cursor-pointer text-sm font-semibold text-ink list-none flex items-center gap-2 [&::-webkit-details-marker]:hidden">
                <span className="text-ink-secondary group-open:rotate-90 transition-transform">▸</span>
                Locality &amp; payment settings
              </summary>
              <div className="px-4 pb-4 pt-0 border-t border-brand-border space-y-3">
                <div>
                  <label className="label">Medicare Locality</label>
                  <select className="input text-sm" value={locality} onChange={(e) => setLocality(e.target.value)}>
                    {(locData?.localities ?? []).map((l) => (
                      <option key={l.locality_num} value={l.locality_num}>
                        {l.state} — {l.locality_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Setting</label>
                  <div className="grid grid-cols-2 rounded-xl overflow-hidden border border-brand-border">
                    <button
                      type="button"
                      className={`py-2 text-xs font-semibold ${!facility ? "bg-brand-gradient text-white" : "bg-surface text-ink-secondary"}`}
                      onClick={() => setFacility(false)}
                    >Non-Facility</button>
                    <button
                      type="button"
                      className={`py-2 text-xs font-semibold border-l border-brand-border ${facility ? "bg-brand-gradient text-white" : "bg-surface text-ink-secondary"}`}
                      onClick={() => setFacility(true)}
                    >Facility</button>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="label">$/RVU (fixed)</label>
                    <input className="input text-sm text-ink-secondary" type="number" step="0.0001" value={cf} readOnly />
                  </div>
                  <div>
                    <label className="label">Year</label>
                    <input className="input text-sm text-ink-secondary" type="text" value="2026" readOnly />
                  </div>
                </div>

                {devCanEdit && devCfg && (
                  <div className="rounded-xl border border-brand-blue/30 bg-brand-muted/30 p-3">
                    <p className="label text-brand-blue mb-2">Developer AI engine (this staff login)</p>
                    <div className="flex flex-wrap gap-2 items-end">
                      <div>
                        <label className="label">Provider</label>
                        <select
                          className="input text-xs w-auto"
                          value={devProvider}
                          onChange={(e) => {
                            const p = e.target.value;
                            setDevProvider(p);
                            setDevModel(defaultModelForProvider(p));
                          }}
                        >
                          <option value="ollama">Ollama</option>
                          <option value="paddle">PaddleOCR (local GPU)</option>
                          <option value="openai">OpenAI</option>
                          <option value="anthropic">Claude (Anthropic)</option>
                        </select>
                      </div>
                      <div className="flex-1 min-w-[160px]">
                        <label className="label">Vision model</label>
                        <input className="input text-xs" value={devModel} onChange={(e) => setDevModel(e.target.value)} />
                      </div>
                      <div className="flex-1 min-w-[160px]">
                        <label className="label">OpenAI API key (optional)</label>
                        <input className="input text-xs" type="password" value={devOpenAiKey} onChange={(e) => setDevOpenAiKey(e.target.value)} placeholder="Paste only if updating" />
                      </div>
                      <div className="flex-1 min-w-[160px]">
                        <label className="label">Anthropic API key (optional)</label>
                        <input className="input text-xs" type="password" value={devAnthropicKey} onChange={(e) => setDevAnthropicKey(e.target.value)} placeholder="Paste only if updating" />
                      </div>
                      <button
                        type="button"
                        className="btn-primary text-xs px-3 py-2"
                        disabled={devSaving}
                        onClick={() => {
                          if (!devModel || devModel.includes("@") || /\s/.test(devModel)) {
                            setDevErr("Vision model is invalid (do not use email/spaces).");
                            return;
                          }
                          setDevSaving(true);
                          setDevErr(null);
                          void api.patchStaffDevVisionConfig({
                            provider: devProvider,
                            vision_model: devModel,
                            openai_api_key: devOpenAiKey || undefined,
                            anthropic_api_key: devAnthropicKey || undefined,
                          })
                            .then((cfg) => {
                              setDevCfg(cfg);
                              setDevProvider(cfg.provider);
                              setDevModel(cfg.vision_model);
                              setDevOpenAiKey("");
                              setDevAnthropicKey("");
                            })
                            .catch((e: unknown) => setDevErr(e instanceof Error ? e.message : "Failed"))
                            .finally(() => setDevSaving(false));
                        }}
                      >
                        {devSaving ? "Saving..." : "Save"}
                      </button>
                    </div>
                    <p className="text-[10px] text-ink-secondary mt-2">
                      Active: <span className="font-semibold text-ink">{devCfg.provider}</span> · <span className="font-mono">{devCfg.vision_model}</span>
                    </p>
                    <p className="text-[10px] text-ink-secondary">
                      Keys: OpenAI {devCfg.openai_key_set === "yes" ? "set" : "not set"} · Claude {devCfg.anthropic_key_set === "yes" ? "set" : "not set"}
                    </p>
                    {devErr && <p className="text-[10px] text-red-600 mt-1">{devErr}</p>}
                  </div>
                )}
              </div>
            </details>

            <div className="card p-3 mb-3">
              <p className="label mb-2">Manual CPTs</p>
              <div className="flex gap-2">
                <input
                  className="input text-sm flex-1 min-w-0"
                  placeholder="Comma-separated CPT codes"
                  value={manualCptQuick}
                  onChange={(e) => setManualCptQuick(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") void loadManualCpts(); }}
                />
                <button type="button" className="btn-primary shrink-0 px-4 text-sm" disabled={busy} onClick={() => void loadManualCpts()}>
                  Load
                </button>
              </div>
            </div>

            {/* ── Camera Capture ── */}
            <div className="card p-4 mb-3">
              <div className="flex items-center justify-between mb-2">
                <p className="label">Scan charge screen</p>
                {devCfg && (
                  <span className="badge badge-blue text-[10px]">
                    Dev engine: {devCfg.provider} · {devCfg.vision_model}
                  </span>
                )}
              </div>
              <div className="mb-2">
                <label className="label">Scan mode</label>
                <div className="grid grid-cols-3 rounded-xl overflow-hidden border border-brand-border">
                  {([
                    ["fast", "Fast"],
                    ["balanced", "Balanced"],
                    ["thorough", "Thorough"],
                  ] as const).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className={`py-2 text-xs font-semibold ${scanMode === id ? "bg-brand-gradient text-white" : "bg-surface text-ink-secondary"}`}
                      onClick={() => setScanMode(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <input
                ref={cameraRef}
                id="camera-input"
                type="file"
                accept="image/*"
                capture="environment"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (cameraRef.current) cameraRef.current.value = "";
                  if (f) void sendVision(f);
                }}
              />

              {previewSrc && (
                <div className="mb-3 rounded-xl border border-brand-blue/30 bg-brand-muted/40 p-2">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-brand-blue mb-1.5">Photo sent to local AI</p>
                  <img
                    src={previewSrc}
                    alt="Charge screen capture"
                    className="w-full max-h-56 sm:max-h-64 object-contain rounded-lg border border-brand-border bg-ink/5 mx-auto"
                  />
                </div>
              )}

              <label
                htmlFor={busy ? "" : "camera-input"}
                className={`flex flex-col items-center justify-center gap-1.5 w-full h-24 rounded-2xl border-2 border-dashed transition-all cursor-pointer select-none mb-2
                  ${busy
                    ? "border-brand-blue/40 bg-brand-muted cursor-not-allowed"
                    : "border-brand-border bg-surface-soft hover:border-brand-blue/50 hover:bg-brand-muted/60 active:scale-[0.99]"
                  }`}
              >
                {busy ? (
                  <>
                    <Spinner className="w-6 h-6 text-brand-blue" />
                    <span className="text-sm font-semibold text-brand-blue">Analyzing…</span>
                  </>
                ) : (
                  <>
                    <svg className="w-7 h-7 text-brand-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round"
                        d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    <span className="text-sm font-semibold text-brand-blue">Tap to scan</span>
                    <span className="text-[10px] text-ink-secondary">Epic / charge screen</span>
                  </>
                )}
              </label>

              {pill.state !== "hidden" && (
                <div className={`flex items-center gap-2 border rounded-full px-4 py-2 text-xs mb-2 ${pillColors[pill.state]}`}>
                  {pill.state === "loading" && <Spinner className="w-3.5 h-3.5 flex-shrink-0" />}
                  {pill.state === "ok" && (
                    <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                  {pill.state === "err" && (
                    <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  )}
                  <span className="flex-1">{pill.msg}</span>
                  {elapsed ? <span className="ml-auto tabular-nums text-ink-secondary">{elapsed}</span> : null}
                </div>
              )}

              {showThink && (
                <div
                  ref={thinkRef}
                  className="bg-surface-soft border border-brand-border rounded-xl p-2 mb-2 font-mono text-[10px] leading-relaxed text-ink-secondary max-h-40 overflow-y-auto whitespace-pre-wrap break-words"
                >
                  <span className="text-[9px] font-bold text-ink-secondary block mb-1">Model output</span>
                  {thinkText}
                </div>
              )}

              <div className="flex items-center gap-2 text-ink-secondary text-[10px] my-1 mb-2">
                <span className="flex-1 h-px bg-brand-border" />or<span className="flex-1 h-px bg-brand-border" />
              </div>

              <label className="flex items-center gap-2 w-full bg-surface-soft border border-brand-border rounded-xl px-3 py-2.5 text-xs text-ink-secondary cursor-pointer hover:bg-brand-muted/40 transition-colors relative overflow-hidden">
                <span className="truncate">Choose photo / screenshot</span>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  className="absolute inset-0 opacity-0 cursor-pointer"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) void sendVision(f); }}
                />
              </label>
            </div>

            <div className="card mb-3 overflow-hidden">
              <button
                type="button"
                className="w-full flex items-center gap-3 px-4 py-3 text-sm font-semibold text-ink-secondary hover:bg-surface-soft transition-colors"
                onClick={() => setPasteOpen((o) => !o)}
              >
                Paste charge text (AI extract)
                <svg
                  className={`w-4 h-4 ml-auto transition-transform ${pasteOpen ? "rotate-180" : ""}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {pasteOpen && (
                <div className="px-4 pb-4 pt-1 border-t border-brand-border">
                  <textarea
                    value={pasteText}
                    onChange={(e) => setPasteText(e.target.value)}
                    placeholder="Paste CPT codes or charge screen text…"
                    className="input min-h-14 resize-y mb-2 text-sm"
                  />
                  <button
                    type="button"
                    disabled={busy || !pasteText.trim()}
                    onClick={() => void sendText()}
                    className="btn-primary w-full py-2.5 text-sm"
                  >Extract CPTs</button>
                </div>
              )}
            </div>
          </>
        )}

        {/* ── Results + Approval ── */}
        {workMode === "rvu" && showResults && (
          <div ref={approvalRef}>

            {/* CPT results table */}
            <div className="card p-4 mb-3">
              <div className="flex items-start gap-3 mb-4">
                <div>
                  <div className="text-3xl font-black text-green-700 tabular-nums leading-none">
                    ${surgeonValue.toFixed(2)}
                  </div>
                  <div className="flex items-center flex-wrap gap-2 mt-1.5">
                    <span className="text-xs text-ink-secondary">
                      {displayRows.length} CPT code(s)
                    </span>
                    <span className="text-xs text-ink-secondary">wRVU {sumWorkRvu.toFixed(2)}</span>
                    {assistLines.length > 0 && <span className="text-xs text-amber-700">PA/Assist lines saved: {assistLines.length}</span>}
                  </div>
                </div>
                <button
                  onClick={clearResults}
                  className="ml-auto btn-danger text-xs px-3 py-1.5"
                >Clear</button>
              </div>
              <div className="text-[11px] text-ink-secondary mb-2">
                Parsed: Surgeon {parsedSurgeonName || "—"} · DOS {approvalDos || "—"} · MRN {approvalMrn || "—"}
              </div>

              <div className="overflow-x-auto -mx-4 px-4" style={{ WebkitOverflowScrolling: "touch" }}>
                <table className="w-full border-collapse text-xs min-w-[480px]">
                  <thead>
                    <tr>
                      {["CPT", "Description", "wRVU", "PE RVU", "MP RVU", "Total RVU", "Payment"].map((h, i) => (
                        <th
                          key={h}
                          className={`px-2 py-2 text-[10px] font-semibold uppercase tracking-wide text-ink-secondary border-b border-brand-border whitespace-nowrap ${i >= 2 ? "text-right" : "text-left"}`}
                        >{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {displayRows.map((r, i) => (
                      <tr key={i} className="border-b border-brand-border/50">
                        <td className="px-2 py-2 font-bold">{r.CPT ?? r.cpt ?? ""}</td>
                        <td className="px-2 py-2 text-ink-secondary max-w-[140px] overflow-hidden text-ellipsis whitespace-nowrap" title={r.desc ?? ""}>{r.desc ?? "—"}</td>
                        {[r.work_rvu, r.pe_rvu, r.mp_rvu, r.total_rvu].map((v, j) => (
                          <td key={j} className="px-2 py-2 text-right font-mono tabular-nums">{(v ?? 0).toFixed(2)}</td>
                        ))}
                        <td className="px-2 py-2 text-right font-mono tabular-nums font-bold text-green-700">${(r.payment ?? 0).toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="bg-brand-muted border-t-2 border-brand-blue/30">
                      <td colSpan={5} className="px-2 py-2 font-bold">Total</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums font-bold">{sumRvu.toFixed(2)}</td>
                      <td className="px-2 py-2 text-right font-mono tabular-nums font-bold text-green-700">${sumPay.toFixed(2)}</td>
                    </tr>
                    <tr className="bg-surface-soft">
                      <td colSpan={7} className="px-2 py-2 text-right text-[11px] text-ink-secondary">
                        Surgeon wRVU: <span className="font-mono font-bold text-ink">{sumWorkRvu.toFixed(2)}</span>{" "}
                        · Value$: <span className="font-mono font-bold text-ink">${surgeonValue.toFixed(2)}</span>
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>

            {/* ── Approval / Save ── */}
            <div className="card border-2 border-brand-blue/25 p-4 mb-3">
              <p className="label text-brand-blue mb-3">Review &amp; save</p>

              <div className="mb-4">
                <label className="label">CPT codes</label>
                <div className="flex flex-wrap gap-2 mb-3">
                  {approvalCpts.map((code) => (
                    <span
                      key={code}
                      className="inline-flex items-center gap-1.5 badge-blue px-3 py-1.5 text-sm font-bold"
                    >
                      {code}
                      <button
                        type="button"
                        onClick={() => removeCpt(code)}
                        className="text-red-500 hover:text-red-700 transition-colors leading-none ml-0.5"
                        title="Remove"
                      >×</button>
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={5}
                    placeholder="Add CPT…"
                    value={newCptInput}
                    onChange={(e) => setNewCptInput(e.target.value.replace(/\D/g, "").slice(0, 5))}
                    onKeyDown={(e) => { if (e.key === "Enter") addCpt(); }}
                    className="input flex-1"
                  />
                  <button
                    type="button"
                    onClick={addCpt}
                    className="btn-secondary px-4 py-2 text-sm whitespace-nowrap"
                  >+ Add</button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 mb-4">
                <div>
                  <label className="label">Date of service</label>
                  <input
                    type="date"
                    className="input"
                    value={approvalDos}
                    onChange={(e) => setApprovalDos(e.target.value)}
                  />
                </div>
                <div>
                  <label className="label">MRN (optional)</label>
                  <input
                    type="text"
                    className="input"
                    placeholder="MRN"
                    value={approvalMrn}
                    onChange={(e) => setApprovalMrn(e.target.value)}
                  />
                </div>
              </div>

              <button
                type="button"
                disabled={saving || !approvalCpts.length}
                onClick={() => void commitScan()}
                className="btn-primary w-full py-3.5 text-base"
              >
                {saving ? (
                  <><Spinner /> Saving…</>
                ) : (
                  <>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                    </svg>
                    Save to record
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        <footer className="mt-8 text-center text-[10px] text-ink-secondary/60 leading-relaxed">
          2026 CMS MPFS · Local AI only — nothing leaves your network<br />
          Illustrative only — not a claim determination
        </footer>
      </div>
    </div>
  );
}
