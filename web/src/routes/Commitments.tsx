import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { CitationTime } from '@/components/CitationTime';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * The rows behind the dashboard's commitment counters.
 *
 * Filters come from the query string, which is what makes the dashboard link
 * reproduce its own number: `/commitments?overdue=true` returns exactly the
 * rows that stat counted. If the two ever disagree, the bug is visible.
 */
export function Commitments() {
  const { t } = useTranslation();
  const [params] = useSearchParams();

  const filters: Record<string, string> = {};
  for (const key of ['overdue', 'owner', 'status', 'kind'] as const) {
    const value = params.get(key);
    if (value) filters[key] = value;
  }

  const commitments = useQuery({
    queryKey: ['commitments', filters],
    queryFn: () => api.listCommitments(filters),
  });

  const overdueOnly = filters.overdue === 'true';

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-display text-3xl font-black tracking-tight">
          {overdueOnly ? t('commitments.overdueTitle') : t('commitments.title')}
        </h1>
        <Link
          to="/dashboard"
          className="text-sm text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        >
          {t('commitments.backToDashboard')}
        </Link>
      </header>

      {commitments.isLoading && (
        <p className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          {t('common.loading')}
        </p>
      )}

      {commitments.isError && (
        <p role="alert" className="mt-8 text-sm text-destructive">
          {t('commitments.loadFailed')}
        </p>
      )}

      {commitments.data && (
        <>
          <p
            className="mt-2 text-sm text-muted-foreground"
            data-testid="commitments-total"
            data-value={commitments.data.total}
          >
            {t('commitments.count', { count: commitments.data.total })}
          </p>

          {commitments.data.items.length === 0 ? (
            <p className="mt-8 rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              {t('commitments.empty')}
            </p>
          ) : (
            <ul className="mt-4 space-y-2" data-testid="commitment-list">
              {commitments.data.items.map((item) => (
                <li
                  key={item.id}
                  data-testid="commitment-row"
                  data-overdue={item.overdue}
                  className="rounded-lg border border-border bg-card p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
                      {t(`commitments.kind_${item.kind}`, item.kind)}
                    </span>
                    {item.overdue && (
                      <span
                        className="inline-flex items-center gap-1.5 rounded-full bg-destructive/10 px-2.5 py-0.5 text-xs font-semibold text-destructive"
                        data-testid="overdue-badge"
                      >
                        <AlertTriangle aria-hidden="true" className="size-3.5" />
                        {t('commitments.overdueBy', { days: item.days_overdue ?? 0 })}
                      </span>
                    )}
                    {item.start_ms !== null && item.meeting_id && (
                      <CitationTime ms={item.start_ms} className="ml-auto" />
                    )}
                  </div>

                  {/* Commitment text is meeting content — never translated. */}
                  <p className="mt-2 text-sm font-medium">{item.text}</p>

                  <dl className="mt-1 flex flex-wrap gap-x-4 text-xs text-muted-foreground">
                    <div className="flex gap-1">
                      <dt>{t('intelligence.assignee')}:</dt>
                      <dd className={cn(!item.owner_name && 'italic')}>
                        {item.owner_name ?? t('intelligence.unassigned')}
                      </dd>
                    </div>
                    {item.due_date && (
                      <div className="flex gap-1">
                        <dt>{t('intelligence.due')}:</dt>
                        <dd className="font-mono tabular-nums">
                          {new Date(item.due_date).toLocaleDateString()}
                        </dd>
                      </div>
                    )}
                    {item.meeting_title && item.meeting_id && (
                      <Link
                        to={`/meetings/${item.meeting_id}`}
                        className="underline-offset-2 hover:text-foreground hover:underline"
                      >
                        {item.meeting_title}
                      </Link>
                    )}
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
