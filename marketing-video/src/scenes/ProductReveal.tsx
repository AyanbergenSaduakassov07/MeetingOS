import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { Caption, Logo } from '../components/Brand';
import { Shot } from '../components/Shot';
import { C, clamp, DISPLAY, SANS, settle } from '../theme';

const WINDOW_AT = 108;

export const ProductReveal: React.FC = () => {
  const frame = useCurrentFrame();
  const leave = interpolate(frame, [96, 126], [0, 1], { ...clamp });
  const enter = settle(frame, WINDOW_AT);
  return (
    <AbsoluteFill style={{ background: C.stage }}>
      <div
        style={{
          position: 'absolute',
          top: 380,
          width: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 40,
          opacity: 1 - leave,
          translate: `0 ${-90 * leave}px`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 34 }}>
          <div style={{ scale: interpolate(settle(frame, 0), [0, 1], [0.82, 1]) }}>
            <Logo size={128} growAt={6} />
          </div>
          <div
            style={{
              fontFamily: DISPLAY,
              fontWeight: 900,
              fontSize: 128,
              letterSpacing: -4,
              color: C.ink,
              opacity: settle(frame, 14),
              translate: `${interpolate(settle(frame, 14), [0, 1], [-16, 0])}px 0`,
            }}
          >
            MeetingOS
          </div>
        </div>
        <div style={{ fontFamily: SANS, fontSize: 36, color: C.dim, opacity: settle(frame, 36) }}>
          Meeting intelligence, grounded in the transcript.
        </div>
      </div>

      {frame >= WINDOW_AT && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            perspective: 2400,
            opacity: Math.min(1, enter * 1.6),
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: 0,
              transformOrigin: '50% 100%',
              rotate: `x ${(1 - enter) * 22}deg`,
              translate: `0 ${(1 - enter) * 240}px`,
              scale: 0.9 + 0.1 * enter,
            }}
          >
            <Shot
              src="dashboard"
              keys={[
                { at: WINDOW_AT, rect: [0, 0, 3200, 2000] },
                { at: 210, rect: [260, 140, 2720, 1700] },
              ]}
            />
          </div>
        </div>
      )}
      <Caption text="Every meeting, one command centre." from={146} to={222} />
    </AbsoluteFill>
  );
};
