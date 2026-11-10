import { AbsoluteFill, Img, interpolate, Sequence, staticFile, useCurrentFrame } from 'remotion';
import { Caption, Ring } from '../components/Brand';
import { Shot } from '../components/Shot';
import { C, clamp, fade, settle, useLayout } from '../theme';

const CARDS_AT = 120;
const FOLLOW_UP_AT = 255;
const LANGUAGES_AT = 345;
const CARD_WIDTH = 1400;
// Element captures at 2x: desktop cards and phone-width cards, with the timestamp chip in each.
const SOURCE = {
  landscape: { dir: '', width: 2176, chip: [2016, 44, 132, 62] },
  vertical: { dir: 'phone/', width: 704, chip: [556, 118, 108, 50] },
};
const GAP = 28;

type Card = { name: string; height: number };

/** Real item cards from the meeting, lifted onto the stage. */
const CardStack: React.FC<{ cards: Card[]; until: number; ringAt?: number }> = ({
  cards,
  until,
  ringAt,
}) => {
  const frame = useCurrentFrame();
  const { vertical, window: win, width: stage } = useLayout();
  const source = SOURCE[vertical ? 'vertical' : 'landscape'];
  const sum = cards.reduce((total, card) => total + card.height, 0);
  // Vertical: as wide as the window allows while the stack still fits its height.
  const scale = vertical
    ? Math.min(win.width / source.width, (win.height - GAP * (cards.length - 1)) / sum)
    : CARD_WIDTH / source.width;
  const cardWidth = source.width * scale;
  const heights = cards.map((card) => card.height * scale);
  const total = heights.reduce((a, b) => a + b, 0) + GAP * (cards.length - 1);
  let top = win.top + (win.height - total) / 2;
  return (
    <AbsoluteFill style={{ opacity: fade(frame, 0, until, 10) }}>
      {cards.map((card, index) => {
        const enter = settle(frame, 4 + index * 7);
        const style: React.CSSProperties = {
          position: 'absolute',
          left: (stage - cardWidth) / 2,
          top,
          width: cardWidth,
          height: heights[index],
          borderRadius: 16,
          overflow: 'hidden',
          boxShadow: '0 30px 80px rgba(0,0,0,0.5)',
          opacity: enter,
          translate: `0 ${interpolate(enter, [0, 1], [46, 0])}px`,
        };
        top += heights[index] + GAP;
        return (
          <div key={card.name} style={style}>
            <Img
              src={staticFile(`screenshots/${source.dir}${card.name}.png`)}
              style={{ width: '100%' }}
            />
            {ringAt !== undefined && (
              // The timestamp chip: every item seeks to the second it came from.
              <Ring
                at={ringAt + index * 6}
                style={{
                  position: 'absolute',
                  left: source.chip[0] * scale,
                  top: source.chip[1] * scale,
                  width: source.chip[2] * scale,
                  height: source.chip[3] * scale,
                }}
              />
            )}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

const LANG_BOX = { top: 200, width: 720, height: 760 };

// Phone-width card heights (px at 2x). Three cards don't fit a 9:16 window legibly, so the
// vertical cut shows the price and cost decisions only.
const VERTICAL_DECISIONS = [
  { name: 'card-price', height: 520 },
  { name: 'card-cost', height: 480 },
];
const VERTICAL_FOLLOW_UPS = [
  { name: 'card-risk', height: 604 },
  { name: 'card-action', height: 684 },
];

export const Intelligence: React.FC = () => {
  const { vertical } = useLayout();
  return (
    <AbsoluteFill style={{ background: C.stage }}>
      <Sequence durationInFrames={CARDS_AT} layout="none">
        {vertical ? (
          <Shot
            src="phone/detail-summary"
            keys={[
              { at: 0, rect: [160, 810, 800, 883] },
              { at: CARDS_AT, rect: [190, 840, 740, 817] },
            ]}
          />
        ) : (
          <Shot
            src="detail-summary"
            keys={[
              { at: 0, rect: [90, 520, 2520, 1470] },
              { at: CARDS_AT, rect: [180, 630, 2260, 1340] },
            ]}
          />
        )}
      </Sequence>
      <Sequence from={CARDS_AT} durationInFrames={FOLLOW_UP_AT - CARDS_AT} layout="none">
        <CardStack
          until={FOLLOW_UP_AT - CARDS_AT}
          ringAt={56}
          cards={
            vertical
              ? VERTICAL_DECISIONS
              : [
                  { name: 'card-price', height: 336 },
                  { name: 'card-cost', height: 336 },
                  { name: 'card-profit', height: 336 },
                ]
          }
        />
      </Sequence>
      <Sequence from={FOLLOW_UP_AT} durationInFrames={LANGUAGES_AT - FOLLOW_UP_AT} layout="none">
        <CardStack
          until={LANGUAGES_AT - FOLLOW_UP_AT}
          cards={
            vertical
              ? VERTICAL_FOLLOW_UPS
              : [
                  { name: 'card-risk', height: 376 },
                  { name: 'card-action', height: 376 },
                ]
          }
        />
      </Sequence>
      <Sequence from={LANGUAGES_AT} layout="none">
        <Languages />
      </Sequence>
      <Caption step="02" text="Decisions, actions, risks, commitments." from={4} to={CARDS_AT} />
      <Caption
        step="02"
        text="Each one cites the moment it was said."
        from={CARDS_AT}
        to={FOLLOW_UP_AT}
      />
      <Caption step="02" text="Risks and next steps, too." from={FOLLOW_UP_AT} to={LANGUAGES_AT} />
      <Caption step="02" text="English. Русский. Қазақша." from={LANGUAGES_AT} to={1e6} />
    </AbsoluteFill>
  );
};

// Vertical: the two transcripts stacked in the window.
const VERTICAL_LANG = { left: 60, width: 960, height: 510, gap: 40 };

const Languages: React.FC = () => {
  const frame = useCurrentFrame();
  const { vertical, window: win } = useLayout();
  return (
    <>
      {(['lang-kk-transcript', 'lang-ru-transcript'] as const).map((src, index) => {
        const enter = settle(frame, index * 8);
        return (
          <Shot
            key={src}
            src={vertical ? `phone/${src}` : src}
            box={
              vertical
                ? {
                    left: VERTICAL_LANG.left,
                    top: win.top + index * (VERTICAL_LANG.height + VERTICAL_LANG.gap),
                    width: VERTICAL_LANG.width,
                    height: VERTICAL_LANG.height,
                  }
                : { ...LANG_BOX, left: win.left + index * (LANG_BOX.width + 32) }
            }
            style={{
              opacity: enter,
              translate: `0 ${interpolate(enter, [0, 1], [40, 0], clamp)}px`,
            }}
            keys={
              vertical
                ? [
                    { at: 0, rect: [200, 770, 760, 404] },
                    { at: 105, rect: [215, 775, 700, 372] },
                  ]
                : [
                    { at: 0, rect: [190, 540, 1340, 1414] },
                    { at: 105, rect: [200, 570, 1200, 1267] },
                  ]
            }
          />
        );
      })}
    </>
  );
};
