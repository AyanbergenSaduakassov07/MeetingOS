import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import { ErrorNotice } from '@/components/ErrorNotice';
import { FollowUpList } from '@/components/FollowUpList';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { api, type CommitmentItem } from '@/lib/api';
import { completionRate, formatCompletionRate } from '@/lib/followups';

const KINDS = ['all', 'commitment', 'action_item'] as const;
const VIEWS = ['all', 'overdue', 'mine', 'person'] as const;
const MINE_KEY = 'meetingos:followups:mine';
const LIST_LIMIT = '500';

function getView(params: URLSearchParams) {
  if (params.get('overdue') === 'true') return 'overdue';
  if (params.get('view') === 'mine') return 'mine';
  if (params.get('view') === 'person' || params.has('owner')) return 'person';
  return 'all';
}

function readMine() {
  try {
    return localStorage.getItem(MINE_KEY) ?? '';
  } catch {
    return '';
  }
}

function useMine() {
  const [mine, setMine] = useState(readMine);
  return [
    mine,
    (id: string) => {
      setMine(id);
      try {
        localStorage.setItem(MINE_KEY, id);
      } catch {
        // The selection stays usable for this visit.
      }
    },
  ] as const;
}

function PersonPicker({
  owner,
  mine,
  onChange,
}: {
  owner: string;
  mine: boolean;
  onChange: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const pickerId = useId();
  const filters = { limit: LIST_LIMIT };
  const directory = useQuery({
    queryKey: ['commitments', filters],
    queryFn: () => api.listCommitments(filters),
  });
  const people = new Map<string, string>();
  for (const item of directory.data?.items ?? []) {
    if (item.owner_id) people.set(item.owner_id, item.owner_name || item.owner_id);
  }
  if (owner && !people.has(owner)) people.set(owner, owner);
  const options = [...people].sort((a, b) => a[1].localeCompare(b[1], i18n.language));

  return (
    <div className="mb-5 w-full max-w-xs">
      <label htmlFor={pickerId} className="text-sm font-medium">
        {mine ? t('followups.yourPerson') : t('followups.person')}
      </label>
      <select
        id={pickerId}
        className="mt-1 block h-10 w-full rounded-md border border-input bg-card px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        value={owner}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{t('followups.choosePerson')}</option>
        {options.map(([id, name]) => (
          <option key={id} value={id}>
            {name}
          </option>
        ))}
      </select>
      {directory.isError && (
        <p role="alert" className="mt-1 text-sm text-destructive">
          {t('followups.peopleFailed')}
        </p>
      )}
    </div>
  );
}

function RegisterResults({ items, total }: { items: CommitmentItem[]; total: number }) {
  const { t, i18n } = useTranslation();
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm text-muted-foreground">
        <p data-testid="commitments-total" data-value={total}>
          {t('commitments.count', { count: total })}
        </p>
        <dl className="flex items-baseline gap-2">
          <dt>{t('followups.completionRate')}</dt>
          <dd
            className="font-mono font-medium tabular-nums text-foreground"
            data-testid="followups-completion-rate"
          >
            {formatCompletionRate(completionRate(items), i18n.language)}
          </dd>
        </dl>
      </div>
      <FollowUpList items={items} />
    </>
  );
}

function useFollowUps() {
  const [params, setParams] = useSearchParams();
  const [mine, setMine] = useMine();
  const view = getView(params);
  const kind = params.get('kind') ?? 'all';
  const personView = view === 'person' || view === 'mine';
  const owner = view === 'mine' ? mine : (params.get('owner') ?? '');
  const filters = Object.fromEntries(
    ['overdue', 'status', 'kind'].flatMap((key) => {
      const value = params.get(key);
      return value ? [[key, value]] : [];
    }),
  );
  filters.limit = LIST_LIMIT;
  if (owner) filters.owner = owner;

  const results = useQuery({
    queryKey: ['commitments', filters],
    queryFn: () => api.listCommitments(filters),
    enabled: !personView || Boolean(owner),
  });

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  }

  function setView(nextView: string) {
    const next = new URLSearchParams(params);
    for (const key of ['view', 'overdue', 'owner']) next.delete(key);
    if (nextView === 'overdue') next.set('overdue', 'true');
    if (nextView === 'mine' || nextView === 'person') next.set('view', nextView);
    setParams(next);
  }

  return { view, kind, personView, owner, results, setFilter, setView, setMine };
}

export function Commitments() {
  const { t } = useTranslation();
  const { view, kind, personView, owner, results, setFilter, setView, setMine } = useFollowUps();

  return (
    <div className="mx-auto max-w-4xl px-4 pb-8 pt-14 md:px-6 md:pt-8">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h1 className="font-display text-3xl font-semibold tracking-tight">
          {t('followups.title')}
        </h1>
        <Link to="/dashboard" className="text-sm text-link underline-offset-2 hover:underline">
          {t('commitments.backToDashboard')}
        </Link>
      </header>

      <fieldset className="mt-5 flex min-w-0 flex-wrap gap-1">
        <legend className="sr-only">{t('followups.kind')}</legend>
        {KINDS.map((value) => (
          <Button
            key={value}
            type="button"
            variant="ghost"
            size="sm"
            aria-pressed={kind === value}
            className="rounded-md border border-transparent text-muted-foreground aria-pressed:border-border aria-pressed:bg-accent aria-pressed:text-accent-foreground"
            onClick={() => setFilter('kind', value === 'all' ? '' : value)}
          >
            {t(`followups.kinds.${value}`)}
          </Button>
        ))}
      </fieldset>

      <Tabs value={view} onValueChange={setView} className="mt-4">
        <TabsList
          aria-label={t('followups.views')}
          className="h-auto w-full flex-wrap justify-start gap-1 rounded-none border-b border-border bg-transparent px-0 pb-2"
        >
          {VIEWS.map((value) => (
            <TabsTrigger
              key={value}
              value={value}
              className="rounded-md px-2.5 data-[state=active]:bg-accent data-[state=active]:text-accent-foreground data-[state=active]:shadow-none"
            >
              {t(`followups.tabs.${value}`)}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value={view} className="mt-4">
          {personView && (
            <PersonPicker
              owner={owner}
              mine={view === 'mine'}
              onChange={view === 'mine' ? setMine : (id) => setFilter('owner', id)}
            />
          )}
          {results.isLoading && (
            <output className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 aria-hidden="true" className="size-4 animate-spin" />
              {t('common.loading')}
            </output>
          )}
          {results.isError && (
            <ErrorNotice
              message={t('followups.loadFailed')}
              error={results.error}
              onRetry={() => void results.refetch()}
            />
          )}
          {results.data && (!personView || owner) && (
            <RegisterResults items={results.data.items} total={results.data.total} />
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
