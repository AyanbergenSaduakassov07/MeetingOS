import { loadFont as loadGolos } from '@remotion/google-fonts/GolosText';
import { loadFont as loadPlexMono } from '@remotion/google-fonts/IBMPlexMono';
import { loadFont as loadManrope } from '@remotion/google-fonts/Manrope';
import { Easing, interpolate, spring } from 'remotion';

// The app's own type and palette (web/src/index.css), on a dark stage.
const subsets: ('latin' | 'cyrillic' | 'cyrillic-ext')[] = ['latin', 'cyrillic', 'cyrillic-ext'];
export const DISPLAY = loadGolos('normal', { weights: ['700', '900'], subsets }).fontFamily;
export const SANS = loadManrope('normal', { weights: ['400', '500', '600'], subsets }).fontFamily;
export const MONO = loadPlexMono('normal', { weights: ['400', '500'], subsets: ['latin'] }).fontFamily;

export const C = {
  stage: '#0A0C0B',
  ink: '#F4F6EF',
  dim: 'rgba(244, 246, 239, 0.56)',
  faint: 'rgba(244, 246, 239, 0.16)',
  lime: '#C6E619',
  limeInk: '#14200A',
  page: '#F5F8F2', // app background, sampled from the captures
};

export const FPS = 30;
// Scene starts in frames. scripts/make_audio.py CUTS_S mirrors these.
export const T = {
  opening: 0,
  reveal: 210,
  workflow: 420,
  intelligence: 840,
  copilot: 1290,
  closing: 1590,
  end: 1800,
};

// The app window every product shot sits in: 16:10 like the captures.
export const WINDOW = { left: 224, top: 128, width: 1472, height: 920 };

export const glide = Easing.bezier(0.65, 0, 0.35, 1);

export const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

/** 0 → 1 settle, starting at `at`. */
export const settle = (frame: number, at: number, fps = FPS) =>
  spring({ frame: frame - at, fps, config: { damping: 200 }, durationInFrames: 24 });

/** Opacity that fades in at `inAt` and out at `outAt`. */
export const fade = (frame: number, inAt: number, outAt: number, length = 12) =>
  Math.min(
    interpolate(frame, [inAt, inAt + length], [0, 1], clamp),
    interpolate(frame, [outAt - length, outAt], [1, 0], clamp),
  );
