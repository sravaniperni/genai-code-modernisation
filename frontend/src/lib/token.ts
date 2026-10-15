/**
 * The optional API token (MODERNISATION_API_TOKEN on the backend) is kept in this browser's localStorage.
 * Storage can be unavailable (private windows, blocked site data), so every access is guarded.
 */
const STORAGE_KEY = 'modernisation.apiToken';

type Listener = () => void;
const listeners = new Set<Listener>();

export function getApiToken(): string | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value && value.trim() ? value.trim() : null;
  } catch {
    return null;
  }
}

/** Store (or, with null/empty, remove) the token. Returns false when storage is unavailable. */
export function setApiToken(token: string | null): boolean {
  try {
    if (token && token.trim()) {
      window.localStorage.setItem(STORAGE_KEY, token.trim());
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
    listeners.forEach((listener) => listener());
    return true;
  } catch {
    return false;
  }
}

export function subscribeToToken(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
