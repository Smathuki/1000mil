export type Role = "guest" | "owner" | "admin" | "partner";

export const DEMO_ACCOUNTS: { role: Role; label: string; token: string }[] = [
  { role: "guest", label: "Guest · Amina", token: "demo-guest" },
  { role: "owner", label: "Owner · Joseph", token: "demo-owner" },
  { role: "admin", label: "Ops desk", token: "demo-admin" },
  { role: "partner", label: "Partner · Wanjiru", token: "demo-partner" },
];

const KEY = "makao.token";

export function getToken(): string {
  try {
    return localStorage.getItem(KEY) ?? "demo-guest";
  } catch {
    return "demo-guest";
  }
}

export function setToken(token: string) {
  try {
    localStorage.setItem(KEY, token);
  } catch {
    /* private mode: keep the in-memory default */
  }
  // Offline API cache is per-device; drop it when the person using the device changes.
  if ("caches" in window) caches.delete("makao-data-v1").catch(() => undefined);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; params?: Record<string, any> } = {}): Promise<T> {
  const qs = opts.params
    ? "?" +
      new URLSearchParams(
        Object.entries(opts.params)
          .filter(([, v]) => v !== undefined && v !== null && v !== "")
          .map(([k, v]) => [k, String(v)])
      ).toString()
    : "";
  const res = await fetch(`/api${path}${qs}`, {
    method: opts.method ?? (opts.body ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d: any) => d.msg).join("; ") : data.detail;
    throw new ApiError(res.status, detail || res.statusText);
  }
  return data as T;
}

export const usd = (cents: number | null | undefined) =>
  cents == null ? "—" : `$${(cents / 100).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

export const local = (amount: number, currency: string) => `${currency} ${amount.toLocaleString("en-US")}`;

export const isoDate = (d: Date) => d.toISOString().slice(0, 10);

export const addDays = (iso: string, n: number) => {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return isoDate(d);
};

export const today = () => isoDate(new Date());

export const fmtDate = (iso: string) =>
  new Date(iso + (iso.length === 10 ? "T00:00:00Z" : "")).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

export const label = (s: string) => s.replace(/_/g, " ").replace(/-/g, " ");

export interface Market {
  key: string;
  name: string;
  country: string;
  currency: string;
  airport: string;
  profile: string;
  live_units: number;
}

export interface PropertyCard {
  id: number;
  slug: string;
  name: string;
  kind: string;
  city: string;
  country: string;
  neighbourhood: string | null;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  base_rate_cents: number;
  photos: { url: string; room: string; verified: boolean }[];
  power_backup: string;
  security: string[];
  staff: string[];
  quality_score: number | null;
  status: string;
}

export interface PropertyDetail extends PropertyCard {
  description: string;
  lat: number | null;
  lng: number | null;
  amenities: string[];
  water_backup: boolean;
  wifi_mbps: number;
  min_nights: number;
  cleaning_fee_cents: number;
  cancellation_policy: string;
  readiness_score: number;
  smart_lock: boolean;
  status_reason?: string | null;
}

export interface Night {
  date: string;
  price_cents: number;
  factors: Record<string, number>;
  signals: string[];
}

export interface Quote {
  property_id: number;
  property_name: string;
  check_in: string;
  check_out: string;
  guests: number;
  nights: Night[];
  accommodation_cents: number;
  discount_cents: number;
  cleaning_fee_cents: number;
  service_fee_cents: number;
  total_cents: number;
  local: { currency: string; total: number };
  cancellation_policy: string;
  available: boolean;
}

export interface Booking {
  id: number;
  code: string;
  property_id: number;
  package_id: number | null;
  check_in: string;
  check_out: string;
  guests: number;
  nightly: Night[];
  accommodation_cents: number;
  cleaning_fee_cents: number;
  service_fee_cents: number;
  discount_cents: number;
  total_cents: number;
  refunded_cents: number;
  cancellation_policy: string;
  status: string;
  escrow: string;
  airport_transfer: boolean;
  commission_cents?: number;
  owner_payout_cents?: number;
}

export interface Package {
  id: number;
  code: string;
  total_cents: number;
  discount_cents: number;
  status: string;
  bookings: Booking[];
}

export interface Payment {
  id: number;
  method: string;
  status: string;
  currency: string;
  amount_local: number;
  amount_cents_usd: number;
  provider_ref: string | null;
  receipt: string | null;
  failure_reason: string | null;
}

export interface Task {
  id: number;
  property_id: number;
  property_name: string;
  property_city: string;
  property_location: [number, number] | null;
  booking_id: number | null;
  kind: string;
  title: string;
  due_at: string;
  status: string;
  partner_id: number | null;
  requires_photo: boolean;
  checkin_distance_m: number | null;
  proof_photos: string[];
  notes: string | null;
  rating: number | null;
}
