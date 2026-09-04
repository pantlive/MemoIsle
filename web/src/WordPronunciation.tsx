import { useEffect, useRef, useState } from "react";

import {
  speakLemma,
  speechLocaleAvailable,
  type SpeechLocale,
} from "./wordSpeech";

interface WordPronunciationProps {
  lemma: string;
  usAudioUrl?: string | null;
  ukAudioUrl?: string | null;
}

export default function WordPronunciation({
  lemma,
  usAudioUrl,
  ukAudioUrl,
}: WordPronunciationProps) {
  const [usAvailable, setUsAvailable] = useState(false);
  const [ukAvailable, setUkAvailable] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const refresh = () => {
      setUsAvailable(speechLocaleAvailable("en-US"));
      setUkAvailable(speechLocaleAvailable("en-GB"));
    };
    refresh();
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      return;
    }
    window.speechSynthesis.addEventListener("voiceschanged", refresh);
    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", refresh);
      audioRef.current?.pause();
    };
  }, []);

  const speak = async (
    locale: SpeechLocale,
    available: boolean,
    audioUrl?: string | null,
  ) => {
    if (!lemma.trim()) {
      return;
    }
    if (audioUrl) {
      audioRef.current?.pause();
      const audio = new Audio(audioUrl);
      audioRef.current = audio;
      try {
        await audio.play();
        return;
      } catch {
        audioRef.current = null;
      }
    }
    if (available) {
      speakLemma(lemma, locale);
    }
  };

  return (
    <div className="word-pronunciation" aria-label="单词发音">
      <button
        type="button"
        disabled={!lemma.trim() || (!usAvailable && !usAudioUrl)}
        onClick={() => void speak("en-US", usAvailable, usAudioUrl)}
        title={usAudioUrl ? "美式词典音源" : "美式系统发音"}
      >
        美式
      </button>
      <button
        type="button"
        disabled={!lemma.trim() || (!ukAvailable && !ukAudioUrl)}
        onClick={() => void speak("en-GB", ukAvailable, ukAudioUrl)}
        title={ukAudioUrl ? "英式词典音源" : "英式系统发音"}
      >
        英式
      </button>
    </div>
  );
}
