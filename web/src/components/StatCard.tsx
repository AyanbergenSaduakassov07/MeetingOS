import { ArrowUpRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Stat } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * One dashboard figure, and the way to the rows behind it.
 *
 * The whole card is the link, not a separate "view" affordance: a number a
 * reader cannot get behind is a number they have to take on faith, and the
 * point of this product is to stop people doing that. `data-value` carries the
 * count so a test can compare it against a direct API query without parsing
 * rendered text.
 */
const TONE_STYLES: Record<Stat['tone'], string> = {
  neutral: 'text-foreground',
  good: 'text-good',
  warn: 'text-warn',
  destructive: 'text-destructive',
};

export function StatCard({
  stat,
  label,
  testId,
}: {
  stat: Stat;
  /** Translated label; the server's English one is the fallback. */
  label?: string;
  testId?: string;
}) {
  const query = new URLSearchParams(stat.link.query).toString();
  const to = query ? `${stat.link.path}?${query}` : stat.link.path;

  return (
    <Link
      to={to}
      data-testid={testId}
      data-value={stat.value}
      data-link={to}
      className={cn(
        'group flex min-h-28 flex-col justify-between rounded-lg border border-border bg-card p-4',
        'transition-colors duration-150 hover:border-muted-foreground/40',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm text-muted-foreground">{label ?? stat.label}</span>
        <ArrowUpRight
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
        />
      </div>
      <span
        className={cn(
          'font-display text-4xl font-black tabular-nums leading-none',
          TONE_STYLES[stat.tone],
        )}
      >
        {stat.value}
      </span>
    </Link>
  );
}
