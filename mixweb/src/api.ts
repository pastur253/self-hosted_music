const BASE = import.meta.env.VITE_CORE_URL ?? "";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      /* non-json body */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<import("./types").HealthResponse>("/healthz"),
  synths: () => request<import("./types").SynthListResponse>("/api/v1/synths"),
  context: (user: string) =>
    request<Record<string, unknown>>(`/api/v1/context?user=${encodeURIComponent(user)}`),
  mixes: () => request<{ items: import("./types").MixDefinitionDto[] }>("/api/v1/mixes"),
  createMix: (payload: Record<string, unknown>) =>
    request<import("./types").MixDefinitionDto>("/api/v1/mixes", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  generate: (mixId: string, payload: Record<string, unknown> = {}) =>
    request<import("./types").GenerateResponse>(`/api/v1/mixes/${encodeURIComponent(mixId)}/generate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  preview: (code: string, user: string) =>
    request<import("./types").GenerateResponse>(
      `/api/v1/synths/${encodeURIComponent(code)}/preview?user=${encodeURIComponent(user)}`,
    ),
  playlists: (user: string) =>
    request<{ items: import("./types").CollabPlaylistDto[] }>(
      `/api/v1/playlists?user=${encodeURIComponent(user)}`,
    ),
  playlist: (playlistId: string, user: string) =>
    request<import("./types").CollabPlaylistDto>(
      `/api/v1/playlists/${encodeURIComponent(playlistId)}?user=${encodeURIComponent(user)}`,
    ),
  createPlaylist: (payload: Record<string, unknown>) =>
    request<import("./types").CollabPlaylistDto>("/api/v1/playlists", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  addTracks: (playlistId: string, payload: Record<string, unknown>) =>
    request<{ op: import("./types").CollabOpDto; duplicate: boolean; applied: boolean }>(
      `/api/v1/playlists/${encodeURIComponent(playlistId)}/tracks`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  removeTrack: (playlistId: string, trackId: string, actorId: string) =>
    request<{ op: import("./types").CollabOpDto }>(
      `/api/v1/playlists/${encodeURIComponent(playlistId)}/tracks/${encodeURIComponent(trackId)}?actor_id=${encodeURIComponent(actorId)}`,
      { method: "DELETE" },
    ),
  opsSince: (playlistId: string, sinceSeq: number) =>
    request<{ items: import("./types").CollabOpDto[] }>(
      `/api/v1/playlists/${encodeURIComponent(playlistId)}/ops?since_seq=${sinceSeq}`,
    ),
  syncLibrary: () => request<{ total: number; duration_hours: number }>("/api/v1/library/sync"),
};

export function wsUrl(user: string, playlists: string[]): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const query = new URLSearchParams({ user });
  if (playlists.length > 0) query.set("playlists", playlists.join(","));
  return `${protocol}//${window.location.host}/ws/v1?${query.toString()}`;
}