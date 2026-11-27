import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { ErrorNotice } from '@/components/ErrorNotice';
import { ItemCard, type ItemKind } from '@/components/ItemCard';
import { Skeleton } from '@/components/ui/skeleton';
import type { ExtractedItem, MeetingIntelligence, MeetingSummary } from '@/lib/api';
import { formatTimestamp } from '@/lib/playback';
import { useOrgIntelligence } from '@/lib/register';
import { cn } from '@/lib/utils';
import { StatusChip } from './DecisionRecord';

export type RegisterKind = 'decisions' | 'risks' | 'quality';

interface Row {
  item: ExtractedItem;
  kind: ItemKind;
}

const CLOSED_RISK = new Set(['closed', 'mitigated']);
const VERIFICATION_STATES = ['verified', 'low_confidence', 'unsupported', 'unverified'] as const;

function allItems(data: MeetingIntelligence): Row[] {
  return [
    ...data.decisions.map((item) => ({ item, kind: 'decision' as const })),
    ...data.action_items.map((item) => ({ item, kind: 'action' as const })),
    ...data.risks.map((item) => ({ item, kind: 'risk' as const })),
    ...data.commitments.map((item) => ({ item, kind: 'commitment' as const })),
  ];
}

/**
 * Rows for one register, filtered exactly as the dashboard counter that
 * links here: decisions by `status` (comma list), risks open only, quality
 * by `verification`.
 */
function selectRows(kind: RegisterKind, data: MeetingIntelligence, params: URLSearchParams): Row[] {
  if (kind === 'decisions') {
    const statuses = params.get('status')?.split(',').filter(Boolean);
    return data.decisions
      .filter((item) => !statuses || statuses.includes(item.status ?? ''))
      .map((item) => ({ item, kind: 'decision' }));
  }
  if (kind === 'risks') {
    return data.risks
      .filter((item) => !CLOSED_RISK.has(item.status ?? 'open'))
      .map((item) => ({ item, kind: 'risk' }));
  }
  const verification = params.get('verification');
  return allItems(data).filter(
    ({ item }) => !verification || item.verification_status === verification,
  );
}

