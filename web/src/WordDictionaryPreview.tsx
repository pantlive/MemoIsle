import type { WordLookupResponse } from "./types";
import WordPronunciation from "./WordPronunciation";
import { useI18n } from "./I18nProvider";

interface WordDictionaryPreviewProps {
  preview: WordLookupResponse;
  selectedIndices: number[];
  busy: boolean;
  onToggle: (index: number) => void;
  onApply: () => void;
  onClose: () => void;
}

export default function WordDictionaryPreview({
  preview,
  selectedIndices,
  busy,
  onToggle,
  onApply,
  onClose,
}: WordDictionaryPreviewProps) {
  const { t } = useI18n();
  return (
    <section className="word-lookup-preview" aria-label={t("词典查词预览")}>
      <div className="word-lookup-header">
        <div>
          <strong>{t("词典预览")}</strong>
          <span>
            {preview.lemma !== preview.word
              ? t("按词元 {lemma} 查询中文释义", { lemma: preview.lemma })
              : t("选择要保存的中文释义")}
          </span>
        </div>
        <button type="button" className="word-lookup-close" onClick={onClose}>
          {t("收起")}
        </button>
      </div>
      <WordPronunciation
        lemma={preview.word}
        phonetic={preview.phonetic}
        usAudioUrl={preview.us_audio_url}
        ukAudioUrl={preview.uk_audio_url}
      />
      {preview.senses.length > 0 ? (
        <div className="word-lookup-senses">
          {preview.senses.map((sense) => (
            <label className="word-lookup-sense" key={sense.index}>
              <input
                type="checkbox"
                checked={selectedIndices.includes(sense.index)}
                onChange={() => onToggle(sense.index)}
                disabled={busy}
              />
              <span>
                {sense.part_of_speech && (
                  <em>{sense.part_of_speech}</em>
                )}
                <strong>{sense.definition}</strong>
                {sense.example && <small>{t("例句：{example}", { example: sense.example })}</small>}
              </span>
            </label>
          ))}
        </div>
      ) : (
        <p className="word-lookup-empty">{t("词典没有返回中文释义，请手动填写。")}</p>
      )}
      {preview.source_url && (
        <p className="word-lookup-source">
          {t("来源：")}
          <a href={preview.source_url} target="_blank" rel="noreferrer">
            {preview.source_name || preview.source_url}
          </a>
        </p>
      )}
      <div className="word-lookup-actions">
        <button
          type="button"
          className="primary"
          disabled={busy || selectedIndices.length === 0}
          onClick={onApply}
        >
          {t("使用所选释义")}
        </button>
        <button type="button" disabled={busy} onClick={onClose}>
          {t("保留手动填写")}
        </button>
      </div>
    </section>
  );
}
