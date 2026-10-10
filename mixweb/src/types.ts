export interface TrackRef {
  id: string;
  title: string;
  artist: string;
}

export interface SynthTemplate {
  code: string;
  name_ru: string;
  name_en: string;
  goal: string;
  length: number;
  context_types: string[];
  period: string;
  requires_ai: boolean;
}

export interface SynthListResponse {
  mode: string;
  enabled_modules: string[];
  degraded_reason: string;
  items: SynthTemplate[];
}

export interface GenerateResponse {
  mix_id: string;
  title: string;
  description: string;
  mode: string;
  enabled_modules: string[];
  degraded_reason: string;
  track_ids: string[];
  metrics: Record<string, number>;
  quality_problems: string[];
  stage_counts: Record<string, number>;
  context: Record<string, unknown>;
  playlist_id: string;
  written: boolean;
}

export interface MixDefinitionDto {
  mix_id: string;
  name: string;
  owner_id: string;
  template_code: string;
  length: number;
  schedule: string;
  navidrome_playlist_id: string;
  enabled: boolean;
}

export interface CollabPlaylistDto {
  playlist_id: string;
  navidrome_playlist_id: string;
  name: string;
  description: string;
  owner_id: string;
  role: string;
  members: { user_id: string; role: string }[];
  track_ids?: string[];
}

export interface CollabOpDto {
  playlist_id: string;
  seq: number;
  op: string;
  actor_id: string;
  op_id: string;
  ts: number;
  payload: Record<string, unknown>;
}

export interface HealthResponse {
  status: string;
  version: string;
  schema_version: number | null;
  synth_mode: string;
  effective_mode: string;
  enabled_modules: string[];
  degraded_reason: string;
  navidrome: { status: string; detail?: string };
  ai: { name: string; available: boolean; reason: string }[];
  weather_provider: string;
  library_tracks: number;
  storage: { state_dir: string; play_events: number; mode: string };
  uptime_seconds: number;
}