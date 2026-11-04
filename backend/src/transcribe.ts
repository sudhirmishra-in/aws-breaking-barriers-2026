import { StartStreamTranscriptionCommand, TranscribeStreamingClient } from "@aws-sdk/client-transcribe-streaming";
import type { Language } from "./contracts";

/** Speech to text port. Audio is held in memory for the request only: nothing is written anywhere. */
export interface Transcriber { transcribe(pcm: Uint8Array, language: Language): Promise<string> }

const LANGUAGE_CODE: Record<Language, "en-US" | "es-US"> = { en: "en-US", es: "es-US" };
const CHUNK_BYTES = 16000 * 2 * 0.2; // 200 ms of 16 kHz 16-bit mono PCM

export class TranscribeStreamingTranscriber implements Transcriber {
  private client = new TranscribeStreamingClient({});
  async transcribe(pcm: Uint8Array, language: Language): Promise<string> {
    async function* audio() {
      for (let i = 0; i < pcm.length; i += CHUNK_BYTES) yield { AudioEvent: { AudioChunk: pcm.subarray(i, i + CHUNK_BYTES) } };
    }
    const out = await this.client.send(new StartStreamTranscriptionCommand({
      LanguageCode: LANGUAGE_CODE[language], MediaSampleRateHertz: 16000, MediaEncoding: "pcm", AudioStream: audio(),
    }));
    const parts: string[] = [];
    for await (const ev of out.TranscriptResultStream ?? []) {
      for (const r of ev.TranscriptEvent?.Transcript?.Results ?? []) {
        if (!r.IsPartial && r.Alternatives?.[0]?.Transcript) parts.push(r.Alternatives[0].Transcript);
      }
    }
    return parts.join(" ").trim();
  }
}
