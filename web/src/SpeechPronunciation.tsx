import { useEffect, useRef, useState } from "react";

import { synthesizeSpeech } from "./api";
import Icon from "./Icon";
import { speakText } from "./wordSpeech";

interface SpeechPronunciationProps {
  text: string;
  label?: string;
}

/** 播放句子或灵感正文，优先使用服务端 sanoTTS，失败时回退浏览器 TTS。 */
export default function SpeechPronunciation({
  text,
  label = "播放语音",
}: SpeechPronunciationProps) {
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      audioRef.current?.pause();
      audioRef.current = null;
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, []);

  const stopAudio = () => {
    audioRef.current?.pause();
    audioRef.current = null;
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  };

  const play = async () => {
    const cleaned = text.trim();
    if (!cleaned || playing) {
      return;
    }
    stopAudio();
    setPlaying(true);
    try {
      const audioBlob = await synthesizeSpeech(cleaned);
      if (!aliveRef.current) {
        return;
      }
      const objectUrl = URL.createObjectURL(audioBlob);
      objectUrlRef.current = objectUrl;
      const audio = new Audio(objectUrl);
      audioRef.current = audio;
      const release = () => {
        if (objectUrlRef.current === objectUrl) {
          URL.revokeObjectURL(objectUrl);
          objectUrlRef.current = null;
        }
        if (audioRef.current === audio) {
          audioRef.current = null;
        }
        if (aliveRef.current) {
          setPlaying(false);
        }
      };
      audio.onended = release;
      audio.onerror = release;
      await audio.play();
      return;
    } catch {
      stopAudio();
    }
    if (!aliveRef.current) {
      return;
    }
    const browserPlayed = speakText(cleaned, "en-US", () => {
      if (aliveRef.current) {
        setPlaying(false);
      }
    });
    if (!browserPlayed) {
      setPlaying(false);
    }
  };

  return (
    <div className="word-pronunciation speech-pronunciation" aria-label={label}>
      <button type="button" onClick={() => void play()} disabled={!text.trim() || playing}>
        {playing ? "播放中…" : <><Icon name="play" size={14} /> {label}</>}
      </button>
    </div>
  );
}
