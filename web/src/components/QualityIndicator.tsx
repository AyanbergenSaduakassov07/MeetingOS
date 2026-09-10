import { AlertTriangle, CheckCircle2, CircleHelp, ShieldAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import type { ExtractionQuality } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * Aggregate extraction quality. Display only — every number here was computed
 * by the verifier; this surfaces them.
 *
 * Deliberately not a single score. A "92% quality" badge is the kind of number
 * that gets glanced at and trusted, and it would bury the two counts that
 * actually need a person's attention: claims the verifier could not support,
 * and claims it never checked. Those get their own rows and their own colour.
 */
export function QualityIndicator({ quality }: { quality: ExtractionQuality }) {
  const { t } = useTranslation();
  const query = new URLSearchParams(quality.link.query).toString();
  const to = query ? `${quality.link.path}?${query}` : quality.link.path;

  const needsAttention = quality.low_confidence + quality.unsupported;
  const rows = [
    { key: 'verified', value: quality.verified, icon: CheckCircle2, tone: 'text-good' },
    { key: 'lowConfidence', value: quality.low_confidence, icon: AlertTriangle, tone: 'text-warn' },
    { key: 'unsupported', value: quality.unsupported, icon: ShieldAlert, tone: 'text-destructive' },
    {
      key: 'unverified',
      value: quality.unverified,
      icon: CircleHelp,
      tone: 'text-muted-foreground',
    },
  ];

  return (
    <section
      data-testid="quality-indicator"
      data-total={quality.total_items}
      data-needs-attention={needsAttention}
      className="rounded-lg border border-border bg-card p-4"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-display text-sm font-bold">{t('quality.title')}</h2>
        <Link
          to={to}
          className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t('quality.reviewAll')}
        </Link>
      </div>

      {quality.total_items === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">{t('quality.nothingExtracted')}</p>
      ) : (
        <>
          <p className="mt-2 font-mono text-3xl font-bold tabular-nums">
            {quality.verified_rate === null ? '—' : `${Math.round(quality.verified_rate * 100)}%`}
            <span className="ml-2 font-sans text-sm font-normal text-muted-foreground">
              {t('quality.verifiedOf', { total: quality.total_items })}
            </span>
          </p>

          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
            {rows.map(({ key, value, icon: Icon, tone }) => (
              <div key={key} className="flex items-center gap-2 text-sm">
                <Icon aria-hidden="true" className={cn('size-4 shrink-0', tone)} />
                <dt className="flex-1 text-muted-foreground">{t(`status.${key}`)}</dt>
                <dd className={cn('font-mono tabular-nums', value > 0 && tone)}>{value}</dd>
              </div>
            ))}
          </dl>

          {/* Stated plainly rather than folded into the percentage above. */}
          {quality.has_unverified && (
            <p className="mt-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
              {t('quality.unverifiedNotice')}
            </p>
          )}
          {needsAttention > 0 && (
            <p
              data-testid="quality-warning"
              className="mt-2 rounded-md bg-warn-tint px-3 py-2 text-xs font-medium text-warn"
            >
              {t('quality.needsReview', { count: needsAttention })}
            </p>
          )}
        </>
      )}
    </section>
  );
}
