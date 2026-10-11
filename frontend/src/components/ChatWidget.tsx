import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";

type Msg = { dir: "in" | "out"; text: string };

/** Same concierge brain that answers on WhatsApp, embedded for web guests and demos. */
export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([
    { dir: "out", text: 'Karibu! I\'m the Makao concierge — the same one on WhatsApp. Try "Villa in Nairobi this weekend for 4".' },
  ]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth" }), [msgs, open]);

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const message = text.trim();
    if (!message) return;
    setText("");
    setMsgs((m) => [...m, { dir: "in", text: message }]);
    setBusy(true);
    try {
      const { reply } = await api<{ reply: string }>("/messaging/chat", { body: { message } });
      setMsgs((m) => [...m, { dir: "out", text: reply }]);
    } catch (err: any) {
      setMsgs((m) => [...m, { dir: "out", text: "Sorry — " + err.message }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="chat">
      {open ? (
        <div className="card panel">
          <div className="row between" style={{ padding: "10px 12px", borderBottom: "1px solid var(--line)" }}>
            <strong>Concierge · WhatsApp</strong>
            <button className="btn ghost sm" onClick={() => setOpen(false)} aria-label="Close chat">✕</button>
          </div>
          <div className="msgs" aria-live="polite">
            {msgs.map((m, i) => (
              <div key={i} className={`msg ${m.dir}`}>{m.text}</div>
            ))}
            {busy && <div className="msg out muted">typing…</div>}
            <div ref={end} />
          </div>
          <form onSubmit={send}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Where & when?" aria-label="Message" />
            <button className="btn" disabled={busy}>Send</button>
          </form>
        </div>
      ) : (
        <button className="btn gold" onClick={() => setOpen(true)} style={{ boxShadow: "var(--shadow)" }}>💬 Concierge</button>
      )}
    </div>
  );
}
