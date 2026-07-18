import {Composition} from 'remotion';
import {ShortVideo, ShortProps, defaultShortProps} from './ShortVideo';

export const RemotionRoot = () => {
  return (
    <Composition
      id="Short"
      component={ShortVideo}
      durationInFrames={1350}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={defaultShortProps as ShortProps}
      calculateMetadata={({props}) => ({
        durationInFrames: Math.max(1, Math.round(props.durationSec * props.fps)),
        fps: props.fps,
        width: props.width,
        height: props.height,
      })}
    />
  );
};
