import { useQuery } from '@tanstack/react-query';
import { AlertCircle, AlertTriangle, Loader2 } from 'lucide-react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { CitationTime } from '@/components/CitationTime';
import { CopilotPanel } from '@/components/CopilotPanel';
import { ItemCard, type ItemKind } from '@/components/ItemCard';
import { PlayerBar } from '@/components/PlayerBar';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ApiError, api, type ExtractedItem } from '@/lib/api';
import { formatTimestamp } from '@/lib/playback';

const TABS = ['summary', 'decisions', 'actions', 'risks', 'transcript'] as const;

const isNotFound = (error: unknown) => error instanceof ApiError && error.status === 404;

function StateCard({
  icon,
  title,
  detail,
  testId,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  detail?: string | null;
  testId: string;
  children?: React.ReactNode;
}) {
  return (
    <output
      data-testid={testId}
      className="mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-lg border border-border bg-card p-8 text-center"
    >
      {icon}
      <h2 className="font-display text-lg font-bold">{title}</h2>
      {detail && <p className="text-sm text-muted-foreground">{detail}</p>}
      {children}
    </output>
  );
}

function ItemList({ items, kind }: { items: ExtractedItem[]; kind: ItemKind }) {
  const { t } = useTranslation();
  if (items.length === 0) {
    return <p className="py-8 text-sm text-muted-foreground">{t('intelligence.empty')}</p>;
  }
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <ItemCard key={item.id} item={item} kind={kind} />
      ))}
    </div>
  );
}

