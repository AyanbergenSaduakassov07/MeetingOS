import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { Logo } from '../components/Brand';
import { C, clamp, DISPLAY, MONO, SANS, settle } from '../theme';

export const CREDITS =
  'Real product footage · Demo meetings: AMI Meeting Corpus (CC BY 4.0), FLEURS (CC BY 4.0) · Copilot answer replayed from a recorded run';

export const Lockup: React.FC<{ frame: number; scale?: number }> = ({ frame, scale = 1 }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 44 * scale }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 30 * scale }}>
      <div style={{ scale: interpolate(settle(frame, 0), [0, 1], [0.86, 1]) }}>
        <Logo size={112 * scale} growAt={4} frame={frame} />
      </div>
      <div
        style={{
          fontFamily: DISPLAY,
          fontWeight: 900,
          fontSize: 112 * scale,
          letterSpacing: -3.5 * scale,
          color: C.ink,
          opacity: settle(frame, 10),
        }}
      >
        MeetingOS
      </div>
    </div>
    <div
      style={{
        fontFamily: SANS,
        fontWeight: 500,
        fontSize: 44 * scale,
        color: C.ink,
        opacity: settle(frame, 34),
        translate: `0 ${interpolate(settle(frame, 34), [0, 1], [12, 0])}px`,
      }}
    >
      Every meeting. <span style={{ color: C.lime }}>More meaningful.</span>
    </div>
  </div>
);

export const Closing: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        background: C.stage,
        justifyContent: 'center',
        alignItems: 'center',
        opacity: interpolate(frame, [192, 210], [1, 0], clamp),
      }}
    >
      <Lockup frame={frame} />
      <div
        style={{
          position: 'absolute',
          bottom: 48,
          fontFamily: MONO,
          fontSize: 17,
          color: C.dim,
          opacity: interpolate(frame, [70, 90], [0, 0.8], clamp),
        }}
      >
        {CREDITS}
      </div>
    </AbsoluteFill>
  );
};
