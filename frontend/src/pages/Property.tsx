import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { addDays, api, Booking, fmtDate, label, local, PropertyDetail, Quote, today, usd } from "../api";
import { TrustBadges } from "../components/Badges";
import Img from "../components/Img";
import PayModal from "../components/PayModal";
import { useAsync } from "../hooks";

const FACTOR_NAMES: Record<string, string> = {
  season: "Season",
  weekend: "Weekend",
  events: "Events & demand",
  compression: "Market occupancy",
  lead_time: "Short notice",
  length_of_stay: "Length of stay",
};

export default function PropertyPage() {
  const { slug } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const prop = useAsync(() => api<PropertyDetail>(`/properties/${slug}`), [slug]);
  const extras = useAsync(() => api<{ recommendations: { name: string; type: string }[] }>(`/properties/${slug}/extras`), [slug]);
  const [stay, setStay] = useState({
    check_in: params.get("in") ?? addDays(today(), 14),
    check_out: params.get("out") ?? addDays(today(), 17),
    guests: Number(params.get("guests") ?? 2),
    airport_transfer: false,
  });
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteErr, setQuoteErr] = useState<string | null>(null);
  const [booking, setBooking] = useState<Booking | null>(null);
  const [busy, setBusy] = useState(false);
  const avail = useAsync(
    () => (prop.data ? api<{ date: string; available: boolean }[]>(`/properties/${prop.data.id}/availability`, { params: { days: 42 } }) : Promise.resolve([])),
    [prop.data?.id]
  );

  useEffect(() => {
    if (!prop.data) return;
    setQuoteErr(null);
    api<Quote>("/quote", { body: { property_id: prop.data.id, check_in: stay.check_in, check_out: stay.check_out, guests: stay.guests } })
      .then(setQuote)
      .catch((e) => {
        setQuote(null);
        setQuoteErr(e.message);
      });
  }, [prop.data, stay.check_in, stay.check_out, stay.guests]);

  if (prop.error) return <div className="empty">{prop.error}. <Link to="/">Back to explore</Link></div>;
  if (!prop.data) return <div className="empty">Loading…</div>;
  const p = prop.data;

  const reserve = async () => {
    setBusy(true);
    try {
      setBooking(await api<Booking>("/bookings", { body: { property_id: p.id, ...stay } }));
    } catch (e: any) {
      setQuoteErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const factorSummary = (() => {
    if (!quote) return [];
    const keys = Object.keys(FACTOR_NAMES);
    return keys
      .map((k) => {
        const avg = quote.nights.reduce((s, n) => s + (n.factors[k] ?? 1), 0) / quote.nights.length;
        return { k, pct: Math.round((avg - 1) * 100) };
      })
      .filter((f) => f.pct !== 0);
  })();
  const signals = quote ? [...new Set(quote.nights.flatMap((n) => n.signals))] : [];

  return (
    <div className="section">
      <div className="gallery">
        {p.photos.slice(0, 5).map((ph, i) => (
          <Img key={i} src={ph.url} alt={`${p.name} — ${ph.room}`} caption={ph.room} />
        ))}
      </div>
      <div className="grid two section">
        <div className="stack">
          <div>
            <span className="chip">{label(p.kind)} · {p.neighbourhood}</span>
            <h1 style={{ marginTop: 8 }}>{p.name}</h1>
            <p className="muted">{p.bedrooms} bedroom{p.bedrooms === 1 ? "" : "s"} · {p.bathrooms} bath{p.bathrooms === 1 ? "" : "s"} · sleeps {p.max_guests} · min {p.min_nights} night{p.min_nights > 1 ? "s" : ""}</p>
            <TrustBadges p={p} />
          </div>
          <p>{p.description}</p>

          <div className="card">
            <h3>Hotel-ready, verified</h3>
            <div className="grid tiles">
              <div className="tile"><div className="k">Readiness</div><div className="v">{p.readiness_score}/100</div></div>
              <div className="tile"><div className="k">Power</div><div className="v" style={{ fontSize: 16 }}>{label(p.power_backup)}{p.water_backup ? " · water tank" : ""}</div></div>
              <div className="tile"><div className="k">Wi-Fi</div><div className="v">{p.wifi_mbps} Mbps</div></div>
              <div className="tile"><div className="k">Access</div><div className="v" style={{ fontSize: 16 }}>{p.smart_lock ? "Smart lock" : "Staff welcome"}</div></div>
            </div>
            <p className="muted" style={{ marginTop: 10, marginBottom: 0 }}>
              Security: {p.security.map(label).join(", ") || "—"} · Amenities: {p.amenities.map(label).join(", ")}
            </p>
          </div>

          <div className="card">
            <h3>Next 6 weeks</h3>
            <div className="cal">
              {avail.data?.map((d) => (
                <button
                  key={d.date}
                  className={`day ${d.available ? "" : "busy"} ${d.date >= stay.check_in && d.date < stay.check_out ? "selected" : ""}`}
                  disabled={!d.available}
                  onClick={() => setStay({ ...stay, check_in: d.date, check_out: addDays(d.date, Math.max(p.min_nights, 2)) })}
                  title={d.available ? "Start stay here" : "Unavailable"}
                >
                  <b>{fmtDate(d.date)}</b>
                  {d.available ? "" : "—"}
                </button>
              ))}
            </div>
          </div>

          {extras.data && extras.data.recommendations.length > 0 && (
            <div className="card">
              <h3>Around here</h3>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {extras.data.recommendations.map((r) => (
                  <li key={r.name}>{r.name} <small className="muted">· {r.type}</small></li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <aside className="card stack" style={{ alignSelf: "start", position: "sticky", top: 80 }}>
          <div className="row" style={{ gap: 8 }}>
            <label className="field" style={{ flex: 1 }}>Check-in<input type="date" value={stay.check_in} min={today()} onChange={(e) => setStay({ ...stay, check_in: e.target.value })} /></label>
            <label className="field" style={{ flex: 1 }}>Check-out<input type="date" value={stay.check_out} min={addDays(stay.check_in, 1)} onChange={(e) => setStay({ ...stay, check_out: e.target.value })} /></label>
          </div>
          <label className="field">Guests<input type="number" min={1} max={p.max_guests} value={stay.guests} onChange={(e) => setStay({ ...stay, guests: Number(e.target.value) })} /></label>
          <label className="row" style={{ gap: 8 }}>
            <input type="checkbox" checked={stay.airport_transfer} onChange={(e) => setStay({ ...stay, airport_transfer: e.target.checked })} />
            Airport pickup on arrival
          </label>

          {quoteErr && <div className="notice bad">{quoteErr}</div>}
          {quote && (
            <>
              {!quote.available && <div className="notice bad">Those dates are taken — pick another start date.</div>}
              {signals.length > 0 && <div className="notice">High demand: {signals.join(", ")}</div>}
              <table>
                <tbody>
                  <tr><td>{quote.nights.length} nights</td><td className="r num">{usd(quote.accommodation_cents)}</td></tr>
                  <tr><td>Cleaning &amp; turnover</td><td className="r num">{usd(quote.cleaning_fee_cents)}</td></tr>
                  <tr><td>Service &amp; concierge</td><td className="r num">{usd(quote.service_fee_cents)}</td></tr>
                  <tr><td><strong>Total</strong></td><td className="r num"><strong>{usd(quote.total_cents)}</strong><br /><small>≈ {local(quote.local.total, quote.local.currency)}</small></td></tr>
                </tbody>
              </table>
              {factorSummary.length > 0 && (
                <details>
                  <summary className="muted" style={{ cursor: "pointer" }}>Why this price?</summary>
                  <div className="row" style={{ gap: 6, marginTop: 8 }}>
                    {factorSummary.map((f) => (
                      <span key={f.k} className={`chip ${f.pct > 0 ? "warn" : "ok"}`}>{FACTOR_NAMES[f.k]} {f.pct > 0 ? "+" : ""}{f.pct}%</span>
                    ))}
                  </div>
                </details>
              )}
              <small className="muted">{label(quote.cancellation_policy)} cancellation · paid into escrow</small>
              <button className="btn" disabled={!quote.available || busy} onClick={reserve}>Reserve &amp; pay</button>
            </>
          )}
        </aside>
      </div>
      {booking && (
        <PayModal
          target={{ booking_id: booking.id }}
          totalCents={booking.total_cents}
          onClose={() => setBooking(null)}
          onPaid={() => setTimeout(() => navigate(`/stay/${booking.code}`), 900)}
        />
      )}
    </div>
  );
}
