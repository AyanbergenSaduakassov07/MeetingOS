import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { api, type DecisionConflict, type DecisionTimelineEntry } from '@/lib/api';
import { formatTimestamp } from '@/lib/playback';
import { cn } from '@/lib/utils';

/** Tint per decision status / chain relationship; unknown values fall back to neutral. */
const TONE: Record<string, string> = {
  agreed: 'bg-good-tint text-good',
  consistent: 'bg-good-tint text-good',
  refined: 'bg-link-tint text-link',
  revisited: 'bg-link-tint text-link',
  contradicted: 'bg-warn-tint text-warn',
  reversed: 'bg-destructive/10 text-destructive',
  superseded: 'bg-muted text-muted-foreground',
};

export function StatusChip({
  value,
  group = 'state',
}: {
  value: string;
  group?: 'state' | 'event';
}) {
  const { t } = useTranslation();
  return (
    <span
      className={cn(
        'rounded-md px-2 py-0.5 text-xs font-medium',
        TONE[value] ?? 'bg-secondary text-secondary-foreground',
      )}
    >
      {t(`decisionRecord.${group}.${value}`, value)}
    </span>
  );
}

function Citation({
  meetingId,
  meetingTitle,
  ms,
}: {
  meetingId: string | null;
  meetingTitle: string | null;
  ms: number | null;
}) {
  if (!meetingId) return null;
  return (
    <span className="text-xs text-muted-foreground">
      <Link to={`/meetings/${meetingId}`} className="text-link hover:underline">
        {meetingTitle ?? meetingId}
      </Link>
      {ms != null && <span className="ml-1.5 font-mono">{formatTimestamp(ms)}</span>}
    </span>
  );
}

function Chain({ entries }: { entries: DecisionTimelineEntry[] }) {
  const { t, i18n } = useTranslation();
  return (
    <ol className="mt-3 border-l border-border" data-testid="decision-chain">
      {entries.map((entry) => (
        <li key={`${entry.decision_id}-${entry.event_type}`} className="relative pb-5 pl-5">
          <span
            aria-hidden="true"
            className={cn(
              'absolute -left-[5px] top-1.5 size-2.5 rounded-full border-2 border-card',
              entry.is_current ? 'bg-primary' : 'bg-border',
            )}
          />
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip value={entry.event_type} group="event" />
            {entry.occurred_at && (
              <time className="text-xs text-muted-foreground" dateTime={entry.occurred_at}>
                {new Date(entry.occurred_at).toLocaleDateString(i18n.language)}
              </time>
            )}
            {entry.is_current && (
              <span className="text-xs font-medium">{t('decisionRecord.current')}</span>
            )}
          </div>
          <p className="mt-1 text-sm">{entry.title}</p>
          <Citation
            meetingId={entry.meeting_id}
            meetingTitle={entry.meeting_title}
            ms={entry.start_ms}
          />
        </li>
      ))}
    </ol>
  );
}

function Quote({
  label,
  claim,
  children,
}: {
  label: string;
  claim: string;
  children: React.ReactNode;
}) {
  return (
    <figure className="rounded-md border border-border p-3">
      <figcaption className="font-mono text-[10.5px] uppercase tracking-wider text-muted-foreground">
        {label}
      </figcaption>
      <blockquote className="mt-1 text-sm italic">“{claim}”</blockquote>
      <div className="mt-1">{children}</div>
    </figure>
  );
}

function Conflicts({ conflicts }: { conflicts: DecisionConflict[] }) {
  const { t } = useTranslation();
  if (conflicts.length === 0) {
    return <p className="mt-3 text-sm text-muted-foreground">{t('decisionRecord.noConflicts')}</p>;
  }
  return (
    <div className="mt-3 space-y-4" data-testid="decision-conflicts">
      {conflicts.map((c) => (
        <div
          key={`${c.prior_decision_id}-${c.relationship}`}
          className="rounded-lg border border-border p-4"
        >
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip value={c.relationship} />
            {c.low_confidence && (
              <span className="text-xs text-warn">{t('status.lowConfidence')}</span>
            )}
          </div>
          <p className="mt-2 text-sm text-muted-foreground">{c.reasoning}</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <Quote label={t('decisionRecord.before')} claim={c.prior_claim}>
              <Citation
                meetingId={c.prior_meeting_id}
                meetingTitle={c.prior_meeting_title}
                ms={c.prior_start_ms}
              />
            </Quote>
            <Quote label={t('decisionRecord.after')} claim={c.new_claim}>
              <Citation
                meetingId={c.new_meeting_id}
                meetingTitle={c.new_meeting_title}
                ms={c.new_start_ms}
              />
            </Quote>
          </div>
        </div>
      ))}
    </div>
  );
}

/** One decision: current state, then its chain oldest first, then how it stands against earlier links. */
export function DecisionRecord() {
  const { t } = useTranslation();
  const { decisionId = '' } = useParams();
  const timeline = useQuery({
    queryKey: ['decision-timeline', decisionId],
    queryFn: () => api.getDecisionTimeline(decisionId),
  });
  const conflicts = useQuery({
    queryKey: ['decision-conflicts', decisionId],
    queryFn: () => api.getDecisionConflicts(decisionId),
  });

  const entries = timeline.data?.entries ?? [];
  const current = entries.find((e) => e.is_current) ?? entries[entries.length - 1];

  return (
    <div className="mx-auto max-w-4xl px-6 py-8" data-testid="decision-record">
      <nav className="text-sm text-muted-foreground">
        <Link to="/decisions" className="text-link hover:underline">
          {t('register.decisions')}
        </Link>
      </nav>

      {timeline.isLoading && (
        <p className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          {t('common.loading')}
        </p>
      )}
      {(timeline.isError || (timeline.isSuccess && !current)) && (
        <p role="alert" className="mt-8 text-sm text-destructive">
          {t('decisionRecord.loadFailed')}
        </p>
      )}

      {current && (
        <>
          <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight">
            {current.title}
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <StatusChip value={current.status} />
            <Citation
              meetingId={current.meeting_id}
              meetingTitle={current.meeting_title}
              ms={current.start_ms}
            />
          </div>

          <section className="mt-8">
            <h2 className="text-lg font-semibold">
              {t('decisionRecord.chain')}{' '}
              <span className="text-sm font-normal text-muted-foreground">{entries.length}</span>
            </h2>
            <Chain entries={entries} />
          </section>

          <section className="mt-6">
            <h2 className="text-lg font-semibold">{t('decisionRecord.conflicts')}</h2>
            {conflicts.isError ? (
              <p role="alert" className="mt-3 text-sm text-destructive">
                {t('decisionRecord.conflictsFailed')}
              </p>
            ) : conflicts.isLoading ? (
              <Loader2 aria-label={t('common.loading')} className="mt-3 size-4 animate-spin" />
            ) : (
              <Conflicts conflicts={conflicts.data?.conflicts ?? []} />
            )}
          </section>
        </>
      )}
    </div>
  );
}
