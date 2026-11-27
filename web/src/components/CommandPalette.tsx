import * as DialogPrimitive from '@radix-ui/react-dialog';
import { useQuery } from '@tanstack/react-query';
import { CornerDownLeft, FileText, Globe, type LucideIcon, Search } from 'lucide-react';
import { type KeyboardEvent, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { NAV_GROUPS } from '@/components/Sidebar';
import { SUPPORTED_LANGUAGES } from '@/i18n';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

interface Command {
  id: string;
  group: string;
  label: string;
  icon: LucideIcon;
  run: () => void;
}

const MAX_MEETINGS = 8;

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** ⌘K: jump to any page or meeting, or switch interface language. */
export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const meetings = useQuery({ queryKey: ['meetings'], queryFn: api.listMeetings, enabled: open });

  const close = () => {
    onOpenChange(false);
    setQuery('');
    setActive(0);
  };
  const go = (to: string) => () => navigate(to);

  const pages: Command[] = [
    ...NAV_GROUPS.flatMap((g) => g.items),
    { to: '/brief', icon: FileText, labelKey: 'nav.prepareBrief' },
    { to: '/quality', icon: Search, labelKey: 'register.quality' },
    { to: '/settings/language', icon: Globe, labelKey: 'settings.language' },
    { to: '/settings/privacy', icon: Search, labelKey: 'settings.privacy' },
  ].map(({ to, icon, labelKey }) => ({
    id: `page:${to}`,
    group: t('palette.pages'),
    label: t(labelKey),
    icon,
    run: go(to),
  }));
  const meetingCommands: Command[] = (meetings.data ?? []).map((m) => ({
    id: `meeting:${m.id}`,
    group: t('palette.meetings'),
    label: m.title,
    icon: FileText,
    run: go(`/meetings/${m.id}`),
  }));
  const languages: Command[] = SUPPORTED_LANGUAGES.map(({ code, name }) => ({
    id: `lang:${code}`,
    group: t('palette.languages'),
    label: name,
    icon: Globe,
    run: () => void i18n.changeLanguage(code),
  }));

  const needle = query.trim().toLocaleLowerCase();
  const matches = (c: Command) => !needle || c.label.toLocaleLowerCase().includes(needle);
  const results = [
    ...pages.filter(matches),
    ...meetingCommands.filter(matches).slice(0, MAX_MEETINGS),
    ...languages.filter(matches),
  ];
  const current = Math.min(active, Math.max(results.length - 1, 0));

  const runCommand = (command: Command | undefined) => {
    if (!command) return;
    close();
    command.run();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    const step = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (step) {
      event.preventDefault();
      setActive((current + step + results.length) % Math.max(results.length, 1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      runCommand(results[current]);
    }
  };

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-foreground/20" />
        <DialogPrimitive.Content
          data-testid="command-palette"
          className="fixed left-1/2 top-[15vh] z-50 w-[min(560px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-lg border border-border bg-card shadow-xl"
        >
          <DialogPrimitive.Title className="sr-only">{t('palette.title')}</DialogPrimitive.Title>
          <div className="flex items-center gap-2 border-b border-border px-3">
            <Search aria-hidden="true" className="size-4 text-muted-foreground" />
            <input
              role="combobox"
              aria-expanded="true"
              aria-controls="palette-results"
              aria-activedescendant={results[current] ? `cmd-${current}` : undefined}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              placeholder={t('palette.placeholder')}
              className="h-11 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <div id="palette-results" role="listbox" className="max-h-[50vh] overflow-y-auto p-1.5">
            {results.length === 0 && (
              <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                {t('palette.empty')}
              </p>
            )}
            {results.map((command, i) => {
              const Icon = command.icon;
              const showGroup = i === 0 || results[i - 1].group !== command.group;
              return (
                <div key={command.id} role="presentation">
                  {showGroup && (
                    <p className="px-2.5 pb-1 pt-2 font-mono text-[10.5px] uppercase tracking-wider text-muted-foreground">
                      {command.group}
                    </p>
                  )}
                  <div
                    id={`cmd-${i}`}
                    role="option"
                    aria-selected={i === current}
                    tabIndex={-1}
                    onMouseMove={() => setActive(i)}
                    onClick={() => runCommand(command)}
                    onKeyDown={() => undefined}
                    className={cn(
                      'flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm',
                      i === current && 'bg-accent text-accent-foreground',
                    )}
                  >
                    <Icon aria-hidden="true" className="size-4 shrink-0 opacity-70" />
                    <span className="truncate">{command.label}</span>
                    {i === current && (
                      <CornerDownLeft aria-hidden="true" className="ml-auto size-3.5 opacity-60" />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
