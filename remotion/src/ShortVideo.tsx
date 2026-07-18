import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';

export type Word = {word: string; start: number; end: number};

export type ShortProps = {
  width: number;
  height: number;
  fps: number;
  durationSec: number;
  clips: string[];
  clipSec: number;
  transitionSec: number;
  words: Word[];
  hook: string | null;
  captions: {
    font: string;
    fontSize: number;
    wordsPerChunk: number;
    primary: string;
    highlight: string;
  };
  voice: string;
  music: string | null;
  musicVolume: number;
  logo: string | null;
  logoVolume: number;
};

export const defaultShortProps: ShortProps = {
  width: 1080,
  height: 1920,
  fps: 30,
  durationSec: 45,
  clips: [],
  clipSec: 9.5,
  transitionSec: 0.35,
  words: [],
  hook: null,
  captions: {font: 'Arial Black', fontSize: 88, wordsPerChunk: 3, primary: '#ffffff', highlight: '#FFD700'},
  voice: '',
  music: null,
  musicVolume: 0.06,
  logo: null,
  logoVolume: 0.5,
};

const OUTLINE =
  '0 0 14px rgba(0,0,0,0.85), 3px 3px 0 #000, -3px 3px 0 #000, 3px -3px 0 #000, ' +
  '-3px -3px 0 #000, 0 4px 0 #000, 0 -4px 0 #000, 4px 0 0 #000, -4px 0 0 #000';

type Chunk = {words: Word[]; start: number; end: number};

const chunkWords = (words: Word[], per: number): Chunk[] => {
  const chunks: Chunk[] = [];
  for (let i = 0; i < words.length; i += per) {
    const group = words.slice(i, i + per);
    chunks.push({words: group, start: group[0].start, end: group[group.length - 1].end});
  }
  // each chunk stays on screen until the next one begins
  for (let i = 0; i < chunks.length - 1; i++) chunks[i].end = chunks[i + 1].start;
  if (chunks.length) chunks[chunks.length - 1].end += 1.0;
  return chunks;
};

const Captions = ({words, captions}: {words: Word[]; captions: ShortProps['captions']}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const chunks = chunkWords(words, Math.max(1, captions.wordsPerChunk));
  const active = chunks.find((c) => t >= c.start && t < c.end);
  if (!active) return null;
  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center'}}>
      <div
        style={{
          marginBottom: '28%',
          maxWidth: '86%',
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          gap: '0.28em',
          fontFamily: `'${captions.font}', 'Arial Black', Arial, sans-serif`,
          fontSize: captions.fontSize,
          fontWeight: 900,
          textTransform: 'uppercase',
          lineHeight: 1.15,
          textAlign: 'center',
        }}
      >
        {active.words.map((w, i) => {
          const spoken = t >= w.start;
          const pop = spoken
            ? interpolate(t - w.start, [0, 0.09, 0.2], [0.85, 1.12, 1], {
                extrapolateRight: 'clamp',
              })
            : 1;
          return (
            <span
              key={`${w.start}-${i}`}
              style={{
                color: spoken ? captions.highlight : captions.primary,
                textShadow: OUTLINE,
                transform: `scale(${pop})`,
                display: 'inline-block',
              }}
            >
              {w.word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const HookCard = ({hook, captions}: {hook: string; captions: ShortProps['captions']}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const opacity = interpolate(t, [0, 0.25, 2.1, 2.5], [0, 1, 1, 0], {
    extrapolateRight: 'clamp',
  });
  const slide = interpolate(t, [0, 0.35], [26, 0], {extrapolateRight: 'clamp'});
  if (t > 2.6) return null;
  return (
    <AbsoluteFill style={{alignItems: 'center', opacity}}>
      <div
        style={{
          marginTop: '14%',
          maxWidth: '88%',
          transform: `translateY(${slide}px)`,
          fontFamily: `'${captions.font}', 'Arial Black', Arial, sans-serif`,
          fontSize: captions.fontSize * 0.92,
          fontWeight: 900,
          textTransform: 'uppercase',
          textAlign: 'center',
          lineHeight: 1.18,
          color: '#ffffff',
          textShadow: OUTLINE,
          backgroundColor: 'rgba(0,0,0,0.42)',
          padding: '0.35em 0.5em',
          borderRadius: 18,
        }}
      >
        {hook}
      </div>
    </AbsoluteFill>
  );
};

export const ShortVideo = (props: ShortProps) => {
  const {fps} = useVideoConfig();
  const clipFrames = Math.max(1, Math.round(props.clipSec * fps));
  const transFrames = Math.max(1, Math.round(props.transitionSec * fps));

  const series: JSX.Element[] = [];
  props.clips.forEach((clip, i) => {
    const isLast = i === props.clips.length - 1;
    series.push(
      <TransitionSeries.Sequence
        key={`clip-${i}`}
        // generous tail on the last clip so rounding never shows black
        durationInFrames={isLast ? clipFrames + fps : clipFrames}
      >
        <OffthreadVideo
          muted
          src={staticFile(clip)}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      </TransitionSeries.Sequence>
    );
    if (!isLast) {
      series.push(
        <TransitionSeries.Transition
          key={`trans-${i}`}
          presentation={fade()}
          timing={linearTiming({durationInFrames: transFrames})}
        />
      );
    }
  });

  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      <TransitionSeries>{series}</TransitionSeries>

      {props.hook ? <HookCard hook={props.hook} captions={props.captions} /> : null}
      <Captions words={props.words} captions={props.captions} />

      {props.voice ? <Audio src={staticFile(props.voice)} /> : null}
      {props.music ? <Audio loop src={staticFile(props.music)} volume={props.musicVolume} /> : null}
      {props.logo ? (
        <Sequence from={0}>
          <Audio src={staticFile(props.logo)} volume={props.logoVolume} />
        </Sequence>
      ) : null}
    </AbsoluteFill>
  );
};
