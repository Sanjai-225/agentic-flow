/* Access-token storage. Tokens are JWTs issued by the backend; no provider secrets ever reach the browser. */

const TOKEN_KEY = 'agentic_flow_token';
const EMAIL_KEY = 'agentic_flow_email';

export function getToken(): string | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getEmail(): string | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage.getItem(EMAIL_KEY);
  } catch {
    return null;
  }
}

export function setSession(token: string, email: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(EMAIL_KEY, email);
  } catch {
    /* storage unavailable (private mode) — session lasts for this page only */
  }
}

export function clearSession(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(EMAIL_KEY);
  } catch {
    /* ignore */
  }
}
