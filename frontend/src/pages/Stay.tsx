import { FormEvent, useState } from "react";
import { useParams } from "react-router-dom";
import { api, Booking, fmtDate, label, PropertyDetail, usd } from "../api";
import { StatusChip } from "../components/Badges";
import { useAsync } from "../hooks";

interface StayData {
  booking: Booking;
  property: PropertyDetail;
  unit_status: {
    power: { source: string | null; label: string; battery_pct: string | null; fuel_pct: string | null; ok: boolean };
    water: { tank_pct: string | null; ok: boolean };
    security: { alarm: string; door: string; guard_on_site: boolean; ok: boolean };
    internet: { status: string; ok: boolean };
    updated_at: string | null;
    uptime_30d: number | null;
  };
  readiness: { ready: boolean; completed: number; total: number };
  access: { code: string | null; method: string; valid_from: string; valid_until: string } | null;
  upsells: { sku: string; title: string; price_cents: number }[];
  my_upsells: { id: number; title: string; price_cents: number; status: string }[];
  tickets: { id: number; category: string; message: string; status: string; priority: string }[];
  recommendations: { name: string; type: string }[];
  support_whatsapp: string;
}

/** The in-stay guest app: live unit status, access, one-tap support and extras. */
export default function Stay() {
  const { code } = useParams();
  const stay = useAsync(() => api<StayData>(`/stay/${code}`), [code]);
  const [support, setSupport] = useState({ category: "other", message: "" });
  const [review, setReview] = useState({ rating: 5, text: "" });
  const [note, setNote] = useState<string | null>(null);

  if (stay.error) return <div className="empty">{stay.error}</div>;
  if (!stay.data) return <div className="empty">Loading your stay…</div>;
  const { booking: b, property: p, unit_status: u, readiness, access } = stay.data;

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try {
      await fn();
      setNote(msg);
      stay.reload();
    } catch (e: any) {
      setNote(e.message);
    }
  };

  const sendSupport = (e: FormEvent) => {
    e.preventDefault();
    act(() => api(`/stay/${b.code}/support`, { body: support }), "Concierge notified — we'll reply on WhatsApp.");
    setSupport({ category: "other", message: "" });
  };

  return (
    <div className="section stack">
      <div className="row between">
        <div>
          <div className="row"><h1 style={{ margin: 0 }}>{p.name}</h1><StatusChip status={b.status} /></div>
          <p className="muted num" style={{ margin: 0 }}>{b.code} · {fmtDate(b.check_in)} → {fmtDate(b.check_out)} · {b.guests} guests</p>
        </div>
        <div className="row">
          {b.status === "confirmed" && <button className="btn" onClick={() => act(() => api(`/bookings/${b.code}/check-in`, { method: "POST" }), "Welcome! You're checked in.")}>I've arrived</button>}
          <a className="btn gold" href={`https://wa.me/${stay.data.support_whatsapp.replace(/\D/g, "")}?text=${encodeURIComponent(`Hi, booking ${b.code}`)}`} target="_blank" rel="noreferrer">WhatsApp concierge</a>
        </div>
      </div>
      {note && <div className="notice ok" role="status">{note}</div>}

      <div className="grid tiles">
        <div className={`tile ${u.power.ok ? "ok" : "bad"}`}>
          <div className="k">Power</div>
          <div className="v" style={{ fontSize: 16 }}>{u.power.label}</div>
          <small>{u.power.battery_pct ? `Battery ${u.power.battery_pct}%` : ""}{u.uptime_30d != null ? ` · ${(u.uptime_30d * 100).toFixed(0)}% uptime` : ""}</small>
        </div>
        <div className={`tile ${u.water.ok ? "ok" : "bad"}`}>
          <div className="k">Water</div>
          <div className="v">{u.water.tank_pct ? `${u.water.tank_pct}%` : "—"}</div>
          <small>Storage tank level</small>
        </div>
        <div className={`tile ${u.security.ok ? "ok" : "bad"}`}>
          <div className="k">Security</div>
          <div className="v" style={{ fontSize: 16 }}>{label(u.security.alarm)}</div>
          <small>{u.security.guard_on_site ? "Guard on site 24h" : "Monitored"}</small>
        </div>
        <div className={`tile ${u.internet.ok ? "ok" : "bad"}`}>
          <div className="k">Internet</div>
          <div className="v" style={{ fontSize: 16 }}>{u.internet.status === "up" ? "Online" : label(u.internet.status)}</div>
          <small>{p.wifi_mbps} Mbps</small>
        </div>
      </div>

      <div className="grid two">
        <div className="stack">
          <div className="card">
            <h3>Arrival</h3>
            <div className="row between">
              <span>Home prepared {readiness.completed}/{readiness.total}</span>
              <span className={`chip ${readiness.ready ? "ok" : "warn"}`}>{readiness.ready ? "Ready for you" : "Team preparing"}</span>
            </div>
            <div className="bar-track" style={{ marginTop: 8 }}><div className="bar-fill" style={{ width: `${readiness.total ? (readiness.completed / readiness.total) * 100 : 0}%` }} /></div>
            {access ? (
              access.code ? (
                <div style={{ marginTop: 14 }}>
                  <small className="muted">Smart-lock code · valid {new Date(access.valid_from).toLocaleString()} → {new Date(access.valid_until).toLocaleString()}</small>
                  <div className="code">{access.code}</div>
                </div>
              ) : (
                <p style={{ marginTop: 14 }}>Your host team will welcome you and hand over keys.</p>
              )
            ) : (
              <p className="muted" style={{ marginTop: 14 }}>Access details appear here 24 hours before check-in.</p>
            )}
            {p.lat != null && <a className="btn ghost sm" style={{ marginTop: 8, display: "inline-block" }} href={`https://www.google.com/maps?q=${p.lat},${p.lng}`} target="_blank" rel="noreferrer">Directions</a>}
          </div>

          <div className="card">
            <h3>Add to your stay</h3>
            <div className="stack">
              {stay.data.upsells.map((x) => (
                <div key={x.sku} className="row between">
                  <span>{x.title}</span>
                  <span className="row"><span className="num">{usd(x.price_cents)}</span>
                    <button className="btn sm" disabled={!["confirmed", "checked_in"].includes(b.status)} onClick={() => act(() => api(`/stay/${b.code}/upsells`, { body: { sku: x.sku } }), `${x.title} booked — a partner has been assigned.`)}>Add</button>
                  </span>
                </div>
              ))}
            </div>
            {stay.data.my_upsells.length > 0 && (
              <p className="muted" style={{ marginTop: 10, marginBottom: 0 }}>Booked: {stay.data.my_upsells.map((x) => x.title).join(", ")}</p>
            )}
          </div>
        </div>

        <div className="stack">
          <form className="card stack" onSubmit={sendSupport}>
            <h3 style={{ margin: 0 }}>Need anything?</h3>
            <select value={support.category} onChange={(e) => setSupport({ ...support, category: e.target.value })} aria-label="Topic">
              {["access", "power", "water", "security", "cleanliness", "transport", "other"].map((c) => <option key={c} value={c}>{label(c)}</option>)}
            </select>
            <textarea rows={3} value={support.message} onChange={(e) => setSupport({ ...support, message: e.target.value })} placeholder="Tell us what you need" required minLength={2} />
            <button className="btn">Send to concierge</button>
            {stay.data.tickets.map((t) => (
              <small key={t.id}><span className={`chip ${t.priority === "urgent" ? "bad" : ""}`}>{t.category}</span> {t.message} — {t.status}</small>
            ))}
          </form>

          {["checked_in", "completed"].includes(b.status) && (
            <form className="card stack" onSubmit={(e) => { e.preventDefault(); act(() => api(`/bookings/${b.code}/review`, { body: review }), "Thanks for your review!"); }}>
              <h3 style={{ margin: 0 }}>Rate your stay</h3>
              <select value={review.rating} onChange={(e) => setReview({ ...review, rating: Number(e.target.value) })} aria-label="Rating">
                {[5, 4, 3, 2, 1].map((r) => <option key={r} value={r}>{"★".repeat(r)}</option>)}
              </select>
              <textarea rows={3} value={review.text} onChange={(e) => setReview({ ...review, text: e.target.value })} placeholder="What stood out?" />
              <button className="btn">Submit review</button>
            </form>
          )}

          <div className="card">
            <h3>Local picks</h3>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {stay.data.recommendations.map((r) => <li key={r.name}>{r.name} <small className="muted">· {r.type}</small></li>)}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
