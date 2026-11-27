import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { FollowUpList } from '@/components/FollowUpList';
import { api, type PersonCommitments } from '@/lib/api';
import { formatCompletionRate } from '@/lib/followups';

function PersonMetric({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3 sm:p-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="mt-2 font-mono text-2xl font-medium tabular-nums" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

function PersonActivity({ personId }: { personId: string }) {
  const { t, i18n } = useTranslation();
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: () => api.getDashboard() });
  const activity = dashboard.data?.most_active_people.find(
    (person) => person.person_id === personId,
  );
  const number = new Intl.NumberFormat(i18n.language);
  return (
    <section className="mt-6" aria-labelledby="person-activity">
      <h2 className="font-display text-lg font-semibold" id="person-activity">
        {t('person.activity')}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {dashboard.isLoading
          ? t('common.loading')
          : activity && dashboard.data
            ? t('person.activityPeriod', { count: dashboard.data.period_days })
            : t('person.activityUnavailable')}
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-2 sm:gap-3">
        <PersonMetric
          label={t('person.meetings')}
          testId="person-meetings"
          value={activity ? number.format(activity.meetings) : '—'}
        />
        <PersonMetric
          label={t('person.decisions')}
          testId="person-decisions"
          value={activity ? number.format(activity.decisions) : '—'}
        />
      </dl>
    </section>
  );
}

function PersonFollowUps({ history }: { history: PersonCommitments }) {
  const { t, i18n } = useTranslation();
  const overdue = history.items.filter((item) => item.overdue);
  const other = history.items.filter((item) => !item.overdue);
  return (
    <section className="mt-6" aria-labelledby="person-followups">
      <h2 className="font-display text-lg font-semibold" id="person-followups">
        {t('person.followups')}
      </h2>
      <p
        className="mt-1 text-sm text-muted-foreground"
        data-testid="commitments-total"
        data-value={history.total}
      >
        {t('commitments.count', { count: history.total })}
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-2 sm:gap-3">
        <PersonMetric
          label={t('followups.completionRate')}
          testId="person-completion-rate"
          value={formatCompletionRate(history.completion_rate, i18n.language)}
        />
        <PersonMetric
          label={t('person.overdue')}
          testId="person-overdue"
          value={new Intl.NumberFormat(i18n.language).format(history.overdue)}
        />
      </dl>
      {overdue.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold">{t('person.overdue')}</h3>
          <FollowUpList items={overdue} />
        </div>
      )}
      {(other.length > 0 || overdue.length === 0) && (
        <div className="mt-4">
          {overdue.length > 0 && (
            <h3 className="text-sm font-semibold">{t('person.otherFollowups')}</h3>
          )}
          <FollowUpList items={other} />
        </div>
      )}
    </section>
  );
}

export function PersonRecord() {
  const { t } = useTranslation();
  const { personId = '' } = useParams();
  const history = useQuery({
    queryKey: ['person-commitments', personId],
    queryFn: () => api.getPersonCommitments(personId),
  });
  const person = history.data;
  const name = person && (person.person_name || person.person_email || personId);

  return (
    <div className="mx-auto max-w-4xl px-4 pb-8 pt-14 md:px-6 md:pt-8">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h1 className="break-words font-display text-3xl font-semibold tracking-tight">
          {name || t('person.title')}
        </h1>
        <Link to="/dashboard" className="text-sm text-link underline-offset-2 hover:underline">
          {t('commitments.backToDashboard')}
        </Link>
      </header>
      {history.isLoading && (
        <output className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          {t('common.loading')}
        </output>
      )}
      {history.isError && (
        <p role="alert" className="mt-6 text-sm text-destructive">
          {t('person.loadFailed')}
        </p>
      )}
      {person && (
        <>
          <PersonActivity personId={person.person_id} />
          <PersonFollowUps history={person} />
        </>
      )}
    </div>
  );
}
