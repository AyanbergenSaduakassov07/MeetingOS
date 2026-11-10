import { useMutation } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowRight,
  ArrowUp,
  Check,
  Copy,
  Info,
  RotateCcw,
  Sparkles,
} from 'lucide-react';
import { Fragment, type ReactNode, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { type AskResponse, api } from '@/lib/api';
import { cn } from '@/lib/utils';
import { CitationTime } from './CitationTime';

interface Turn {
  id: string;
  question: string;
  response?: AskResponse;
  error?: string;
}

const SUGGESTIONS = ['copilot.suggest1', 'copilot.suggest2', 'copilot.suggest3'] as const;
const MAX_INPUT_HEIGHT_PX = 160;

/**
 * Meeting Copilot, laid out like a modern answer engine: sources first, then
 * the answer, then actions.
 *
 * The two ungrounded cases are called out rather than smoothed over:
 *
 * - `not_discussed` — the transcript does not cover the question. A neutral
 *   notice, because it is a correct answer and should not look like a failure.
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
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

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

  // Keep the newest turn in view, as every chat UI does.
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll when the thread changes
  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns]);

  const resizeInput = () => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, MAX_INPUT_HEIGHT_PX)}px`;
  };

  const submit = (text = draft) => {
    const question = text.trim();
    if (!question || ask.isPending) return;
    const id = `turn-${Date.now()}`;
    setTurns((current) => [...current, { id, question }]);
    setDraft('');
    requestAnimationFrame(resizeInput);
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
        <h2 className="flex-1 font-display text-sm font-bold">{t('copilot.title')}</h2>
        {turns.length > 0 && (
          <button
            type="button"
            onClick={() => setTurns([])}
            disabled={ask.isPending}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-40"
          >
            <RotateCcw aria-hidden="true" className="size-3.5" />
            {t('copilot.newChat')}
          </button>
        )}
      </header>

      <div
        ref={threadRef}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-5"
        data-testid="copilot-thread"
        aria-live="polite"
        aria-busy={ask.isPending}
      >
        {turns.length === 0 ? (
          <EmptyState onPick={submit} />
        ) : (
          <div className="space-y-6">
            {turns.map((turn) => (
              <div key={turn.id} className="space-y-3">
                <div
                  data-role="user"
                  className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-md bg-secondary px-3.5 py-2 text-sm text-foreground"
                >
                  {turn.question}
                </div>

                <AssistantRow>
                  {turn.error ? (
                    <p data-role="error" className="text-sm text-destructive">
                      {turn.error}
                    </p>
                  ) : turn.response ? (
                    <Answer response={turn.response} />
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
        className="shrink-0 p-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label htmlFor="copilot-input" className="sr-only">
          {t('copilot.placeholder')}
        </label>
        <div className="flex items-end gap-2 rounded-2xl border border-border bg-background px-3 py-2 shadow-sm transition-shadow focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/30">
          <textarea
            ref={inputRef}
            id="copilot-input"
            data-testid="copilot-input"
            rows={1}
            value={draft}
            disabled={ask.isPending}
            onChange={(event) => {
              setDraft(event.target.value);
              resizeInput();
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder={t('copilot.placeholder')}
            className="max-h-40 min-h-6 flex-1 resize-none bg-transparent py-1 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
          <button
            type="submit"
            data-testid="copilot-send"
            disabled={ask.isPending || !draft.trim()}
            aria-label={t('copilot.send')}
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ArrowUp aria-hidden="true" className="size-4" />
          </button>
        </div>
        <p className="mt-1.5 px-1 text-[11px] text-muted-foreground">{t('copilot.hint')}</p>
      </form>
    </aside>
  );
}

function EmptyState({ onPick }: { onPick: (question: string) => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full flex-col justify-center gap-4">
      <div className="space-y-2 text-center">
        <span className="mx-auto flex size-10 items-center justify-center rounded-full bg-primary/15">
          <Sparkles aria-hidden="true" className="size-5 text-primary" />
        </span>
        <p className="font-display text-base font-bold">{t('copilot.emptyTitle')}</p>
        <p className="text-sm text-muted-foreground">{t('copilot.empty')}</p>
      </div>
      <ul className="flex flex-col gap-2" data-testid="copilot-suggestions">
        {SUGGESTIONS.map((key) => (
          <li key={key}>
            <button
              type="button"
              className="group flex w-full items-center gap-2 rounded-xl border border-border px-3 py-2.5 text-left text-sm transition-colors hover:border-primary/50 hover:bg-secondary"
              onClick={() => onPick(t(key))}
            >
              <span className="flex-1">{t(key)}</span>
              <ArrowRight
                aria-hidden="true"
                className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5"
              />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AssistantRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-2.5">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/15">
        <Sparkles aria-hidden="true" className="size-3.5 text-primary" />
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function Thinking() {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
      <span className="flex gap-1" aria-hidden="true">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="size-1.5 animate-bounce rounded-full bg-muted-foreground"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>
      {t('copilot.thinking')}
    </div>
  );
}

function Answer({ response }: { response: AskResponse }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  if (response.not_discussed) {
    return (
      <div
        data-role="assistant"
        data-state="not-discussed"
        className="flex items-start gap-2 rounded-xl bg-secondary px-3 py-2 text-sm text-secondary-foreground"
      >
        <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <span>{t('copilot.notDiscussed')}</span>
      </div>
    );
  }

  const copy = async () => {
    await navigator.clipboard.writeText(response.answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      data-role="assistant"
      data-state={response.unsupported ? 'unsupported' : 'grounded'}
      className="space-y-3"
    >
      {response.citations.length > 0 && (
        <section>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">
            {t('copilot.citations')}
          </p>
          <ol className="flex gap-2 overflow-x-auto pb-1">
            {response.citations.map((citation, index) => (
              <li
                key={citation.segment_id}
                className="w-44 shrink-0 rounded-lg border border-border bg-background p-2"
              >
                <div className="flex items-center gap-1.5">
                  <span className="flex size-4 items-center justify-center rounded-full bg-muted text-[10px] font-semibold tabular-nums">
                    {index + 1}
                  </span>
                  <CitationTime ms={citation.start_ms} />
                </div>
                <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">
                  {citation.speaker_label && (
                    <span className="font-medium text-foreground">{citation.speaker_label}: </span>
                  )}
                  {citation.text}
                </p>
              </li>
            ))}
          </ol>
        </section>
      )}

      {response.unsupported && (
        <p className="flex items-center gap-1.5 rounded-lg bg-warn-tint px-3 py-2 text-sm font-medium text-warn">
          <AlertTriangle aria-hidden="true" className="size-4 shrink-0" />
          {t('copilot.unsupported')}
        </p>
      )}

      {/* Answer text is derived from meeting content — never translated. */}
      <div
        className={cn('space-y-2 text-sm leading-relaxed', response.unsupported && 'opacity-80')}
        data-testid="copilot-answer"
      >
        <RichText text={response.answer} />
      </div>

      <button
        type="button"
        onClick={copy}
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
      >
        {copied ? (
          <Check aria-hidden="true" className="size-3.5" />
        ) : (
          <Copy aria-hidden="true" className="size-3.5" />
        )}
        {copied ? t('copilot.copied') : t('copilot.copy')}
      </button>
    </div>
  );
}

