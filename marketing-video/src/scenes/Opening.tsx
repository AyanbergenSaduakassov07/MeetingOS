import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import peaks from '../peaks.json';
import { C, clamp, DISPLAY, fade, settle, useLayout } from '../theme';

// 96 s of the AMI meeting's loudness: a real conversation, drawn once.
const BAR = 8;
const GAP = 7;

const Line: React.FC<{ from: number; to: number; children: React.ReactNode }> = ({
  from,
  to,
  children,
}) => {
  const frame = useCurrentFrame();
  const { vertical } = useLayout();
  return (
    <div
      style={{
        position: 'absolute',
        top: vertical ? 560 : 360,
        width: '100%',
        padding: vertical ? '0 70px' : 0,
        boxSizing: 'border-box',
        lineHeight: 1.1,
        textAlign: 'center',
        fontFamily: DISPLAY,
        fontWeight: 700,
        fontSize: vertical ? 84 : 70,
        letterSpacing: vertical ? -1.8 : -1.4,
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
  const layout = useLayout();
  const width = peaks.length * (BAR + GAP) - GAP;
  // Vertical: the same bars, shrunk to the narrower stage.
  const fit = Math.min(1, (layout.width - 120) / width);
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
          left: (layout.width - width) / 2,
          top: layout.vertical ? 1000 : 640,
          scale: `${fit} ${layout.vertical ? 1.3 * fit : 1}`,
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
