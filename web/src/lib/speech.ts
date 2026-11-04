// Plays agent replies through the Web Audio API. Using Web Audio (rather than an <audio> element with a
// blob: URL) keeps the site's content-security policy unchanged, and resuming the AudioContext during a tap
// "unlocks" sound so later replies can play automatically, including on iPhone Safari.
let ctx: AudioContext | undefined;
let current: AudioBufferSourceNode | undefined;

export const audioSupported = typeof window !== "undefined" && typeof window.AudioContext !== "undefined";

/** Call from a user gesture (a click or tap) so the browser allows sound afterwards. */
export function unlockAudio() {
  if (!audioSupported) return;
  ctx ??= new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
}

export function stopAudio() {
  try { current?.stop(); } catch { /* already stopped */ }
  current = undefined;
}

/** Decodes base64 MP3 and plays it; resolves when playback ends or is stopped. */
export async function playMp3(base64: string): Promise<void> {
  unlockAudio();
  stopAudio();
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const buffer = await ctx!.decodeAudioData(bytes.buffer);
  await new Promise<void>((resolve) => {
    const src = ctx!.createBufferSource();
    src.buffer = buffer; src.connect(ctx!.destination);
    src.onended = () => { if (current === src) current = undefined; resolve(); };
    current = src; src.start();
  });
}
