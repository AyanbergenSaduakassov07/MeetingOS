import { create } from 'zustand';

/**
 * The seam between "a citation was clicked, somewhere on the page" and "the
 * waveform at the bottom of the screen".
 *
 * Citations appear in item cards, in the transcript, and later in Copilot
 * answers. None of those should know that wavesurfer exists, or be able to
 * reach the DOM node it draws into. So the interface is one verb — `seek(ms)` —
 * and the waveform bar is the only subscriber that knows what to do with it.
 *
 * `seekToken` increments on every request so that seeking to the *same*
 * timestamp twice still fires: the subscriber reacts to the token, not the
 * value.
 */
interface PlaybackState {
  /** Milliseconds requested by the last seek, or null if none yet. */
  seekMs: number | null;
  seekToken: number;
  /** Total media length in ms, published by the waveform once decoded. */
  durationMs: number;
  positionMs: number;
  isPlaying: boolean;

  seek: (ms: number) => void;
  setDuration: (ms: number) => void;
  setPosition: (ms: number) => void;
  setPlaying: (playing: boolean) => void;
}

export const usePlayback = create<PlaybackState>((set) => ({
  seekMs: null,
  seekToken: 0,
  durationMs: 0,
  positionMs: 0,
  isPlaying: false,

  seek: (ms) => set((state) => ({ seekMs: ms, seekToken: state.seekToken + 1 })),
  setDuration: (ms) => set({ durationMs: ms }),
  setPosition: (ms) => set({ positionMs: ms }),
  setPlaying: (playing) => set({ isPlaying: playing }),
}));

/** `125300` -> `"2:05"`. Used for every timestamp the reader sees. */
export function formatTimestamp(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}
