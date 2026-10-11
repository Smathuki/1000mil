import { FormEvent, useEffect, useState } from "react";
import { api, Booking, fmtDate, label, Market, PropertyDetail, today, usd } from "../api";
import { StatusChip } from "../components/Badges";
import { useAsync } from "../hooks";

interface Day { date: string; available: boolean; source: string | null; block_id: number | null; price_cents: number | null }
interface Check { key: string; label: string; weight: number; score: number; hint: string | null }
interface Earnings { in_escrow_cents: number; paid_out_cents: number; commission_cents: number; bookings: number; room_nights: number; full_service: boolean }

const TABS = ["Calendar & pricing", "Readiness", "Channels", "Quality"] as const;

export default function Owner() {
  const props = useAsync(() => api<PropertyDetail[]>("/owner/properties"), []);
  const earnings = useAsync(() => api<Earnings>("/owner/earnings"), []);
  const bookings = useAsync(() => api<Booking[]>("/owner/bookings"), []);
  const [selected, setSelected] = useState<number | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Calendar & pricing");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (selected == null && props.data?.length) setSelected(props.data[0].id);
  }, [props.data, selected]);

  if (props.error) return <div className="empty">{props.error}</div>;
  const current = props.data?.find((p) => p.id === selected);
  const e = earnings.data;

  return (
    <div className="section stack">
      <div className="row between">
        <h1 style={{ margin: 0 }}>Owner console</h1>
        <button className="btn" onClick={() => setAdding(true)}>+ List a property</button>
      </div>

      {e && (
        <div className="grid tiles">
          <div className="tile"><div className="k">In escrow</div><div className="v">{usd(e.in_escrow_cents)}</div></div>
          <div className="tile"><div className="k">Paid out</div><div className="v">{usd(e.paid_out_cents)}</div></div>
          <div className="tile"><div className="k">Stays · nights</div><div className="v">{e.bookings} · {e.room_nights}</div></div>
          <div className="tile"><div className="k">Plan</div><div className="v" style={{ fontSize: 16 }}>{e.full_service ? "Full-service (ops included)" : "Marketplace"}</div></div>
        </div>
      )}

      {adding && <AddProperty onDone={(id) => { setAdding(false); props.reload().then(() => { setSelected(id); setTab("Readiness"); }); }} onCancel={() => setAdding(false)} />}

      <div className="grid side">
        <div className="stack">
          {props.data?.map((p) => (
            <button key={p.id} className="card" style={{ textAlign: "left", cursor: "pointer", borderColor: p.id === selected ? "var(--accent)" : undefined, padding: 12 }} onClick={() => setSelected(p.id)}>
              <div className="row between"><strong>{p.name}</strong><StatusChip status={p.status} /></div>
              <small>{label(p.city)} · readiness {p.readiness_score} · quality {p.quality_score?.toFixed(0) ?? "—"}</small>
            </button>
          ))}
        </div>
        {current && (
          <div className="card">
            <div className="row between">
              <h2 style={{ margin: 0 }}>{current.name}</h2>
              <small className="muted">Base {usd(current.base_rate_cents)}/night</small>
            </div>
            {current.status_reason && <div className="notice" style={{ marginTop: 10 }}>{current.status_reason}</div>}
            <div className="tabs" style={{ marginTop: 12 }}>
              {TABS.map((t) => <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}</button>)}
            </div>
            {tab === "Calendar & pricing" && <OwnerCalendar property={current} />}
            {tab === "Readiness" && <Readiness property={current} onChange={props.reload} />}
            {tab === "Channels" && <Channels property={current} />}
            {tab === "Quality" && <Quality property={current} />}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Bookings</h2>
        <div className="scroll-x">
          <table>
            <thead><tr><th>Code</th><th>Unit</th><th>Dates</th><th>Status</th><th>Escrow</th><th className="r">Guest paid</th><th className="r">Your payout</th></tr></thead>
            <tbody>
              {bookings.data?.filter((b) => b.status !== "pending_payment").slice(-25).reverse().map((b) => (
                <tr key={b.id}>
                  <td>{b.code}</td>
                  <td>{props.data?.find((p) => p.id === b.property_id)?.name}</td>
                  <td className="num">{fmtDate(b.check_in)} → {fmtDate(b.check_out)}</td>
                  <td><StatusChip status={b.status} /></td>
                  <td>{label(b.escrow)}</td>
                  <td className="r num">{usd(b.total_cents)}</td>
                  <td className="r num">{usd(b.owner_payout_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function OwnerCalendar({ property }: { property: PropertyDetail }) {
  const cal = useAsync(() => api<Day[]>(`/owner/properties/${property.id}/calendar`, { params: { start: today(), days: 42 } }), [property.id]);
  const [range, setRange] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  const click = async (d: Day) => {
    if (!d.available) {
      if (d.source === "owner" || d.source === "maintenance" || d.source === "whatsapp") {
        if (!confirm("Release these dates back to the network?")) return;
        await api(`/owner/properties/${property.id}/blocks/${d.block_id}`, { method: "DELETE" });
        setMsg("Dates released.");
        cal.reload();
      } else setMsg(`Blocked by ${label(d.source ?? "")} — manage it on that channel.`);
      return;
    }
    setRange(range.length === 1 && d.date > range[0] ? [range[0], d.date] : [d.date]);
  };

  const block = async () => {
    const [start, last] = range;
    const end = new Date(Date.parse((last ?? start) + "T00:00:00Z") + 86400000).toISOString().slice(0, 10);
    try {
      await api(`/owner/properties/${property.id}/blocks`, { body: { start, end, note: "Owner use" } });
      setMsg("Blocked. Synced to every channel via your iCal feed.");
      setRange([]);
      cal.reload();
    } catch (e: any) {
      setMsg(e.message);
    }
  };

  const inRange = (date: string) => range.length && date >= range[0] && date <= (range[1] ?? range[0]);
  return (
    <div className="stack">
      <small className="muted">Dynamic nightly rates. Tap a start and end date to block for personal use; tap your own block to release it.</small>
      <div className="cal">
        {cal.data?.map((d) => (
          <button key={d.date} className={`day ${!d.available ? (d.source === "booking" || d.source === "hold" ? "booking" : "busy") : ""} ${inRange(d.date) ? "selected" : ""}`} onClick={() => click(d)}>
            <b>{fmtDate(d.date)}</b>
            <span className="num">{d.available ? usd(d.price_cents) : label(d.source ?? "")}</span>
          </button>
        ))}
      </div>
      <div className="row">
        <button className="btn" disabled={!range.length} onClick={block}>Block {range.length ? `${fmtDate(range[0])}${range[1] ? " → " + fmtDate(range[1]) : ""}` : "dates"}</button>
        {msg && <small>{msg}</small>}
      </div>
    </div>
  );
}

function Readiness({ property, onChange }: { property: PropertyDetail; onChange: () => void }) {
  const r = useAsync(() => api<{ score: number; checks: Check[]; threshold: number; status: string }>(`/owner/properties/${property.id}/readiness`), [property.id]);
  const [msg, setMsg] = useState<string | null>(null);
  const activate = async () => {
    try {
      await api(`/owner/properties/${property.id}/activate`, { method: "POST" });
      setMsg("Live on the network.");
      onChange();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  if (!r.data) return <div className="empty">Assessing…</div>;
  return (
    <div className="stack">
      <div className="row between">
        <strong>Hotel-ready score: {r.data.score}/100</strong>
        <small className="muted">Goes live at {r.data.threshold}</small>
      </div>
      <div className="bar-track"><div className="bar-fill" style={{ width: `${r.data.score}%`, background: r.data.score >= r.data.threshold ? "var(--ok)" : "var(--warn)" }} /></div>
      <table>
        <tbody>
          {r.data.checks.map((c) => (
            <tr key={c.key}>
              <td>{c.label}<br />{c.hint && <small className="muted">{c.hint}</small>}</td>
              <td className="r num">{c.score}/{c.weight}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {property.status !== "active" && <button className="btn" onClick={activate}>Go live</button>}
      {msg && <div className="notice">{msg}</div>}
    </div>
  );
}

function Channels({ property }: { property: PropertyDetail }) {
  const ch = useAsync(() => api<{ export_url: string; feeds: { channel: string; ical_url: string; last_result: string | null }[] }>(`/owner/properties/${property.id}/channels`), [property.id]);
  const [ical, setIcal] = useState("");
  const [channel, setChannel] = useState("airbnb");
  const [msg, setMsg] = useState<string | null>(null);
  const doImport = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const r = await api<{ imported: number; conflicts: unknown[] }>(`/owner/properties/${property.id}/ical/import`, { body: { channel, ical } });
      setMsg(`Imported ${r.imported} stays${r.conflicts.length ? ` · ${r.conflicts.length} conflict(s) flagged to ops` : ""}.`);
    } catch (err: any) {
      setMsg(err.message);
    }
  };
  return (
    <div className="stack">
      <p style={{ margin: 0 }}>Keep Airbnb, Booking.com and direct deals in sync. Paste this feed into each channel so Makao bookings block them automatically:</p>
      <code style={{ wordBreak: "break-all", background: "var(--surface-2)", padding: 10, borderRadius: 8 }}>{ch.data ? location.origin + ch.data.export_url : "…"}</code>
      <form className="stack" onSubmit={doImport}>
        <strong>Import a channel calendar</strong>
        <select value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="airbnb">Airbnb</option>
          <option value="booking_com">Booking.com</option>
        </select>
        <textarea rows={5} value={ical} onChange={(e) => setIcal(e.target.value)} placeholder={"BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;VALUE=DATE:20270105\nDTEND;VALUE=DATE:20270108\nEND:VEVENT\nEND:VCALENDAR"} />
        <button className="btn" disabled={!ical.trim()}>Import</button>
      </form>
      {ch.data?.feeds.map((f) => <small key={f.ical_url}>{label(f.channel)} feed · {f.last_result ?? "not synced yet"}</small>)}
      {msg && <div className="notice ok">{msg}</div>}
    </div>
  );
}

function Quality({ property }: { property: PropertyDetail }) {
  const q = useAsync(() => api<{ score: number | null; reviews: number; components: Record<string, number | null>; weak_aspects: string[]; coaching?: string[] }>(`/owner/properties/${property.id}/quality`), [property.id]);
  if (!q.data) return <div className="empty">Loading…</div>;
  if (q.data.score == null) return <div className="empty">No reviews yet — your quality score appears after the first stay.</div>;
  const c = q.data.components;
  return (
    <div className="stack">
      <div className="grid tiles">
        <div className="tile"><div className="k">Quality score</div><div className="v">{q.data.score}</div></div>
        <div className="tile"><div className="k">Avg rating</div><div className="v">{c.avg_rating}</div></div>
        <div className="tile"><div className="k">Power uptime</div><div className="v">{c.power_uptime != null ? `${((c.power_uptime as number) * 100).toFixed(0)}%` : "—"}</div></div>
        <div className="tile"><div className="k">Incidents 90d</div><div className="v">{c.incidents_90d}</div></div>
      </div>
      {q.data.coaching && q.data.coaching.length > 0 ? (
        <div className="notice"><strong>Coaching plan</strong><ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{q.data.coaching.map((t) => <li key={t}>{t}</li>)}</ul></div>
      ) : (
        <div className="notice ok">Guests love this home. Keep it up.</div>
      )}
    </div>
  );
}

function AddProperty({ onDone, onCancel }: { onDone: (id: number) => void; onCancel: () => void }) {
  const markets = useAsync(() => api<Market[]>("/markets"), []);
  const [f, setF] = useState({ name: "", kind: "villa", city: "nairobi", bedrooms: 3, bathrooms: 3, max_guests: 6, rate: 250 });
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const p = await api<PropertyDetail>("/owner/properties", {
        body: { name: f.name, kind: f.kind, city: f.city, bedrooms: f.bedrooms, bathrooms: f.bathrooms, max_guests: f.max_guests, base_rate_cents: f.rate * 100 },
      });
      onDone(p.id);
    } catch (e: any) {
      setErr(e.message);
    }
  };
  return (
    <form className="card stack" onSubmit={submit}>
      <h3 style={{ margin: 0 }}>List a property</h3>
      <div className="row">
        <label className="field" style={{ flex: 2, minWidth: 200 }}>Name<input required minLength={3} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className="field">Type<select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{["villa", "apartment", "lodge", "residence", "tented_camp"].map((k) => <option key={k} value={k}>{label(k)}</option>)}</select></label>
        <label className="field">Market<select value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })}>{markets.data?.map((m) => <option key={m.key} value={m.key}>{m.name}</option>)}</select></label>
      </div>
      <div className="row">
        <label className="field">Bedrooms<input type="number" min={0} value={f.bedrooms} onChange={(e) => setF({ ...f, bedrooms: Number(e.target.value) })} /></label>
        <label className="field">Bathrooms<input type="number" min={0} value={f.bathrooms} onChange={(e) => setF({ ...f, bathrooms: Number(e.target.value) })} /></label>
        <label className="field">Sleeps<input type="number" min={1} value={f.max_guests} onChange={(e) => setF({ ...f, max_guests: Number(e.target.value) })} /></label>
        <label className="field">Base rate (USD/night)<input type="number" min={50} value={f.rate} onChange={(e) => setF({ ...f, rate: Number(e.target.value) })} /></label>
      </div>
      <small className="muted">Next: a verified partner visits to photograph and capture power, water, security and staff details — your readiness score updates as they do.</small>
      {err && <div className="notice bad">{err}</div>}
      <div className="row"><button className="btn">Create draft</button><button type="button" className="btn ghost" onClick={onCancel}>Cancel</button></div>
    </form>
  );
}
