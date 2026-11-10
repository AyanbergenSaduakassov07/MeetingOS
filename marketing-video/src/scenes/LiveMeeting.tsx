import { AbsoluteFill, interpolate, Sequence } from 'remotion';
import { Caption } from '../components/Brand';
import { type CameraKey, type Rect, Shot } from '../components/Shot';
import { type Box, C, clamp, useLayout } from '../theme';

// A real 22 s upload of the AMI pricing discussion, start to finish.
const CHECKED_AT = 66; // consent box ticked (score tick at 16.2 s)
const PROCESSING_AT = 110; // Upload pressed (score tick at 17.6 s)
const TRANSCRIPT_AT = 190;
// voice.wav starts 30 frames into the transcript; "...for 25 euro" begins 1.4 s later.
const SPOKEN_ROW = 1;
const SPOKEN_AT = 71;

const ROWS = 4;

type Cut = {
  dir: string;
  consent: CameraKey[];
  processing: CameraKey[];
  transcript: CameraKey[];
  transcriptBox?: Box;
  row: (row: number) => Rect;
  spoken: Rect;
};
// Desktop and phone-width captures of the same upload; camera and masks per capture.
const CUTS: Record<'landscape' | 'vertical', Cut> = {
  landscape: {
    dir: '',
    consent: [
      { at: 0, rect: [0, 0, 3200, 2000] },
      { at: 54, rect: [880, 500, 1440, 900] },
    ],
    processing: [
      { at: 0, rect: [880, 60, 1440, 900] },
      { at: 80, rect: [1080, 170, 1040, 650] },
    ],
    transcript: [
      { at: 0, rect: [120, 560, 1560, 975] },
      { at: 220, rect: [170, 630, 1330, 830] },
    ],
    row: (row) => [200, 690 + 128 * row, 2200, 116],
    spoken: [170, 690 + 128 * SPOKEN_ROW - 6, 1290, 112],
  },
  vertical: {
    dir: 'phone/',
    consent: [
      { at: 0, rect: [0, 300, 960, 1060] },
      { at: 54, rect: [30, 500, 900, 994] },
    ],
    processing: [
      { at: 0, rect: [0, 0, 960, 1060] },
      { at: 80, rect: [160, 180, 800, 883] },
    ],
    // The phone capture is scrolled sideways a little; framing starts right of the cut-off title.
    transcript: [
      { at: 0, rect: [160, 700, 800, 633] },
      { at: 220, rect: [175, 740, 740, 585] },
    ],
    // Four rows don't fill a 9:16 window; a shorter one keeps them centred.
    transcriptBox: { left: 60, top: 430, width: 960, height: 760 },
    row: (row) => [180, 780 + 130 * row, 760, 120],
    spoken: [172, 780 + 130 * SPOKEN_ROW - 8, 700, 116],
  },
};

const Transcript: React.FC<{ cut: Cut }> = ({ cut }) => (
  <Shot src={`${cut.dir}upload-transcript`} keys={cut.transcript} box={cut.transcriptBox}>
    {(place, frame) => (
      <>
        {Array.from({ length: ROWS }, (_, row) => (
          <div
            key={row}
            style={{
              ...place(cut.row(row)),
              background: C.page,
              opacity: interpolate(frame, [10 + row * 16, 24 + row * 16], [1, 0], clamp),
            }}
          />
        ))}
        <div
          style={{
            ...place(cut.spoken),
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
  const cut = CUTS[useLayout().vertical ? 'vertical' : 'landscape'];
  return (
    <AbsoluteFill style={{ background: C.stage }}>
      <Sequence durationInFrames={PROCESSING_AT} layout="none">
        <Shot
          src={(f) => cut.dir + (f < CHECKED_AT ? 'upload-consent' : 'upload-consent-checked')}
          keys={cut.consent}
        />
      </Sequence>
      <Sequence from={PROCESSING_AT} durationInFrames={TRANSCRIPT_AT - PROCESSING_AT} layout="none">
        <Shot src={`${cut.dir}upload-processing`} keys={cut.processing} />
      </Sequence>
      <Sequence from={TRANSCRIPT_AT} layout="none">
        <Transcript cut={cut} />
      </Sequence>
      <Caption step="01" text="Upload a recording." from={4} to={PROCESSING_AT} />
      <Caption
        step="01"
        text="It transcribes on its own."
        from={PROCESSING_AT}
        to={TRANSCRIPT_AT}
      />
      <Caption
        step="01"
        text="Every word timestamped. Click to hear it."
        from={TRANSCRIPT_AT}
        to={1e6}
      />
    </AbsoluteFill>
  );
};
