import { AbsoluteFill } from 'remotion';
import { Shot } from '../components/Shot';
import { Lockup } from '../scenes/Closing';
import { C } from '../theme';

/** LinkedIn cover: the lockup over the real copilot answer with its sources. */
export const Thumbnail: React.FC = () => (
  <AbsoluteFill style={{ background: C.stage, alignItems: 'center' }}>
    <div style={{ marginTop: 110 }}>
      <Lockup frame={120} scale={0.78} />
    </div>
    <Shot
      src="copilot-99-answer"
      box={{ left: 330, top: 470, width: 1260, height: 520 }}
      keys={[{ at: 0, rect: [2445, 250, 755, 312] }]}
    />
  </AbsoluteFill>
);
