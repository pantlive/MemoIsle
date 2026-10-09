import type { WordLookupResponse } from "./types";
import WordPronunciation from "./WordPronunciation";

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
  return (
    <section className="word-lookup-preview" aria-label="词典查词预览">
      <div className="word-lookup-header">
        <div>
          <strong>词典预览</strong>
          <span>
            {preview.lemma !== preview.word
              ? `按词元 ${preview.lemma} 查询中文释义`
              : "选择要保存的中文释义"}
          </span>
        </div>
        <button type="button" className="word-lookup-close" onClick={onClose}>
          收起
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
                {sense.example && <small>例句：{sense.example}</small>}
              </span>
            </label>
          ))}
        </div>
      ) : (
        <p className="word-lookup-empty">词典没有返回中文释义，请手动填写。</p>
      )}
      {preview.source_url && (
        <p className="word-lookup-source">
          来源：
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
          使用所选释义
        </button>
        <button type="button" disabled={busy} onClick={onClose}>
          保留手动填写
        </button>
      </div>
    </section>
  );
}
