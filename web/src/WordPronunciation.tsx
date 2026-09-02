import { useEffect, useState } from "react";

import {
  speakLemma,
  speechLocaleAvailable,
  type SpeechLocale,
} from "./wordSpeech";

interface WordPronunciationProps {
  lemma: string;
}

export default function WordPronunciation({ lemma }: WordPronunciationProps) {
  const [usAvailable, setUsAvailable] = useState(false);
  const [ukAvailable, setUkAvailable] = useState(false);

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
    };
  }, []);

  const speak = (locale: SpeechLocale, available: boolean) => {
    if (!available) {
      return;
    }
    speakLemma(lemma, locale);
  };

  return (
    <div className="word-pronunciation" aria-label="单词发音">
      <button
        type="button"
        disabled={!lemma.trim() || !usAvailable}
        onClick={() => speak("en-US", usAvailable)}
        title={usAvailable ? "美式发音" : "当前设备没有美式发音"}
      >
        美式{usAvailable ? "" : "不可用"}
      </button>
      <button
        type="button"
        disabled={!lemma.trim() || !ukAvailable}
        onClick={() => speak("en-GB", ukAvailable)}
        title={ukAvailable ? "英式发音" : "当前设备没有英式发音"}
      >
        英式{ukAvailable ? "" : "不可用"}
      </button>
    </div>
  );
}
