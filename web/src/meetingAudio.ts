// 会议录音：把麦克风和自己电脑播放的声音（对方说话）混成一路再交给 MediaRecorder。
//
// 网页本身拿不到会议客户端（腾讯会议、Zoom、飞书等）的内部音频，
// 只能用浏览器的「共享屏幕并包含系统音频」把系统输出抓进来。
// 这条路在 Windows + Chrome 下可用；Linux / macOS 的 Chrome 只能抓浏览器标签页的音频。

export interface MeetingCapture {
  /** 麦克风与系统音频混音后的单路音轨，直接交给 MediaRecorder。 */
  stream: MediaStream;
  /** 是否真的抓到了系统音频；用户勾选「不分享音频」时为 false。 */
  hasSystemAudio: boolean;
  /** 读取系统音频（对方）的实时音量，0-100。 */
  readRemoteLevel(): number;
  /** 停止所有音轨并释放音频图。 */
  stop(): void;
  /** 用户在浏览器工具栏点了「停止共享」时触发。 */
  onSystemAudioEnded?: () => void;
}

export class MeetingAudioUnavailableError extends Error {}

/** 浏览器是否具备抓取系统音频的基础能力。 */
export function supportsMeetingAudio(): boolean {
  return (
    typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getDisplayMedia === "function"
  );
}

type AudioContextConstructor = typeof AudioContext;

function audioContextConstructor(): AudioContextConstructor | null {
  return (
    window.AudioContext ??
    (window as Window & { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext ??
    null
  );
}

/** 从分析器节点读出当前音量百分比，用于界面上的实时反馈。 */
function levelFromAnalyser(
  analyser: AnalyserNode,
  samples: Uint8Array<ArrayBuffer>,
): number {
  analyser.getByteTimeDomainData(samples);
  let sumSquares = 0;
  for (const sample of samples) {
    const normalized = (sample - 128) / 128;
    sumSquares += normalized * normalized;
  }
  const rms = Math.sqrt(sumSquares / samples.length);
  return Math.min(100, Math.round(rms * 180));
}

/**
 * 启动会议录音所需的两路音频。
 *
 * 会依次弹出两个系统授权框：麦克风、共享屏幕。
 * 麦克风被拒绝时抛错；共享被取消时退化为只有麦克风（`hasSystemAudio` 为 false），
 * 这样用户仍然可以继续录自己说的话，不会白跑一趟。
 */
export async function startMeetingCapture(
  microphoneStream: MediaStream,
): Promise<MeetingCapture> {
  if (!supportsMeetingAudio()) {
    throw new MeetingAudioUnavailableError(
      "当前浏览器不支持抓取系统音频，无法录制对方的声音。",
    );
  }
  const contextConstructor = audioContextConstructor();
  if (!contextConstructor) {
    throw new MeetingAudioUnavailableError("当前浏览器不支持音频混音。");
  }

  const displayStream = await navigator.mediaDevices.getDisplayMedia({
    // Chrome 在只请求 audio 时不会弹出可用的共享选择框，必须同时要视频轨；
    // 视频轨只用来维持共享会话，不会进入录音。
    video: true,
    audio: {
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    },
  });

  const context = new contextConstructor();
  const destination = context.createMediaStreamDestination();
  const micSource = context.createMediaStreamSource(microphoneStream);
  micSource.connect(destination);

  const systemTracks = displayStream.getAudioTracks();
  const hasSystemAudio = systemTracks.length > 0;
  let analyser: AnalyserNode | null = null;
  let samples = new Uint8Array(new ArrayBuffer(0));
  if (hasSystemAudio) {
    const systemSource = context.createMediaStreamSource(displayStream);
    systemSource.connect(destination);
    analyser = context.createAnalyser();
    analyser.fftSize = 512;
    systemSource.connect(analyser);
    samples = new Uint8Array(new ArrayBuffer(analyser.fftSize));
  }

  const capture: MeetingCapture = {
    stream: destination.stream,
    hasSystemAudio,
    readRemoteLevel() {
      return analyser ? levelFromAnalyser(analyser, samples) : 0;
    },
    stop() {
      // 系统音轨停止后浏览器顶部的「正在共享」提示才会消失。
      displayStream.getTracks().forEach((track) => track.stop());
      micSource.disconnect();
      void context.close().catch(() => undefined);
    },
  };

  const [systemTrack] = systemTracks;
  if (systemTrack) {
    systemTrack.addEventListener("ended", () => {
      capture.onSystemAudioEnded?.();
    });
  }

  if (context.state === "suspended") {
    void context.resume();
  }
  return capture;
}
