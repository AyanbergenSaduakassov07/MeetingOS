import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, Cloud, HardDrive, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * Privacy and data-governance control centre.
 *
 * Shows what is actually configured on this install, not what the docs claim.
 * The limitations list is rendered as prominently as the rule list on purpose:
 * a control whose limits the operator cannot read is a control they will
 * over-trust, and over-trusted redaction is worse than none.
 */
export function PrivacySettings() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const privacy = useQuery({ queryKey: ['privacy'], queryFn: api.getPrivacy });

  const update = useMutation({
    mutationFn: ({ enabled, rules }: { enabled: boolean; rules: string[] }) =>
      api.updateRedaction(enabled, rules),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['privacy'] }),
  });

  if (privacy.isLoading) {
    return (
      <output className="mx-auto mt-16 flex max-w-md flex-col items-center gap-3 rounded-lg border border-border bg-card p-8">
        <Loader2 aria-hidden="true" className="size-6 animate-spin text-muted-foreground" />
        {t('common.loading')}
      </output>
    );
  }
  if (privacy.isError || !privacy.data) {
    return (
      <output className="mx-auto mt-16 max-w-md rounded-lg border border-border bg-card p-8 text-center text-destructive">
        {t('privacy.loadFailed')}
      </output>
    );
  }

  const data = privacy.data;
  const enabledRules = data.redaction.rules.filter((r) => r.enabled).map((r) => r.name);

  const toggleRule = (name: string) => {
    const next = enabledRules.includes(name)
      ? enabledRules.filter((r) => r !== name)
      : [...enabledRules, name];
    update.mutate({ enabled: data.redaction.enabled, rules: next });
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-8" data-testid="privacy-settings">
      <h1 className="font-display text-3xl font-black tracking-tight">{t('privacy.title')}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t('privacy.subtitle')}</p>

      {/* -- providers -------------------------------------------------- */}
      <section className="mt-8" aria-labelledby="providers-heading">
        <h2 id="providers-heading" className="font-display text-sm font-bold">
          {t('privacy.providers')}
        </h2>
        <ul className="mt-2 space-y-2" data-testid="provider-list">
          {data.providers.map((provider) => (
            <li
              key={`${provider.name}-${provider.role}`}
              data-testid="provider-row"
              data-cloud={provider.is_cloud}
              className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3"
            >
              <span
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold',
                  provider.is_cloud ? 'bg-warn-tint text-warn' : 'bg-good-tint text-good',
                )}
              >
                {provider.is_cloud ? (
                  <Cloud aria-hidden="true" className="size-3.5" />
                ) : (
                  <HardDrive aria-hidden="true" className="size-3.5" />
                )}
                {t(provider.is_cloud ? 'privacy.cloud' : 'privacy.local')}
              </span>
              <span className="text-sm font-medium">{provider.name}</span>
              <span className="text-xs text-muted-foreground">
                {t(`privacy.role_${provider.role}`)}
              </span>
              <span className="font-mono text-xs text-muted-foreground">{provider.model}</span>
              <span className="ml-auto font-mono text-xs text-muted-foreground">
                {provider.endpoint_host ?? '—'}
              </span>
              {!provider.configured && (
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                  {t('privacy.noCredentials')}
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      {/* -- redaction --------------------------------------------------- */}
      <section className="mt-8" aria-labelledby="redaction-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="redaction-heading" className="font-display text-sm font-bold">
            {t('privacy.redaction')}
          </h2>
          <button
            type="button"
            data-testid="redaction-toggle"
            data-enabled={data.redaction.enabled}
            disabled={update.isPending}
            onClick={() => update.mutate({ enabled: !data.redaction.enabled, rules: enabledRules })}
            className={cn(
              'inline-flex min-h-11 items-center gap-2 rounded-md px-4 text-sm font-semibold transition-opacity hover:opacity-90 disabled:opacity-50',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
              data.redaction.enabled ? 'bg-good-tint text-good' : 'bg-muted text-muted-foreground',
            )}
          >
            {data.redaction.enabled ? (
              <Check aria-hidden="true" className="size-4" />
            ) : (
              <AlertTriangle aria-hidden="true" className="size-4" />
            )}
            {t(data.redaction.enabled ? 'privacy.redactionOn' : 'privacy.redactionOff')}
          </button>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {t('privacy.configSource', {
            source: t(
              data.redaction.source === 'settings'
                ? 'privacy.configSourceSettings'
                : 'privacy.configSourceEnvironment',
            ),
          })}
        </p>

        {/* A ticked green rule under a master switch that is off would read as
            "this is running". Selection and effect are shown as two different
            things, because that is what they are. */}
        {!data.redaction.enabled && (
          <p
            data-testid="rules-inert-notice"
            className="mt-3 rounded-md bg-muted px-3 py-2 text-xs font-medium text-muted-foreground"
          >
            {t('privacy.rulesInert')}
          </p>
        )}

        <ul
          className={cn('mt-3 grid gap-2 sm:grid-cols-2', !data.redaction.enabled && 'opacity-60')}
          data-testid="rule-list"
        >
          {data.redaction.rules.map((rule) => {
            const running = rule.enabled && data.redaction.enabled;
            return (
              <li key={rule.name}>
                <button
                  type="button"
                  data-testid="rule-toggle"
                  data-rule={rule.name}
                  data-enabled={rule.enabled}
                  data-running={running}
                  onClick={() => toggleRule(rule.name)}
                  disabled={update.isPending}
                  className={cn(
                    'flex w-full min-h-14 items-start gap-3 rounded-lg border p-3 text-left transition-colors disabled:opacity-50',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    running
                      ? 'border-good/40 bg-good-tint/40'
                      : 'border-border bg-card hover:border-muted-foreground/40',
                  )}
                >
                  <span
                    className={cn(
                      'mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border-2',
                      running
                        ? 'border-good bg-good'
                        : rule.enabled
                          ? 'border-muted-foreground/40 bg-muted-foreground/20'
                          : 'border-muted-foreground/40',
                    )}
                  >
                    {running && <Check aria-hidden="true" className="size-3 text-good-tint" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{rule.description}</span>
                    <span className="mt-0.5 block font-mono text-xs text-muted-foreground">
                      {rule.name} · {rule.category}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        {/* As prominent as the rules themselves. */}
        <div
          className="mt-4 rounded-lg border border-warn/40 bg-warn-tint p-4"
          data-testid="redaction-limitations"
        >
          <p className="flex items-center gap-2 text-sm font-semibold text-warn">
            <AlertTriangle aria-hidden="true" className="size-4" />
            {t('privacy.limitationsTitle')}
          </p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-warn">
            {data.redaction.limitations.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      </section>

      {/* -- residency --------------------------------------------------- */}
      <section className="mt-8" aria-labelledby="residency-heading">
        <h2 id="residency-heading" className="font-display text-sm font-bold">
          {t('privacy.residency')}
        </h2>
        <dl className="mt-2 space-y-1 rounded-lg border border-border bg-card p-4 text-sm">
          {(
            [
              ['privacy.dataDir', data.residency.data_dir],
              ['privacy.database', data.residency.database],
              ['privacy.recordings', data.residency.recordings_dir],
              ['privacy.documents', data.residency.documents_dir],
            ] as const
          ).map(([key, value]) => (
            <div key={key} className="flex flex-wrap gap-2">
              <dt className="text-muted-foreground">{t(key)}:</dt>
              <dd className="break-all font-mono text-xs">{value}</dd>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <dt className="text-muted-foreground">{t('privacy.allowedHosts')}:</dt>
            <dd className="font-mono text-xs">
              {data.residency.allowed_inference_hosts.join(', ')}
            </dd>
          </div>
        </dl>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {data.residency.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>

      {/* -- audit log ---------------------------------------------------- */}
      <section className="mt-8" aria-labelledby="audit-heading">
        <h2 id="audit-heading" className="font-display text-sm font-bold">
          {t('privacy.auditLog')}
        </h2>
        <dl className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="audit-summary">
          {(
            [
              ['privacy.totalCalls', data.audit_summary.total_calls, 'neutral'],
              ['privacy.cloudCalls', data.audit_summary.cloud_calls, 'warn'],
              ['privacy.failedCalls', data.audit_summary.failed_calls, 'destructive'],
              [
                'privacy.unredactedCalls',
                data.audit_summary.calls_without_redaction,
                'destructive',
              ],
            ] as const
          ).map(([key, value, tone]) => (
            <div key={key} className="rounded-lg border border-border bg-card p-3">
              <dt className="text-xs text-muted-foreground">{t(key)}</dt>
              <dd
                className={cn(
                  'mt-1 font-mono text-2xl font-bold tabular-nums',
                  value === 0
                    ? 'text-foreground'
                    : tone === 'warn'
                      ? 'text-warn'
                      : tone === 'destructive'
                        ? 'text-destructive'
                        : 'text-foreground',
                )}
              >
                {value}
              </dd>
            </div>
          ))}
        </dl>

        {data.recent_calls.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">{t('privacy.noCalls')}</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm" data-testid="audit-table">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">{t('privacy.when')}</th>
                  <th className="py-2 pr-3 font-medium">{t('privacy.provider')}</th>
                  <th className="py-2 pr-3 font-medium">{t('privacy.operation')}</th>
                  <th className="py-2 pr-3 font-medium">{t('privacy.destination')}</th>
                  <th className="py-2 pr-3 text-right font-medium">{t('privacy.chars')}</th>
                  <th className="py-2 font-medium">{t('privacy.redacted')}</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_calls.map((call) => (
                  <tr key={call.id} className="border-b border-border/60" data-testid="audit-row">
                    <td className="py-2 pr-3 font-mono text-xs tabular-nums text-muted-foreground">
                      {call.created_at
                        ? new Date(call.created_at).toLocaleString(i18n.language)
                        : '—'}
                    </td>
                    <td className="py-2 pr-3">{call.provider}</td>
                    <td className="py-2 pr-3 text-muted-foreground">{call.operation}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{call.endpoint_host ?? '—'}</td>
                    <td className="py-2 pr-3 text-right font-mono text-xs tabular-nums">
                      {call.characters_sent ?? '—'}
                    </td>
                    <td className="py-2">
                      <span
                        className={cn(
                          'rounded-full px-2 py-0.5 text-xs font-medium',
                          call.redaction_enabled
                            ? 'bg-good-tint text-good'
                            : 'bg-warn-tint text-warn',
                        )}
                      >
                        {t(call.redaction_enabled ? 'privacy.yes' : 'privacy.no')}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
