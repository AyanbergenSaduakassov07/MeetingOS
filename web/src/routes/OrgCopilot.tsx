import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, ArrowUp, FileText, Info, Mic, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AssistantRow, RichText, Thinking } from '@/components/CopilotPanel';
import { api, type OrgAskResponse } from '@/lib/api';
import { formatTimestamp } from '@/lib/playback';

// The backend wants a plain language name, not a code.
const LANGUAGE_NAMES: Record<string, string> = { en: 'English', ru: 'Russian', kk: 'Kazakh' };

interface Turn {
  id: string;
  question: string;
  response?: OrgAskResponse;
  error?: string;
}

/** Copilot over every meeting and document in the org, not one transcript. */
export function OrgCopilot() {
  const { t, i18n } = useTranslation();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');

  const patchTurn = (id: string, patch: Partial<Turn>) =>
    setTurns((current) => current.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)));

  const ask = useMutation({
    mutationFn: ({ question }: { id: string; question: string }) =>
      api.askOrg(question, LANGUAGE_NAMES[i18n.language.slice(0, 2)] ?? 'English'),
    onSuccess: (response, { id }) => patchTurn(id, { response }),
    onError: (error, { id }) =>
      patchTurn(id, { error: error instanceof Error ? error.message : t('copilot.error') }),
  });

  const submit = () => {
    const question = draft.trim();
    if (!question || ask.isPending) return;
    const id = `turn-${Date.now()}`;
    setTurns((current) => [...current, { id, question }]);
    setDraft('');
    ask.mutate({ id, question });
  };

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col px-6 pb-4" data-testid="org-copilot">
      <div className="min-h-0 flex-1 overflow-y-auto py-6" aria-live="polite">
        {turns.length === 0 ? (
          <div className="mt-16 space-y-2 text-center">
            <span className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/15">
              <Sparkles aria-hidden="true" className="size-6 text-primary" />
            </span>
            <h1 className="font-display text-2xl font-black tracking-tight">
              {t('orgCopilot.title')}
            </h1>
            <p className="text-sm text-muted-foreground">{t('orgCopilot.subtitle')}</p>
          </div>
        ) : (
          <div className="space-y-6">
            {turns.map((turn) => (
              <div key={turn.id} className="space-y-3">
                <div className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-secondary px-3.5 py-2 text-sm">
                  {turn.question}
                </div>
                <AssistantRow>
                  {turn.error ? (
                    <p className="text-sm text-destructive">{turn.error}</p>
                  ) : turn.response ? (
                    <OrgAnswer response={turn.response} />
                  ) : (
                    <Thinking />
                  )}
                </AssistantRow>
              </div>
            ))}
          </div>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
        className="flex items-end gap-2 rounded-2xl border border-border bg-card px-3 py-2 shadow-sm focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/30"
      >
        <label htmlFor="org-copilot-input" className="sr-only">
          {t('orgCopilot.placeholder')}
        </label>
        <textarea
          id="org-copilot-input"
          data-testid="org-copilot-input"
          rows={1}
          value={draft}
          maxLength={1000}
          disabled={ask.isPending}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder={t('orgCopilot.placeholder')}
          className="max-h-40 min-h-6 flex-1 resize-none bg-transparent py-1 text-sm outline-none placeholder:text-muted-foreground"
        />
        <button
          type="submit"
          aria-label={t('copilot.send')}
          disabled={ask.isPending || !draft.trim()}
          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-30"
        >
          <ArrowUp aria-hidden="true" className="size-4" />
        </button>
      </form>
    </div>
  );
}

function OrgAnswer({ response }: { response: OrgAskResponse }) {
  const { t } = useTranslation();

  // Nothing indexed: "not discussed" would claim the meetings were searched when they were not.
  if (response.records_considered === 0) {
    return (
      <p
        data-state="nothing-indexed"
        className="flex items-start gap-2 rounded-xl bg-secondary px-3 py-2 text-sm"
      >
        <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        {t('orgCopilot.nothingIndexed')}
      </p>
    );
  }
  if (response.not_discussed) {
    return (
      <p className="flex items-start gap-2 rounded-xl bg-secondary px-3 py-2 text-sm">
        <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        {t('orgCopilot.notFound')}
      </p>
    );
  }

  return (
    <div className="space-y-3" data-state={response.unsupported ? 'unsupported' : 'grounded'}>
      {response.unsupported && (
        <p className="flex items-center gap-1.5 rounded-lg bg-warn-tint px-3 py-2 text-sm font-medium text-warn">
          <AlertTriangle aria-hidden="true" className="size-4 shrink-0" />
          {t('copilot.unsupported')}
        </p>
      )}
      <div className="space-y-2 text-sm leading-relaxed">
        <RichText text={response.answer} />
      </div>
      {response.citations.length > 0 && (
        <ol className="space-y-2">
          {response.citations.map((citation, index) => (
            <li
              key={citation.record_id}
              className="rounded-lg border border-border bg-card p-2.5 text-xs"
            >
              <div className="flex items-center gap-1.5 font-medium">
                <span className="flex size-4 items-center justify-center rounded-full bg-muted text-[10px] tabular-nums">
                  {index + 1}
                </span>
                {citation.source_kind === 'document' ? (
                  <FileText aria-hidden="true" className="size-3.5 text-muted-foreground" />
                ) : (
                  <Mic aria-hidden="true" className="size-3.5 text-muted-foreground" />
                )}
                {citation.source_kind === 'meeting' && citation.source_id ? (
                  <Link to={`/meetings/${citation.source_id}`} className="truncate hover:underline">
                    {citation.source_title ?? t('orgCopilot.untitled')}
                  </Link>
                ) : (
                  <span className="truncate">
                    {citation.source_title ?? t('orgCopilot.untitled')}
                  </span>
                )}
                {citation.start_ms !== null && (
                  <span className="font-mono tabular-nums text-muted-foreground">
                    {formatTimestamp(citation.start_ms)}
                  </span>
                )}
              </div>
              <p className="mt-1 line-clamp-3 text-muted-foreground">{citation.text}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
