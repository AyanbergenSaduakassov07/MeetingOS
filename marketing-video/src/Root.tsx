import { Composition, Still } from 'remotion';
import { MeetingOSLaunch } from './compositions/MeetingOSLaunch';
import { Thumbnail } from './compositions/Thumbnail';
import { FPS, T } from './theme';

export const Root: React.FC = () => (
  <>
    <Composition
      id="MeetingOSLaunch"
      component={MeetingOSLaunch}
      durationInFrames={T.end}
      fps={FPS}
      width={1920}
      height={1080}
    />
    <Still id="Thumbnail" component={Thumbnail} width={1920} height={1080} />
  </>
);
