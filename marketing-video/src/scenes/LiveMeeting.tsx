import { AbsoluteFill, interpolate, Sequence } from 'remotion';
import { Caption } from '../components/Brand';
import { Shot } from '../components/Shot';
import { C, clamp } from '../theme';

// A real 22 s upload of the AMI pricing discussion, start to finish.
const CHECKED_AT = 66; // consent box ticked (score tick at 16.2 s)
const PROCESSING_AT = 110; // Upload pressed (score tick at 17.6 s)
const TRANSCRIPT_AT = 190;
// voice.wav starts 30 frames into the transcript; "...for 25 euro" begins 1.4 s later.
const SPOKEN_ROW = 1;
const SPOKEN_AT = 71;

const ROWS = 4;
const rowRect = (row: number): [number, number, number, number] => [
  200,
  690 + 128 * row,
  2200,
  116,
];

const Transcript: React.FC = () => (
  <Shot
    src="upload-transcript"
    keys={[
      { at: 0, rect: [120, 560, 1560, 975] },
      { at: 220, rect: [170, 630, 1330, 830] },
    ]}
  >
    {(place, frame) => (
      <>
        {Array.from({ length: ROWS }, (_, row) => (
          <div
            key={row}
            style={{
              ...place(rowRect(row)),
              background: C.page,
              opacity: interpolate(frame, [10 + row * 16, 24 + row * 16], [1, 0], clamp),
            }}
          />
        ))}
        <div
          style={{
            ...place([170, 690 + 128 * SPOKEN_ROW - 6, 1290, 112]),
            borderRadius: 14,
            background: C.lime,
            mixBlendMode: 'multiply',
            opacity: 0.38 * interpolate(frame, [SPOKEN_AT, SPOKEN_AT + 10], [0, 1], clamp),
          }}
        />
      </>
    )}
  </Shot>
);

export const LiveMeeting: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: C.stage }}>
      <Sequence durationInFrames={PROCESSING_AT} layout="none">
        <Shot
          src={(f) => (f < CHECKED_AT ? 'upload-consent' : 'upload-consent-checked')}
          keys={[
            { at: 0, rect: [0, 0, 3200, 2000] },
            { at: 54, rect: [880, 500, 1440, 900] },
          ]}
        />
      </Sequence>
      <Sequence from={PROCESSING_AT} durationInFrames={TRANSCRIPT_AT - PROCESSING_AT} layout="none">
        <Shot
          src="upload-processing"
          keys={[
            { at: 0, rect: [880, 60, 1440, 900] },
            { at: 80, rect: [1080, 170, 1040, 650] },
          ]}
        />
      </Sequence>
      <Sequence from={TRANSCRIPT_AT} layout="none">
        <Transcript />
      </Sequence>
      <Caption step="01" text="Upload a recording." from={4} to={PROCESSING_AT} />
      <Caption step="01" text="It transcribes on its own." from={PROCESSING_AT} to={TRANSCRIPT_AT} />
      <Caption
        step="01"
        text="Every word timestamped. Click to hear it."
        from={TRANSCRIPT_AT}
        to={1e6}
      />
    </AbsoluteFill>
  );
};
