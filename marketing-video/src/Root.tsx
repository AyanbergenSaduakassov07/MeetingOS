import { Composition, Still } from 'remotion';
import { Cover } from './compositions/Cover';
import { MeetingOSLaunch, MeetingOSVertical } from './compositions/MeetingOSLaunch';
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
    <Composition
      id="MeetingOSVertical"
      component={MeetingOSVertical}
      durationInFrames={T.end}
      fps={FPS}
      width={1080}
      height={1920}
    />
    <Still id="Cover" component={Cover} width={1080} height={1920} />
  </>
);
