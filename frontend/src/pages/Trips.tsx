import { Link } from "react-router-dom";
import { api, Booking, fmtDate, usd } from "../api";
import { StatusChip } from "../components/Badges";
import { useAsync } from "../hooks";

export default function Trips() {
  const trips = useAsync(() => api<Booking[]>("/me/bookings"), []);

  const cancel = async (b: Booking) => {
    if (!confirm(`Cancel ${b.code}? Refund follows the ${b.cancellation_policy} policy.`)) return;
    try {
      const r = await api<{ refund_cents: number }>(`/bookings/${b.code}/cancel`, { method: "POST" });
      alert(`Cancelled. Refund: ${usd(r.refund_cents)}`);
      trips.reload();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const visible = trips.data?.filter((b) => b.status !== "expired" && !b.code.startsWith("MKP")) ?? [];
  return (
    <div className="section">
      <h1>My trips</h1>
      {trips.error && <div className="notice bad">{trips.error}</div>}
      {visible.length === 0 && !trips.loading && <div className="card empty">No trips yet. <Link to="/">Find a stay</Link></div>}
      <div className="stack">
        {visible.map((b) => (
          <div key={b.id} className="card row between">
            <div>
              <div className="row"><strong>{b.code}</strong><StatusChip status={b.status} />{b.package_id && <span className="chip gold">Itinerary</span>}</div>
              <small className="num">{fmtDate(b.check_in)} → {fmtDate(b.check_out)} · {b.guests} guests · {usd(b.total_cents)}{b.refunded_cents ? ` · refunded ${usd(b.refunded_cents)}` : ""}</small>
            </div>
            <div className="row">
              {["confirmed", "checked_in", "completed"].includes(b.status) && <Link className="btn sm" to={`/stay/${b.code}`}>Open stay</Link>}
              {["confirmed", "pending_payment"].includes(b.status) && <button className="btn ghost sm" onClick={() => cancel(b)}>Cancel</button>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