export function MeetingDetail() {
  const { t, i18n } = useTranslation();
  const { meetingId = '' } = useParams();

  const meeting = useQuery({
    queryKey: ['meeting', meetingId],
    queryFn: () => api.getMeeting(meetingId),
    // A processing meeting becomes a completed one without the user acting,
    // so poll until it settles rather than making them reload.
    // Errors keep the last data, so a deleted meeting would otherwise be polled forever.
    refetchInterval: (query) =>
      !isNotFound(query.state.error) &&
      ['processing', 'queued', 'analyzing'].includes(query.state.data?.status ?? '')
        ? 3000
        : false,
    retry: (count, error) => !isNotFound(error) && count < 3,
  });

  const status = meeting.data?.status;
  // 'analyzing': the transcript is ready, extraction is still running.
  const settled = status === 'completed' || status === 'analyzing';

  const intelligence = useQuery({
    // Keyed on status so the report refetches when extraction finishes.
    queryKey: ['intelligence', meetingId, status],
    queryFn: () => api.getIntelligence(meetingId),
    enabled: settled,
  });

  const transcript = useQuery({
    queryKey: ['transcript', meetingId],
    queryFn: () => api.getTranscript(meetingId),
    enabled: settled,
  });

  const citations = useMemo(() => {
    const data = intelligence.data;
    if (!data) return [];
    return [...data.decisions, ...data.action_items, ...data.risks, ...data.commitments]
      .filter((item) => item.source_start_ms !== null)
      .map((item) => ({
        id: item.id,
        startMs: item.source_start_ms as number,
        endMs: item.source_end_ms ?? (item.source_start_ms as number) + 1000,
      }));
  }, [intelligence.data]);

  if (meeting.isLoading) {
    return (
      <StateCard
        testId="state-loading"
        icon={<Loader2 aria-hidden="true" className="size-6 animate-spin text-muted-foreground" />}
        title={t('common.loading')}
      />
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
        <Link
          to="/meetings"
          className="text-sm font-medium underline underline-offset-2 hover:text-primary"
        >
          {t('meetings.backToList')}
        </Link>
      </StateCard>
    );
  }

  const data = meeting.data;
  const speakerCount = new Set(
    (transcript.data ?? []).map((segment) => segment.speaker_label).filter(Boolean),
  ).size;

  if (data.status === 'processing' || data.status === 'queued') {
    return (
      <StateCard
        testId="state-processing"
        icon={<Loader2 aria-hidden="true" className="size-6 animate-spin text-primary" />}
        title={t('meetings.processingTitle')}
        detail={t('meetings.processingDetail')}
      />
    );
  }

  if (data.status === 'failed') {
    return (
      <StateCard
        testId="state-failed"
        icon={<AlertCircle aria-hidden="true" className="size-6 text-destructive" />}
        title={t('meetings.failedTitle')}
        detail={data.processing_error || t('meetings.failedDetail')}
      />
    );
  }

  const intel = intelligence.data;

  return (
    <div className="flex h-full flex-col" data-testid="meeting-detail">
      <div className="flex min-h-0 flex-1">
        <section className="flex min-w-0 flex-1 flex-col">
          <header className="border-b border-border px-6 py-5">
            {/* Meeting title is content, not chrome — never translated. */}
            <h1
              className="font-display text-2xl font-black tracking-tight"
              data-testid="meeting-title"
            >
              {data.title}
            </h1>
            <dl className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-muted-foreground">
              <div className="flex gap-1.5">
                <dt>{t('meetings.recorded')}:</dt>
                <dd className="font-mono tabular-nums">
                  {data.created_at
                    ? new Date(data.created_at).toLocaleDateString(i18n.language)
                    : '—'}
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt>{t('meetings.duration')}:</dt>
                <dd className="font-mono tabular-nums" data-testid="meeting-duration">
                  {formatTimestamp((data.audio_duration_seconds ?? 0) * 1000)}
                </dd>
              </div>
              <div className="flex gap-1.5">
                <dt>{t('meetings.speakers')}:</dt>
                <dd className="font-mono tabular-nums">{speakerCount || '—'}</dd>
              </div>
            </dl>
            {status === 'analyzing' && (
              <output
                data-testid="extraction-running"
                className="mt-3 flex items-start gap-2 rounded-md border border-border bg-muted/50 px-3 py-2 text-sm"
              >
                <Loader2
                  aria-hidden="true"
                  className="mt-0.5 size-4 shrink-0 animate-spin text-primary"
                />
                <div>
                  <p className="font-medium">{t('meetings.analyzingTitle')}</p>
                  <p className="text-muted-foreground">{t('meetings.analyzingDetail')}</p>
                </div>
              </output>
            )}
            {/* Transcript is fine but extraction was partial: zero items must not read as "nothing decided". */}
            {data.processing_error && (
              <div
                data-testid="extraction-warning"
                className="mt-3 flex items-start gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm"
              >
                <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warn" />
                <div>
                  <p className="font-medium">{t('meetings.extractionIncomplete')}</p>
                  <p className="text-muted-foreground">{data.processing_error}</p>
                </div>
              </div>
            )}
          </header>

          <Tabs defaultValue="summary" className="flex min-h-0 flex-1 flex-col">
            <TabsList className="mx-6 mt-4 w-fit">
              {TABS.map((tab) => (
                <TabsTrigger key={tab} value={tab} data-testid={`tab-${tab}`}>
                  {t(`tabs.${tab}`)}
                </TabsTrigger>
              ))}
            </TabsList>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
              <TabsContent value="summary">
                {intel && (
                  <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    {(
                      [
                        ['intelligence.decisions', intel.decisions.length],
                        ['intelligence.actions', intel.action_items.length],
                        ['intelligence.risks', intel.risks.length],
                        ['intelligence.commitments', intel.commitments.length],
                      ] as const
                    ).map(([key, count]) => (
                      <div key={key} className="rounded-lg border border-border bg-card p-4">
                        <dt className="text-sm text-muted-foreground">{t(key)}</dt>
                        <dd className="mt-1 font-display text-2xl font-black tabular-nums">
                          {status === 'analyzing' && count === 0 ? '—' : count}
                        </dd>
                      </div>
                    ))}
                  </dl>
                )}
                {intel && intel.topics.length > 0 && (
                  <section className="mt-6">
                    <h2 className="font-display text-sm font-bold">{t('intelligence.topics')}</h2>
                    <ul className="mt-2 space-y-2">
                      {intel.topics.map((topic) => (
                        <li
                          key={topic.id}
                          className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-2"
                        >
                          <span className="truncate text-sm">{topic.label}</span>
                          {topic.start_ms !== null && <CitationTime ms={topic.start_ms} />}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </TabsContent>

              <TabsContent value="decisions">
                <ItemList items={intel?.decisions ?? []} kind="decision" />
              </TabsContent>
              <TabsContent value="actions">
                <ItemList items={intel?.action_items ?? []} kind="action" />
              </TabsContent>
              <TabsContent value="risks">
                <ItemList items={intel?.risks ?? []} kind="risk" />
              </TabsContent>

              <TabsContent value="transcript">
                <ol className="space-y-2" data-testid="transcript-list">
                  {(transcript.data ?? []).map((segment) => (
                    <li
                      key={segment.id}
                      className="flex gap-3 rounded-md px-2 py-1.5 hover:bg-secondary/50"
                    >
                      <CitationTime ms={segment.start_ms} className="shrink-0" />
                      <p className="min-w-0 flex-1 text-sm leading-relaxed">
                        {segment.speaker_label && (
                          <span className="mr-1.5 font-semibold">{segment.speaker_label}:</span>
                        )}
                        {segment.text}
                      </p>
                    </li>
                  ))}
                </ol>
              </TabsContent>
            </div>
          </Tabs>
        </section>

        <div className="hidden min-h-0 w-80 shrink-0 lg:block">
          <CopilotPanel meetingId={meetingId} />
        </div>
      </div>

      <PlayerBar
        audioUrl={api.audioUrl(meetingId)}
        citations={citations}
        fallbackDurationMs={(data.audio_duration_seconds ?? 0) * 1000}
      />
    </div>
  );
}
