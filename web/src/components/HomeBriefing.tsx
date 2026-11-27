import { useQuery } from '@tanstack/react-query';
import { ArrowRight, FileText, Radio, Upload } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { api, type MeetingSummary } from '@/lib/api';
import { formatTimestamp } from '@/lib/playback';
import { useOrgIntelligence } from '@/lib/register';
import { cn } from '@/lib/utils';

const CHIP = 'shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold';
const CARD = 'rounded-lg border border-border bg-card';
const CHECK_STATES = new Set(['low_confidence', 'unsupported']);

interface AttentionRow {
  key: string;
  tone: string;
  label: string;
  text: string;
  detail: string;
  meetingId: string | null;
  meetingTitle: string | null;
  startMs: number | null;
}

function useAttentionRows(periodDays: number): { rows: AttentionRow[]; isLoading: boolean } {
  const { t, i18n } = useTranslation();
  const overdue = useQuery({
    queryKey: ['commitments', { overdue: 'true' }],
    queryFn: () => api.listCommitments({ overdue: 'true' }),
  });
  const org = useOrgIntelligence(periodDays);

  const overdueRows: AttentionRow[] = (overdue.data?.items ?? []).map((item) => ({
    key: `c-${item.id}`,
    tone: 'bg-destructive/10 text-destructive',
    label: t('home.overdue'),
    text: item.text,
    detail: [
      item.owner_name,
      item.due_date &&
        t('home.due', { date: new Date(item.due_date).toLocaleDateString(i18n.language) }),
    ]
      .filter(Boolean)
      .join(' · '),
    meetingId: item.meeting_id,
    meetingTitle: item.meeting_title,
    startMs: item.start_ms,
  }));

  // Every extracted kind can carry a weak quote; the verifier flags them all the same way.
  const checkRows: AttentionRow[] = org.intelligence.flatMap(({ meeting, data }) =>
    [...data.decisions, ...data.action_items, ...data.risks, ...data.commitments]
      .filter((item) => CHECK_STATES.has(item.verification_status))
      .map((item) => ({
        key: `q-${item.id}`,
        tone: 'bg-warn-tint text-warn',
        label: t('home.checkQuote'),
        text: item.title,
        detail: t(
          item.verification_status === 'unsupported' ? 'status.unsupportedHint' : 'home.checkHint',
        ),
        meetingId: meeting.id,
        meetingTitle: meeting.title,
        startMs: item.source_start_ms,
      })),
  );

  return { rows: [...overdueRows, ...checkRows], isLoading: overdue.isLoading || org.isLoading };
}

/** Overdue follow-ups and claims the verifier doubts, in one list. */
export function NeedsAttention({ periodDays }: { periodDays: number }) {
  const { t } = useTranslation();
  const { rows, isLoading } = useAttentionRows(periodDays);

  return (
    <section aria-labelledby="attention-heading" data-testid="needs-attention">
      <h2 id="attention-heading" className="flex items-center gap-2 font-display text-sm font-bold">
        {t('home.needsAttention')}
        {!isLoading && (
          <span className="rounded-full bg-muted px-2 font-mono text-xs text-muted-foreground">
            {rows.length}
          </span>
        )}
      </h2>
      {isLoading ? (
        <div className={cn(CARD, 'mt-2 h-24 animate-pulse')} />
      ) : rows.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">{t('home.allClear')}</p>
      ) : (
        <ul className={cn(CARD, 'mt-2 divide-y divide-border')}>
          {rows.map((row) => (
            <li key={row.key} data-testid="attention-row" className="flex items-start gap-3 p-3">
              <span className={cn(CHIP, row.tone)}>{row.label}</span>
              <div className="min-w-0 flex-1">
                {/* Item text is meeting content, never translated. */}
                <p className="text-sm font-medium">{row.text}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {row.detail}
                  {row.meetingId && (
                    <>
                      {row.detail && ' · '}
                      <Link
                        to={`/meetings/${row.meetingId}`}
                        className="text-link underline-offset-2 hover:underline"
                      >
                        {row.meetingTitle}
                      </Link>
                    </>
                  )}
                </p>
              </div>
              {row.startMs !== null && (
                <span className="shrink-0 font-mono text-xs text-muted-foreground">
                  {formatTimestamp(row.startMs)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function durationLabel(meeting: MeetingSummary): string | null {
  const seconds = meeting.audio_duration_seconds;
  return seconds ? formatTimestamp(seconds * 1000) : null;
}

const STATUS_TONE: Record<string, string> = {
  completed: 'bg-good-tint text-good',
  failed: 'bg-destructive/10 text-destructive',
};

export function RecentMeetings({ meetings }: { meetings: MeetingSummary[] }) {
  const { t, i18n } = useTranslation();
  const recent = [...meetings]
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
    .slice(0, 4);

  return (
    <section aria-labelledby="recent-heading" data-testid="recent-meetings">
      <div className="flex items-baseline justify-between">
        <h2 id="recent-heading" className="font-display text-sm font-bold">
          {t('home.recentMeetings')}
        </h2>
        <Link to="/meetings" className="text-xs text-link underline-offset-2 hover:underline">
          {t('home.allMeetings')}
        </Link>
      </div>
      <ul className={cn(CARD, 'mt-2 divide-y divide-border')}>
        {recent.map((meeting) => (
          <li key={meeting.id}>
            <Link
              to={`/meetings/${meeting.id}`}
              className="flex items-center gap-3 p-3 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            >
              <span
                className={cn(
                  CHIP,
                  STATUS_TONE[meeting.status] ?? 'bg-muted text-muted-foreground',
                )}
              >
                {t(`status.${meeting.status}`, meeting.status)}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{meeting.title}</span>
              <span className="hidden shrink-0 font-mono text-xs text-muted-foreground sm:inline">
                {[
                  meeting.created_at &&
                    new Date(meeting.created_at).toLocaleDateString(i18n.language),
                  durationLabel(meeting),
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function UpcomingBrief() {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="upcoming-heading" className={cn(CARD, 'p-4')}>
      <h2 id="upcoming-heading" className="font-display text-sm font-bold">
        {t('home.upcoming')}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">{t('home.briefHint')}</p>
      <Link
        to="/brief"
        data-testid="home-prepare-brief"
        className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-link underline-offset-2 hover:underline"
      >
        {t('home.prepareBrief')}
        <ArrowRight aria-hidden="true" className="size-4" />
      </Link>
    </section>
  );
}

const FIRST_ACTIONS = [
  { to: '/meetings', icon: Upload, key: 'upload' },
  { to: '/live', icon: Radio, key: 'live' },
  { to: '/library', icon: FileText, key: 'library' },
] as const;

/** First run: nothing recorded yet, so offer the three ways in. */
export function EmptyWorkspace() {
  const { t } = useTranslation();
  return (
    <section data-testid="empty-workspace" className="mt-8">
      <h2 className="font-display text-lg font-semibold">{t('home.emptyTitle')}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{t('home.emptyHint')}</p>
      <ul className="mt-4 grid gap-3 sm:grid-cols-3">
        {FIRST_ACTIONS.map(({ to, icon: Icon, key }) => (
          <li key={key}>
            <Link
              to={to}
              className={cn(
                CARD,
                'flex h-full flex-col gap-2 p-4 hover:border-muted-foreground/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              )}
            >
              <Icon aria-hidden="true" className="size-5 text-muted-foreground" />
              <span className="text-sm font-semibold">{t(`home.first.${key}`)}</span>
              <span className="text-xs text-muted-foreground">{t(`home.first.${key}Hint`)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
