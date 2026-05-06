import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ScanRow } from "../api/client";
import { fmtDateTimeEt } from "../dates";

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

function parseLineItems(scan: ScanRow): LineItem[] {
  const raw = scan.line_items;
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

function doctorTotals(scan: ScanRow) {
  const items = parseLineItems(scan);
  const workRvu = items.reduce((a, li) => {
    const isAssist = Boolean(li.is_assist) || (li.provider_role ?? "").toLowerCase() === "pa" || /\bAS\b/i.test(li.modifier ?? "");
    return a + (isAssist ? 0 : Number(li.work_rvu ?? 0));
  }, 0);
  const cf = Number(scan.cf ?? 32.3465);
  const hasWorkPayment = items.some((li) => !Boolean(li.is_assist) && li.work_payment != null);
  const surgeonValue = hasWorkPayment
    ? items.reduce((a, li) => {
        const isAssist = Boolean(li.is_assist) || (li.provider_role ?? "").toLowerCase() === "pa" || /\bAS\b/i.test(li.modifier ?? "");
        return a + (isAssist ? 0 : Number(li.work_payment ?? 0));
      }, 0)
    : workRvu * cf;
  return { workRvu, value: surgeonValue, items };
}

export default function StaffHistoryPage() {
  const [scans, setScans] = useState<ScanRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [detail, setDetail] = useState<ScanRow | null>(null);

  useEffect(() => {
    api.history().then((r) => setScans(r.scans)).catch(() => setErr("Sign in required."));
  }, []);

  if (err) {
    return (
      <div className="min-h-dvh bg-surface-soft flex items-center justify-center px-4">
        <div className="text-center">
          <p className="text-red-600 mb-4">{err}</p>
          <Link to="/register" className="btn-primary">Register →</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-surface-soft text-ink pb-10 w-full max-w-full overflow-x-hidden">

      {/* Sticky header */}
      <header className="bg-surface border-b border-brand-border px-4 py-3 sm:px-5 sm:py-4 flex items-center gap-3 sticky top-0 z-10 shadow-card max-w-full">
        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-bold text-ink truncate">My Scan History</h1>
        </div>
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          <Link
            to="/done"
            className="text-xs font-semibold text-ink-secondary hover:text-ink transition-colors"
          >
            Done
          </Link>
          <Link
            to="/capture"
            className="flex items-center gap-1.5 text-xs font-semibold text-brand-blue hover:opacity-80 transition-opacity"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            Scanner
          </Link>
        </div>
      </header>

      <div className="px-3 sm:px-4 pt-4 sm:pt-5 w-full max-w-full">
        {scans.length === 0 ? (
          <div className="card p-8 sm:p-10 text-center max-w-full">
            <div className="w-14 h-14 bg-brand-muted rounded-2xl mx-auto mb-4 flex items-center justify-center">
              <svg className="w-7 h-7 text-brand-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
            <p className="text-ink-secondary text-sm">No scans yet — tap the scanner to get started.</p>
            <Link to="/capture" className="btn-primary mt-5 inline-flex">Open Scanner</Link>
          </div>
        ) : (
          <>
            {/* Narrow screens: stacked cards (no horizontal scroll) */}
            <ul className="md:hidden space-y-3 w-full max-w-full">
              {scans.map((s) => {
                const { workRvu, value, items } = doctorTotals(s);
                const cptStr = items.map((li) => li.cpt).filter(Boolean).join(", ");
                const dt = fmtDateTimeEt(s.scanned_at);
                return (
                  <li key={s.id} className="card p-3.5 w-full max-w-full min-w-0 cursor-pointer" onClick={() => setDetail(s)}>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <p className="text-[11px] text-ink-secondary leading-tight">{dt}</p>
                      <span className={`shrink-0 text-[10px] ${s.facility ? "badge-blue" : "badge-gray"}`}>
                        {s.facility ? "Facility" : "Non-Fac"}
                      </span>
                    </div>
                    <p className="text-xs font-mono text-ink break-words hyphens-auto mb-2">{cptStr || "—"}</p>
                    <div className="flex items-baseline justify-between gap-3 pt-2 border-t border-brand-border/70">
                      <span className="text-xs text-ink-secondary">
                        wRVU <span className="font-mono tabular-nums font-semibold text-ink">{workRvu.toFixed(2)}</span>
                      </span>
                      <span className="text-sm font-bold text-green-700 font-mono tabular-nums">
                        ${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>

            {/* Tablet+ : table inside scroll container if needed */}
            <div className="hidden md:block card overflow-hidden w-full max-w-full">
              <div className="overflow-x-auto max-w-full" style={{ WebkitOverflowScrolling: "touch" }}>
                <table className="w-full border-collapse text-sm min-w-[520px]">
                  <thead>
                    <tr className="bg-ink">
                      {["Date", "CPTs", "Setting", "wRVU", "Value$"].map((h, i) => (
                        <th
                          key={h}
                          className={`px-3 lg:px-4 py-3 text-xs font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap ${i >= 3 ? "text-right" : "text-left"}`}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {scans.map((s, idx) => {
                      const { workRvu, value, items } = doctorTotals(s);
                      const cptStr = items.map((li) => li.cpt).filter(Boolean).join(", ");
                      const dt = fmtDateTimeEt(s.scanned_at);
                      return (
                        <tr
                          key={s.id}
                          className={`border-b border-brand-border ${idx % 2 === 0 ? "bg-surface" : "bg-surface-soft"} hover:bg-brand-muted/50 transition-colors cursor-pointer`}
                          onClick={() => setDetail(s)}
                        >
                          <td className="px-3 lg:px-4 py-3 text-xs whitespace-nowrap text-ink-secondary">{dt}</td>
                          <td className="px-3 lg:px-4 py-3 text-xs text-ink-secondary max-w-[200px] truncate" title={cptStr}>{cptStr || "—"}</td>
                          <td className="px-3 lg:px-4 py-3 text-xs">
                            <span className={s.facility ? "badge-blue" : "badge-gray"}>
                              {s.facility ? "Facility" : "Non-Fac"}
                            </span>
                          </td>
                          <td className="px-3 lg:px-4 py-3 text-xs text-right font-mono tabular-nums">
                            {workRvu.toFixed(2)}
                          </td>
                          <td className="px-3 lg:px-4 py-3 text-xs text-right font-semibold text-green-700 font-mono tabular-nums">
                            ${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>

      {detail && (
        <div onClick={() => setDetail(null)} className="fixed inset-0 z-[120] bg-black/45 backdrop-blur-sm flex items-center justify-center p-3">
          <div onClick={(e) => e.stopPropagation()} className="bg-surface rounded-2xl w-full max-w-5xl max-h-[90dvh] overflow-auto border border-brand-border shadow-modal">
            <div className="px-4 py-3 border-b border-brand-border flex items-center gap-3">
              <h2 className="text-sm font-bold text-ink">Scan detail</h2>
              <span className="text-xs text-ink-secondary">{fmtDateTimeEt(detail.scanned_at)}</span>
              <button onClick={() => setDetail(null)} className="ml-auto btn-secondary text-xs px-3 py-1.5">Close</button>
            </div>
            {(() => {
              const { workRvu, value, items } = doctorTotals(detail);
              return (
                <div className="p-4 space-y-4">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="card px-3 py-2"><p className="text-[10px] text-ink-secondary uppercase">wRVU (Surgeon)</p><p className="font-mono font-bold">{workRvu.toFixed(2)}</p></div>
                    <div className="card px-3 py-2"><p className="text-[10px] text-ink-secondary uppercase">Surgeon Payment</p><p className="font-mono font-bold text-green-700">${value.toFixed(2)}</p></div>
                    <div className="card px-3 py-2"><p className="text-[10px] text-ink-secondary uppercase">Total RVU</p><p className="font-mono font-bold">{(detail.total_rvu ?? 0).toFixed(2)}</p></div>
                    <div className="card px-3 py-2"><p className="text-[10px] text-ink-secondary uppercase">Total Medicare</p><p className="font-mono font-bold">${(detail.total_payment ?? 0).toFixed(2)}</p></div>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse min-w-[900px]">
                      <thead>
                        <tr className="bg-surface-soft">
                          {[
                            ["CPT", false], ["Procedure / Provider", false], ["Modifier", false],
                            ["wRVU", true], ["PE RVU", true], ["MP RVU", true], ["Total RVU", true],
                            ["Work $", true], ["PE $", true], ["MP $", true], ["Payment", true], ["AS", false],
                          ].map(([h, right]) => (
                            <th key={h as string} className={`px-3 py-2 text-[10px] font-bold uppercase tracking-wide text-ink-secondary border-b border-brand-border ${right ? "text-right" : "text-left"}`}>{h as string}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((li, idx) => {
                          const isAssist = Boolean(li.is_assist) || (li.provider_role ?? "").toLowerCase() === "pa" || /\bAS\b/i.test(li.modifier ?? "");
                          const rowCls = `border-b border-brand-border/60 ${isAssist ? "bg-amber-50" : ""}`;
                          const modCode = li.modifier_code ? `-${li.modifier_code}` : (li.modifier ? li.modifier : null);
                          const modFactor = li.modifier_factor != null && li.modifier_factor !== 1 ? li.modifier_factor : null;
                          return (
                            <tr key={`${li.cpt ?? "x"}-${idx}`} className={rowCls}>
                              <td className="px-3 py-2 text-xs font-mono whitespace-nowrap">{li.cpt ?? "—"}</td>
                              <td className="px-3 py-2 text-xs">
                                <div>{li.procedure_name || "—"}</div>
                                {(li.provider_name || li.provider_role) && (
                                  <div className="text-[10px] text-ink-secondary mt-0.5">{li.provider_name || li.provider_role}</div>
                                )}
                              </td>
                              <td className="px-3 py-2 text-xs whitespace-nowrap">
                                {modCode ? (
                                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-yellow-100 text-yellow-800 border border-yellow-300">
                                    {modCode}
                                    {modFactor != null && <span className="opacity-70">×{modFactor}</span>}
                                  </span>
                                ) : "—"}
                                {li.modifier_desc && (
                                  <div className="text-[10px] text-ink-secondary mt-0.5">{li.modifier_desc}</div>
                                )}
                              </td>
                              <td className="px-3 py-2 text-xs text-right font-mono tabular-nums">{isAssist ? "—" : Number(li.work_rvu ?? 0).toFixed(2)}</td>
                              <td className="px-3 py-2 text-xs text-right font-mono tabular-nums">{isAssist ? "—" : (li.pe_rvu != null ? Number(li.pe_rvu).toFixed(2) : "—")}</td>
                              <td className="px-3 py-2 text-xs text-right font-mono tabular-nums">{isAssist ? "—" : (li.mp_rvu != null ? Number(li.mp_rvu).toFixed(2) : "—")}</td>
                              <td className="px-3 py-2 text-xs text-right font-mono tabular-nums">{isAssist ? "—" : Number(li.total_rvu ?? 0).toFixed(2)}</td>
                              <td className="px-3 py-2 text-xs text-right font-mono tabular-nums">{isAssist ? "—" : (li.work_payment != null ? `$${Number(li.work_payment).toFixed(2)}` : "—")}</td>
                              <td className="px-3 py-2 text-xs text-right font-mono tabular-nums">{isAssist ? "—" : (li.pe_payment != null ? `$${Number(li.pe_payment).toFixed(2)}` : "—")}</td>
                              <td className="px-3 py-2 text-xs text-right font-mono tabular-nums">{isAssist ? "—" : (li.mp_payment != null ? `$${Number(li.mp_payment).toFixed(2)}` : "—")}</td>
                              <td className="px-3 py-2 text-xs text-right font-mono tabular-nums font-semibold text-green-700">${Number(li.payment ?? 0).toFixed(2)}</td>
                              <td className="px-3 py-2 text-xs text-center">{isAssist ? <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800 border border-amber-300">AS</span> : ""}</td>
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
