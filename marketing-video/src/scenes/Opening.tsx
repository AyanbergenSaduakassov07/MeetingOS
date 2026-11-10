import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import peaks from '../peaks.json';
import { C, clamp, DISPLAY, fade, settle } from '../theme';

// 96 s of the AMI meeting's loudness: a real conversation, drawn once.
const BAR = 8;
const GAP = 7;

const Line: React.FC<{ from: number; to: number; children: React.ReactNode }> = ({
  from,
  to,
  children,
}) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: 'absolute',
        top: 360,
        width: '100%',
        textAlign: 'center',
        fontFamily: DISPLAY,
        fontWeight: 700,
        fontSize: 70,
        letterSpacing: -1.4,
        color: C.ink,
        opacity: fade(frame, from, to, 16),
        translate: `0 ${interpolate(settle(frame, from), [0, 1], [18, 0])}px`,
      }}
    >
      {children}
    </div>
  );
};

export const Opening: React.FC = () => {
  const frame = useCurrentFrame();
  const width = peaks.length * (BAR + GAP) - GAP;
  return (
    <AbsoluteFill style={{ background: C.stage }}>
      <Line from={14} to={104}>
        Every meeting creates information.
      </Line>
      <Line from={112} to={206}>
        But information alone isn&rsquo;t <span style={{ color: C.lime }}>intelligence.</span>
      </Line>
      <div
        style={{
          position: 'absolute',
          left: (1920 - width) / 2,
          top: 640,
          height: 150,
          display: 'flex',
          alignItems: 'center',
          gap: GAP,
          opacity: interpolate(frame, [190, 208], [1, 0], clamp),
        }}
      >
        {peaks.map((peak, index) => {
          const height = 6 + 140 * Math.min(1, Math.sqrt(peak / 0.35));
          const shown = interpolate(frame, [8 + index * 0.9, 20 + index * 0.9], [0, 1], clamp);
          // Information becomes intelligence: the bars light up, left to right.
          const lit = interpolate(frame, [130 + index * 0.6, 142 + index * 0.6], [0, 1], clamp);
          return (
            <div
              key={index}
              style={{
                width: BAR,
                height: height * shown,
                borderRadius: BAR / 2,
                background: lit > 0 ? C.lime : C.faint,
                opacity: lit > 0 ? 0.35 + 0.65 * lit : 1,
              }}
            />
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
