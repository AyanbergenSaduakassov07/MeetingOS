import { FileAudio, ListChecks, Settings } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { LanguageToggle } from './LanguageToggle';

const NAV_ITEMS = [
  { key: 'nav.meetings', href: '/meetings', icon: ListChecks },
  { key: 'nav.upload', href: '/upload', icon: FileAudio },
  { key: 'nav.settings', href: '/settings', icon: Settings },
] as const;

export function MainNav({ current = '/meetings' }: { current?: string }) {
  const { t } = useTranslation();

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
      <nav
        aria-label={t('nav.brand')}
        className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6"
      >
        <span className="font-display text-lg font-black tracking-tight">{t('nav.brand')}</span>

        <ul className="flex flex-1 items-center gap-1">
          {NAV_ITEMS.map(({ key, href, icon: Icon }) => {
            const active = current === href;
            return (
              <li key={href}>
                <a
                  href={href}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors duration-150',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                    active
                      ? 'bg-secondary text-foreground'
                      : 'text-muted-foreground hover:bg-secondary/60 hover:text-foreground',
                  )}
                >
                  <Icon aria-hidden="true" className="size-4 shrink-0" />
                  <span className="hidden sm:inline">{t(key)}</span>
                </a>
              </li>
            );
          })}
        </ul>

        <LanguageToggle />
      </nav>
    </header>
  );
}
