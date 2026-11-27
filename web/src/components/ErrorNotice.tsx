import { AlertCircle, RotateCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

interface ErrorNoticeProps {
  /** Translated "what happened" line. */
  message: string;
  /** Raw error; its text stays behind "Details" so provider noise is not the headline. */
  error?: unknown;
  onRetry?: () => void;
  className?: string;
  testId?: string;
}

/** What happened, what to do, and a Retry button. */
export function ErrorNotice({ message, error, onRetry, className, testId }: ErrorNoticeProps) {
  const { t } = useTranslation();
  const detail = error instanceof Error ? error.message : null;

  return (
    <div
      role="alert"
      data-testid={testId}
      className={cn(
        'flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm',
        className,
      )}
    >
      <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-destructive" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-destructive">{message}</p>
        <p className="mt-0.5 text-muted-foreground">{t('errors.whatToDo')}</p>
        {detail && (
          <details className="mt-2 text-xs text-muted-foreground">
            <summary className="cursor-pointer">{t('common.details')}</summary>
            <p className="mt-1 break-words font-mono">{detail}</p>
          </details>
        )}
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <RotateCw aria-hidden="true" className="size-3.5" />
          {t('common.retry')}
        </button>
      )}
    </div>
  );
}
