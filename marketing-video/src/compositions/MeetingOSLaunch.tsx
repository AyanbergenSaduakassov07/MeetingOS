import { Audio } from '@remotion/media';
import { AbsoluteFill, interpolate, Sequence, staticFile, useCurrentFrame } from 'remotion';
import { Closing } from '../scenes/Closing';
import { Copilot } from '../scenes/Copilot';
import { Intelligence } from '../scenes/Intelligence';
import { LiveMeeting } from '../scenes/LiveMeeting';
import { Opening } from '../scenes/Opening';
import { ProductReveal } from '../scenes/ProductReveal';
import { C, clamp, T } from '../theme';

// The AMI speaker under the transcript shot (public/audio/voice.wav, 6.5 s).
const VOICE_AT = T.workflow + 220;
const VOICE_FRAMES = 195;

const SCENES = [
  { from: T.opening, to: T.reveal, Scene: Opening },
  { from: T.reveal, to: T.workflow, Scene: ProductReveal },
  { from: T.workflow, to: T.intelligence, Scene: LiveMeeting },
  { from: T.intelligence, to: T.copilot, Scene: Intelligence },
  { from: T.copilot, to: T.closing, Scene: Copilot },
  { from: T.closing, to: T.end, Scene: Closing },
];

/** Each scene rises out of the stage colour, so cuts land soft on the score's hits. */
const SoftIn: React.FC<{ children: React.ReactNode; skip: boolean }> = ({ children, skip }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ opacity: skip ? 1 : interpolate(frame, [0, 7], [0, 1], clamp) }}>
      {children}
    </AbsoluteFill>
  );
};

export const MeetingOSLaunch: React.FC = () => {
  const frame = useCurrentFrame();
  const duck = interpolate(
    frame,
    [VOICE_AT - 10, VOICE_AT, VOICE_AT + VOICE_FRAMES - 10, VOICE_AT + VOICE_FRAMES + 10],
    [1, 0.45, 0.45, 1],
    clamp,
  );
  return (
    <AbsoluteFill style={{ background: C.stage }}>
      {SCENES.map(({ from, to, Scene }) => (
        <Sequence key={from} from={from} durationInFrames={to - from}>
          <SoftIn skip={from === T.opening}>
            <Scene />
          </SoftIn>
        </Sequence>
      ))}
      <Audio src={staticFile('audio/score.wav')} volume={0.9 * duck} />
      <Sequence from={VOICE_AT} durationInFrames={VOICE_FRAMES}>
        <Audio src={staticFile('audio/voice.wav')} volume={1} />
      </Sequence>
    </AbsoluteFill>
  );
};
