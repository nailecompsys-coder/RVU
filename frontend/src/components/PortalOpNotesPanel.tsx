import { useEffect, useState } from "react";
import { api, type OpNoteRow } from "../api/client";
import { fmtDateTimeEt } from "../dates";

function Spinner({ className = "w-4 h-4" }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

const TH = "px-3 py-2.5 text-[10px] font-bold uppercase tracking-wide text-ink-secondary whitespace-nowrap border-b-2 border-brand-border bg-surface-soft text-left";
const TD = "px-3 py-2.5 text-sm border-b border-brand-border/60 align-top";

export default function PortalOpNotesPanel() {
  const [notes, setNotes] = useState<OpNoteRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [imgId, setImgId] = useState<number | null>(null);
  const [delId, setDelId] = useState<number | null>(null);

  const load = () => {
    setErr(null);
    api.listPortalOpNotes().then((r) => setNotes(r.notes)).catch((e) => setErr(e instanceof Error ? e.message : "Failed to load"));
  };

  useEffect(() => {
    void load();
  }, []);

  const remove = async (id: number) => {
    if (!window.confirm("Delete this OP note and image?")) return;
    setDelId(id);
    try {
      await api.deletePortalOpNote(id);
      setNotes((prev) => prev.filter((n) => n.id !== id));
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDelId(null);
    }
  };

  return (
    <div>
      <h2 className="text-lg font-bold text-ink mb-1">OP notes</h2>
      <p className="text-sm text-ink-secondary mb-4">
        Transcribed from photos taken in the mobile app (vision model). Open image to verify text.
      </p>
      {err && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl mb-4">{err}</div>}

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse" style={{ minWidth: 720 }}>
            <thead>
              <tr>
                {["When", "Staff", "Preview", "Model", ""].map((h, i) => (
                  <th key={h} className={`${TH} ${i === 4 ? "text-right" : "text-left"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {notes.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-ink-secondary text-sm">No OP notes yet.</td></tr>
              )}
              {notes.map((n) => (
                <tr key={n.id} className="hover:bg-surface-soft">
                  <td className={`${TD} text-xs text-ink-secondary whitespace-nowrap`}>{fmtDateTimeEt(n.scanned_at)}</td>
                  <td className={`${TD} font-medium`}>{n.surgeon_name ?? "—"}</td>
                  <td className={`${TD} text-xs text-ink-secondary max-w-md`}>
                    <div className="line-clamp-3 whitespace-pre-wrap">{n.extracted_text || "—"}</div>
                  </td>
                  <td className={`${TD} text-xs`}>{n.ai_model ?? "—"}</td>
                  <td className={`${TD} text-right whitespace-nowrap`}>
                    {n.has_image ? (
                      <button type="button" onClick={() => setImgId(n.id)} className="text-xs font-semibold text-brand-blue mr-2 hover:underline">Image</button>
                    ) : null}
                    <button type="button" disabled={delId === n.id} onClick={() => void remove(n.id)} className="text-xs font-semibold text-red-600 border border-red-200 rounded-lg px-2 py-1 hover:bg-red-50">
                      {delId === n.id ? <Spinner className="w-3 h-3" /> : "Delete"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {imgId !== null && (
        <div className="fixed inset-0 z-[200] bg-black/80 flex items-center justify-center p-4" onClick={() => setImgId(null)}>
          <img
            src={`/api/v1/portal/rvu/op-notes/${imgId}/image`}
            alt="OP note"
            className="max-w-full max-h-[90dvh] rounded-xl shadow-modal"
            onClick={(e) => e.stopPropagation()}
          />
          <button type="button" className="fixed top-5 right-5 w-9 h-9 rounded-full bg-white/15 text-white text-xl" onClick={() => setImgId(null)}>×</button>
        </div>
      )}
    </div>
  );
}
