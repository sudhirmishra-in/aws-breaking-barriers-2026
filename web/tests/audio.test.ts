// LOCAL MOCK tests: pure audio helpers.
import { describe, expect, it } from "vitest";
import { concat, downsample, toBase64, toInt16Bytes } from "../src/lib/audio";

describe("audio helpers", () => {
  it("concatenates chunks", () => { expect(Array.from(concat([new Float32Array([1, 2]), new Float32Array([3])]))).toEqual([1, 2, 3]); });
  it("downsamples 48 kHz to 16 kHz by averaging (one third as many samples)", () => {
    const out = downsample(new Float32Array([0, 0.3, 0.6, 1, 1, 1]), 48000);
    expect(out.length).toBe(2); expect(out[0]).toBeCloseTo(0.3, 5); expect(out[1]).toBeCloseTo(1, 5);
  });
  it("keeps 16 kHz audio unchanged", () => { const a = new Float32Array([0.1, 0.2]); expect(downsample(a, 16000)).toBe(a); });
  it("converts to little-endian 16-bit with clipping", () => {
    const b = toInt16Bytes(new Float32Array([0, 1, -1, 2]));
    const v = new DataView(b.buffer);
    expect([v.getInt16(0, true), v.getInt16(2, true), v.getInt16(4, true), v.getInt16(6, true)]).toEqual([0, 32767, -32768, 32767]);
  });
  it("base64 encodes large buffers without overflowing the call stack", () => {
    const big = new Uint8Array(1_900_000).fill(7);
    expect(toBase64(big).length).toBe(Math.ceil(1_900_000 / 3) * 4);
  });
});
