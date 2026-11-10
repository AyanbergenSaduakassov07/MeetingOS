import { AbsoluteFill, interpolate } from 'remotion';
import { Caption } from '../components/Brand';
import { type Rect, Shot } from '../components/Shot';
import { C, clamp } from '../theme';

// Frames of the real copilot UI streaming a recorded answer (see scripts/capture.py).
const TYPE_FROM = 18;
const TYPE_TO = 56;
const SEND_AT = 60; // score tick at 45.0 s
const PARTIAL_FROM = 72;
const PARTIAL_STEP = 5;
const PARTIALS = 13; // copilot-03 … copilot-15
const ANSWER_AT = PARTIAL_FROM + PARTIALS * PARTIAL_STEP; // 137, score tick at 47.57 s

// The question wraps onto two lines in the input: 39 + 9 characters.
const LINES: { rect: Rect; chars: number }[] = [
  { rect: [2478, 1672, 560, 48], chars: 39 },
  { rect: [2478, 1720, 560, 48], chars: 9 },
];
const TOTAL_CHARS = 48;

const frameFor = (frame: number) => {
  if (frame < TYPE_FROM) return 'copilot-00-empty';
  if (frame < SEND_AT) return 'copilot-01-typed';
  if (frame < PARTIAL_FROM) return 'copilot-02-thinking';
  if (frame < ANSWER_AT) {
    const step = Math.floor((frame - PARTIAL_FROM) / PARTIAL_STEP) + 3;
    return `copilot-${String(step).padStart(2, '0')}-partial`;
  }
  return 'copilot-99-answer';
};

export const Copilot: React.FC = () => (
  <AbsoluteFill style={{ background: C.stage }}>
    <Shot
      src={frameFor}
      keys={[
        { at: 0, rect: [0, 0, 3200, 2000] },
        { at: TYPE_FROM, rect: [1880, 1080, 1320, 825] },
        { at: SEND_AT, rect: [1880, 1080, 1320, 825] },
        { at: SEND_AT + 30, rect: [2400, 140, 800, 500] },
        { at: ANSWER_AT + 10, rect: [2400, 140, 800, 500] },
        { at: ANSWER_AT + 70, rect: [2420, 390, 800, 500] },
      ]}
    >
      {(place, frame) => {
        if (frame < TYPE_FROM || frame >= SEND_AT) return null;
        // Typing: uncover the captured question character by character.
        const typed = interpolate(frame, [TYPE_FROM, TYPE_TO], [0, TOTAL_CHARS], clamp);
        let before = 0;
        return LINES.map(({ rect, chars }) => {
          const shown = Math.min(1, Math.max(0, (typed - before) / chars));
          before += chars;
          const [x, y, w, h] = rect;
          return (
            <div
              key={y}
              style={{ ...place([x + w * shown, y, w * (1 - shown), h]), background: C.page }}
            />
          );
        });
      }}
    </Shot>
    <Caption step="03" text="Ask anything about the meeting." from={4} to={ANSWER_AT} />
    <Caption step="03" text="Every answer shows its sources." from={ANSWER_AT} to={1e6} />
  </AbsoluteFill>
);
