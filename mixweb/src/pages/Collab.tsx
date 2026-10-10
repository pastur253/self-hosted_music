import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useLiveEvents } from "../useLiveEvents";
import { useStore, useUserId } from "../store";
import type { CollabOpDto } from "../types";

export function CollabPage() {
  const user = useUserId();
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [trackId, setTrackId] = useState("");
  const [name, setName] = useState("");
  const pushOp = useStore((state) => state.pushOp);
  const lastOps = useStore((state) => state.lastOps);

  const playlists = useQuery({ queryKey: ["playlists", user], queryFn: () => api.playlists(user) });
  const active = useQuery({
    queryKey: ["playlist", activeId, user],
    queryFn: () => api.playlist(activeId as string, user),
    enabled: Boolean(activeId),
  });

  useLiveEvents(activeId ? [activeId] : [], (event) => {
    pushOp(event as unknown as CollabOpDto);
    void queryClient.invalidateQueries({ queryKey: ["playlist", activeId, user] });
  });

  useEffect(() => {
    if (!activeId && playlists.data?.items.length) setActiveId(playlists.data.items[0].playlist_id);
  }, [activeId, playlists.data]);

  const createPlaylist = useMutation({
    mutationFn: () => api.createPlaylist({ owner_id: user, name: name || "Новый общий плейлист" }),
    onSuccess: (playlist) => {
      setActiveId(playlist.playlist_id);
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["playlists", user] });
    },
  });

  const addTrack = useMutation({
    mutationFn: () =>
      api.addTracks(activeId as string, { actor_id: user, track_ids: [trackId], position: 0 }),
    onSuccess: () => {
      setTrackId("");
      void queryClient.invalidateQueries({ queryKey: ["playlist", activeId, user] });
    },
  });

  const removeTrack = useMutation({
    mutationFn: (id: string) => api.removeTrack(activeId as string, id, user),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["playlist", activeId, user] }),
  });

  const canEdit = active.data?.role === "owner" || active.data?.role === "editor";

  return (
    <section>
      <div className="card">
        <h3>Совместные плейлисты</h3>
        <div className="row">
          <input
            value={name}
            placeholder="Название нового плейлиста"
            onChange={(event) => setName(event.target.value)}
          />
          <button className="primary" onClick={() => createPlaylist.mutate()} disabled={createPlaylist.isPending}>
            Создать
          </button>
          <select value={activeId ?? ""} onChange={(event) => setActiveId(event.target.value)}>
            {playlists.data?.items.map((item) => (
              <option key={item.playlist_id} value={item.playlist_id}>
                {item.name} ({item.role})
              </option>
            ))}
          </select>
        </div>
        {createPlaylist.error && <p className="error">{String(createPlaylist.error)}</p>}
      </div>

      {active.data && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div>
              <h3>{active.data.name}</h3>
              <p>{active.data.description || "Без описания"}</p>
            </div>
            <span className="badge">роль: {active.data.role}</span>
          </div>

          <div className="row" style={{ marginTop: 8 }}>
            <input
              value={trackId}
              placeholder="id трека"
              onChange={(event) => setTrackId(event.target.value)}
            />
            <button onClick={() => addTrack.mutate()} disabled={!canEdit || addTrack.isPending || !trackId}>
              Добавить трек
            </button>
          </div>
          {!canEdit && <p className="muted">Роль viewer: изменения недоступны</p>}
          {addTrack.error && <p className="error">{String(addTrack.error)}</p>}

          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>#</th>
                <th>Трек</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {active.data.track_ids?.map((id, index) => (
                <tr key={`${id}-${index}`}>
                  <td className="muted">{index + 1}</td>
                  <td>{id}</td>
                  <td style={{ textAlign: "right" }}>
                    <button onClick={() => removeTrack.mutate(id)} disabled={!canEdit}>
                      Удалить
                    </button>
                  </td>
                </tr>
              ))}
              {(active.data.track_ids?.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    Треков нет
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          {lastOps.length > 0 && (
            <div className="metrics">
              <span>событий в этой сессии: {lastOps.length}</span>
              <span>последнее: {lastOps[lastOps.length - 1].op}</span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}