import { PollyClient, SynthesizeSpeechCommand, type VoiceId } from "@aws-sdk/client-polly";
import type { Language } from "./contracts";

/** Text to speech port. Audio is produced per request and never stored. */
export interface Speaker { speak(text: string, language: Language): Promise<{ audio: Uint8Array; voice: string }> }

// Neural voices verified available in the sandbox region (us-west-2).
const VOICE: Record<Language, { id: VoiceId; code: "en-US" | "es-US" | "fr-FR" }> = {
  en: { id: "Joanna", code: "en-US" },
  es: { id: "Lupe", code: "es-US" },
  fr: { id: "Lea", code: "fr-FR" },
};
export const MAX_SPOKEN_CHARS = 2800; // Polly allows 3000 billed characters per request

/** Turns the agent's light markdown into plain spoken text. */
export function toSpokenText(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1$2")
    .replace(/^\s*[-*]\s+/gm, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{2,}/g, "\n")
    .trim();
}

/** Splits long text at sentence boundaries so each piece fits one Polly request. */
export function chunkText(text: string, max = MAX_SPOKEN_CHARS): string[] {
  if (text.length <= max) return [text];
  const parts: string[] = []; let cur = "";
  for (const sentence of text.match(/[^.!?\n]+[.!?]*\s*/g) ?? [text]) {
    if ((cur + sentence).length > max && cur) { parts.push(cur.trim()); cur = ""; }
    cur += sentence.length > max ? sentence.slice(0, max) : sentence;
  }
  if (cur.trim()) parts.push(cur.trim());
  return parts;
}

export class PollySpeaker implements Speaker {
  private client = new PollyClient({});
  async speak(text: string, language: Language) {
    const v = VOICE[language];
    const pieces: Uint8Array[] = [];
    for (const part of chunkText(text)) {
      const out = await this.client.send(new SynthesizeSpeechCommand({ Engine: "neural", VoiceId: v.id, LanguageCode: v.code, OutputFormat: "mp3", SampleRate: "24000", Text: part }));
      pieces.push(await out.AudioStream!.transformToByteArray());
    }
    // MP3 frames can be concatenated back to back.
    const audio = new Uint8Array(pieces.reduce((n, p) => n + p.length, 0));
    let o = 0; for (const p of pieces) { audio.set(p, o); o += p.length; }
    return { audio, voice: v.id };
  }
}
