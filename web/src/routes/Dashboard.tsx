import { useQuery } from '@tanstack/react-query';
import { AlertCircle, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { QualityIndicator } from '@/components/QualityIndicator';
import { StatCard } from '@/components/StatCard';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

const SEVERITY_TONE: Record<string, string> = {
  critical: 'bg-destructive/10 text-destructive',
  high: 'bg-destructive/10 text-destructive',
  medium: 'bg-warn-tint text-warn',
  low: 'bg-muted text-muted-foreground',
};

export function Dashboard() {
  const { t } = useTranslation();
  const dashboard = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.getDashboard(),
  });

  if (dashboard.isLoading) {
    return (
      <output className="mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-lg border border-border bg-card p-8 text-center">
        <Loader2 aria-hidden="true" className="size-6 animate-spin text-muted-foreground" />
        <h2 className="font-display text-lg font-bold">{t('common.loading')}</h2>
      </output>
    );
  }

  if (dashboard.isError || !dashboard.data) {
    return (
      <output
        data-testid="dashboard-error"
        className="mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-lg border border-border bg-card p-8 text-center"
      >
        <AlertCircle aria-hidden="true" className="size-6 text-destructive" />
        <h2 className="font-display text-lg font-bold">{t('dashboard.loadFailed')}</h2>
        <p className="text-sm text-muted-foreground">
          {dashboard.error instanceof Error ? dashboard.error.message : ''}
        </p>
      </output>
    );
  }

  const data = dashboard.data;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8" data-testid="dashboard">
      <header>
        <h1 className="font-display text-3xl font-black tracking-tight">{t('dashboard.title')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('dashboard.period', { days: data.period_days, meetings: data.meetings_in_period })}
        </p>
      </header>

      <section className="mt-6" aria-labelledby="decisions-heading">
        <h2 id="decisions-heading" className="sr-only">
          {t('dashboard.decisionsHeading')}
        </h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatCard stat={data.decisions_approved} testId="stat-approved" />
          <StatCard stat={data.decisions_pending} testId="stat-pending" />
          <StatCard stat={data.decisions_reversed} testId="stat-reversed" />
          <StatCard stat={data.overdue_commitments} testId="stat-overdue" />
          <StatCard stat={data.open_risks} testId="stat-risks" />
        </div>
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-[2fr_1fr]">
        <section aria-labelledby="risks-heading">
          <h2 id="risks-heading" className="font-display text-sm font-bold">
            {t('dashboard.topRisks')}
          </h2>
          {data.top_risks.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">{t('dashboard.noRisks')}</p>
          ) : (
            <ul className="mt-2 space-y-2" data-testid="top-risks">
              {data.top_risks.map((risk) => (
                <li
                  key={risk.id}
                  className="flex items-start gap-3 rounded-lg border border-border bg-card p-3"
                >
                  <span
                    className={cn(
                      'shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold',
                      SEVERITY_TONE[risk.severity ?? 'low'] ?? SEVERITY_TONE.low,
                    )}
                  >
                    {t(`severity.${risk.severity ?? 'low'}`, risk.severity ?? '')}
                  </span>
                  <div className="min-w-0 flex-1">
                    {/* Risk title is meeting content — never translated. */}
                    <p className="text-sm font-medium">{risk.title}</p>
                    {risk.meeting_id && (
                      <Link
                        to={`/meetings/${risk.meeting_id}`}
                        className="mt-0.5 inline-block text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                      >
                        {risk.meeting_title}
                      </Link>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          <h2 className="mt-6 font-display text-sm font-bold">{t('dashboard.mostActive')}</h2>
          {data.most_active_people.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">{t('dashboard.noActivity')}</p>
          ) : (
            <ul className="mt-2 space-y-2" data-testid="active-people">
              {data.most_active_people.map((person) => (
                <li key={person.person_id}>
                  <Link
                    to={person.link.path}
                    data-testid="person-row"
                    className="flex min-h-14 items-center gap-4 rounded-lg border border-border bg-card px-4 py-2 transition-colors hover:border-muted-foreground/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">
                      {person.name}
                    </span>
                    <dl className="flex shrink-0 gap-4 font-mono text-xs tabular-nums text-muted-foreground">
                      <div className="flex gap-1">
                        <dt>{t('dashboard.meetingsShort')}</dt>
                        <dd>{person.meetings}</dd>
                      </div>
                      <div className="flex gap-1">
                        <dt>{t('dashboard.decisionsShort')}</dt>
                        <dd>{person.decisions}</dd>
                      </div>
                      <div className="flex gap-1">
                        <dt>{t('dashboard.commitmentsShort')}</dt>
                        <dd>{person.commitments}</dd>
                      </div>
                    </dl>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <QualityIndicator quality={data.extraction_quality} />
      </div>
    </div>
  );
}
