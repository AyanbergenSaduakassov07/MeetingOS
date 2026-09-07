import { AlertTriangle, CheckCircle2, CircleHelp, ListTodo, ShieldAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ExtractedItem } from '@/lib/api';
import { cn } from '@/lib/utils';
import { CitationTime } from './CitationTime';

export type ItemKind = 'decision' | 'action' | 'risk' | 'commitment';

/**
 * Chip colour by kind. Lime (--primary) is deliberately absent: it is the
 * brand signal, and a decision chip painted brand-lime would read as
 * "MeetingOS" rather than "settled".
 */
const KIND_STYLES: Record<ItemKind, { chip: string; icon: typeof CheckCircle2; labelKey: string }> =
  {
    decision: {
      chip: 'bg-good-tint text-good',
      icon: CheckCircle2,
      labelKey: 'intelligence.kindDecision',
    },
    action: { chip: 'bg-warn-tint text-warn', icon: ListTodo, labelKey: 'intelligence.kindAction' },
    risk: {
      chip: 'bg-destructive/10 text-destructive',
      icon: ShieldAlert,
      labelKey: 'intelligence.kindRisk',
    },
    commitment: {
      chip: 'bg-secondary text-secondary-foreground',
      icon: AlertTriangle,
      labelKey: 'intelligence.kindCommitment',
    },
  };

/**
 * Verification is the load-bearing signal on this card, so it never rides on
 * colour alone — each state pairs a tint with an icon and a word.
 */
const VERIFICATION_STYLES: Record<string, { badge: string; icon: typeof CheckCircle2 }> = {
  verified: { badge: 'bg-good-tint text-good', icon: CheckCircle2 },
  low_confidence: { badge: 'bg-warn-tint text-warn', icon: AlertTriangle },
  unsupported: { badge: 'bg-destructive/10 text-destructive', icon: ShieldAlert },
  unverified: { badge: 'bg-muted text-muted-foreground', icon: CircleHelp },
};

export function ItemCard({ item, kind }: { item: ExtractedItem; kind: ItemKind }) {
  const { t } = useTranslation();
  const kindStyle = KIND_STYLES[kind];
  const KindIcon = kindStyle.icon;

  const verification =
    VERIFICATION_STYLES[item.verification_status] ?? VERIFICATION_STYLES.unverified;
  const VerificationIcon = verification.icon;
  const verificationLabel = t(
    `status.${item.verification_status === 'low_confidence' ? 'lowConfidence' : item.verification_status}`,
    t('status.unverified'),
  );

  const confidence =
    item.extraction_confidence === null ? null : Math.round(item.extraction_confidence * 100);
  const verificationScore =
    item.verification_score === null ? null : Math.round(item.verification_score * 100);
  // A claim the verifier could not support, or never checked, gets a banner —
  // never a card that reads like every other one.
  const needsAttention =
    item.verification_status === 'low_confidence' || item.verification_status === 'unsupported';

  return (
    <article
      data-testid="item-card"
      data-kind={kind}
      data-verification={item.verification_status}
      className={cn(
        'rounded-lg border bg-card p-4 shadow-sm transition-colors duration-150',
        // The border is part of the signal: a reader scanning a long list must
        // be able to see which cards need attention without reading each chip.
        item.verification_status === 'unsupported'
          ? 'border-destructive/40 hover:border-destructive/60'
          : item.verification_status === 'low_confidence'
            ? 'border-warn/40 hover:border-warn/60'
            : 'border-border hover:border-muted-foreground/30',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
            kindStyle.chip,
          )}
        >
          <KindIcon aria-hidden="true" className="size-3.5" />
          {t(kindStyle.labelKey)}
        </span>

        <span
          title={t(
            `status.${item.verification_status === 'low_confidence' ? 'lowConfidenceHint' : `${item.verification_status}Hint`}`,
            '',
          )}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
            verification.badge,
          )}
        >
          <VerificationIcon aria-hidden="true" className="size-3.5" />
          {verificationLabel}
        </span>

        {confidence !== null && (
          <span
            data-testid="confidence-badge"
            className="rounded-full bg-muted px-2.5 py-1 font-mono text-xs font-medium tabular-nums text-muted-foreground"
          >
            {t('status.confidence', { value: `${confidence}%` })}
          </span>
        )}

        {/* The verifier's own score, distinct from the extractor's confidence.
            A model that is 94% sure of a claim the transcript does not support
            is exactly the case worth showing both numbers for. */}
        {verificationScore !== null && (
          <span
            data-testid="verification-score"
            data-score={item.verification_score}
            title={t('status.verificationScoreHint')}
            className={cn(
              'rounded-full px-2.5 py-1 font-mono text-xs font-medium tabular-nums',
              verification.badge,
            )}
          >
            {t('status.verificationScore', { value: `${verificationScore}%` })}
          </span>
        )}

        {item.supersedes_id && (
          <span
            data-testid="revisited-badge"
            className="rounded-full bg-secondary px-2.5 py-1 text-xs font-medium text-secondary-foreground"
          >
            {t('status.revisited')}
          </span>
        )}

        {item.source_start_ms !== null && (
          <CitationTime ms={item.source_start_ms} className="ml-auto" />
        )}
      </div>

      {needsAttention && (
        <p
          data-testid="attention-banner"
          className={cn(
            'mt-3 flex items-start gap-2 rounded-md px-3 py-2 text-xs font-medium',
            item.verification_status === 'unsupported'
              ? 'bg-destructive/10 text-destructive'
              : 'bg-warn-tint text-warn',
          )}
        >
          <VerificationIcon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          {t(
            item.verification_status === 'unsupported'
              ? 'status.unsupportedHint'
              : 'status.lowConfidenceHint',
          )}
        </p>
      )}

      {/* Meeting content: never translated, so it carries no t() call. */}
      <h3 className="mt-3 font-display text-base font-bold leading-snug" data-testid="item-title">
        {item.title}
      </h3>
      {item.description && (
        <p className="mt-1 whitespace-pre-line text-sm text-muted-foreground">{item.description}</p>
      )}

      {item.source_segment_text ? (
        <blockquote className="mt-3 border-l-2 border-border pl-3 text-sm italic text-muted-foreground">
          <span className="not-italic font-medium text-foreground/70">
            {t('intelligence.source')}:{' '}
          </span>
          <span data-testid="item-quote">{item.source_segment_text}</span>
        </blockquote>
      ) : (
        <p className="mt-3 text-sm text-destructive">{t('intelligence.noSource')}</p>
      )}
    </article>
  );
}
