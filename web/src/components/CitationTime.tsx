import { Play } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { formatTimestamp, usePlayback } from '@/lib/playback';
import { cn } from '@/lib/utils';

/**
 * A clickable timestamp. The only way anything on the page asks for a seek.
 *
 * It publishes to the playback store and scrolls the waveform bar into view;
 * it never touches wavesurfer, so a citation can be rendered in a card, in the
 * transcript, or in a Copilot answer without any of them owning the player.
 */
export function CitationTime({
  ms,
  className,
  label,
}: {
  ms: number;
  className?: string;
  label?: string;
}) {
  const { t } = useTranslation();
  const seek = usePlayback((state) => state.seek);
  const text = formatTimestamp(ms);

  return (
    <button
      type="button"
      data-testid="citation-time"
      data-ms={ms}
      aria-label={label ?? t('player.seekTo', { time: text })}
      onClick={() => {
        seek(ms);
        document
          .getElementById('player-bar')
          ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }}
      className={cn(
        'inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 font-mono text-xs font-medium tabular-nums',
        'text-muted-foreground transition-colors duration-150 hover:bg-secondary hover:text-foreground',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        className,
      )}
    >
      <Play aria-hidden="true" className="size-3 shrink-0" />
      {text}
    </button>
  );
}
