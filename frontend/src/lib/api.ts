import axios from "axios";
import Cookies from "js-cookie";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 15000,
});

// Inject JWT token from cookie on every request
api.interceptors.request.use((config) => {
  const token = Cookies.get("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-redirect to login on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && typeof window !== "undefined") {
      Cookies.remove("access_token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export default api;

// ─── Auth ────────────────────────────────────────────────
export async function login(username: string, password: string): Promise<string> {
  const form = new URLSearchParams();
  form.append("username", username);
  form.append("password", password);
  const res = await api.post("/auth/login", form.toString(), {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return res.data.access_token;
}

// ─── Grants ─────────────────────────────────────────────
export interface Grant {
  id: number;
  title: string;
  description?: string;
  organization?: string;
  country?: string;
  category?: string;
  deadline?: string;
  source_url: string;
  status: string;
  ai_score: number;
  created_at: string;
  updated_at: string;
}

export interface GrantListResponse {
  items: Grant[];
  total: number;
  page: number;
  size: number;
}

export async function getGrants(params: {
  status?: string;
  search?: string;
  country?: string;
  category?: string;
  page?: number;
  size?: number;
}): Promise<GrantListResponse> {
  const res = await api.get("/grants", { params });
  return res.data;
}

export async function getGrant(id: number): Promise<Grant> {
  const res = await api.get(`/grants/${id}`);
  return res.data;
}

export async function reviewGrant(
  grantId: number,
  decision: "approved" | "rejected"
): Promise<void> {
  await api.post(`/grants/${grantId}/review`, { decision, reviewer_name: "web_admin" });
}

export async function deleteGrant(grantId: number): Promise<void> {
  await api.delete(`/grants/${grantId}`);
}

export async function deleteGrantsBulk(status?: string): Promise<{ deleted: number }> {
  const res = await api.delete("/grants", { params: status ? { status } : undefined });
  return res.data;
}

export async function runScraper(): Promise<{ status: string; summary: unknown }> {
  const res = await api.post("/scraper/run", null, { timeout: 120000 });
  return res.data;
}

// ─── Stats ──────────────────────────────────────────────
export interface Stats {
  pending: number;
  approved: number;
  rejected: number;
  total: number;
}

export async function getStats(): Promise<Stats> {
  const res = await api.get("/stats");
  return res.data;
}

// ─── Recommendations ─────────────────────────────────────
export async function getRecommendations(q: string, limit = 10): Promise<Grant[]> {
  const res = await api.get("/recommendations", { params: { q, limit } });
  return res.data;
}
