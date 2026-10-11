import { label, PropertyCard } from "../api";

export function TrustBadges({ p }: { p: PropertyCard }) {
  const power = { hybrid: "Solar + generator", solar: "Solar backup", generator: "Generator backup", inverter: "Inverter backup", none: "" }[p.power_backup] ?? "";
  return (
    <div className="row" style={{ gap: 6 }}>
      {power && <span className="chip ok">⚡ {power}</span>}
      {p.security.includes("guard_24h") && <span className="chip ok">🛡 24h security</span>}
      {p.staff.length > 0 && <span className="chip">👤 {p.staff.map(label).join(", ")}</span>}
      {p.quality_score != null && (
        <span className={`chip ${p.quality_score >= 70 ? "gold" : "warn"}`}>★ {p.quality_score.toFixed(0)} quality</span>
      )}
    </div>
  );
}

export function StatusChip({ status }: { status: string }) {
  const tone: Record<string, string> = {
    confirmed: "ok", checked_in: "ok", completed: "", active: "ok", verified: "ok", done: "ok", succeeded: "ok",
    pending_payment: "warn", coaching: "warn", assigned: "warn", in_progress: "warn", open: "warn", draft: "",
    cancelled: "bad", expired: "bad", suspended: "bad", failed: "bad",
  };
  return <span className={`chip ${tone[status] ?? ""}`}>{label(status)}</span>;
}
