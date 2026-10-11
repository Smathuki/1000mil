import { useState } from "react";
import { api, local, Payment, usd } from "../api";

interface Props {
  target: { booking_id?: number; package_id?: number };
  totalCents: number;
  onPaid: () => void;
  onClose: () => void;
}

/** M-Pesa STK push (sandbox simulates the phone prompt) or card. */
export default function PayModal({ target, totalCents, onPaid, onClose }: Props) {
  const [method, setMethod] = useState<"mpesa" | "card">("mpesa");
  const [phone, setPhone] = useState("0712 345 678");
  const [payment, setPayment] = useState<Payment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const p = await api<Payment>("/payments", {
        body: { method, ...target, phone: method === "mpesa" ? phone : undefined, card_token: method === "card" ? "tok_success" : undefined },
      });
      setPayment(p);
      if (p.status === "succeeded") onPaid();
      else if (p.status !== "pending") setError(p.failure_reason ?? "Payment failed");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const approve = async (success: boolean) => {
    if (!payment) return;
    setBusy(true);
    try {
      const p = await api<Payment>(`/payments/${payment.id}/simulate`, { method: "POST", params: { success } });
      setPayment(p);
      if (p.status === "succeeded") onPaid();
      else setError(p.failure_reason ?? "Payment not completed");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label="Payment">
      <div className="card modal stack">
        <div className="row between">
          <h2 style={{ margin: 0 }}>Secure payment</h2>
          <button className="btn ghost sm" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <p className="muted" style={{ margin: 0 }}>
          {usd(totalCents)} held in escrow — released to the host 24h after you check in.
        </p>
        {!payment || payment.status === "failed" ? (
          <>
            <div className="row">
              <button className={`btn sm ${method === "mpesa" ? "" : "ghost"}`} onClick={() => setMethod("mpesa")}>M-Pesa</button>
              <button className={`btn sm ${method === "card" ? "" : "ghost"}`} onClick={() => setMethod("card")}>Card</button>
            </div>
            {method === "mpesa" ? (
              <label className="field">
                M-Pesa number
                <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" />
              </label>
            ) : (
              <p className="muted" style={{ margin: 0 }}>Sandbox card: payments succeed with test token <code>tok_success</code>.</p>
            )}
            <button className="btn" onClick={start} disabled={busy}>{busy ? "Starting…" : method === "mpesa" ? "Send M-Pesa prompt" : "Pay by card"}</button>
          </>
        ) : payment.status === "pending" ? (
          <div className="stack">
            <div className="notice">
              An M-Pesa prompt for <strong>{local(payment.amount_local, payment.currency)}</strong> was sent to your phone. Enter your PIN to approve.
            </div>
            <small className="muted">Sandbox: simulate what the guest does on their phone.</small>
            <div className="row">
              <button className="btn" onClick={() => approve(true)} disabled={busy}>Approve on phone</button>
              <button className="btn ghost" onClick={() => approve(false)} disabled={busy}>Cancel prompt</button>
            </div>
          </div>
        ) : payment.status === "succeeded" ? (
          <div className="notice ok">Paid{payment.receipt ? ` · receipt ${payment.receipt}` : ""}. Your stay is confirmed.</div>
        ) : null}
        {error && <div className="notice bad">{error}</div>}
      </div>
    </div>
  );
}
