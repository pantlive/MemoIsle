using System.IO;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Media.SpeechSynthesis;

namespace MemoIsle.Desktop.Services;

/// <summary>单词发音：使用 Windows 系统语音（WinRT SpeechSynthesizer），离线可用。</summary>
public static class SpeechService
{
    private static readonly MediaPlayer Player = new();

    public static async Task<bool> SpeakAsync(string text)
    {
        var clean = text.Trim();
        if (clean.Length == 0)
        {
            return false;
        }
        try
        {
            using var synthesizer = new SpeechSynthesizer();
            var stream = await synthesizer.SynthesizeTextToStreamAsync(clean);
            Player.Source = MediaSource.CreateFromStream(stream, stream.ContentType);
            Player.Play();
            return true;
        }
        catch (Exception)
        {
            // 系统语音不可用时返回失败，由界面给出提示。
            return false;
        }
    }

    /// <summary>播放服务端合成的语音（sanoTTS 返回的 WAV 字节）。</summary>
    public static void PlayWav(byte[] wav)
    {
        if (wav.Length == 0)
        {
            return;
        }
        try
        {
            var stream = new MemoryStream(wav).AsRandomAccessStream();
            Player.Source = MediaSource.CreateFromStream(stream, "audio/wav");
            Player.Play();
        }
        catch (Exception)
        {
            // 播放失败时静默忽略，调用方会回退到系统语音。
        }
    }
}
