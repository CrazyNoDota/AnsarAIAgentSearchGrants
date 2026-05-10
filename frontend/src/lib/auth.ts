import Cookies from "js-cookie";
import { login as apiLogin } from "./api";

export function getToken(): string | undefined {
  return Cookies.get("access_token");
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

export async function signIn(username: string, password: string): Promise<void> {
  const token = await apiLogin(username, password);
  Cookies.set("access_token", token, { expires: 7, sameSite: "lax" });
}

export function signOut(): void {
  Cookies.remove("access_token");
  window.location.href = "/login";
}
