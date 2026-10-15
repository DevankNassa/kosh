import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorNote, useApi } from "../components/ui";
import { date, inrc, num } from "../format";

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<any>(null);
  const [target, setTarget] = useState<string>("auto");
  const [newName, setNewName] = useState("");
  const clients = useApi<any[]>("/api/clients");
  const history = useApi<any[]>("/api/imports");

  const upload = () => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("password", password);
    setBusy(true);
    setErr(null);
    setDone(null);
    api
      .upload("/api/import/preview", fd)
      .then((p) => {
        setPreview(p);
        setTarget(p.matched_client ? String(p.matched_client.id) : "new");
        setNewName(p.investor_name ? p.investor_name.replace(/\b\w/g, (c: string) => c.toUpperCase()) : "");
      })
      .catch((e) => setErr(e.message))
      .finally(() => setBusy(false));
  };

  const commit = () => {
    setBusy(true);
    setErr(null);
    api
      .post("/api/import/commit", {
        token: preview.token,
        client_id: target !== "new" ? Number(target) : null,
        new_client: target === "new" ? { name: newName } : null,
      })
      .then((r) => {
        setDone(r);
        setPreview(null);
        setFile(null);
        setPassword("");
        history.reload();
        clients.reload();
      })
      .catch((e) => setErr(e.message))
      .finally(() => setBusy(false));
  };

  const mismatches = preview?.reconciliation.filter((r: any) => !r.matches) || [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Import a statement</h1>
          <div className="sub">Upload a Consolidated Account Statement (CAS) PDF from CAMS, KFintech, NSDL or CDSL.</div>
        </div>
      </div>

      {done && (
        <div className="notice info" style={{ marginBottom: 16 }}>
          Imported {done.added} new transactions{done.skipped ? ` (${done.skipped} already in Kosh were skipped)` : ""}.{" "}
          <Link to={`/clients/${done.client_id}`}>Open the client →</Link>
        </div>
      )}

      {!preview && (
        <div className="card">
          <h2>1. Choose the PDF</h2>
          <div className="form-grid" style={{ alignItems: "end" }}>
            <label className="field" style={{ gridColumn: "span 2" }}>
              Statement PDF
              <input type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
            <label className="field">
              PDF password
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" />
            </label>
            <button className="primary" onClick={upload} disabled={!file || busy}>
              {busy ? "Reading statement…" : "Read statement"}
            </button>
          </div>
          <p className="small faint" style={{ marginTop: 10 }}>
            The password is the one set when the CAS was requested (CAMS / KFintech), or usually the PAN (NSDL / CDSL). The PDF and password are only used to read the statement; neither is saved.
          </p>
          <div className="small muted" style={{ marginTop: 10 }}>
            <b>Which statement?</b> A <i>detailed</i> mutual fund CAS from CAMS or KFintech gives full purchase history, so gains and tax work straight away. NSDL / CDSL statements give demat holdings without purchase cost; you can add costs afterwards in the client's Holdings tab.
          </div>
          <ErrorNote error={err} />
        </div>
      )}

      {preview && (
        <div className="stack">
          <div className="card">
            <h2>2. Check what was read</h2>
            <div className="grid g4" style={{ gap: 12 }}>
              <div><div className="small muted">Statement</div><b>{preview.file_type} {preview.cas_type?.toLowerCase()}</b></div>
              <div><div className="small muted">Period</div><b>{date(preview.period_from)} – {date(preview.period_to)}</b></div>
              <div><div className="small muted">Investor</div><b>{preview.investor_name || "—"}</b> <span className="small faint">{preview.pans_masked.join(", ")}</span></div>
              <div><div className="small muted">Value on statement</div><b>{inrc(preview.total_value)}</b></div>
            </div>
            {preview.warnings.map((w: string) => <div key={w} className="notice warn" style={{ marginTop: 10 }}>{w}</div>)}
            {mismatches.length > 0 ? (
              <div className="notice warn" style={{ marginTop: 10 }}>
                {mismatches.length} holding(s) don't reconcile: units after import differ from the statement. Check them below before importing.
              </div>
            ) : (
              <div className="notice info" style={{ marginTop: 10 }}>All {preview.reconciliation.length} holdings reconcile with the statement.</div>
            )}
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table>
                <thead><tr><th>Account</th><th>Provider</th><th>Distributor code</th><th className="num">Holdings</th><th className="num">Transactions</th><th className="num">Cost missing</th></tr></thead>
                <tbody>
                  {preview.accounts.map((a: any) => (
                    <tr key={a.kind + a.identifier}>
                      <td>{a.kind === "demat" ? "Demat" : "Folio"} {a.identifier}</td>
                      <td>{a.provider}</td>
                      <td>{a.arn || "—"}</td>
                      <td className="num">{a.holdings}</td>
                      <td className="num">{a.transactions}</td>
                      <td className="num">{a.cost_unknown || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <details style={{ marginTop: 12 }}>
              <summary className="small" style={{ cursor: "pointer" }}>Reconciliation by holding</summary>
              <table>
                <thead><tr><th>Holding</th><th className="num">On statement</th><th className="num">After import</th><th /></tr></thead>
                <tbody>
                  {preview.reconciliation.map((r: any) => (
                    <tr key={r.account + r.isin}>
                      <td>{r.name}<div className="sub">{r.isin}</div></td>
                      <td className="num">{num(r.statement_units, 3)}</td>
                      <td className="num">{num(r.units_after_import, 3)}</td>
                      <td>{r.matches ? <span className="badge good">Matches</span> : <span className="badge bad">Differs</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </div>

          <div className="card">
            <h2>3. Import into</h2>
            <div className="row">
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="new">A new client</option>
                {(clients.data || []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}{preview.matched_client?.id === c.id ? " (matched by PAN)" : ""}
                  </option>
                ))}
              </select>
              {target === "new" && <input placeholder="Client name" value={newName} onChange={(e) => setNewName(e.target.value)} />}
              <span className="spacer" />
              <button onClick={() => setPreview(null)}>Cancel</button>
              <button className="primary" onClick={commit} disabled={busy || (target === "new" && !newName)}>
                Import {preview.new_transactions} new transactions
              </button>
            </div>
            <p className="small faint" style={{ marginTop: 8 }}>Re-importing a statement is safe: transactions already in Kosh are skipped.</p>
            <ErrorNote error={err} />
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <h2>Past imports</h2>
        {(history.data || []).length === 0 ? (
          <div className="empty">No statements imported yet.</div>
        ) : (
          <table>
            <thead><tr><th>When</th><th>Client</th><th>File</th><th>Type</th><th>Period</th><th className="num">Added</th></tr></thead>
            <tbody>
              {history.data!.map((i) => (
                <tr key={i.id}>
                  <td>{date(i.created_at)}</td>
                  <td>{i.client_id ? <Link to={`/clients/${i.client_id}`}>{i.client_name}</Link> : "—"}</td>
                  <td className="small">{i.filename}</td>
                  <td>{i.file_type}</td>
                  <td className="small">{i.period}</td>
                  <td className="num">{i.summary?.added ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
