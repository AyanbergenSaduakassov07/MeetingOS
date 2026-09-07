import { Pause, Play } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import WaveSurfer from 'wavesurfer.js';
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js';
import { formatTimestamp, usePlayback } from '@/lib/playback';

interface PlayerBarProps {
  audioUrl: string;
  /** Citation times to mark on the waveform, in ms. */
  citations: Array<{ id: string; startMs: number; endMs: number }>;
  /** Fallback used for the total-time readout until the media decodes. */
  fallbackDurationMs?: number;
}

/**
 * Full-width bottom bar: waveform, transport, elapsed/total.
 *
 * Owns the only WaveSurfer instance on the page. Seeks arrive through the
 * playback store rather than as props, so a citation anywhere in the tree can
 * drive it without threading a callback down.
 */
export function PlayerBar({ audioUrl, citations, fallbackDurationMs = 0 }: PlayerBarProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const waveRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<ReturnType<typeof RegionsPlugin.create> | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  const {
    seekMs,
    seekToken,
    durationMs,
    positionMs,
    isPlaying,
    setDuration,
    setPosition,
    setPlaying,
  } = usePlayback();

  // Build the instance once per audio source.
  useEffect(() => {
    if (!containerRef.current) return;

    const regions = RegionsPlugin.create();
    const style = getComputedStyle(document.documentElement);
    const read = (token: string, fallback: string) =>
      style.getPropertyValue(token).trim()
        ? `hsl(${style.getPropertyValue(token).trim()})`
        : fallback;

    const wave = WaveSurfer.create({
      container: containerRef.current,
      height: 48,
      waveColor: read('--muted-foreground', '#8a8a8a'),
      progressColor: read('--primary', '#c6e619'),
      cursorColor: read('--foreground', '#14181a'),
      cursorWidth: 2,
      barWidth: 2,
      barGap: 2,
      barRadius: 2,
      normalize: true,
      plugins: [regions],
    });

    waveRef.current = wave;
    regionsRef.current = regions;

    // Tearing down an instance aborts its in-flight fetch and decode, which
    // wavesurfer reports as an error. Under StrictMode that happens on every
    // mount, so an unguarded handler shows "audio unavailable" over a waveform
    // that loaded perfectly well. Only errors from the live instance count.
    let disposed = false;

    wave.on('ready', () => {
      if (disposed) return;
      setReady(true);
      setFailed(false);
      setDuration(Math.round(wave.getDuration() * 1000));
    });
    wave.on('error', () => {
      if (!disposed) setFailed(true);
    });
    wave.on('timeupdate', (seconds: number) => setPosition(Math.round(seconds * 1000)));
    wave.on('play', () => setPlaying(true));
    wave.on('pause', () => setPlaying(false));
    wave.on('finish', () => setPlaying(false));

    wave.load(audioUrl).catch(() => {
      if (!disposed) setFailed(true);
    });

    return () => {
      disposed = true;
      wave.destroy();
      waveRef.current = null;
      regionsRef.current = null;
      setReady(false);
      setPlaying(false);
    };
  }, [audioUrl, setDuration, setPosition, setPlaying]);

  // Mark every citation on the waveform once the media has decoded.
  useEffect(() => {
    const regions = regionsRef.current;
    if (!ready || !regions) return;
    regions.clearRegions();
    const style = getComputedStyle(document.documentElement);
    const good = style.getPropertyValue('--good').trim();
    for (const citation of citations) {
      regions.addRegion({
        id: citation.id,
        start: citation.startMs / 1000,
        end: Math.max(citation.endMs, citation.startMs + 250) / 1000,
        color: good ? `hsl(${good} / 0.28)` : 'rgba(40, 120, 80, 0.28)',
        drag: false,
        resize: false,
      });
    }
  }, [ready, citations]);

  // Respond to seek requests from anywhere on the page. seekToken is the
  // trigger rather than a value this effect reads: it is what makes a repeat
  // seek to the same millisecond fire again.
  // biome-ignore lint/correctness/useExhaustiveDependencies: seekToken is a deliberate trigger, not a read dependency.
  useEffect(() => {
    const wave = waveRef.current;
    if (!ready || !wave || seekMs === null) return;
    const total = wave.getDuration();
    if (total > 0) wave.seekTo(Math.min(1, Math.max(0, seekMs / 1000 / total)));
    setPosition(seekMs);
  }, [seekToken, seekMs, ready, setPosition]);

  const total = durationMs || fallbackDurationMs;

  return (
    <div
      id="player-bar"
      data-testid="player-bar"
      data-ready={ready}
      data-position-ms={positionMs}
      className="sticky bottom-0 z-30 border-t border-border bg-card/95 px-4 py-3 backdrop-blur sm:px-6"
    >
      <div className="flex items-center gap-4">
        <button
          type="button"
          data-testid="player-toggle"
          disabled={!ready}
          aria-label={isPlaying ? t('player.pause') : t('player.play')}
          onClick={() => waveRef.current?.playPause()}
          className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity duration-150 hover:opacity-90 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card"
        >
          {isPlaying ? (
            <Pause aria-hidden="true" className="size-5" />
          ) : (
            <Play aria-hidden="true" className="size-5" />
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div ref={containerRef} aria-hidden="true" />
          {failed && <p className="text-xs text-destructive">{t('player.unavailable')}</p>}
          {!ready && !failed && (
            <p className="text-xs text-muted-foreground">{t('player.loading')}</p>
          )}
        </div>

        <p
          data-testid="player-time"
          aria-live="off"
          className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground"
        >
          <span data-testid="player-elapsed">{formatTimestamp(positionMs)}</span>
          {' / '}
          {formatTimestamp(total)}
        </p>
      </div>
    </div>
  );
}
