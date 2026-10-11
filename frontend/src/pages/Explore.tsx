import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { addDays, api, label, Market, PropertyCard, today, usd } from "../api";
import { TrustBadges } from "../components/Badges";
import Img from "../components/Img";
import { useAsync } from "../hooks";

interface Result {
  property: PropertyCard;
  nightly_avg_cents: number;
  accommodation_cents: number;
  signals: string[];
}

export default function Explore() {
  const [params, setParams] = useSearchParams();
  const markets = useAsync(() => api<Market[]>("/markets"), []);
  const [form, setForm] = useState({
    city: params.get("city") ?? "nairobi",
    check_in: params.get("in") ?? addDays(today(), 14),
    check_out: params.get("out") ?? addDays(today(), 17),
    guests: Number(params.get("guests") ?? 2),
    kind: params.get("kind") ?? "",
  });
  const [results, setResults] = useState<Result[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const run = async (f = form) => {
    setLoading(true);
    setError(null);
    try {
      setResults(await api<Result[]>("/search", { params: { ...f } }));
    } catch (e: any) {
      setError(e.message);
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParams({ city: form.city, in: form.check_in, out: form.check_out, guests: String(form.guests), ...(form.kind ? { kind: form.kind } : {}) });
    run();
  };

  const pick = (city: string) => {
    const f = { ...form, city };
    setForm(f);
    run(f);
  };

  const nights = Math.max(1, (Date.parse(form.check_out) - Date.parse(form.check_in)) / 86400000);
  const market = markets.data?.find((m) => m.key === form.city);

  return (
    <>
      <section className="hero">
        <h1>Verified luxury homes, lodges &amp; villas — on demand.</h1>
        <p className="lede">
          Hotel-grade stays across East Africa: backup power, 24h security, on-call staff and a concierge on WhatsApp.
          Book one stay, or a whole Nairobi → Mara → Zanzibar itinerary in one go.
        </p>
        <form className="card searchbar" onSubmit={submit}>
          <label className="field">
            Destination
            <select value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })}>
              {markets.data?.map((m) => (
                <option key={m.key} value={m.key}>{m.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Check-in
            <input type="date" value={form.check_in} min={today()} onChange={(e) => setForm({ ...form, check_in: e.target.value, check_out: e.target.value >= form.check_out ? addDays(e.target.value, 2) : form.check_out })} />
          </label>
          <label className="field">
            Check-out
            <input type="date" value={form.check_out} min={addDays(form.check_in, 1)} onChange={(e) => setForm({ ...form, check_out: e.target.value })} />
          </label>
          <label className="field">
            Guests
            <input type="number" min={1} max={30} value={form.guests} onChange={(e) => setForm({ ...form, guests: Number(e.target.value) })} />
          </label>
          <button className="btn">Search</button>
        </form>
        <div className="row" style={{ marginTop: 12, gap: 6 }}>
          {markets.data?.map((m) => (
            <button key={m.key} className={`chip ${m.key === form.city ? "gold" : ""}`} style={{ border: 0, cursor: "pointer" }} onClick={() => pick(m.key)}>
              {m.name} · {m.live_units}
            </button>
          ))}
        </div>
      </section>

      <div className="row between">
        <h2 style={{ margin: 0 }}>
          {market?.name ?? ""} <small className="muted">· {nights} night{nights > 1 ? "s" : ""}</small>
        </h2>
        <select value={form.kind} onChange={(e) => { const f = { ...form, kind: e.target.value }; setForm(f); run(f); }} aria-label="Type">
          <option value="">All types</option>
          {["villa", "apartment", "lodge", "residence", "tented_camp"].map((k) => (
            <option key={k} value={k}>{label(k)}</option>
          ))}
        </select>
      </div>
      {error && <div className="notice bad" style={{ marginTop: 12 }}>{error}</div>}
      {loading && <div className="empty">Finding verified homes…</div>}
      {!loading && results?.length === 0 && (
        <div className="card empty" style={{ marginTop: 16 }}>
          No verified homes free for those dates. Message the concierge — we activate new supply on request.
        </div>
      )}
      <div className="grid cards" style={{ marginTop: 16 }}>
        {results?.map(({ property: p, nightly_avg_cents, accommodation_cents, signals }) => (
          <Link key={p.id} to={`/p/${p.slug}?in=${form.check_in}&out=${form.check_out}&guests=${form.guests}`} className="card listing">
            <Img src={p.photos[0]?.url} alt={p.name} caption={p.neighbourhood ?? p.name} />
            <div className="body">
              <div className="row between">
                <span className="chip">{label(p.kind)}</span>
                {signals.length > 0 && <span className="chip warn" title={signals.join(", ")}>High demand</span>}
              </div>
              <h3 style={{ margin: 0 }}>{p.name}</h3>
              <small>{p.neighbourhood} · {p.bedrooms} bd · sleeps {p.max_guests}</small>
              <TrustBadges p={p} />
              <div className="row between" style={{ marginTop: "auto", paddingTop: 6 }}>
                <span className="price num">{usd(nightly_avg_cents)}<small className="muted"> /night</small></span>
                <small className="num">{usd(accommodation_cents)} total</small>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
