import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { LogOut } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AuthGate } from './components/AuthGate';
import { IconRail } from './components/IconRail';
import { LanguageToggle } from './components/LanguageToggle';
import { Toaster } from './components/ui/toaster';
import { api } from './lib/api';
import { Commitments } from './routes/Commitments';
import { Dashboard } from './routes/Dashboard';
import { MeetingDetail } from './routes/MeetingDetail';
import { MeetingsList } from './routes/MeetingsList';
import { PrivacySettings } from './routes/PrivacySettings';

export default function App() {
  const { t } = useTranslation();

  return (
    <AuthGate>
      <div className="h-dvh overflow-hidden bg-background text-foreground">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-card focus:px-4 focus:py-2 focus:ring-2 focus:ring-ring"
        >
          {t('nav.skipToContent')}
        </a>

        <IconRail />

        {/* The shell owns the viewport height: a header of its own height plus a
          main that takes the rest. Pages inside use h-full, never h-dvh, or
          they would be one header taller than the screen. */}
        <div className="flex h-dvh flex-col pl-20">
          <div className="flex shrink-0 items-center justify-end gap-2 px-6 py-3">
            <LanguageToggle />
            <SignOutButton />
          </div>
          <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto">
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/commitments" element={<Commitments />} />
              <Route path="/settings/privacy" element={<PrivacySettings />} />
              <Route path="/meetings" element={<MeetingsList />} />
              <Route path="/meetings/:meetingId" element={<MeetingDetail />} />
            </Routes>
          </main>
        </div>

        <Toaster />
      </div>
    </AuthGate>
  );
}

function SignOutButton() {
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
      title={t('auth.signOut')}
      aria-label={t('auth.signOut')}
      disabled={logout.isPending}
      onClick={() => logout.mutate()}
      className="flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <LogOut aria-hidden="true" className="size-4" />
    </button>
  );
}
