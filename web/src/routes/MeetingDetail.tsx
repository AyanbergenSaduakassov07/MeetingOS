import { useQuery } from '@tanstack/react-query';
import { AlertCircle, AlertTriangle, ChevronRight, MessageSquare, PanelRight } from 'lucide-react';
import { type ReactNode, type RefObject, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { CitationTime } from '@/components/CitationTime';
import { ItemCard, type ItemKind } from '@/components/ItemCard';
import { MeetingRecordActions } from '@/components/MeetingRecordActions';
import { MeetingRecordPane, useRecordPane } from '@/components/MeetingRecordPane';
import { PlayerBar } from '@/components/PlayerBar';
import { MINUTES_LANGUAGES, MinutesDialog, SummaryPanel } from '@/components/SummaryPanel';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { languageName } from '@/i18n';
import {
  ApiError,
  api,
  type ExtractedItem,
  type MeetingDetail as MeetingData,
  type MeetingIntelligence,
  type Topic,
  type TranscriptSegment,
} from '@/lib/api';
import { formatTimestamp, usePlayback } from '@/lib/playback';
import { cn } from '@/lib/utils';

const isNotFound = (error: unknown) => error instanceof ApiError && error.status === 404;

function StateCard({
  icon,
  title,
  detail,
  testId,
  children,
}: {
  icon?: ReactNode;
  title: string;
  detail?: string | null;
  testId: string;
  children?: ReactNode;
}) {
  return (
    <section
      data-testid={testId}
      aria-live="polite"
      className="mx-4 mt-16 flex max-w-md flex-col items-center gap-3 rounded-lg border border-border bg-card p-8 text-center sm:mx-auto"
    >
      {icon}
      <h2 className="font-display text-lg font-bold">{title}</h2>
      {detail && <p className="text-sm text-muted-foreground">{detail}</p>}
      {children}
    </section>
  );
}

function ItemList({
  items,
  kind,
  selectedId,
  onSelect,
}: {
  items: ExtractedItem[];
  kind: ItemKind;
  selectedId: string | null;
  onSelect: (item: ExtractedItem) => void;
}) {
  const { t } = useTranslation();
  if (!items.length) {
    return <p className="text-sm text-muted-foreground">{t('intelligence.empty')}</p>;
  }
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <ItemCard
          key={item.id}
          item={item}
          kind={kind}
          isSelected={selectedId === item.id}
          onSelect={item.source_start_ms == null ? undefined : () => onSelect(item)}
        />
      ))}
    </div>
  );
}

const EMPTY_ITEMS: ExtractedItem[] = [];
const EMPTY_TRANSCRIPT: TranscriptSegment[] = [];
const ITEMS = [
  ['decisions', 'decision', 'decisions'],
  ['actions', 'action', 'action_items'],
  ['commitments', 'commitment', 'commitments'],
  ['risks', 'risk', 'risks'],
] as const;

function PipelineSteps({ status }: { status: string }) {
  const { t } = useTranslation();
  const active = status === 'failed' ? 'processing' : status;

  return (
    <ol className="flex flex-wrap justify-center gap-2" aria-label={t('record.pipeline')}>
      {(['queued', 'processing', 'analyzing'] as const).map((step) => (
        <li
          key={step}
          aria-current={step === active ? 'step' : undefined}
          className={cn(
            'rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground',
            step === active &&
              (status === 'failed'
                ? 'bg-destructive/10 text-destructive'
                : 'bg-accent font-medium text-accent-foreground'),
          )}
        >
          {t(`record.step.${step}`)}
        </li>
      ))}
    </ol>
  );
}

function PipelineState({ meeting }: { meeting: MeetingData }) {
  const { t } = useTranslation();
  const failed = meeting.status === 'failed';
  return (
    <StateCard
      testId={failed ? 'state-failed' : 'state-processing'}
      title={t(failed ? 'meetings.failedTitle' : 'meetings.processingTitle')}
      detail={t(failed ? 'record.transcriptionFix' : 'meetings.processingDetail')}
    >
      <PipelineSteps status={meeting.status} />
      {failed && (
        <>
          {meeting.processing_error && (
            <details className="w-full text-sm text-muted-foreground">
              <summary className="cursor-pointer">{t('common.details')}</summary>
              <p className="mt-1 wrap-anywhere">{meeting.processing_error}</p>
            </details>
          )}
          <BackToMeetings />
        </>
      )}
    </StateCard>
  );
}

function BackToMeetings() {
  const { t } = useTranslation();
  return (
    <Link
      to="/meetings"
      className="rounded-sm text-sm font-medium text-link hover:underline focus-visible:outline-2 focus-visible:outline-ring"
    >
      {t('meetings.backToList')}
    </Link>
  );
}

