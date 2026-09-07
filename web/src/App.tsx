import { useTranslation } from 'react-i18next';
import { Navigate, Route, Routes } from 'react-router-dom';
import { IconRail } from './components/IconRail';
import { LanguageToggle } from './components/LanguageToggle';
import { Toaster } from './components/ui/toaster';
import { Commitments } from './routes/Commitments';
import { Dashboard } from './routes/Dashboard';
import { MeetingDetail } from './routes/MeetingDetail';
import { MeetingsList } from './routes/MeetingsList';

export default function App() {
  const { t } = useTranslation();

  return (
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
        <div className="flex shrink-0 justify-end px-6 py-3">
          <LanguageToggle />
        </div>
        <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/commitments" element={<Commitments />} />
            <Route path="/meetings" element={<MeetingsList />} />
            <Route path="/meetings/:meetingId" element={<MeetingDetail />} />
          </Routes>
        </main>
      </div>

      <Toaster />
    </div>
  );
}
