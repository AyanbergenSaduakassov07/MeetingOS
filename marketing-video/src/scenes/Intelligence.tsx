import { AbsoluteFill, Img, interpolate, Sequence, staticFile, useCurrentFrame } from 'remotion';
import { Caption, Ring } from '../components/Brand';
import { Shot } from '../components/Shot';
import { C, clamp, fade, settle, WINDOW } from '../theme';

const CARDS_AT = 120;
const FOLLOW_UP_AT = 255;
const LANGUAGES_AT = 345;
const CARD_WIDTH = 1400;
const CARD_SOURCE_WIDTH = 2176; // element captures at 2x
const GAP = 28;

type Card = { name: string; height: number };

/** Real item cards from the meeting, lifted onto the stage. */
const CardStack: React.FC<{ cards: Card[]; until: number; ringAt?: number }> = ({
  cards,
  until,
  ringAt,
}) => {
  const frame = useCurrentFrame();
  const scale = CARD_WIDTH / CARD_SOURCE_WIDTH;
  const heights = cards.map((card) => card.height * scale);
  const total = heights.reduce((a, b) => a + b, 0) + GAP * (cards.length - 1);
  let top = WINDOW.top + (WINDOW.height - total) / 2;
  return (
    <AbsoluteFill style={{ opacity: fade(frame, 0, until, 10) }}>
      {cards.map((card, index) => {
        const enter = settle(frame, 4 + index * 7);
        const style: React.CSSProperties = {
          position: 'absolute',
          left: (1920 - CARD_WIDTH) / 2,
          top,
          width: CARD_WIDTH,
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
            <Img src={staticFile(`screenshots/${card.name}.png`)} style={{ width: '100%' }} />
            {ringAt !== undefined && (
              // The timestamp chip: every item seeks to the second it came from.
              <Ring
                at={ringAt + index * 6}
                style={{
                  position: 'absolute',
                  left: 2016 * scale,
                  top: 44 * scale,
                  width: 132 * scale,
                  height: 62 * scale,
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

export const Intelligence: React.FC = () => (
  <AbsoluteFill style={{ background: C.stage }}>
    <Sequence durationInFrames={CARDS_AT} layout="none">
      <Shot
        src="detail-summary"
        keys={[
          { at: 0, rect: [90, 520, 2520, 1470] },
          { at: CARDS_AT, rect: [180, 630, 2260, 1340] },
        ]}
      />
    </Sequence>
    <Sequence from={CARDS_AT} durationInFrames={FOLLOW_UP_AT - CARDS_AT} layout="none">
      <CardStack
        until={FOLLOW_UP_AT - CARDS_AT}
        ringAt={56}
        cards={[
          { name: 'card-price', height: 336 },
          { name: 'card-cost', height: 336 },
          { name: 'card-profit', height: 336 },
        ]}
      />
    </Sequence>
    <Sequence from={FOLLOW_UP_AT} durationInFrames={LANGUAGES_AT - FOLLOW_UP_AT} layout="none">
      <CardStack
        until={LANGUAGES_AT - FOLLOW_UP_AT}
        cards={[
          { name: 'card-risk', height: 376 },
          { name: 'card-action', height: 376 },
        ]}
      />
    </Sequence>
    <Sequence from={LANGUAGES_AT} layout="none">
      <Languages />
    </Sequence>
    <Caption step="02" text="Decisions, actions, risks, commitments." from={4} to={CARDS_AT} />
    <Caption step="02" text="Each one cites the moment it was said." from={CARDS_AT} to={FOLLOW_UP_AT} />
    <Caption step="02" text="Risks and next steps, too." from={FOLLOW_UP_AT} to={LANGUAGES_AT} />
    <Caption step="02" text="English. Русский. Қазақша." from={LANGUAGES_AT} to={1e6} />
  </AbsoluteFill>
);

const Languages: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      {(['lang-kk-transcript', 'lang-ru-transcript'] as const).map((src, index) => {
        const enter = settle(frame, index * 8);
        return (
          <Shot
            key={src}
            src={src}
            box={{ ...LANG_BOX, left: WINDOW.left + index * (LANG_BOX.width + 32) }}
            style={{ opacity: enter, translate: `0 ${interpolate(enter, [0, 1], [40, 0], clamp)}px` }}
            keys={[
              { at: 0, rect: [190, 540, 1340, 1414] },
              { at: 105, rect: [200, 570, 1200, 1267] },
            ]}
          />
        );
      })}
    </>
  );
};
