import { type LevelStore, useLevel } from "./levelStore";

interface VoiceLevelMeterProps {
  store: LevelStore;
  label: string;
  ariaSubject: string;
  /** 对方声音未接入时显示「未接入」并使用灰色样式。 */
  missing?: boolean;
}

/** 录音音量条：自己订阅电平，不带动父组件重渲染。 */
export default function VoiceLevelMeter({
  store,
  label,
  ariaSubject,
  missing = false,
}: VoiceLevelMeterProps) {
  const level = useLevel(store);
  return (
    <div
      className={missing ? "voice-meter missing" : "voice-meter"}
      aria-label={`${ariaSubject} ${level}%`}
    >
      <span>{label}</span>
      <div className="voice-meter-track" aria-hidden="true">
        <span style={{ width: `${level}%` }} />
      </div>
      <strong>{missing ? "未接入" : `${level}%`}</strong>
    </div>
  );
}
