import { AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { CitationTime } from '@/components/CitationTime';
import type { CommitmentItem } from '@/lib/api';
import { cn } from '@/lib/utils';

function FollowUpRow({ item }: { item: CommitmentItem }) {
  const { t, i18n } = useTranslation();
  return (
    <li
      data-testid="commitment-row"
      data-overdue={item.overdue}
      data-kind={item.kind}
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
      <p className="mt-2 break-words text-sm font-medium">{item.text}</p>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <dl className="flex flex-wrap gap-x-4">
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
                {new Date(item.due_date).toLocaleDateString(i18n.language)}
              </dd>
            </div>
          )}
        </dl>
        {item.meeting_title && item.meeting_id && (
          <Link
            to={`/meetings/${encodeURIComponent(item.meeting_id)}`}
            className="break-words text-link underline-offset-2 hover:underline"
          >
            {item.meeting_title}
          </Link>
        )}
      </div>
    </li>
  );
}

export function FollowUpList({ items }: { items: CommitmentItem[] }) {
  const { t } = useTranslation();
  if (!items.length) {
    return (
      <p className="mt-3 rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        {t('commitments.empty')}
      </p>
    );
  }
  return (
    <ul className="mt-3 space-y-2" data-testid="commitment-list">
      {items.map((item) => (
        <FollowUpRow key={item.id} item={item} />
      ))}
    </ul>
  );
}
