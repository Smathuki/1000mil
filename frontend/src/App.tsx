import { useState } from "react";
import { Link, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { DEMO_ACCOUNTS, getToken, setToken } from "./api";
import ChatWidget from "./components/ChatWidget";
import Explore from "./pages/Explore";
import Itinerary from "./pages/Itinerary";
import Ops from "./pages/Ops";
import Owner from "./pages/Owner";
import PropertyPage from "./pages/Property";
import Stay from "./pages/Stay";
import Trips from "./pages/Trips";

export default function App() {
  const [token, setTok] = useState(getToken());
  const navigate = useNavigate();
  const account = DEMO_ACCOUNTS.find((a) => a.token === token) ?? DEMO_ACCOUNTS[0];

  const switchTo = (t: string) => {
    setToken(t);
    setTok(t);
    const role = DEMO_ACCOUNTS.find((a) => a.token === t)?.role;
    navigate(role === "owner" ? "/owner" : role === "admin" || role === "partner" ? "/ops" : "/");
  };

  return (
    <>
      <header className="top">
        <div className="bar">
          <Link to="/" className="logo">
            <img src="/icon.svg" alt="" /> Makao
          </Link>
          <nav className="main">
            <NavLink to="/" end>Explore</NavLink>
            <NavLink to="/itinerary">Itineraries</NavLink>
            {account.role === "guest" && <NavLink to="/trips">My trips</NavLink>}
            {(account.role === "owner" || account.role === "admin") && <NavLink to="/owner">Owner console</NavLink>}
            {(account.role === "admin" || account.role === "partner") && <NavLink to="/ops">{account.role === "partner" ? "My jobs" : "Ops desk"}</NavLink>}
          </nav>
          <label className="row" style={{ gap: 6 }}>
            <small>Demo as</small>
            <select value={token} onChange={(e) => switchTo(e.target.value)} aria-label="Demo account">
              {DEMO_ACCOUNTS.map((a) => (
                <option key={a.token} value={a.token}>{a.label}</option>
              ))}
            </select>
          </label>
        </div>
      </header>
      <main className="shell" key={token}>
        <Routes>
          <Route path="/" element={<Explore />} />
          <Route path="/p/:slug" element={<PropertyPage />} />
          <Route path="/itinerary" element={<Itinerary />} />
          <Route path="/trips" element={<Trips />} />
          <Route path="/stay/:code" element={<Stay />} />
          <Route path="/owner" element={<Owner />} />
          <Route path="/ops" element={<Ops role={account.role} />} />
          <Route path="*" element={<div className="empty">Page not found. <Link to="/">Back to explore</Link></div>} />
        </Routes>
      </main>
      <ChatWidget />
    </>
  );
}
