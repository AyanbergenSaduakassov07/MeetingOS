import { AbsoluteFill } from 'remotion';
import { Shot } from '../components/Shot';
import { Lockup } from '../scenes/Closing';
import { C } from '../theme';

/** Reel cover, 1080x1920; the profile grid crops it to the middle 1080x1350. */
export const Cover: React.FC = () => (
  <AbsoluteFill style={{ background: C.stage, alignItems: 'center' }}>
    <div style={{ marginTop: 420 }}>
      <Lockup frame={120} scale={0.8} />
    </div>
    <Shot
      src="copilot-99-answer"
      box={{ left: 60, top: 760, width: 960, height: 700 }}
      keys={[{ at: 0, rect: [2432, 160, 768, 560] }]}
    />
  </AbsoluteFill>
);
