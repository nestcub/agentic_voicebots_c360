// Auth for the Telehub API — the ONLY module that knows how tokens are stored or refreshed,
// so swapping simplejwt for Chat360 SSO later means changing this file, not call sites.
// Tokens live in localStorage (the dashboard on Vercel and the API on Render are different
// sites, so cookies would need cross-site SameSite=None + CSRF handling).

const BASE = process.env.NEXT_PUBLIC_TELEHUB_API_URL || "http://localhost:8000";

const ACCESS_KEY = "telehub.access";
const REFRESH_KEY = "telehub.refresh";
const ORG_KEY = "telehub.org";

export interface MeOrganization {
  slug: string;
  name: string;
  role: string;
}

export interface Me {
  id: number;
  username: string;
  is_platform_staff: boolean;
  organizations: MeOrganization[];
}

function read(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // storage unavailable — the user will simply be asked to log in again
  }
}

export function getAccessToken(): string | null {
  return read(ACCESS_KEY);
}

export function getOrganization(): string | null {
  return read(ORG_KEY);
}

export function setOrganization(slug: string) {
  write(ORG_KEY, slug);
}

/** Headers every Telehub API call carries. Empty while logged out (backend flag off). */
export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getAccessToken();
  const org = getOrganization();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (org) headers["X-Organization"] = org;
  return headers;
}

export async function login(username: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}/api/auth/token/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    throw new Error(res.status === 401 ? "Invalid username or password" : `Login failed (${res.status})`);
  }
  const data = (await res.json()) as { access: string; refresh: string };
  write(ACCESS_KEY, data.access);
  write(REFRESH_KEY, data.refresh);
  write(ORG_KEY, null); // re-pick from the new user's memberships
}

export function logout() {
  write(ACCESS_KEY, null);
  write(REFRESH_KEY, null);
  write(ORG_KEY, null);
  if (typeof window !== "undefined") window.location.assign("/login");
}

let refreshing: Promise<boolean> | null = null;

/** Exchanges the refresh token for a new access token. Resolves false if that isn't possible. */
export function refreshAccessToken(): Promise<boolean> {
  const refresh = read(REFRESH_KEY);
  if (!refresh) return Promise.resolve(false);
  if (!refreshing) {
    refreshing = fetch(`${BASE}/api/auth/token/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    })
      .then(async (res) => {
        if (!res.ok) return false;
        const data = (await res.json()) as { access: string; refresh?: string };
        write(ACCESS_KEY, data.access);
        if (data.refresh) write(REFRESH_KEY, data.refresh);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

export function redirectToLogin() {
  if (typeof window === "undefined" || window.location.pathname === "/login") return;
  write(ACCESS_KEY, null);
  write(REFRESH_KEY, null);
  window.location.assign("/login");
}

export async function fetchMe(): Promise<Me | null> {
  const token = getAccessToken();
  if (!token) return null;
  const call = () => fetch(`${BASE}/api/auth/me/`, { headers: { Authorization: `Bearer ${getAccessToken()}` } });
  let res = await call();
  if (res.status === 401 && (await refreshAccessToken())) res = await call();
  if (!res.ok) return null;
  return (await res.json()) as Me;
}
