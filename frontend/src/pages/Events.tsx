import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { describeShock, ImpactView, Shock, ShockBuilder } from "../components/Impact";
import { ErrorNote, Loading, Modal, useApi } from "../components/ui";
import { date, inrc, tone } from "../format";
import { EVENT_KIND } from "./Dashboard";

export default function Events() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data, error, reload } = useApi<any[]>("/api/events");
  const [adding, setAdding] = useState(false);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const selected = id ? Number(id) : data[0]?.id;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Events &amp; impact</h1>
          <div className="sub">Log a news event as a market move and see which clients it touches, and by roughly how much.</div>
        </div>
        <button className="primary" onClick={() => setAdding(true)}>Log an event</button>
      </div>
      <div className="grid g-events">
        <div className="card" style={{ padding: 8, alignSelf: "start" }}>
          {data.map((e) => (
            <Link
              key={e.id}
              to={`/events/${e.id}`}
              style={{
                display: "block", padding: "10px", borderRadius: 8, color: "inherit", textDecoration: "none",
                background: e.id === selected ? "var(--accent-soft)" : undefined,
              }}
            >
              <div className="row" style={{ gap: 6 }}>
                <span className="badge">{EVENT_KIND[e.kind] || e.kind}</span>
                {e.is_sample && <span className="badge info">Sample</span>}
                <span className="spacer" />
                <span className="small faint">{date(e.date)}</span>
              </div>
              <div style={{ fontWeight: 560, margin: "4px 0 2px" }}>{e.title}</div>
              <div className="small muted">
                {e.clients_exposed} {e.clients_exposed === 1 ? "client" : "clients"} · <span className={tone(e.impact)}>{inrc(e.impact, { sign: true })}</span>
              </div>
            </Link>
          ))}
          {data.length === 0 && <div className="empty">No events yet.</div>}
        </div>
        <div style={{ minWidth: 0 }}>{selected ? <EventDetail id={selected} onDeleted={() => { reload(); nav("/events"); }} /> : null}</div>
      </div>
      {adding && (
        <AddEvent
          onClose={() => setAdding(false)}
          onDone={(eid) => { setAdding(false); reload(); nav(`/events/${eid}`); }}
        />
      )}
    </>
  );
}

function EventDetail({ id, onDeleted }: { id: number; onDeleted: () => void }) {
  const { data, error } = useApi<any>(`/api/events/${id}/impact`, [id]);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading label="Mapping the event to client holdings…" />;
  const e = data.event;
  return (
    <div className="stack">
      <div className="card">
        <div className="row">
          <span className="badge">{EVENT_KIND[e.kind] || e.kind}</span>
          {e.is_sample && <span className="badge info">Sample scenario · hypothetical, not real news</span>}
          <span className="spacer" />
          <span className="small faint">{date(e.date)}</span>
        </div>
        <h2 style={{ margin: "8px 0 4px", fontSize: 18 }}>{e.title}</h2>
        {e.summary && <p className="muted">{e.summary}</p>}
        <div className="small faint">
          Estimated at the time: {describeShock(e.tags || {})}
          {e.source_url && <> · <a href={e.source_url} target="_blank" rel="noreferrer">Source</a></>}
          {e.source && !e.source_url && <> · {e.source}</>}
        </div>
        {e.actual_tags ? (
          <div className="small faint">
            What actually happened: <b>{describeShock(e.actual_tags)}</b> — the figures below use this, not the original estimate.
          </div>
        ) : (
          !e.is_sample && <div className="small faint">What actually happened: not yet known — Kosh checks ~5 trading days after the event.</div>
        )}
        <div className="row" style={{ marginTop: 8 }}>
          <span className="spacer" />
          <button className="ghost danger" onClick={() => api.del(`/api/events/${id}`).then(onDeleted)}>Delete event</button>
        </div>
      </div>
      <ImpactView impact={data} />
    </div>
  );
}

function AddEvent({ onClose, onDone }: { onClose: () => void; onDone: (id: number) => void }) {
  const [f, setF] = useState({ title: "", kind: "rate", date: new Date().toISOString().slice(0, 10), summary: "", source_url: "" });
  const [shock, setShock] = useState<Shock>({ yield_shift_bps: -25 });
  const [err, setErr] = useState<string | null>(null);
  const save = () =>
    api
      .post("/api/events", { ...f, source_url: f.source_url || null, tags: shock })
      .then((e) => onDone(e.id))
      .catch((e) => setErr(e.message));
  return (
    <Modal
      title="Log an event"
      onClose={onClose}
      footer={<><button onClick={onClose}>Cancel</button><button className="primary" disabled={!f.title} onClick={save}>Save and see impact</button></>}
    >
      <div className="form-grid">
        <label className="field" style={{ gridColumn: "1 / -1" }}>
          What happened
          <input placeholder="e.g. RBI cuts repo rate by 25 bps" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} autoFocus />
        </label>
        <label className="field">Type
          <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
            {Object.entries(EVENT_KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="field">Date<input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></label>
        <label className="field" style={{ gridColumn: "1 / -1" }}>Source link (optional)<input value={f.source_url} onChange={(e) => setF({ ...f, source_url: e.target.value })} /></label>
        <label className="field" style={{ gridColumn: "1 / -1" }}>Notes<textarea rows={2} value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} /></label>
      </div>
      <h3 style={{ marginTop: 16 }}>How should Kosh model it?</h3>
      <ShockBuilder value={shock} onChange={setShock} />
      <ErrorNote error={err} />
    </Modal>
  );
}
