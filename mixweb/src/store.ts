import { create } from "zustand";
import type { CollabOpDto } from "./types";

interface PresenceState {
  userId: string;
  setUserId: (userId: string) => void;
  online: Record<string, string[]>;
  lastOps: CollabOpDto[];
  connected: boolean;
  setConnected: (connected: boolean) => void;
  addPresence: (playlistId: string, users: string[]) => void;
  pushOp: (op: CollabOpDto) => void;
  resetOps: () => void;
}

export const useStore = create<PresenceState>((set) => ({
  userId: localStorage.getItem("mixcore.user") ?? "admin",
  setUserId: (userId) => {
    localStorage.setItem("mixcore.user", userId);
    set({ userId });
  },
  online: {},
  lastOps: [],
  connected: false,
  setConnected: (connected) => set({ connected }),
  addPresence: (playlistId, users) =>
    set((state) => ({ online: { ...state.online, [playlistId]: users } })),
  pushOp: (op) => set((state) => ({ lastOps: [...state.lastOps, op].slice(-50) })),
  resetOps: () => set({ lastOps: [] }),
}));

export function useUserId(): string {
  return useStore((state) => state.userId);
}