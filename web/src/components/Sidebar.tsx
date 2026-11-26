import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BookMarked,
  Check,
  ChevronsLeft,
  ClipboardCheck,
  FileUp,
  Gavel,
  Globe,
  LayoutDashboard,
  ListChecks,
  LogOut,
  type LucideIcon,
  Plus,
  Radio,
  Search,
  Settings,
  ShieldAlert,
  Sparkles,
  Upload,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { languageName, SUPPORTED_LANGUAGES } from '@/i18n';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

interface NavItem {
  to: string;
  icon: LucideIcon;
  labelKey: string;
}

export const NAV_GROUPS: Array<{ labelKey: string; items: NavItem[] }> = [
  {
    labelKey: 'nav.groupRecord',
    items: [
      { to: '/dashboard', icon: LayoutDashboard, labelKey: 'nav.dashboard' },
      { to: '/meetings', icon: ListChecks, labelKey: 'nav.meetings' },
      { to: '/decisions', icon: Gavel, labelKey: 'nav.decisions' },
      { to: '/commitments', icon: ClipboardCheck, labelKey: 'nav.commitments' },
      { to: '/risks', icon: ShieldAlert, labelKey: 'nav.risks' },
    ],
  },
  {
    labelKey: 'nav.groupTools',
    items: [
      { to: '/live', icon: Radio, labelKey: 'nav.live' },
      { to: '/copilot', icon: Sparkles, labelKey: 'nav.copilot' },
      { to: '/library', icon: BookMarked, labelKey: 'nav.library' },
    ],
  },
];

const NEW_ITEMS: NavItem[] = [
  { to: '/meetings', icon: Upload, labelKey: 'nav.newMeeting' },
  { to: '/live', icon: Radio, labelKey: 'nav.newLive' },
  { to: '/library', icon: FileUp, labelKey: 'nav.newDocument' },
];

const rowClass =
  'flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

function NavRow({ to, icon: Icon, labelKey }: NavItem) {
  const { t } = useTranslation();
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          rowClass,
          isActive
            ? 'bg-accent text-accent-foreground'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground',
        )
      }
    >
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      <span className="truncate">{t(labelKey)}</span>
    </NavLink>
  );
}

function NewMenu() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-testid="new-menu"
        className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-md bg-primary text-[13px] font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Plus aria-hidden="true" className="size-4" />
        {t('nav.new')}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-52">
        {NEW_ITEMS.map(({ to, icon: Icon, labelKey }) => (
          <DropdownMenuItem key={labelKey} onSelect={() => navigate(to)} className="gap-2">
            <Icon aria-hidden="true" className="size-4" />
            {t(labelKey)}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Quick switch between the translated interfaces; any other language lives in Settings. */
function LanguageMenu() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-testid="language-menu"
        className={cn(rowClass, 'text-muted-foreground hover:bg-muted hover:text-foreground')}
      >
        <Globe aria-hidden="true" className="size-4 shrink-0" />
        <span className="sr-only">{t('nav.language')}: </span>
        <span className="truncate" lang={i18n.language}>
          {languageName(i18n.language, i18n.language)}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="end" className="w-52">
        {SUPPORTED_LANGUAGES.map(({ code, name }) => (
          <DropdownMenuItem
            key={code}
            lang={code}
            onSelect={() => void i18n.changeLanguage(code)}
            className="justify-between"
          >
            {name}
            {i18n.language === code && (
              <Check aria-label={t('settings.current')} className="size-4" />
            )}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate('/settings/language')}>
          {t('nav.moreLanguages')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SignOutRow() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const session = useQuery({ queryKey: ['session'], queryFn: api.getSession });
  const logout = useMutation({
    mutationFn: api.logout,
    // Refetch the session first so the gate swaps to the login screen, then
    // drop cached meeting data so it is not sitting in memory behind it.
    onSuccess: async () => {
      await queryClient.resetQueries({ queryKey: ['session'] });
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'session' });
    },
  });

  // No key configured means there is nothing to sign out of.
  if (!session.data?.auth_required) return null;
  return (
    <button
      type="button"
      disabled={logout.isPending}
      onClick={() => logout.mutate()}
      className={cn(rowClass, 'text-muted-foreground hover:bg-muted hover:text-foreground')}
    >
      <LogOut aria-hidden="true" className="size-4 shrink-0" />
      {t('auth.signOut')}
    </button>
  );
}

interface SidebarProps {
  onHide: () => void;
  onSearch: () => void;
}

/** 184px labelled sidebar. Hidden state and shortcuts are owned by the shell. */
export function Sidebar({ onHide, onSearch }: SidebarProps) {
  const { t } = useTranslation();
  const isMac = /Mac|iPhone|iPad/.test(navigator.userAgent);

  return (
    <nav
      aria-label={t('nav.primary')}
      data-testid="sidebar"
      className="flex h-full w-46 shrink-0 flex-col border-r border-border bg-card"
    >
      <div className="flex h-14 items-center gap-2 px-3">
        <NavLink
          to="/dashboard"
          className="flex min-w-0 flex-1 items-center gap-2 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <img src="/favicon.svg" alt="" className="size-6" />
          <span className="truncate text-sm font-semibold">{t('nav.brand')}</span>
        </NavLink>
        <button
          type="button"
          onClick={onHide}
          aria-label={t('nav.hideSidebar')}
          title={`${t('nav.hideSidebar')} (${isMac ? '⌘' : 'Ctrl'}\\)`}
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ChevronsLeft aria-hidden="true" className="size-4" />
        </button>
      </div>

      <div className="flex gap-1.5 px-3">
        <NewMenu />
        <button
          type="button"
          onClick={onSearch}
          aria-label={t('nav.search')}
          title={`${t('nav.search')} (${isMac ? '⌘' : 'Ctrl'}K)`}
          data-testid="open-palette"
          className="flex size-8 items-center justify-center rounded-md border border-border text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Search aria-hidden="true" className="size-4" />
        </button>
      </div>

      <div className="mt-4 min-h-0 flex-1 space-y-5 overflow-y-auto px-3">
        {NAV_GROUPS.map((group) => (
          <div key={group.labelKey}>
            <p className="mb-1 px-2.5 font-mono text-[10.5px] font-medium uppercase tracking-wider text-muted-foreground">
              {t(group.labelKey)}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.to}>
                  <NavRow {...item} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="space-y-0.5 border-t border-border p-3">
        <LanguageMenu />
        <NavRow to="/settings" icon={Settings} labelKey="nav.settings" />
        <SignOutRow />
      </div>
    </nav>
  );
}
