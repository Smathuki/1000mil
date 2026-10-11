import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { addDays, api, Market, Package, PropertyCard, Quote, today, usd } from "../api";
import PayModal from "../components/PayModal";
import { useAsync } from "../hooks";

interface Leg {
  city: string;
  property_id: number | "";
  nights: number;
}

interface ItinQuote {
  legs: Quote[];
  discount_rate: number;
  discount_cents: number;
  total_cents: number;
  all_available: boolean;
}

/** Multi-property trip, priced, booked and paid as one package. */
export default function Itinerary() {
  const navigate = useNavigate();
  const markets = useAsync(() => api<Market[]>("/markets"), []);
  const [start, setStart] = useState(addDays(today(), 30));
  const [guests, setGuests] = useState(2);
  const [legs, setLegs] = useState<Leg[]>([
    { city: "nairobi", property_id: "", nights: 2 },
    { city: "maasai-mara", property_id: "", nights: 3 },
    { city: "zanzibar", property_id: "", nights: 4 },
  ]);
  const [options, setOptions] = useState<Record<string, { property: PropertyCard; nightly_avg_cents: number }[]>>({});
  const [quote, setQuote] = useState<ItinQuote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pkg, setPkg] = useState<Package | null>(null);

  const dated = legs.reduce<{ leg: Leg; check_in: string; check_out: string }[]>((acc, leg) => {
    const check_in = acc.length ? acc[acc.length - 1].check_out : start;
    return [...acc, { leg, check_in, check_out: addDays(check_in, leg.nights) }];
  }, []);
  const datesKey = dated.map((d) => `${d.leg.city}:${d.check_in}:${d.check_out}`).join("|");

  useEffect(() => {
    dated.forEach((d, i) => {
      api("/search", { params: { city: d.leg.city, check_in: d.check_in, check_out: d.check_out, guests } })
        .then((r: any[]) => {
          setOptions((o) => ({ ...o, [i]: r }));
          setLegs((ls) => ls.map((l, j) => (j === i && (!l.property_id || !r.some((x) => x.property.id === l.property_id)) ? { ...l, property_id: r[0]?.property.id ?? "" } : l)));
        })
        .catch(() => setOptions((o) => ({ ...o, [i]: [] })));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datesKey, guests]);

  const ready = legs.length >= 2 && legs.every((l) => l.property_id);
  const body = { legs: dated.map((d) => ({ property_id: d.leg.property_id, check_in: d.check_in, check_out: d.check_out, guests })) };
  const bodyKey = JSON.stringify(body);

  useEffect(() => {
    if (!ready) return setQuote(null);
    setError(null);
    api<ItinQuote>("/quote/itinerary", { body }).then(setQuote).catch((e) => { setQuote(null); setError(e.message); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bodyKey, ready]);

  const book = async () => {
    try {
      setPkg(await api<Package>("/packages", { body }));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const update = (i: number, patch: Partial<Leg>) => setLegs((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  return (
    <div className="section">
      <h1>Build an itinerary</h1>
      <p className="muted">Chain stays across cities and safari circuits. One payment, one concierge, transfers between legs arranged for you — and 5% off three stays or more.</p>
      <div className="card row" style={{ gap: 16 }}>
        <label className="field">Start<input type="date" value={start} min={today()} onChange={(e) => setStart(e.target.value)} /></label>
        <label className="field">Guests<input type="number" min={1} max={20} value={guests} onChange={(e) => setGuests(Number(e.target.value))} /></label>
      </div>

      <div className="stack section">
        {dated.map((d, i) => (
          <div key={i} className="card row" style={{ gap: 12, alignItems: "end" }}>
            <strong style={{ width: 24 }}>{i + 1}</strong>
            <label className="field">Destination
              <select value={d.leg.city} onChange={(e) => update(i, { city: e.target.value, property_id: "" })}>
                {markets.data?.map((m) => <option key={m.key} value={m.key}>{m.name}</option>)}
              </select>
            </label>
            <label className="field">Nights<input type="number" min={1} max={30} value={d.leg.nights} onChange={(e) => update(i, { nights: Math.max(1, Number(e.target.value)) })} style={{ width: 80 }} /></label>
            <label className="field" style={{ flex: 1, minWidth: 220 }}>Stay
              <select value={d.leg.property_id} onChange={(e) => update(i, { property_id: Number(e.target.value) })}>
                {(options[i] ?? []).length === 0 && <option value="">No verified homes free</option>}
                {(options[i] ?? []).map((o) => (
                  <option key={o.property.id} value={o.property.id}>{o.property.name} — {usd(o.nightly_avg_cents)}/night</option>
                ))}
              </select>
            </label>
            <small className="muted num">{d.check_in} → {d.check_out}</small>
            {legs.length > 2 && <button className="btn ghost sm" onClick={() => setLegs(legs.filter((_, j) => j !== i))}>Remove</button>}
          </div>
        ))}
        {legs.length < 6 && (
          <button className="btn ghost" style={{ alignSelf: "start" }} onClick={() => setLegs([...legs, { city: "diani", property_id: "", nights: 3 }])}>+ Add a stay</button>
        )}
      </div>

      {error && <div className="notice bad section">{error}</div>}
      {quote && (
        <div className="card section stack">
          <table>
            <thead><tr><th>Stay</th><th>Dates</th><th className="r">Price</th></tr></thead>
            <tbody>
              {quote.legs.map((l) => (
                <tr key={l.property_id + l.check_in}>
                  <td>{l.property_name}{!l.available && <span className="chip bad">taken</span>}</td>
                  <td className="num">{l.check_in} → {l.check_out}</td>
                  <td className="r num">{usd(l.total_cents)}</td>
                </tr>
              ))}
              {quote.discount_cents > 0 && <tr><td colSpan={2}>Itinerary discount ({quote.discount_rate * 100}%)</td><td className="r num">−{usd(quote.discount_cents)}</td></tr>}
              <tr><td colSpan={2}><strong>Total</strong></td><td className="r num"><strong>{usd(quote.total_cents)}</strong></td></tr>
            </tbody>
          </table>
          <button className="btn" style={{ alignSelf: "end" }} disabled={!quote.all_available} onClick={book}>Book whole itinerary</button>
        </div>
      )}
      {pkg && (
        <PayModal target={{ package_id: pkg.id }} totalCents={pkg.total_cents} onClose={() => setPkg(null)} onPaid={() => setTimeout(() => navigate("/trips"), 900)} />
      )}
    </div>
  );
}
