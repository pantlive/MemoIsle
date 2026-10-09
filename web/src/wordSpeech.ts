export type SpeechLocale = "en-US" | "en-GB";

function localePrefix(locale: SpeechLocale): string {
  return locale.toLowerCase();
}

export function findSpeechVoice(
  locale: SpeechLocale,
): SpeechSynthesisVoice | null {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) {
    return null;
  }
  const voices = window.speechSynthesis.getVoices();
  const prefix = localePrefix(locale);
  return (
    voices.find((voice) => voice.lang.toLowerCase().replace("_", "-") === prefix) ??
    voices.find((voice) =>
      voice.lang.toLowerCase().replace("_", "-").startsWith(prefix.split("-")[0] ?? prefix),
    ) ??
    null
  );
}

export function speechLocaleAvailable(locale: SpeechLocale): boolean {
  return findSpeechVoice(locale) !== null;
}

export function speakText(
  text: string,
  locale: SpeechLocale,
  onDone?: () => void,
): boolean {
  const cleaned = text.trim();
  if (!cleaned || typeof window === "undefined" || !("speechSynthesis" in window)) {
    return false;
  }
  const voice = findSpeechVoice(locale);
  if (voice === null) {
    return false;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(cleaned);
  utterance.lang = locale;
  utterance.voice = voice;
  if (onDone) {
    utterance.onend = onDone;
    utterance.onerror = onDone;
  }
  window.speechSynthesis.speak(utterance);
  return true;
}

export function speakLemma(lemma: string, locale: SpeechLocale): boolean {
  return speakText(lemma, locale);
}
