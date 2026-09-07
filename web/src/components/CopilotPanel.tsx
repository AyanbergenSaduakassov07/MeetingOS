import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, Info, Send, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Textarea } from '@/components/ui/textarea';
import { type AskResponse, api } from '@/lib/api';
import { cn } from '@/lib/utils';
import { CitationTime } from './CitationTime';

interface Turn {
  id: string;
  question: string;
  response?: AskResponse;
  error?: string;
}

/**
 * Meeting Copilot.
 *
 * Answers are rendered with their provenance attached, and the two ungrounded
 * cases are called out rather than smoothed over:
 *
 * - `not_discussed` — the transcript does not cover the question. Shown as a
 *   neutral notice, because it is a correct answer and should not look like a
 *   failure.
 * - `unsupported` — the model asserted something but cited nothing valid.
 *   Shown with a warning, because an uncited answer that looks like every
 *   other answer is the exact failure this product exists to prevent.
 *
 * Citations reuse `CitationTime`, so a copilot answer seeks the waveform by
 * the same path an item card does.
 */
export function CopilotPanel({ meetingId }: { meetingId: string }) {
  const { t } = useTranslation();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');

  const ask = useMutation({
    mutationFn: ({ question }: { id: string; question: string }) => api.ask(meetingId, question),
    onSuccess: (response, variables) =>
      setTurns((current) =>
        current.map((turn) => (turn.id === variables.id ? { ...turn, response } : turn)),
      ),
    onError: (error, variables) =>
      setTurns((current) =>
        current.map((turn) =>
          turn.id === variables.id
            ? { ...turn, error: error instanceof Error ? error.message : t('copilot.error') }
            : turn,
        ),
      ),
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
    <aside
      aria-label={t('copilot.title')}
      data-testid="copilot-panel"
      className="flex h-full min-h-0 flex-col border-l border-border bg-card"
    >
      <header className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-3">
        <Sparkles aria-hidden="true" className="size-4 text-primary" />
        <h2 className="font-display text-sm font-bold">{t('copilot.title')}</h2>
      </header>

      <div
        className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4"
        data-testid="copilot-thread"
        aria-live="polite"
        aria-busy={ask.isPending}
      >
        {turns.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('copilot.empty')}</p>
        ) : (
          turns.map((turn) => (
            <div key={turn.id} className="space-y-2">
              <div
                data-role="user"
                className="ml-auto max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
              >
                {turn.question}
              </div>

              {turn.error && (
                <p
                  data-role="error"
                  className="mr-auto max-w-[90%] rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
                >
                  {turn.error}
                </p>
              )}

              {!turn.response && !turn.error && (
                <p className="mr-auto text-sm text-muted-foreground">{t('copilot.thinking')}</p>
              )}

              {turn.response && <AnswerBubble response={turn.response} />}
            </div>
          ))
        )}
      </div>

      <form
        className="shrink-0 border-t border-border p-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label htmlFor="copilot-input" className="sr-only">
          {t('copilot.placeholder')}
        </label>
        <div className="flex items-end gap-2">
          <Textarea
            id="copilot-input"
            data-testid="copilot-input"
            rows={2}
            value={draft}
            disabled={ask.isPending}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder={t('copilot.placeholder')}
            className="min-h-11 resize-none"
          />
          <button
            type="submit"
            data-testid="copilot-send"
            disabled={ask.isPending || !draft.trim()}
            aria-label={t('copilot.send')}
            className="flex size-11 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground transition-opacity duration-150 hover:opacity-90 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card"
          >
            <Send aria-hidden="true" className="size-4" />
          </button>
        </div>
      </form>
    </aside>
  );
}

function AnswerBubble({ response }: { response: AskResponse }) {
  const { t } = useTranslation();

  if (response.not_discussed) {
    return (
      <div
        data-role="assistant"
        data-state="not-discussed"
        className="mr-auto flex max-w-[90%] items-start gap-2 rounded-lg bg-secondary px-3 py-2 text-sm text-secondary-foreground"
      >
        <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <span>{t('copilot.notDiscussed')}</span>
      </div>
    );
  }

  return (
    <div
      data-role="assistant"
      data-state={response.unsupported ? 'unsupported' : 'grounded'}
      className={cn(
        'mr-auto max-w-[90%] rounded-lg px-3 py-2 text-sm',
        response.unsupported ? 'bg-warn-tint text-warn' : 'bg-secondary text-secondary-foreground',
      )}
    >
      {response.unsupported && (
        <p className="mb-1.5 flex items-center gap-1.5 font-medium">
          <AlertTriangle aria-hidden="true" className="size-4 shrink-0" />
          {t('copilot.unsupported')}
        </p>
      )}

      {/* Answer text is derived from meeting content — never translated. */}
      <p className="whitespace-pre-line" data-testid="copilot-answer">
        {response.answer}
      </p>

      {response.citations.length > 0 && (
        <div className="mt-2 border-t border-border/60 pt-2">
          <p className="text-xs font-medium text-muted-foreground">{t('copilot.citations')}</p>
          <ul className="mt-1 space-y-1">
            {response.citations.map((citation) => (
              <li key={citation.segment_id} className="flex items-start gap-1.5">
                <CitationTime ms={citation.start_ms} className="shrink-0" />
                <span className="min-w-0 flex-1 py-2.5 text-xs italic text-muted-foreground">
                  {citation.speaker_label && (
                    <span className="not-italic font-medium">{citation.speaker_label}: </span>
                  )}
                  {citation.text}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
