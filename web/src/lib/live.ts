/**
 * Live captions: API calls, microphone/tab capture, and the caption stream.
 *
 * Stream protocol (backend/live/eventlog.py): load a snapshot, which carries the
 * `last_seq` it was taken at, then open SSE after that seq. EventSource resumes
 * with Last-Event-ID by itself; `session.reset` means we fell behind and must
 * reload the snapshot.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { request } from './api';

const BASE = import.meta.env.VITE_API_URL ?? '';

export interface LiveLanguage {
  code: string;
  name: string;
  native: string;
  rtl: boolean;
}

export interface StartedSession {
  session_id: string;
  meeting_id: string;
  viewer_token: string;
  asr: string;
  translator: string | null;
}

export interface Caption {
  segment_id: string;
  sequence: number;
  text: string;
  language: string | null;
  translation?: string | null;
  translationFailed?: boolean;
}

interface Snapshot {
  title: string;
  state: string;
  last_seq: number;
  meeting_id: string;
  segments: Caption[];
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });

export const liveApi = {
  languages: () => request<LiveLanguage[]>('/api/live/languages'),
  start: (body: { title: string; consent_confirmed: boolean; source_language?: string }) =>
    post<StartedSession>('/api/live/sessions', body),
  end: (id: string) => post<{ meeting_id: string }>(`/api/live/sessions/${id}/end`),
  newLink: (id: string) => post<{ viewer_token: string }>(`/api/live/sessions/${id}/links`),
  revokeLinks: (id: string) => post<{ revoked: number }>(`/api/live/sessions/${id}/links/revoke`),
};

export function viewerUrl(sessionId: string, token: string): string {
  return `${window.location.origin}/watch/${sessionId}?t=${encodeURIComponent(token)}`;
}

function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params))
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  return q.toString();
}

/** Capture mic or a browser tab and stream PCM16 to the session. Returns a stop function. */
export async function startCapture(sessionId: string, source: 'mic' | 'tab'): Promise<() => void> {
  const stream =
    source === 'mic'
      ? await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
        })
      : await navigator.mediaDevices.getDisplayMedia({ audio: true, video: true });
  for (const track of stream.getVideoTracks()) track.stop(); // Chrome needs video to offer tab audio
  if (!stream.getAudioTracks().length) throw new Error('no-audio-track');

  const ctx = new AudioContext();
  await ctx.audioWorklet.addModule('/pcm-worklet.js');
  const node = new AudioWorkletNode(ctx, 'pcm-downsampler');
  const wsBase = (BASE || window.location.origin).replace(/^http/, 'ws');
  const ws = new WebSocket(`${wsBase}/api/live/sessions/${sessionId}/audio`);
  ws.binaryType = 'arraybuffer';
  node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(e.data);
  };
  ctx.createMediaStreamSource(stream).connect(node);

  return () => {
    node.port.onmessage = null;
    for (const track of stream.getTracks()) track.stop();
    ws.close();
    void ctx.close();
  };
}

export type StreamState = 'connecting' | 'live' | 'ended' | 'error';

/** Captions for one session in one target language, kept in sync with the server. */
export function useLiveCaptions(sessionId: string, token: string | null, lang: string | null) {
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [partial, setPartial] = useState('');
  const [title, setTitle] = useState('');
  const [state, setState] = useState<StreamState>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [viewers, setViewers] = useState(0);
  const [epoch, setEpoch] = useState(0); // bump to reload snapshot + reconnect
  const reload = useCallback(() => setEpoch((n) => n + 1), []);
  const esRef = useRef<EventSource | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: epoch is the reload trigger
  useEffect(() => {
    let cancelled = false;
    const auth = { t: token, lang };
    const upsert = (c: Caption) =>
      setCaptions((prev) =>
        prev.some((p) => p.segment_id === c.segment_id)
          ? prev
          : [...prev, c].sort((a, b) => a.sequence - b.sequence),
      );
    const patch = (id: string, change: Partial<Caption>) =>
      setCaptions((prev) => prev.map((p) => (p.segment_id === id ? { ...p, ...change } : p)));

    request<Snapshot>(`/api/live/view/${sessionId}/snapshot?${query(auth)}`)
      .then((snap) => {
        if (cancelled) return;
        setTitle(snap.title);
        setCaptions(snap.segments);
        if (snap.state !== 'live') {
          setState('ended');
          return;
        }
        const es = new EventSource(
          `${BASE}/api/live/view/${sessionId}/events?${query({ ...auth, after: snap.last_seq })}`,
          {
            withCredentials: true,
          },
        );
        esRef.current = es;
        const on = (type: string, fn: (d: Record<string, unknown>) => void) =>
          es.addEventListener(type, (e) => fn(JSON.parse((e as MessageEvent).data)));
        es.onopen = () => setState('live');
        es.onerror = () => {
          if (es.readyState === EventSource.CLOSED && !cancelled) reload(); // 410/401: re-read the snapshot
        };
        on('transcript.partial', (d) => setPartial(String(d.text ?? '')));
        on('transcript.final', (d) => {
          setPartial('');
          upsert(d as unknown as Caption);
        });
        on('translation.final', (d) =>
          patch(String(d.segment_id), { translation: String(d.text) }),
        );
        on('translation.failed', (d) => patch(String(d.segment_id), { translationFailed: true }));
        on('participant.count', (d) => setViewers(Number(d.viewers) || 0));
        on('session.reset', () => {
          es.close();
          reload();
        });
        on('session.state', (d) => {
          if (d.state !== 'live') {
            es.close();
            setPartial('');
            setState('ended');
          }
        });
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setState('error');
        setError(e.message);
      });

    return () => {
      cancelled = true;
      esRef.current?.close();
      esRef.current = null;
    };
  }, [sessionId, token, lang, epoch, reload]);

  return { captions, partial, title, state, error, viewers };
}
