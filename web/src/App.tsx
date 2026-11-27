import { ChevronsRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AuthGate } from './components/AuthGate';
import { CommandPalette } from './components/CommandPalette';
import { Sidebar } from './components/Sidebar';
import { Toaster } from './components/ui/toaster';
import { Commitments } from './routes/Commitments';
import { Dashboard } from './routes/Dashboard';
import { DecisionRecord } from './routes/DecisionRecord';
import { Library } from './routes/Library';
import { LiveHost } from './routes/LiveHost';
import { LiveViewer } from './routes/LiveViewer';
import { MeetingDetail } from './routes/MeetingDetail';
import { MeetingsList } from './routes/MeetingsList';
import { OrgCopilot } from './routes/OrgCopilot';
import { PersonRecord } from './routes/PersonRecord';
import { PrepareBrief } from './routes/PrepareBrief';
import { PrivacySettings } from './routes/PrivacySettings';
import { Register } from './routes/Register';
import { LanguageSettings, SettingsLayout } from './routes/Settings';

export default function App() {
  return (
    <Routes>
      {/* Guest caption viewers hold a join token, not the API key. */}
      <Route path="/watch/:sessionId" element={<LiveViewer />} />
      <Route path="*" element={<Shell />} />
    </Routes>
  );
}

const SIDEBAR_KEY = 'meetingos:sidebar';

function LegacyCommitments() {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: '/follow-ups', search, hash }} replace />;
}

function readSidebarHidden(): boolean {
  try {
    const stored = localStorage.getItem(SIDEBAR_KEY);
    if (stored) return stored === 'hidden';
  } catch {
    // Storage blocked: fall through to the width default.
  }
  // No saved choice: phones start with the sidebar hidden so content gets the width.
  return window.matchMedia('(max-width: 767px)').matches;
}

/** Sidebar visibility, remembered per browser; ⌘\ toggles it, ⌘K opens the palette. */
function useShellShortcuts() {
  const [sidebarHidden, setSidebarHidden] = useState(readSidebarHidden);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_KEY, sidebarHidden ? 'hidden' : 'shown');
    } catch {
      // Storage blocked: the choice just will not survive a reload.
    }
  }, [sidebarHidden]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      if (event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      } else if (event.key === '\\') {
        event.preventDefault();
        setSidebarHidden((hidden) => !hidden);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return { sidebarHidden, setSidebarHidden, paletteOpen, setPaletteOpen };
}

function Shell() {
  const { t } = useTranslation();
  const { sidebarHidden, setSidebarHidden, paletteOpen, setPaletteOpen } = useShellShortcuts();

  return (
    <AuthGate>
      <div className="flex h-dvh overflow-hidden bg-background text-foreground">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-card focus:px-4 focus:py-2 focus:ring-2 focus:ring-ring"
        >
          {t('nav.skipToContent')}
        </a>

        {sidebarHidden ? (
          <button
            type="button"
            onClick={() => setSidebarHidden(false)}
            aria-label={t('nav.showSidebar')}
            title={t('nav.showSidebar')}
            data-testid="show-sidebar"
            className="fixed left-3 top-3 z-40 flex size-8 items-center justify-center rounded-md border border-border bg-card text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronsRight aria-hidden="true" className="size-4" />
          </button>
        ) : (
          <Sidebar onHide={() => setSidebarHidden(true)} onSearch={() => setPaletteOpen(true)} />
        )}

        {/* The shell owns the viewport height; pages use h-full, never h-dvh. */}
        <main id="main" tabIndex={-1} className="min-h-0 min-w-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/follow-ups" element={<Commitments />} />
            <Route path="/commitments" element={<LegacyCommitments />} />
            <Route path="/people/:personId" element={<PersonRecord />} />
            <Route path="/people/:personId/commitments" element={<PersonRecord />} />
            <Route path="/decisions" element={<Register kind="decisions" />} />
            <Route path="/decisions/:decisionId" element={<DecisionRecord />} />
            <Route path="/risks" element={<Register kind="risks" />} />
            <Route path="/quality" element={<Register kind="quality" />} />
            <Route path="/settings" element={<SettingsLayout />}>
              <Route index element={<Navigate to="language" replace />} />
              <Route path="language" element={<LanguageSettings />} />
              <Route path="privacy" element={<PrivacySettings />} />
            </Route>
            <Route path="/copilot" element={<OrgCopilot />} />
            <Route path="/brief" element={<PrepareBrief />} />
            <Route path="/library" element={<Library />} />
            <Route path="/live" element={<LiveHost />} />
            <Route path="/meetings" element={<MeetingsList />} />
            <Route
              path="/meetings/:meetingId"
              element={<MeetingDetail showOutline={!sidebarHidden} />}
            />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </main>

        <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
        <Toaster />
      </div>
    </AuthGate>
  );
}
