import {
  BookMarked,
  LayoutDashboard,
  ListChecks,
  type LucideIcon,
  Settings,
  Sparkles,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router-dom';
import { cn } from '@/lib/utils';

/**
 * Narrow icon-only rail: fixed left, logo at top, a column of 48px circular
 * targets.
 *
 * Icon-only navigation costs discoverability, so every target carries both
 * `title` (pointer) and `aria-label` (assistive tech), and the active one is
 * marked with `aria-current` rather than colour alone.
 */
const RAIL_ITEMS: Array<{ to: string; icon: LucideIcon; labelKey: string; end?: boolean }> = [
  { to: '/dashboard', icon: LayoutDashboard, labelKey: 'nav.dashboard' },
  { to: '/meetings', icon: ListChecks, labelKey: 'nav.meetings' },
  { to: '/copilot', icon: Sparkles, labelKey: 'nav.copilot' },
  { to: '/library', icon: BookMarked, labelKey: 'nav.library' },
  { to: '/settings/privacy', icon: Settings, labelKey: 'nav.settings' },
];

export function IconRail() {
  const { t } = useTranslation();

  return (
    <nav
      aria-label={t('nav.primary')}
      className="fixed left-0 top-0 z-40 flex h-full w-20 flex-col items-center gap-6 border-r border-border bg-card py-6"
    >
      <NavLink
        to="/meetings"
        aria-label={t('nav.brand')}
        title={t('nav.brand')}
        className="size-12 shrink-0 rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <img src="/favicon.svg" alt="" className="size-12" />
      </NavLink>

      <ul className="flex flex-col gap-3">
        {RAIL_ITEMS.map(({ to, icon: Icon, labelKey, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              title={t(labelKey)}
              aria-label={t(labelKey)}
              className={({ isActive }) =>
                cn(
                  'flex size-12 items-center justify-center rounded-full transition-colors duration-200',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-card',
                  isActive
                    ? 'bg-secondary text-foreground ring-1 ring-border'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )
              }
            >
              {({ isActive }) => (
                <>
                  <Icon aria-hidden="true" className="size-5" />
                  {isActive && <span className="sr-only">{t('nav.current')}</span>}
                </>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
