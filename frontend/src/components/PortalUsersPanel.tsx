import { useEffect, useState } from "react";
import { api, type PortalMe, type PortalUserCreateBody, type PortalUserPatchBody, type PortalUserRecord } from "../api/client";

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

export default function PortalUsersPanel({ admin }: { admin: PortalMe }) {
  const [users, setUsers] = useState<PortalUserRecord[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [addDraft, setAddDraft] = useState<PortalUserCreateBody>({ username: "", email: "", password: "", role: "admin" });
  const [addBusy, setAddBusy] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<PortalUserPatchBody>({});
  const [editBusy, setEditBusy] = useState(false);

  const load = () => {
    setErr(null);
    api.listPortalUsers().then((r) => setUsers(r.users)).catch((e) => setErr(e instanceof Error ? e.message : "Failed to load users"));
  };

  useEffect(() => {
    void load();
  }, []);

  const submitAdd = async () => {
    if (!addDraft.username.trim() || !addDraft.email.trim() || addDraft.password.length < 8) {
      setErr("Username, email, and password (8+ chars) required.");
      return;
    }
    setAddBusy(true);
    setErr(null);
    try {
      await api.createPortalUser({
        username: addDraft.username.trim(),
        email: addDraft.email.trim(),
        password: addDraft.password,
        role: addDraft.role || "admin",
      });
      setShowAdd(false);
      setAddDraft({ username: "", email: "", password: "", role: "admin" });
      load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Create failed");
    } finally {
      setAddBusy(false);
    }
  };

  const saveEdit = async (id: number) => {
    setEditBusy(true);
    setErr(null);
    try {
      await api.patchPortalUser(id, editDraft);
      setEditId(null);
      setEditDraft({});
      load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setEditBusy(false);
    }
  };

  const deactivate = async (id: number) => {
    if (!window.confirm("Deactivate this portal user? They can no longer sign in.")) return;
    setErr(null);
    try {
      await api.deletePortalUser(id);
      load();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    }
  };

  const startEdit = (u: PortalUserRecord) => {
    setEditId(u.id);
    setEditDraft({ email: u.email, role: u.role, is_active: u.is_active });
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-bold text-ink">Portal users</h2>
          <p className="text-sm text-ink-secondary">Username / password accounts for this office portal.</p>
        </div>
        <button type="button" onClick={() => { setShowAdd((v) => !v); setErr(null); }} className={showAdd ? "btn-secondary" : "btn-primary"}>
          {showAdd ? "Cancel" : "+ Add user"}
        </button>
      </div>

      {err && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl mb-4">{err}</div>}

      {showAdd && (
        <div className="card p-5 mb-4 border-2 border-brand-blue/25">
          <p className="label text-brand-blue mb-3">New portal user</p>
          <div className="grid sm:grid-cols-2 gap-3 mb-3">
            <div>
              <label className="label">Username</label>
              <input className="input text-sm" value={addDraft.username} onChange={(e) => setAddDraft((d) => ({ ...d, username: e.target.value }))} autoComplete="off" />
            </div>
            <div>
              <label className="label">Email</label>
              <input className="input text-sm" type="email" value={addDraft.email} onChange={(e) => setAddDraft((d) => ({ ...d, email: e.target.value }))} />
            </div>
            <div>
              <label className="label">Password (min 8)</label>
              <input className="input text-sm" type="password" value={addDraft.password} onChange={(e) => setAddDraft((d) => ({ ...d, password: e.target.value }))} />
            </div>
            <div>
              <label className="label">Role</label>
              <select className="input text-sm w-full" value={addDraft.role} onChange={(e) => setAddDraft((d) => ({ ...d, role: e.target.value }))}>
                <option value="admin">Admin</option>
                <option value="superadmin">Superadmin</option>
              </select>
            </div>
          </div>
          <button type="button" disabled={addBusy} onClick={() => void submitAdd()} className="btn-primary">
            {addBusy ? <><Spinner /> Creating…</> : "Create user"}
          </button>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse" style={{ minWidth: 640 }}>
            <thead>
              <tr>
                {["Username", "Email", "Role", "Status", ""].map((h, i) => (
                  <th key={h} className={`${TH} ${i === 4 ? "text-right" : "text-left"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((u) =>
                editId === u.id ? (
                  <tr key={u.id} className="bg-brand-muted/50">
                    <td colSpan={5} className="px-4 py-3">
                      <div className="flex flex-wrap gap-3 items-end">
                        <div className="flex-1 min-w-[180px]">
                          <label className="label">Email</label>
                          <input className="input text-xs" value={editDraft.email ?? ""} onChange={(e) => setEditDraft((d) => ({ ...d, email: e.target.value }))} />
                        </div>
                        <div>
                          <label className="label">New password</label>
                          <input className="input text-xs w-40" type="password" placeholder="leave blank to keep" onChange={(e) => setEditDraft((d) => ({ ...d, password: e.target.value || undefined }))} />
                        </div>
                        <div>
                          <label className="label">Role</label>
                          <select className="input text-xs w-auto" value={editDraft.role ?? "admin"} onChange={(e) => setEditDraft((d) => ({ ...d, role: e.target.value }))}>
                            <option value="admin">Admin</option>
                            <option value="superadmin">Superadmin</option>
                          </select>
                        </div>
                        <div>
                          <label className="label">Active</label>
                          <select className="input text-xs w-auto" value={editDraft.is_active ? "yes" : "no"} onChange={(e) => setEditDraft((d) => ({ ...d, is_active: e.target.value === "yes" }))}>
                            <option value="yes">Yes</option>
                            <option value="no">No</option>
                          </select>
                        </div>
                        <button type="button" disabled={editBusy} onClick={() => void saveEdit(u.id)} className="btn-primary text-xs px-3 py-2">
                          {editBusy ? <Spinner className="w-3 h-3" /> : "Save"}
                        </button>
                        <button type="button" onClick={() => { setEditId(null); setEditDraft({}); }} className="btn-secondary text-xs px-3 py-2">Cancel</button>
                      </div>
                    </td>
                  </tr>
                ) : (
                  <tr key={u.id} className="hover:bg-surface-soft">
                    <td className={`${TD} font-semibold`}>{u.username}{u.id === admin.id ? <span className="text-xs text-ink-secondary ml-2">(you)</span> : null}</td>
                    <td className={TD}>{u.email}</td>
                    <td className={TD}><span className="badge-blue">{u.role}</span></td>
                    <td className={TD}>{u.is_active ? <span className="badge-green">Active</span> : <span className="badge-gray">Inactive</span>}</td>
                    <td className={`${TD} text-right`}>
                      <span className="inline-flex gap-2">
                        <button type="button" onClick={() => startEdit(u)} className="text-xs font-semibold text-indigo-600 border border-indigo-200 rounded-lg px-2 py-1 hover:bg-indigo-50">Edit</button>
                        {u.id !== admin.id && u.is_active ? (
                          <button type="button" onClick={() => void deactivate(u.id)} className="text-xs font-semibold text-red-600 border border-red-200 rounded-lg px-2 py-1 hover:bg-red-50">Deactivate</button>
                        ) : null}
                      </span>
                    </td>
                  </tr>
                )
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
