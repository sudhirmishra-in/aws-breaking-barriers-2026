/** Pure helpers for turning microphone samples into what the API expects: 16 kHz, 16-bit, mono PCM, base64. */
export const TARGET_RATE = 16000;
export const MAX_SECONDS = 60;
export const MIN_SECONDS = 0.3;

export function concat(chunks: Float32Array[]): Float32Array {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0));
  let o = 0; for (const c of chunks) { out.set(c, o); o += c.length; }
  return out;
}

/** Averages source samples that fall into each target sample (a simple low-pass downsample). */
export function downsample(input: Float32Array, fromRate: number, toRate = TARGET_RATE): Float32Array {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio), end = Math.min(Math.floor((i + 1) * ratio), input.length);
    let sum = 0; for (let j = start; j < end; j++) sum += input[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

export function toInt16Bytes(input: Float32Array): Uint8Array {
  const out = new Uint8Array(input.length * 2); const view = new DataView(out.buffer);
  for (let i = 0; i < input.length; i++) { const s = Math.max(-1, Math.min(1, input[i])); view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true); }
  return out;
}

export function toBase64(bytes: Uint8Array): string {
  let bin = ""; for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

export const seconds = (samples: number, rate: number) => samples / rate;
