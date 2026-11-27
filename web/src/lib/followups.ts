import type { CommitmentItem } from '@/lib/api';

const OPEN_STATUSES = {
  commitment: ['pending'],
  action_item: ['open', 'in_progress', 'blocked'],
};

export function completionRate(items: CommitmentItem[]): number | null {
  let settled = 0;
  let completed = 0;
  for (const { kind, status } of items) {
    if (kind !== 'commitment' && kind !== 'action_item') continue;
    if (OPEN_STATUSES[kind].includes(status)) continue;
    settled++;
    if (status === (kind === 'commitment' ? 'kept' : 'done')) completed++;
  }
  return settled ? completed / settled : null;
}

export function formatCompletionRate(rate: number | null, language: string): string {
  return rate === null ? '—' : new Intl.NumberFormat(language, { style: 'percent' }).format(rate);
}
