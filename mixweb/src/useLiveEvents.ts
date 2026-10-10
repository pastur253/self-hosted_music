import { useEffect, useRef } from "react";
import { useStore, useUserId } from "./store";
import { wsUrl } from "./api";

interface Event {
  type: string;
  playlist_id?: string;
  seq?: number;
  op?: string;
  op_id?: string;
  actor_id?: string;
  ts?: number;
  payload?: Record<string, unknown>;
}

export function useLiveEvents(playlists: string[], onEvent: (event: Event) => void): void {
  const userId = useUserId();
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const key = playlists.join(",");

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry = 0;
    let closed = false;
    let timer: number | undefined;

    const connect = () => {
      socket = new WebSocket(wsUrl(userId, key ? key.split(",") : []));
      socket.onopen = () => {
        retry = 0;
        useStore.getState().setConnected(true);
      };
      socket.onclose = () => {
        useStore.getState().setConnected(false);
        if (closed) return;
        retry += 1;
        timer = window.setTimeout(connect, Math.min(1000 * retry, 10_000));
      };
      socket.onerror = () => socket?.close();
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data as string) as Event;
        if (event.type === "hello" || event.type === "ping") return;
        handler.current(event);
      };
    };

    connect();
    return () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      socket?.close();
    };
  }, [userId, key]);
}