function QualityFilter({ params }: { params: URLSearchParams }) {
  const { t } = useTranslation();
  const active = params.get('verification');
  const hrefFor = (value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set('verification', value);
    else next.delete('verification');
    return `?${next}`;
  };
  const options = [
    { value: null, label: t('register.all') },
    ...VERIFICATION_STATES.map((value) => ({
      value,
      label: t(`status.${value === 'low_confidence' ? 'lowConfidence' : value}`),
    })),
  ];

  return (
    <nav aria-label={t('register.quality')} className="mt-4 flex flex-wrap gap-2">
      {options.map(({ value, label }) => (
        <Link
          key={value ?? 'all'}
          to={hrefFor(value)}
          aria-current={active === value ? 'page' : undefined}
          className={cn(
            'rounded-full border px-3 py-1 text-xs font-medium',
            active === value
              ? 'border-foreground bg-foreground text-background'
              : 'border-border text-muted-foreground hover:text-foreground',
          )}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}

const SEVERITY_STRIPE: Record<string, string> = {
  critical: 'border-l-destructive',
  high: 'border-l-destructive',
  medium: 'border-l-warn',
  low: 'border-l-border',
};

type Group = { meeting: MeetingSummary; rows: Row[] };

/** Decisions and risks read as a register table: one row per item, linked to its record or meeting. */
function RegisterTable({ kind, groups }: { kind: 'decisions' | 'risks'; groups: Group[] }) {
  const { t } = useTranslation();
  const th = 'px-3 py-2 text-left font-mono text-[10.5px] font-medium uppercase tracking-wider';
  return (
    <div className="mt-6 overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm" data-testid="register-table">
        <thead className="sticky top-0 bg-muted text-muted-foreground">
          <tr>
            {kind === 'risks' && <th className={th}>{t('register.severity')}</th>}
            <th className={th}>{t(kind === 'risks' ? 'register.risk' : 'register.decision')}</th>
            {kind === 'decisions' && <th className={th}>{t('register.status')}</th>}
            <th className={th}>{t('register.raisedIn')}</th>
            {kind === 'risks' && <th className={th}>{t('register.status')}</th>}
          </tr>
        </thead>
        <tbody>
          {groups.flatMap(({ meeting, rows }) =>
            rows.map(({ item }) => (
              <tr
                key={item.id}
                data-testid="register-row"
                className="border-t border-border align-top"
              >
                {kind === 'risks' && (
                  <td
                    className={cn(
                      'border-l-4 px-3 py-2.5 text-xs font-medium',
                      SEVERITY_STRIPE[item.severity ?? ''] ?? 'border-l-border',
                    )}
                  >
                    {t(`register.sev.${item.severity ?? 'unknown'}`, item.severity ?? '—')}
                  </td>
                )}
                <td className="px-3 py-2.5">
                  {kind === 'decisions' ? (
                    <Link
                      to={`/decisions/${item.id}`}
                      className="font-medium text-link hover:underline"
                    >
                      {item.title}
                    </Link>
                  ) : (
                    <span className="font-medium">{item.title}</span>
                  )}
                  {item.supersedes_id && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      {t('status.revisited')}
                    </span>
                  )}
                </td>
                {kind === 'decisions' && (
                  <td className="px-3 py-2.5">
                    <StatusChip value={item.status ?? 'proposed'} />
                  </td>
                )}
                <td className="px-3 py-2.5 text-xs text-muted-foreground">
                  <Link to={`/meetings/${meeting.id}`} className="text-link hover:underline">
                    {meeting.title}
                  </Link>
                  {item.source_start_ms != null && (
                    <span className="ml-1.5 font-mono">
                      {formatTimestamp(item.source_start_ms)}
                    </span>
                  )}
                </td>
                {kind === 'risks' && (
                  <td className="px-3 py-2.5 text-xs">
                    {t(`decisionRecord.state.${item.status ?? 'open'}`, item.status ?? 'open')}
                  </td>
                )}
              </tr>
            )),
          )}
        </tbody>
      </table>
    </div>
  );
}

/** Cross-meeting list behind a dashboard counter. */
export function Register({ kind }: { kind: RegisterKind }) {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const periodParam = Number(params.get('period_days'));
  const periodDays = Number.isFinite(periodParam) && periodParam > 0 ? periodParam : null;
  const org = useOrgIntelligence(periodDays);

  const groups = org.intelligence
    .map(({ meeting, data }) => ({ meeting, rows: selectRows(kind, data, params) }))
    .filter((group) => group.rows.length > 0);
  const total = groups.reduce((sum, group) => sum + group.rows.length, 0);

  return (
    <div className="mx-auto max-w-4xl px-6 py-8" data-testid={`register-${kind}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-display text-3xl font-semibold tracking-tight">
          {t(`register.${kind}`)}
        </h1>
        <Link
          to="/dashboard"
          className="text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          {t('commitments.backToDashboard')}
        </Link>
      </header>
      <p className="mt-1 text-sm text-muted-foreground">
        {periodDays ? t('register.period', { days: periodDays }) : t('register.allTime')}
      </p>

      {kind === 'quality' && <QualityFilter params={params} />}

      {org.isError && (
        <ErrorNotice className="mt-8" message={t('register.loadFailed')} onRetry={org.retry} />
      )}
      {org.failedCount > 0 && (
        <p role="alert" className="mt-4 text-sm text-warn">
          {t('register.partial', { count: org.failedCount })}
        </p>
      )}

      {org.isLoading ? (
        <div aria-busy="true" className="mt-6 space-y-2">
          <span className="sr-only">{t('common.loading')}</span>
          <Skeleton className="h-4 w-28" />
          {[1, 2, 3].map((row) => (
            <Skeleton key={row} className={kind === 'quality' ? 'h-24' : 'h-10'} />
          ))}
        </div>
      ) : (
        !org.isError && (
          <>
            <p className="mt-4 text-sm" data-testid="register-total" data-value={total}>
              {t('register.count', { count: total })}
            </p>
            {total === 0 ? (
              <p className="mt-6 rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                {t('register.empty')}
              </p>
            ) : kind !== 'quality' ? (
              <RegisterTable kind={kind} groups={groups} />
            ) : (
              groups.map(({ meeting, rows }) => (
                <section key={meeting.id} className="mt-6">
                  <h2 className="mb-2 text-sm font-semibold">
                    <Link to={`/meetings/${meeting.id}`} className="hover:underline">
                      {meeting.title}
                    </Link>
                  </h2>
                  <div className="space-y-3">
                    {rows.map(({ item, kind: itemKind }) => (
                      <ItemCard key={item.id} item={item} kind={itemKind} />
                    ))}
                  </div>
                </section>
              ))
            )}
          </>
        )
      )}
    </div>
  );
}
