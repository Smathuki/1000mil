import { FormEvent, useState } from "react";
import { addDays, api, fmtDate, label, Role, Task, today, usd } from "../api";
import { StatusChip } from "../components/Badges";
import { useAsync } from "../hooks";

const COLUMNS = ["open", "assigned", "in_progress", "done"] as const;

export default function Ops({ role }: { role: Role }) {
  return role === "partner" ? <PartnerJobs /> : <OpsDesk />;
}

/* ------------------------------------------------------------------ partner app */

function PartnerJobs() {
  const tasks = useAsync(() => api<Task[]>("/ops/tasks"), []);
  const [msg, setMsg] = useState<string | null>(null);
  const [photo, setPhoto] = useState<Record<number, string>>({});

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      setMsg(ok);
      tasks.reload();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  const checkIn = (t: Task, simulate: boolean) => {
    const send = (lat: number, lng: number) => run(() => api(`/ops/tasks/${t.id}/check-in`, { body: { lat, lng } }), "Checked in on site.");
    if (simulate && t.property_location) return send(t.property_location[0] + 0.0004, t.property_location[1]);
    if (!navigator.geolocation) return setMsg("GPS not available on this device");
    navigator.geolocation.getCurrentPosition((pos) => send(pos.coords.latitude, pos.coords.longitude), (err) => setMsg(err.message), { enableHighAccuracy: true });
  };

  const active = tasks.data?.filter((t) => ["assigned", "in_progress"].includes(t.status)) ?? [];
  const finished = tasks.data?.filter((t) => ["done", "verified"].includes(t.status)) ?? [];
  return (
    <div className="section stack">
      <h1 style={{ margin: 0 }}>My jobs</h1>
      <p className="muted" style={{ margin: 0 }}>Check in on site (GPS-verified within 250 m), then upload photo proof to complete.</p>
      {msg && <div className="notice" role="status">{msg}</div>}
      {active.length === 0 && <div className="card empty">No open jobs. New jobs arrive as guests book.</div>}
      {active.map((t) => (
        <div key={t.id} className="card stack">
          <div className="row between">
            <strong>{t.title}</strong>
            <StatusChip status={t.status} />
          </div>
          <small>{t.property_name} · {label(t.property_city)} · due {new Date(t.due_at).toLocaleString()}</small>
          {t.status === "assigned" && (
            <div className="row">
              <button className="btn" onClick={() => checkIn(t, false)}>Check in with GPS</button>
              <button className="btn ghost" onClick={() => checkIn(t, true)}>Demo: I'm at the unit</button>
              {t.property_location && <a className="btn ghost" href={`https://www.google.com/maps/dir/?api=1&destination=${t.property_location.join(",")}`} target="_blank" rel="noreferrer">Navigate</a>}
            </div>
          )}
          {t.status === "in_progress" && (
            <div className="row">
              {t.requires_photo && (
                <input style={{ flex: 1, minWidth: 200 }} placeholder="Photo URL (camera upload in the native app)" value={photo[t.id] ?? ""} onChange={(e) => setPhoto({ ...photo, [t.id]: e.target.value })} />
              )}
              <button className="btn" onClick={() => run(() => api(`/ops/tasks/${t.id}/complete`, { body: { photos: photo[t.id] ? [photo[t.id]] : [] } }), "Job completed — thank you!")}>Complete</button>
              {t.requires_photo && !photo[t.id] && (
                <button className="btn ghost sm" onClick={() => setPhoto({ ...photo, [t.id]: `https://picsum.photos/seed/proof-${t.id}/800/600` })}>Demo photo</button>
              )}
            </div>
          )}
        </div>
      ))}
      {finished.length > 0 && (
        <div className="card">
          <h3>Completed</h3>
          {finished.map((t) => (
            <div key={t.id} className="row between"><span>{t.title}</span><span>{t.rating ? "★".repeat(t.rating) : <StatusChip status={t.status} />}</span></div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ ops desk */

const TABS = ["Task board", "Support", "Quality", "Demand", "Insights"] as const;

function OpsDesk() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Task board");
  const [jobMsg, setJobMsg] = useState<string | null>(null);
  const runJobs = async () => {
    const r = await api<{ expired_bookings: number; escrow_released: string[]; completed_stays: number }>("/ops/jobs/run", { method: "POST" });
    setJobMsg(`Expired ${r.expired_bookings} unpaid · released escrow for ${r.escrow_released.length} · closed ${r.completed_stays} stays`);
  };
  return (
    <div className="section">
      <div className="row between">
        <h1 style={{ margin: 0 }}>Ops desk</h1>
        <div className="row">{jobMsg && <small>{jobMsg}</small>}<button className="btn ghost sm" onClick={runJobs}>Run scheduled jobs</button></div>
      </div>
      <div className="tabs" style={{ marginTop: 12 }}>
        {TABS.map((t) => <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}
      </div>
      {tab === "Task board" && <TaskBoard />}
      {tab === "Support" && <Support />}
      {tab === "Quality" && <QualityBoard />}
      {tab === "Demand" && <Demand />}
      {tab === "Insights" && <Insights />}
    </div>
  );
}

function TaskBoard() {
  const [city, setCity] = useState("");
  const tasks = useAsync(() => api<Task[]>("/ops/tasks", { params: { city } }), [city]);
  const partners = useAsync(() => api<{ id: number; name: string }[]>("/ops/partners"), []);
  const name = (id: number | null) => partners.data?.find((p) => p.id === id)?.name ?? "Unassigned";
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      tasks.reload();
    } catch (e: any) {
      alert(e.message);
    }
  };
  return (
    <div className="stack">
      <select value={city} onChange={(e) => setCity(e.target.value)} style={{ alignSelf: "start" }} aria-label="City">
        <option value="">All markets</option>
        {["nairobi", "maasai-mara", "diani", "zanzibar", "arusha", "dar-es-salaam", "kigali", "kampala", "addis-ababa"].map((c) => <option key={c} value={c}>{label(c)}</option>)}
      </select>
      <div className="kanban">
        {COLUMNS.map((col) => (
          <div key={col} className="col">
            <strong>{label(col)} <small className="muted">{tasks.data?.filter((t) => t.status === col).length ?? 0}</small></strong>
            {tasks.data?.filter((t) => t.status === col).slice(0, 40).map((t) => (
              <div key={t.id} className="task">
                <div className="row between"><span className="chip">{label(t.kind)}</span><small>{fmtDate(t.due_at.slice(0, 10))}</small></div>
                <span>{t.title}</span>
                <small className="muted">{t.property_name} · {name(t.partner_id)}{t.checkin_distance_m != null ? ` · GPS ${t.checkin_distance_m} m` : ""}</small>
                {t.proof_photos.length > 0 && <img src={t.proof_photos[0]} alt="Proof" style={{ width: "100%", borderRadius: 6 }} />}
                {t.status === "open" && <button className="btn sm" onClick={() => act(() => api(`/ops/tasks/${t.id}/dispatch`, { method: "POST" }))}>Auto-dispatch</button>}
                {t.status === "done" && (
                  <div className="row">{[5, 4, 3].map((r) => <button key={r} className="btn ghost sm" onClick={() => act(() => api(`/ops/tasks/${t.id}/verify`, { body: { rating: r } }))}>Verify {r}★</button>)}</div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function Support() {
  const t = useAsync(() => api<{ id: number; booking: string; property: string; category: string; message: string; priority: string; status: string }[]>("/ops/tickets"), []);
  return (
    <div className="card scroll-x">
      {t.data?.length === 0 && <div className="empty">No tickets.</div>}
      <table>
        <tbody>
          {t.data?.map((x) => (
            <tr key={x.id}>
              <td><span className={`chip ${x.priority === "urgent" ? "bad" : ""}`}>{x.priority}</span></td>
              <td>{x.booking}<br /><small>{x.property}</small></td>
              <td>{label(x.category)}: {x.message}</td>
              <td>{x.status === "open" ? <button className="btn sm" onClick={() => api(`/ops/tickets/${x.id}/resolve`, { method: "POST" }).then(t.reload)}>Resolve</button> : x.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function QualityBoard() {
  const q = useAsync(() => api<any[]>("/admin/quality"), []);
  return (
    <div className="card scroll-x">
      <table>
        <thead><tr><th>Unit</th><th>Status</th><th className="r">Score</th><th className="r">Rating</th><th className="r">Uptime</th><th>Weak spots</th><th /></tr></thead>
        <tbody>
          {q.data?.map((r) => (
            <tr key={r.property_id}>
              <td>{r.name}<br /><small>{label(r.city)}</small></td>
              <td><StatusChip status={r.status} /></td>
              <td className="r num">{r.score ?? "—"}</td>
              <td className="r num">{r.components?.avg_rating ?? "—"}</td>
              <td className="r num">{r.components?.power_uptime != null ? `${(r.components.power_uptime * 100).toFixed(0)}%` : "—"}</td>
              <td>{r.weak_aspects?.map((a: string) => <span key={a} className="chip bad" style={{ marginRight: 4 }}>{a}</span>)}</td>
              <td>{r.status === "suspended" && <button className="btn sm" onClick={() => api(`/admin/properties/${r.property_id}/reinstate`, { method: "POST" }).then(q.reload)}>Reinstate after inspection</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Demand() {
  const [city, setCity] = useState("nairobi");
  const outlook = useAsync(() => api<{ date: string; occupancy: number; events: string[]; demand_index: number }[]>(`/markets/${city}/outlook`, { params: { days: 45 } }), [city]);
  const signals = useAsync(() => api<any[]>("/signals", { params: { city } }), [city]);
  const [f, setF] = useState({ name: "", kind: "conference", start: addDays(today(), 20), end: addDays(today(), 23), intensity: 0.6 });
  const add = async (e: FormEvent) => {
    e.preventDefault();
    await api("/signals", { body: { ...f, city } });
    setF({ ...f, name: "" });
    signals.reload();
    outlook.reload();
  };
  const max = Math.max(...(outlook.data?.map((d) => d.demand_index) ?? [1]));
  return (
    <div className="stack">
      <select value={city} onChange={(e) => setCity(e.target.value)} style={{ alignSelf: "start" }} aria-label="Market">
        {["nairobi", "maasai-mara", "diani", "zanzibar", "arusha", "dar-es-salaam", "kigali", "kampala", "addis-ababa"].map((c) => <option key={c} value={c}>{label(c)}</option>)}
      </select>
      <div className="card">
        <h3>45-day demand index</h3>
        <svg viewBox={`0 0 ${(outlook.data?.length ?? 1) * 12} 100`} style={{ width: "100%", height: 140 }} role="img" aria-label="Demand index by day">
          {outlook.data?.map((d, i) => (
            <rect key={d.date} x={i * 12 + 1} width={9} y={100 - (d.demand_index / max) * 95} height={(d.demand_index / max) * 95} rx={2}
              fill={d.events.length ? "var(--accent)" : "var(--brand)"}>
              <title>{`${d.date}: index ${d.demand_index}, occupancy ${(d.occupancy * 100).toFixed(0)}%${d.events.length ? " — " + d.events.join(", ") : ""}`}</title>
            </rect>
          ))}
        </svg>
        <small className="muted">Gold bars carry an event or season signal; hover for detail. Signals feed nightly prices immediately.</small>
      </div>
      <div className="card">
        <h3>Signals</h3>
        <table><tbody>
          {signals.data?.map((s) => <tr key={s.id}><td>{s.name}</td><td>{label(s.kind)}</td><td className="num">{s.start} → {s.end}</td><td className="r num">{s.intensity}</td><td><small>{s.source}</small></td></tr>)}
        </tbody></table>
        <form className="row" style={{ marginTop: 12 }} onSubmit={add}>
          <input required placeholder="Event / signal name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} style={{ flex: 1, minWidth: 180 }} />
          <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{["conference", "safari", "holiday", "diaspora", "sports", "flights", "corporate"].map((k) => <option key={k}>{k}</option>)}</select>
          <input type="date" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} />
          <input type="date" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} />
          <input type="number" step={0.1} min={0} max={1} value={f.intensity} onChange={(e) => setF({ ...f, intensity: Number(e.target.value) })} style={{ width: 80 }} aria-label="Intensity" />
          <button className="btn">Add signal</button>
        </form>
      </div>
    </div>
  );
}

function Insights() {
  const d = useAsync(() => api<{ k_anonymity: number; cells: any[]; expansion_candidates: any[] }>("/admin/insights"), []);
  if (!d.data) return <div className="empty">Loading…</div>;
  return (
    <div className="stack">
      <div className="card">
        <h3>Where to activate supply next</h3>
        <p className="muted">Markets ranked by searches that found no verified home — the anonymised signal sold to developers and investors.</p>
        {d.data.expansion_candidates.slice(0, 6).map((m) => (
          <div key={m.market} className="stack" style={{ gap: 4, marginBottom: 10 }}>
            <div className="row between"><span>{m.market_name}</span><small className="num">{m.unmet_searches}/{m.searches} unmet · {(m.unmet_demand_rate * 100).toFixed(0)}%</small></div>
            <div className="bar-track"><div className="bar-fill" style={{ width: `${m.unmet_demand_rate * 100}%`, background: "var(--accent)" }} /></div>
          </div>
        ))}
      </div>
      <div className="card scroll-x">
        <h3>Market × month <small className="muted">(cells with &lt; {d.data.k_anonymity} bookings suppressed)</small></h3>
        <table>
          <thead><tr><th>Market</th><th>Month</th><th className="r">Searches</th><th className="r">Unmet</th><th className="r">Bookings</th><th className="r">ADR</th><th className="r">Lead (d)</th></tr></thead>
          <tbody>
            {d.data.cells.map((c) => (
              <tr key={c.market + c.month}>
                <td>{c.market_name}</td><td>{c.month}</td><td className="r num">{c.searches}</td>
                <td className="r num">{(c.unmet_demand_rate * 100).toFixed(0)}%</td>
                <td className="r num">{c.suppressed ? "‹k" : c.bookings}</td>
                <td className="r num">{c.suppressed ? "—" : usd(c.adr_cents)}</td>
                <td className="r num">{c.avg_lead_days ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
