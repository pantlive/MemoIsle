import { useEffect, useRef, useState } from "react";

import { synthesizeSpeech } from "./api";
import {
  speakLemma,
  speechLocaleAvailable,
  type SpeechLocale,
} from "./wordSpeech";

interface WordPronunciationProps {
  lemma: string;
  phonetic?: string | null;
  usAudioUrl?: string | null;
  ukAudioUrl?: string | null;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export default function WordPronunciation({
  lemma,
  phonetic,
  usAudioUrl,
  ukAudioUrl,
}: WordPronunciationProps) {
  const [usAvailable, setUsAvailable] = useState(false);
  const [ukAvailable, setUkAvailable] = useState(false);
  const [playing, setPlaying] = useState<SpeechLocale | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const inflightRef = useRef<{ cancel: () => void } | null>(null);
  const playGeneration = useRef(0);

  const stopAudio = () => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    audioRef.current = null;
  };

  const cancelInflight = () => {
    inflightRef.current?.cancel();
    inflightRef.current = null;
    stopAudio();
  };

  useEffect(() => {
    const refresh = () => {
      setUsAvailable(speechLocaleAvailable("en-US"));
      setUkAvailable(speechLocaleAvailable("en-GB"));
    };
    refresh();
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      return () => {
        playGeneration.current += 1;
        cancelInflight();
      };
    }
    window.speechSynthesis.addEventListener("voiceschanged", refresh);
    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", refresh);
      playGeneration.current += 1;
      cancelInflight();
    };
  }, []);

  const playUrl = (url: string) =>
    new Promise<void>((resolve, reject) => {
      const audio = new Audio(url);
      audioRef.current = audio;
      let settled = false;
      const finish = (error?: Error) => {
        if (settled) {
          return;
        }
        settled = true;
        inflightRef.current = null;
        audio.onended = null;
        audio.onerror = null;
        if (audioRef.current === audio) {
          audioRef.current = null;
        }
        if (error) {
          audio.pause();
          reject(error);
          return;
        }
        setPlaying(null);
        resolve();
      };
      inflightRef.current = {
        cancel: () =>
          finish(new DOMException("The operation was aborted.", "AbortError")),
      };
      audio.onended = () => finish();
      audio.onerror = () => finish(new Error("audio error"));
      audio.play().catch((error: unknown) => {
        finish(error instanceof Error ? error : new Error("audio error"));
      });
    });

  const cleaned = lemma.trim();
  const canPlay = Boolean(cleaned);
  const resolvedUsAudio = usAudioUrl?.trim() || null;
  const resolvedUkAudio = ukAudioUrl?.trim() || null;

  const speak = async (
    locale: SpeechLocale,
    available: boolean,
    audioUrl?: string | null,
  ) => {
    if (!cleaned) {
      return;
    }
    const token = ++playGeneration.current;
    cancelInflight();
    if (audioUrl) {
      try {
        setPlaying(locale);
        await playUrl(audioUrl);
        return;
      } catch (error) {
        if (isAbortError(error) || token !== playGeneration.current) {
          return;
        }
      }
    }
    try {
      setPlaying(locale);
      const audioBlob = await synthesizeSpeech(lemma);
      if (token !== playGeneration.current) {
        return;
      }
      const objectUrl = URL.createObjectURL(audioBlob);
      try {
        await playUrl(objectUrl);
      } finally {
        URL.revokeObjectURL(objectUrl);
      }
      return;
    } catch (error) {
      if (isAbortError(error) || token !== playGeneration.current) {
        return;
      }
    }
    if (available) {
      setPlaying(locale);
      speakLemma(lemma, locale);
      window.setTimeout(() => setPlaying(null), 1_200);
      return;
    }
    setPlaying(null);
  };

  return (
    <div className="word-pronunciation" aria-label="单词发音">
      {phonetic?.trim() ? (
        <button
          type="button"
          className="word-phonetic-play"
          disabled={!canPlay}
          onClick={() => void speak("en-US", usAvailable, resolvedUsAudio)}
          title="点击音标播放美式读音"
        >
          {playing === "en-US" ? "播放中…" : phonetic.trim()}
        </button>
      ) : null}
      <button
        type="button"
        disabled={!canPlay}
        onClick={() => void speak("en-US", usAvailable, resolvedUsAudio)}
        title="美式读音"
      >
        {playing === "en-US" && !phonetic?.trim() ? "播放中…" : "▶美"}
      </button>
      <button
        type="button"
        disabled={!canPlay}
        onClick={() => void speak("en-GB", ukAvailable, resolvedUkAudio)}
        title="英式读音"
      >
        {playing === "en-GB" ? "播放中…" : "▶英"}
      </button>
    </div>
  );
}
