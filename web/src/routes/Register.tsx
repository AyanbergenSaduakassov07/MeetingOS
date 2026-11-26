import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { ItemCard, type ItemKind } from '@/components/ItemCard';
import type { ExtractedItem, MeetingIntelligence } from '@/lib/api';
import { useOrgIntelligence } from '@/lib/register';
import { cn } from '@/lib/utils';

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
        <p role="alert" className="mt-8 text-sm text-destructive">
          {t('register.loadFailed')}
        </p>
      )}
      {org.failedCount > 0 && (
        <p role="alert" className="mt-4 text-sm text-warn">
          {t('register.partial', { count: org.failedCount })}
        </p>
      )}

      {org.isLoading ? (
        <p className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          {t('common.loading')}
        </p>
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
