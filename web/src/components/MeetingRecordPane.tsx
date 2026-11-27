import { X } from 'lucide-react';
import { type CSSProperties, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TranscriptSegment } from '@/lib/api';
import { usePlayback } from '@/lib/playback';
import { cn } from '@/lib/utils';
import { CitationTime } from './CitationTime';
import { CopilotPanel } from './CopilotPanel';
import { Button } from './ui/button';

export type RecordPaneMode = 'transcript' | 'ask';

const PANE_KEY = 'meetingos:record-pane';
const MIN_WIDTH = 248;
const MAX_WIDTH = 480;

function readPaneHidden() {
  try {
    const value = localStorage.getItem(PANE_KEY);
    if (value) return value === 'hidden';
  } catch {
    // Storage blocked: use the width default.
  }
  return window.matchMedia('(max-width: 1023px)').matches;
}

export function useRecordPane() {
  const [isHidden, setHidden] = useState(readPaneHidden);
  const [mode, setMode] = useState<RecordPaneMode>('transcript');

  useEffect(() => {
    try {
      localStorage.setItem(PANE_KEY, isHidden ? 'hidden' : 'shown');
    } catch {
      // The choice applies to this visit.
    }
  }, [isHidden]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.repeat ||
        event.isComposing ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        event.key.toLowerCase() !== 't'
      )
        return;

      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || target.closest('input, textarea, select, [role="textbox"]'))
      )
        return;

      event.preventDefault();
      setHidden((hidden) => !hidden);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return {
    isHidden,
    mode,
    setMode,
    hide: () => setHidden(true),
    open: (next: RecordPaneMode) => {
      setMode(next);
      setHidden(false);
    },
  };
}

function RecordTranscript({
  segments,
  isVisible,
}: {
  segments: TranscriptSegment[];
  isVisible: boolean;
}) {
  const { t } = useTranslation();
  const list = useRef<HTMLOListElement>(null);
  const current = useRef<HTMLLIElement>(null);
  const activeId = usePlayback(
    ({ positionMs }) =>
      segments.find((segment) => segment.start_ms <= positionMs && positionMs < segment.end_ms)?.id,
  );
  const seekToken = usePlayback((state) => state.seekToken);

  // biome-ignore lint/correctness/useExhaustiveDependencies: repeated seeks reveal the same row again.
  useEffect(() => {
    if (!isVisible || !activeId || !current.current || !list.current) return;
    const row = current.current.getBoundingClientRect();
    const viewport = list.current.getBoundingClientRect();
    if (row.top < viewport.top || row.bottom > viewport.bottom) {
      list.current.scrollTop += row.top - viewport.top;
    }
  }, [activeId, isVisible, seekToken]);

  return (
    <ol
      ref={list}
      className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain p-2"
      data-testid="transcript-list"
    >
      {segments.map((segment) => (
        <li
          key={segment.id}
          ref={segment.id === activeId ? current : undefined}
          aria-current={segment.id === activeId ? 'true' : undefined}
          className={cn(
            'rounded-md px-2 pb-2 text-sm leading-relaxed',
            segment.id === activeId ? 'bg-accent' : 'hover:bg-muted',
          )}
        >
          <CitationTime ms={segment.start_ms} className="-ml-2 min-h-9" />
          <p className="wrap-anywhere">
            {segment.speaker_label && (
              <span className="mr-1.5 font-semibold">{segment.speaker_label}:</span>
            )}
            {segment.text}
          </p>
        </li>
      ))}
      {segments.length === 0 && (
        <li className="px-2 py-3 text-sm text-muted-foreground">{t('record.transcriptEmpty')}</li>
      )}
    </ol>
  );
}

function PaneResizeHandle({
  width,
  onResize,
}: {
  width: number;
  onResize: (width: number) => void;
}) {
  const { t } = useTranslation();
  const drag = useRef({ x: 0, width });
  const resize = (next: number) => onResize(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, next)));

  return (
    // biome-ignore lint/a11y/useSemanticElements: a focusable window splitter uses the interactive separator role.
    <div
      role="separator"
      tabIndex={0}
      aria-label={t('record.resizePane')}
      aria-controls="record-pane"
      aria-orientation="vertical"
      aria-valuenow={width}
      aria-valuemin={MIN_WIDTH}
      aria-valuemax={MAX_WIDTH}
      onPointerDown={(event) => {
        drag.current = { x: event.clientX, width };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          resize(drag.current.width + drag.current.x - event.clientX);
        }
      }}
      onKeyDown={(event) => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        resize(width + (event.key === 'ArrowLeft' ? 16 : -16));
      }}
      className="absolute inset-y-0 -left-1 hidden w-2 cursor-col-resize touch-none hover:bg-accent focus-visible:bg-accent focus-visible:outline-none lg:block"
    />
  );
}

export function MeetingRecordPane({
  meetingId,
  segments,
  pane,
  onHide,
}: {
  meetingId: string;
  segments: TranscriptSegment[];
  pane: ReturnType<typeof useRecordPane>;
  onHide: () => void;
}) {
  const { t } = useTranslation();
  const [width, setWidth] = useState(280);
  const showsTranscript = pane.mode === 'transcript';

  return (
    <aside
      id="record-pane"
      data-testid="record-pane"
      aria-label={t('record.pane')}
      style={{ '--record-pane-width': `${width}px` } as CSSProperties}
      className={cn(
        'absolute inset-y-0 right-0 z-20 w-(--record-pane-width) max-w-full shrink-0 flex-col border-l border-border bg-card lg:relative',
        pane.isHidden ? 'hidden' : 'flex',
      )}
    >
      <PaneResizeHandle width={width} onResize={setWidth} />
      <header className="flex shrink-0 items-center gap-1 border-b border-border p-2">
        {(['transcript', 'ask'] as const).map((mode) => (
          <Button
            key={mode}
            type="button"
            size="sm"
            variant="ghost"
            aria-pressed={pane.mode === mode}
            onClick={() => pane.setMode(mode)}
            className="flex-1 rounded-md aria-pressed:bg-accent aria-pressed:text-accent-foreground"
          >
            {t(mode === 'transcript' ? 'tabs.transcript' : 'record.ask')}
          </Button>
        ))}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-9 rounded-md"
          data-testid="hide-record-pane"
          aria-label={t('record.hidePane')}
          title={`${t('record.hidePane')} (T)`}
          aria-keyshortcuts="T"
          onClick={onHide}
        >
          <X aria-hidden="true" />
        </Button>
      </header>
      {showsTranscript && <RecordTranscript segments={segments} isVisible={!pane.isHidden} />}
      <div hidden={showsTranscript} className="min-h-0 flex-1">
        <CopilotPanel meetingId={meetingId} />
      </div>
    </aside>
  );
}
