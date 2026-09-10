#!/usr/bin/env node

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');

function value(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
}

function required(name) {
  const result = value(name);
  if (!result) throw new Error(`Missing required argument ${name}`);
  return result;
}

function run(binary, args, options = {}) {
  const result = spawnSync(binary, args, { encoding: 'utf8', ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${binary} failed: ${result.stderr || ''}`.trim());
  return result.stdout.trim();
}

const audio = required('--audio');
const image = required('--image');
const output = required('--output');
const resolution = value('--resolution', '1920x1080');
const [width, height] = resolution.split('x').map(Number);
const fps = Number(value('--fps', '30'));
const duration = value('--duration');
const ffmpeg = value('--ffmpeg', process.env.FFMPEG_PATH || 'ffmpeg');
const ffprobe = value('--ffprobe', process.env.FFPROBE_PATH || 'ffprobe');
const preset = value('--preset', 'medium');
const crf = value('--crf', '18');
const audioBitrate = value('--audio-bitrate', '320k');
const glowOpacity = Math.max(0, Math.min(1, Number(value('--glow-opacity', '0.22'))));
const vignetteOpacity = Math.max(0, Math.min(1, Number(value('--vignette-opacity', '0.22'))));
const watermark = value('--watermark');
const watermarkOpacity = Math.max(0, Math.min(1, Number(value('--watermark-opacity', '0.75'))));

if (!Number.isInteger(width) || !Number.isInteger(height) || width < 2 || height < 2 || width % 2 || height % 2) {
  throw new Error(`Resolution must contain positive even dimensions: ${resolution}`);
}
if (!fs.existsSync(audio) || !fs.existsSync(image)) throw new Error('Audio and image files must exist.');
if (watermark && !fs.existsSync(watermark)) throw new Error(`Watermark does not exist: ${watermark}`);

const targetDuration = duration || run(ffprobe, ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio], { shell: false });
const spectrumHeight = Math.max(120, Math.round(height * 0.28));
const glowAlpha = glowOpacity.toFixed(3);
const vignetteAngle = (Math.PI * (0.18 + vignetteOpacity * 0.12)).toFixed(4);

const args = [
  '-y', '-loop', '1', '-framerate', String(fps), '-i', image,
  '-i', audio,
];
if (watermark) args.push('-loop', '1', '-i', watermark);

const bg = `[0:v]scale=${width}:${height}:force_original_aspect_ratio=increase:flags=lanczos,crop=${width}:${height},setsar=1[bg]`;
const spectrum = `[1:a]showspectrum=s=${width}x${spectrumHeight}:fps=${fps}:mode=combined:color=rainbow:scale=log:fscale=log:slide=replace:win_func=hann,format=rgba,colorkey=black:0.02:0.1[spec]`;
const glow = `[spec]split[sharp][blur];[blur]gblur=sigma=${Math.max(2, Math.round(width / 480))}:steps=2,colorchannelmixer=aa=${glowAlpha}[glow]`;
const composite = `[bg][glow]overlay=x=(W-w)/2:y=H-h-${Math.round(height * 0.07)}:format=auto[glowed];[glowed][sharp]overlay=x=(W-w)/2:y=H-h-${Math.round(height * 0.07)}:format=auto[viz];[viz]vignette=${vignetteAngle}:mode=forward[styled]`;
let graph = `${bg};${spectrum};${glow};${composite}`;
let videoLabel = 'styled';
if (watermark) {
  const markWidth = Math.max(48, Math.round(width * 0.1));
  graph += `;[2:v]scale=${markWidth}:-1,format=rgba,colorchannelmixer=aa=${watermarkOpacity.toFixed(3)}[mark];[styled][mark]overlay=x=W-w-${Math.round(width * 0.02)}:y=H-h-${Math.round(height * 0.02)}:format=auto[final]`;
  videoLabel = 'final';
}

args.push(
  '-filter_complex', graph,
  '-map', `[${videoLabel}]`, '-map', '1:a:0',
  '-t', String(targetDuration), '-r', String(fps),
  '-c:v', 'libx264', '-preset', preset, '-crf', crf, '-tune', 'stillimage',
  '-pix_fmt', 'yuv420p', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
  '-c:a', 'aac', '-b:a', audioBitrate, '-shortest', output,
);

const result = spawnSync(ffmpeg, args, { stdio: 'inherit' });
process.exit(result.status ?? 1);