function ExtractionStatus({ meeting }: { meeting: MeetingData }) {
  const { t } = useTranslation();
  if (meeting.status === 'analyzing') {
    return (
      <div
        data-testid="extraction-running"
        aria-live="polite"
        className="mt-4 block space-y-2 rounded-md border border-border bg-card p-3 text-sm"
      >
        <PipelineSteps status={meeting.status} />
        <p className="text-muted-foreground">{t('meetings.analyzingDetail')}</p>
      </div>
    );
  }
  if (!meeting.processing_error) return null;
  return (
    <div
      data-testid="extraction-warning"
      className="mt-4 flex items-start gap-2 rounded-md border border-warn/40 bg-warn-tint p-3 text-sm"
    >
      <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warn" />
      <div className="min-w-0">
        <p className="font-medium">{t('meetings.extractionIncomplete')}</p>
        <p className="text-muted-foreground">{t('meetings.extractionIncompleteHint')}</p>
        <details className="mt-1 text-xs text-muted-foreground">
          <summary className="cursor-pointer">{t('common.details')}</summary>
          <p className="mt-1 wrap-anywhere">{meeting.processing_error}</p>
        </details>
      </div>
    </div>
  );
}

function RecordHeader({
  data,
  segments,
  pane,
  hasSidebar,
  transcriptButton,
  children,
}: {
  data: MeetingData;
  segments: TranscriptSegment[];
  pane: ReturnType<typeof useRecordPane>;
  hasSidebar: boolean;
  transcriptButton: RefObject<HTMLButtonElement>;
  children: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const speakerCount = new Set(segments.map((segment) => segment.speaker_label).filter(Boolean))
    .size;
  const metadata = [
    [
      'meetings.recorded',
      data.created_at ? new Date(data.created_at).toLocaleDateString(i18n.language) : '—',
    ],
    ['meetings.duration', formatTimestamp((data.audio_duration_seconds ?? 0) * 1000)],
    ['meetings.speakers', speakerCount || '—'],
    ['consent.languageLabel', data.language ? languageName(data.language, i18n.language) : '—'],
  ] as const;

  return (
    <header className="border-b border-border pb-5">
      <div
        className={cn(
          'flex items-center gap-2 text-sm text-muted-foreground',
          !hasSidebar && 'pl-9',
        )}
      >
        <Link to="/meetings" className="text-link hover:underline">
          {t('nav.meetings')}
        </Link>
        <ChevronRight aria-hidden="true" className="size-3.5" />
        <span className="truncate">{data.title}</span>
      </div>
      <h1
        className="mt-2 wrap-anywhere text-2xl font-semibold tracking-tight sm:text-3xl"
        data-testid="meeting-title"
      >
        {data.title}
      </h1>
      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
        {metadata.map(([label, value]) => (
          <div key={label} className="flex items-baseline gap-1">
            <dt>{t(label)}</dt>
            <dd
              className="font-mono tabular-nums"
              data-testid={label === 'meetings.duration' ? 'meeting-duration' : undefined}
            >
              {value}
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {children}
        <Button
          ref={transcriptButton}
          type="button"
          size="sm"
          variant="outline"
          className="rounded-md"
          aria-controls="record-pane"
          aria-expanded={!pane.isHidden && pane.mode === 'transcript'}
          onClick={() => pane.open('transcript')}
        >
          <PanelRight aria-hidden="true" />
          {t('tabs.transcript')}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="rounded-md"
          data-testid="open-ask"
          aria-controls="record-pane"
          aria-expanded={!pane.isHidden && pane.mode === 'ask'}
          onClick={() => pane.open('ask')}
        >
          <MessageSquare aria-hidden="true" />
          {t('record.ask')}
        </Button>
        <MeetingRecordActions meeting={data} />
      </div>
      <ExtractionStatus meeting={data} />
    </header>
  );
}

type RecordSection = {
  id: string;
  label: string;
  count?: number;
  content: ReactNode;
};

function RecordOutline({ sections }: { sections: RecordSection[] }) {
  const { t } = useTranslation();
  const [active, setActive] = useState(() => window.location.hash.slice(1));

  return (
    <nav
      className="sticky top-0 hidden w-32 shrink-0 self-start border-r border-border bg-background px-2 py-5 md:block"
      aria-label={t('record.sections')}
      data-testid="record-outline"
    >
      {sections.map(({ id, label, count }, index) => {
        const selected = active ? id === active : index === 0;
        return (
          <a
            key={id}
            href={`#${id}`}
            onClick={() => setActive(id)}
            aria-current={selected ? 'location' : undefined}
            data-state={selected ? 'active' : 'inactive'}
            data-testid={`tab-${id}`}
            title={label}
            className={cn(
              'flex items-center justify-between gap-1 rounded-md px-1.5 py-2 text-[13px] font-medium text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring',
              selected && 'bg-accent text-accent-foreground hover:bg-accent',
            )}
          >
            <span className="truncate">{label}</span>
            {count !== undefined && <span className="font-mono text-xs tabular-nums">{count}</span>}
          </a>
        );
      })}
    </nav>
  );
}

function TopicsList({ topics }: { topics: Topic[] }) {
  const { t } = useTranslation();
  if (!topics.length)
    return <p className="text-sm text-muted-foreground">{t('intelligence.empty')}</p>;

  return (
    <ul className="space-y-2">
      {topics.map((topic) => (
        <li
          key={topic.id}
          className="flex items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-1"
        >
          <span className="min-w-0 wrap-anywhere text-sm">{topic.label}</span>
          {topic.start_ms !== null && <CitationTime ms={topic.start_ms} className="shrink-0" />}
        </li>
      ))}
    </ul>
  );
}

function useRecordSections({
  data,
  intel,
  isBoard,
  language,
  listProps,
}: {
  data: MeetingData;
  intel: MeetingIntelligence | undefined;
  isBoard: boolean;
  language: string;
  listProps: Pick<Parameters<typeof ItemList>[0], 'selectedId' | 'onSelect'>;
}): RecordSection[] {
  const { t } = useTranslation();
  const sections: RecordSection[] = [
    {
      id: 'summary',
      label: t('tabs.summary'),
      content:
        data.status === 'completed' ? (
          <SummaryPanel
            key={language}
            meetingId={data.id}
            savedSummary={data.summary}
            language={language}
          />
        ) : (
          <p className="text-sm text-muted-foreground">{t('meetings.analyzingTitle')}</p>
        ),
    },
    ...ITEMS.map(([id, kind, key]) => ({
      id,
      label: t(`tabs.${id}`),
      count: intel?.[key].length,
      content: <ItemList items={intel?.[key] ?? EMPTY_ITEMS} kind={kind} {...listProps} />,
    })),
    {
      id: 'topics',
      label: t('intelligence.topics'),
      count: intel?.topics.length,
      content: <TopicsList topics={intel?.topics ?? []} />,
    },
  ];

  if (isBoard) {
    // shortcut: the API stores formal motions as decisions and dissent/financial implications as risks; use structured fields when exposed
    const motions = (intel?.decisions ?? []).filter((item) =>
      ['agreed', 'rejected', 'withdrawn', 'deferred'].includes(item.status ?? ''),
    );
    const boardNotes = (intel?.risks ?? []).filter(
      (item) => item.title.startsWith('Dissent recorded — ') || item.title.startsWith('Financial '),
    );
    sections.unshift({
      id: 'resolutions',
      label: t('record.resolutions'),
      count: motions.length,
      content: (
        <div className="space-y-3">
          <ItemList items={motions} kind="decision" {...listProps} />
          {boardNotes.length > 0 && <ItemList items={boardNotes} kind="risk" {...listProps} />}
        </div>
      ),
    });
  }
  return sections;
}

function MeetingRecord({
  data,
  intel,
  segments,
  showOutline,
}: {
  data: MeetingData;
  intel: MeetingIntelligence | undefined;
  segments: TranscriptSegment[];
  showOutline: boolean;
}) {
  const { i18n } = useTranslation();
  const [chosenLanguage, setLanguage] = useState<string>();
  const locale = chosenLanguage ?? i18n.language.split('-')[0];
  const language = MINUTES_LANGUAGES.has(locale) ? locale : 'en';
  const [isMinutesOpen, setMinutesOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const pane = useRecordPane();
  const transcriptButton = useRef<HTMLButtonElement>(null);

  const minutes = useQuery({
    queryKey: ['minutes', data.id],
    queryFn: () => api.getMinutes(data.id, false, 'en'),
    enabled: data.status === 'completed' && (isMinutesOpen || Boolean(data.template_id)),
    staleTime: 60_000,
  });
  const sections = useRecordSections({
    data,
    intel,
    isBoard: Boolean(minutes.data?.is_board_meeting),
    language,
    listProps: {
      selectedId,
      onSelect: (item) => {
        if (item.source_start_ms === null) return;
        setSelectedId(item.id);
        usePlayback.getState().seek(item.source_start_ms);
        pane.setMode('transcript');
      },
    },
  });

  const citations = useMemo(() => {
    if (!intel) return [];
    return ITEMS.flatMap(([, , key]) => intel[key]).flatMap((item) =>
      item.source_start_ms === null
        ? []
        : [
            {
              id: item.id,
              startMs: item.source_start_ms,
              endMs: item.source_end_ms ?? item.source_start_ms + 1000,
            },
          ],
    );
  }, [intel]);

  return (
    <div className="flex h-full flex-col" data-testid="meeting-detail">
      <div className="relative flex min-h-0 flex-1">
        <div
          className="flex min-w-0 flex-1 overflow-y-auto scroll-pt-4"
          data-testid="record-scroll"
        >
          {showOutline && <RecordOutline sections={sections} />}
          <article className="mx-auto min-w-0 max-w-4xl flex-1 px-4 py-5 sm:px-8">
            <RecordHeader
              data={data}
              segments={segments}
              pane={pane}
              hasSidebar={showOutline}
              transcriptButton={transcriptButton}
            >
              {data.status === 'completed' && (
                <MinutesDialog
                  title={data.title}
                  minutes={minutes.data}
                  hasError={minutes.isError}
                  isOpen={isMinutesOpen}
                  onOpenChange={setMinutesOpen}
                  language={language}
                  onLanguageChange={setLanguage}
                />
              )}
            </RecordHeader>
            <div className="pb-6">
              {sections.map(({ id, label, count, content }) => (
                <section
                  key={id}
                  id={id}
                  aria-labelledby={`record-heading-${id}`}
                  className="space-y-3 border-b border-border py-5"
                >
                  <h2 id={`record-heading-${id}`} className="flex items-baseline gap-2 text-lg">
                    {label}
                    {count !== undefined && (
                      <span className="font-mono text-xs font-normal text-muted-foreground">
                        {count}
                      </span>
                    )}
                  </h2>
                  {content}
                </section>
              ))}
            </div>
          </article>
        </div>
        <MeetingRecordPane
          meetingId={data.id}
          segments={segments}
          pane={pane}
          onHide={() => {
            pane.hide();
            transcriptButton.current?.focus({ preventScroll: true });
          }}
        />
      </div>
      <PlayerBar
        audioUrl={api.audioUrl(data.id)}
        citations={citations}
        fallbackDurationMs={(data.audio_duration_seconds ?? 0) * 1000}
      />
    </div>
  );
}

export function MeetingDetail({ showOutline }: { showOutline: boolean }) {
  const { t } = useTranslation();
  const { meetingId = '' } = useParams();
  const meeting = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => api.getMeeting(meetingId),
    // Poll only while the pipeline is running. A deleted meeting can leave stale data in the cache.
    refetchInterval: (query) =>
      !isNotFound(query.state.error) &&
      ['processing', 'queued', 'analyzing'].includes(query.state.data?.status ?? '')
        ? 3000
        : false,
    retry: (count, error) => !isNotFound(error) && count < 3,
  });
  const status = meeting.data?.status;
  const settled = status === 'completed' || status === 'analyzing';
  const intelligence = useQuery({
    queryKey: ['intelligence', meetingId, status],
    queryFn: () => api.getIntelligence(meetingId),
    enabled: settled,
  });
  const transcript = useQuery({
    queryKey: ['transcript', meetingId],
    queryFn: () => api.getTranscript(meetingId),
    enabled: settled,
  });

  if (meeting.isLoading) {
    return (
      <div
        aria-busy="true"
        className="mx-auto max-w-4xl px-4 py-5 sm:px-8"
        data-testid="state-loading"
      >
        <span className="sr-only">{t('common.loading')}</span>
        <div className="border-b border-border pb-5">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="mt-2 h-9 w-3/4 max-w-md" />
          <Skeleton className="mt-3 h-5 w-64 max-w-full" />
        </div>
        <div className="space-y-3 py-5">
          <Skeleton className="h-6 w-32" />
          <Skeleton className="h-24" />
          <Skeleton className="h-16" />
        </div>
      </div>
    );
  }
  if (meeting.isError || !meeting.data) {
    return (
      <StateCard
        testId="state-error"
        icon={<AlertCircle aria-hidden="true" className="size-6 text-destructive" />}
        title={t(isNotFound(meeting.error) ? 'meetings.notFound' : 'meetings.loadFailed')}
        detail={
          !isNotFound(meeting.error) && meeting.error instanceof Error
            ? meeting.error.message
            : undefined
        }
      >
        <BackToMeetings />
      </StateCard>
    );
  }
  if (status === 'queued' || status === 'processing' || status === 'failed') {
    return <PipelineState meeting={meeting.data} />;
  }

  return (
    <MeetingRecord
      key={meetingId}
      data={meeting.data}
      intel={intelligence.data}
      segments={transcript.data ?? EMPTY_TRANSCRIPT}
      showOutline={showOutline}
    />
  );
}
