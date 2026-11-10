import type React from 'react';
import { Img, interpolate, staticFile, useCurrentFrame } from 'remotion';
import { clamp, glide, WINDOW } from '../theme';

/** A region of a screenshot, in screenshot pixels: [x, y, width, height]. */
export type Rect = [number, number, number, number];
export type CameraKey = { at: number; rect: Rect };
export type Place = (rect: Rect) => React.CSSProperties;

type Props = {
  src: string | ((frame: number) => string);
  keys: CameraKey[];
  box?: { left: number; top: number; width: number; height: number };
  image?: { width: number; height: number };
  style?: React.CSSProperties;
  /** Overlays drawn in screenshot coordinates, so they track the camera. */
  children?: (place: Place, frame: number) => React.ReactNode;
};

/**
 * A real screenshot in an app window, with a camera that eases between
 * focus rectangles. Captures are 2x, so a push-in stays sharp.
 */
export const Shot: React.FC<Props> = ({
  src,
  keys,
  box = WINDOW,
  image = { width: 3200, height: 2000 },
  style,
  children,
}) => {
  const frame = useCurrentFrame();
  const at = keys.map((key) => key.at);
  const [x, y, w, h] = [0, 1, 2, 3].map((i) =>
    keys.length === 1
      ? keys[0].rect[i]
      : interpolate(frame, at, keys.map((key) => key.rect[i]), { ...clamp, easing: glide }),
  );
  const scale = Math.min(box.width / w, box.height / h);
  const offsetX = box.width / 2 - (x + w / 2) * scale;
  const offsetY = box.height / 2 - (y + h / 2) * scale;
  const place: Place = ([rx, ry, rw, rh]) => ({
    position: 'absolute',
    left: offsetX + rx * scale,
    top: offsetY + ry * scale,
    width: rw * scale,
    height: rh * scale,
  });
  const file = typeof src === 'function' ? src(frame) : src;

  return (
    <div
      style={{
        position: 'absolute',
        ...box,
        overflow: 'hidden',
        borderRadius: 20,
        background: '#F5F8F2',
        boxShadow: '0 50px 140px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.09)',
        ...style,
      }}
    >
      <Img
        src={staticFile(`screenshots/${file}.png`)}
        style={{
          position: 'absolute',
          left: offsetX,
          top: offsetY,
          width: image.width * scale,
          height: image.height * scale,
        }}
      />
      {children?.(place, frame)}
    </div>
  );
};