const LIST_ITEM = /^\s*(?:[-*•]|\d+[.)])\s+/;

/** **bold** only; built as React nodes, never as HTML, so model text cannot inject markup. */
function inline(text: string): ReactNode[] {
  return text.split(/\*\*(.+?)\*\*/g).map((part, index) =>
    // biome-ignore lint/suspicious/noArrayIndexKey: static split of one string
    index % 2 ? <strong key={index}>{part}</strong> : <Fragment key={index}>{part}</Fragment>,
  );
}

/** Paragraphs and bullet/numbered lists: the subset of Markdown models actually emit in answers. */
export function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const Tag = list.ordered ? 'ol' : 'ul';
    blocks.push(
      <Tag
        key={blocks.length}
        className={cn('space-y-1 pl-5', list.ordered ? 'list-decimal' : 'list-disc')}
      >
        {list.items.map((item, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: static list from one string
          <li key={index}>{inline(item)}</li>
        ))}
      </Tag>,
    );
    list = null;
  };
  for (const line of text.split('\n')) {
    if (LIST_ITEM.test(line)) {
      const ordered = /^\s*\d/.test(line);
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push(line.replace(LIST_ITEM, ''));
    } else {
      flush();
      if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
    }
  }
  flush();
  return <>{blocks}</>;
}
