import type React from 'react';
import { interpolate, useCurrentFrame } from 'remotion';
import { C, clamp, DISPLAY, fade, MONO, settle, WINDOW } from '../theme';

// web/public/favicon.svg, bar by bar, so the bars can grow in.
const BARS = [
  { x: 7, y: 12, h: 8 },
  { x: 12, y: 8, h: 16 },
  { x: 17, y: 10, h: 12 },
  { x: 22, y: 14, h: 4 },
];

export const Logo: React.FC<{ size: number; growAt?: number; frame?: number }> = ({
  size,
  growAt,
  frame: given,
}) => {
  const current = useCurrentFrame();
  const frame = given ?? current; // a Still passes its own frame
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" style={{ display: 'block' }}>
      <rect width="32" height="32" rx="8" fill={C.lime} />
      {BARS.map((bar, index) => {
        const grow = growAt === undefined ? 1 : settle(frame, growAt + index * 4);
        const h = Math.max(3, bar.h * grow);
        return (
          <rect
            key={bar.x}
            x={bar.x}
            y={16 - h / 2}
            width="3"
            height={h}
            rx="1.5"
            fill={C.limeInk}
          />
        );
      })}
    </svg>
  );
};

/** Scene caption above the app window: a mono step marker and a line. */
export const Caption: React.FC<{ step?: string; text: string; from: number; to: number }> = ({
  step,
  text,
  from,
  to,
}) => {
  const frame = useCurrentFrame();
  const rise = interpolate(settle(frame, from), [0, 1], [14, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        left: WINDOW.left,
        top: 46,
        display: 'flex',
        alignItems: 'baseline',
        gap: 22,
        opacity: fade(frame, from, to),
        translate: `0 ${rise}px`,
      }}
    >
      {step && (
        <span style={{ fontFamily: MONO, fontSize: 20, color: C.lime, letterSpacing: 1 }}>
          {step}
        </span>
      )}
      <span
        style={{
          fontFamily: DISPLAY,
          fontWeight: 700,
          fontSize: 42,
          color: C.ink,
          letterSpacing: -0.6,
        }}
      >
        {text}
      </span>
    </div>
  );
};

/** Lime frame around a spot in a shot, drawn on as it appears. */
export const Ring: React.FC<{ style: React.CSSProperties; at: number }> = ({ style, at }) => {
  const frame = useCurrentFrame();
  const p = settle(frame, at);
  return (
    <div
      style={{
        ...style,
        borderRadius: 10,
        boxShadow: `0 0 0 ${interpolate(p, [0, 1], [10, 3], clamp)}px ${C.lime}`,
        opacity: p,
      }}
    />
  );
};
