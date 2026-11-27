import { useMutation, useQuery } from '@tanstack/react-query';
import { type FormEvent, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { ApiError, api, type BriefItemOut, type BriefOut } from '@/lib/api';
import { formatTimestamp } from '@/lib/playback';

const SECTIONS = ['open_commitments', 'unresolved_decisions', 'recent_changes'] as const;

function BriefRow({ item }: { item: BriefItemOut }) {
  const { t, i18n } = useTranslation();
  return (
    <li className="space-y-1 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {item.overdue && (
          <span className="rounded-md bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
            {t('brief.overdue')}
          </span>
        )}
        <p className="break-words text-sm font-medium">{item.text}</p>
      </div>
      {item.detail && <p className="break-words text-sm text-muted-foreground">{item.detail}</p>}
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {item.owner_name && <span>{item.owner_name}</span>}
        {item.due_date && (
          <time dateTime={item.due_date}>
            {t('brief.due', {
              date: new Date(item.due_date).toLocaleDateString(i18n.language, {
                dateStyle: 'medium',
                timeZone: 'UTC',
              }),
            })}
          </time>
        )}
        {item.meeting_id ? (
          <span className="break-words">
            <Link
              to={`/meetings/${encodeURIComponent(item.meeting_id)}`}
              className="text-link underline-offset-2 hover:underline"
            >
              {item.meeting_title ?? item.meeting_id}
            </Link>
            {item.start_ms != null && (
              <span className="ml-1.5 font-mono">{formatTimestamp(item.start_ms)}</span>
            )}
          </span>
        ) : (
          <span>{t('brief.sourceUnavailable')}</span>
        )}
      </div>
    </li>
  );
}

function BriefResult({ brief }: { brief: BriefOut }) {
  const { t } = useTranslation();
  const context = [brief.project, ...brief.attendee_names].filter(Boolean).join(' · ');

  return (
    <section
      data-testid="brief-result"
      aria-labelledby="brief-result-heading"
      className="space-y-4"
    >
      <div>
        <h2 id="brief-result-heading" className="text-xl font-semibold">
          {t('brief.result')}
        </h2>
        {context && <p className="mt-1 break-words text-sm text-muted-foreground">{context}</p>}
      </div>
      {brief.summary && <p className="whitespace-pre-wrap break-words text-sm">{brief.summary}</p>}
      {SECTIONS.map((section) => (
        <section
          key={section}
          aria-labelledby={`brief-${section}`}
          data-testid="brief-section"
          className="rounded-lg border border-border bg-card"
        >
          <h3 id={`brief-${section}`} className="border-b border-border px-4 py-3 font-semibold">
            {t(`brief.sections.${section}.title`)}
          </h3>
          {brief[section].length > 0 ? (
            <ul className="divide-y divide-border">
              {brief[section].map((item) => (
                <BriefRow
                  key={`${item.kind}:${item.meeting_id}:${item.evidence_id}:${item.text}:${item.detail}:${item.owner_name}:${item.due_date}`}
                  item={item}
                />
              ))}
            </ul>
          ) : (
            <p className="px-4 py-3 text-sm text-muted-foreground">
              {t(`brief.sections.${section}.empty`)}
            </p>
          )}
        </section>
      ))}
    </section>
  );
}

function AttendeePicker({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const { t } = useTranslation();
  const pickerId = useId();
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: () => api.getDashboard() });
  const people = new Map(
    dashboard.data?.most_active_people.map(({ person_id, name }) => [person_id, name ?? person_id]),
  );
  for (const id of selected) {
    if (!people.has(id)) people.set(id, id);
  }

  return (
    <fieldset>
      <legend className="text-sm font-medium">{t('brief.attendees')}</legend>
      {dashboard.isPending && (
        <p className="mt-1 text-sm text-muted-foreground">{t('brief.peopleLoading')}</p>
      )}
      {dashboard.isError && (
        <p role="alert" className="mt-1 text-sm text-destructive">
          {t('brief.peopleFailed')}
        </p>
      )}
      {dashboard.isSuccess && people.size === 0 && (
        <p className="mt-1 text-sm text-muted-foreground">{t('brief.peopleEmpty')}</p>
      )}
      {people.size > 0 && (
        <div className="mt-1 grid sm:grid-cols-2">
          {[...people].map(([id, name]) => (
            <label
              key={id}
              htmlFor={`${pickerId}-${encodeURIComponent(id)}`}
              className="flex min-h-11 cursor-pointer items-center gap-2 px-3.5 text-sm"
            >
              <Checkbox
                id={`${pickerId}-${encodeURIComponent(id)}`}
                checked={selected.includes(id)}
                onCheckedChange={(checked) =>
                  onChange(checked ? [...selected, id] : selected.filter((person) => person !== id))
                }
              />
              <span className="min-w-0 break-words">{name}</span>
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

function BriefForm({ attendee }: { attendee: string }) {
  const { t } = useTranslation();
  const projectId = useId();
  const summaryId = useId();
  const [selected, setSelected] = useState(attendee ? [attendee] : []);
  const [project, setProject] = useState('');
  const [summarise, setSummarise] = useState(false);
  const brief = useMutation({ mutationFn: api.prepareBrief });
  const canPrepare = selected.length > 0 || project.trim().length > 0;
  const needsContext = brief.error instanceof ApiError && brief.error.status === 422;

  function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canPrepare || brief.isPending) return;
    brief.mutate({ attendee_ids: selected, project: project.trim() || null, summarise });
  }

  return (
    <>
      <form
        data-testid="brief-form"
        onSubmit={prepare}
        className="rounded-lg border border-border bg-card p-4 sm:p-5"
      >
        <fieldset disabled={brief.isPending} className="space-y-4">
          <AttendeePicker selected={selected} onChange={setSelected} />
          <label htmlFor={projectId} className="block space-y-1 text-sm font-medium">
            <span>{t('brief.project')}</span>
            <Input
              id={projectId}
              value={project}
              onChange={(event) => setProject(event.target.value)}
            />
          </label>
          <label
            htmlFor={summaryId}
            className="flex min-h-11 cursor-pointer items-center gap-2 px-3.5 text-sm"
          >
            <Checkbox id={summaryId} checked={summarise} onCheckedChange={setSummarise} />
            {t('brief.writeSummary')}
          </label>
          {brief.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {t(needsContext ? 'brief.contextRequired' : 'brief.prepareFailed')}
            </p>
          ) : !canPrepare ? (
            <p className="text-sm text-muted-foreground">{t('brief.contextRequired')}</p>
          ) : null}
          <Button type="submit" disabled={!canPrepare || brief.isPending} className="rounded-md">
            {t(brief.isPending ? 'brief.preparing' : 'brief.prepare')}
          </Button>
        </fieldset>
      </form>
      <div aria-live="polite">{brief.data && <BriefResult brief={brief.data} />}</div>
    </>
  );
}

export function PrepareBrief() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const attendee = params.get('attendee')?.trim() ?? '';

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-4 py-8 sm:px-6">
      <h1 className="font-display text-2xl font-semibold">{t('nav.prepareBrief')}</h1>
      <BriefForm key={attendee} attendee={attendee} />
    </div>
  );
}
