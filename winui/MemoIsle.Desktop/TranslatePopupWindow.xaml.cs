using System.Runtime.InteropServices;
using MemoIsle.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.ApplicationModel.DataTransfer;
using Windows.Graphics;

namespace MemoIsle.Desktop;

/// <summary>
/// 划词翻译结果小窗：无标题栏、置顶显示在鼠标附近，
/// 失去焦点即自动关闭；支持复制译文、收藏为灵感、失败重试。
/// </summary>
public sealed partial class TranslatePopupWindow : Window
{
    private const int GwlExStyle = -20;
    private const int WsExToolWindow = 0x00000080;
    private const uint SwpNoSize = 0x0001;
    private const uint SwpNoZOrder = 0x0004;
    private const uint SwpNoActivate = 0x0010;
    private static readonly IntPtr HwndTopmost = new(-1);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(
        IntPtr hWnd, IntPtr hWndInsertAfter, int x, int y, int cx, int cy, uint flags);

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out Point lpPoint);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtr(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    private static extern IntPtr SetWindowLongPtr(IntPtr hWnd, int nIndex, IntPtr dwNewLong);

    [StructLayout(LayoutKind.Sequential)]
    private struct Point
    {
        public int X;
        public int Y;
    }

    private readonly TranslationService _service = new();
    private readonly AppState _state;
    private string _source = string.Empty;
    private string _translation = string.Empty;
    private bool _everActivated;

    public TranslatePopupWindow(AppState state)
    {
        InitializeComponent();
        _state = state;

        Title = "MemoIsle 翻译";
        var presenter = AppWindow.Presenter as Microsoft.UI.Windowing.OverlappedPresenter;
        presenter?.SetBorderAndTitleBar(false, false);
        if (presenter is not null)
        {
            presenter.IsResizable = false;
            presenter.IsMaximizable = false;
            presenter.IsMinimizable = false;
        }
        AppWindow.Resize(new SizeInt32(420, 260));

        // 失去焦点即关闭，符合划词工具的轻量体验。
        // 注意：若窗口尚未真正获得过焦点就触发 Deactivated，不能立即关闭，
        // 否则在被系统拒绝抢焦点时会刚弹出就消失。
        Activated += (_, args) =>
        {
            if (args.WindowActivationState == WindowActivationState.Deactivated)
            {
                if (_everActivated)
                {
                    Close();
                }
            }
            else
            {
                _everActivated = true;
            }
        };
    }

    /// <summary>按当前鼠标位置摆放窗口（靠近光标但不越出工作区）。</summary>
    public void MoveNearCursor()
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        // 工具窗口样式：不出现在 Alt+Tab。
        var style = GetWindowLongPtr(hwnd, GwlExStyle).ToInt64();
        SetWindowLongPtr(hwnd, GwlExStyle, new IntPtr(style | WsExToolWindow));

        GetCursorPos(out var cursor);
        var display = Microsoft.UI.Windowing.DisplayArea.GetFromPoint(
            new PointInt32(cursor.X, cursor.Y),
            Microsoft.UI.Windowing.DisplayAreaFallback.Primary);
        var work = display.WorkArea;
        var x = Math.Min(Math.Max(cursor.X + 16, work.X), work.X + work.Width - 440);
        var y = Math.Min(Math.Max(cursor.Y + 20, work.Y), work.Y + work.Height - 300);
        AppWindow.Move(new PointInt32(x, y));
        SetWindowPos(hwnd, HwndTopmost, 0, 0, 0, 0, SwpNoSize | SwpNoZOrder | SwpNoActivate);
    }

    /// <summary>执行翻译并更新界面。</summary>
    public async Task TranslateAsync(string text)
    {
        _source = text.Trim();
        _translation = string.Empty;
        SourceText.Text = _source;
        ResultText.Text = string.Empty;
        ErrorText.Visibility = Visibility.Collapsed;
        RetryButton.Visibility = Visibility.Collapsed;
        BusyText.Visibility = Visibility.Visible;
        HeaderText.Text = $"翻译为 {TranslationSettings.LanguageLabel(TranslationSettings.Current.TargetLanguage)}"
                          + (TranslationSettings.Current.ResolvedProvider == TranslationProvider.Llm
                              ? "（大模型）"
                              : "（Google）");
        UpdateActionButtons(enabled: false);

        var result = await _service.TranslateAsync(_source);
        BusyText.Visibility = Visibility.Collapsed;
        DiagnosticsLog.Write(
            $"[{DateTime.Now:HH:mm:ss}] 翻译结果："
            + (result.Succeeded
                ? $"成功 {result.Translation!.Length} 字（源语言 {result.SourceLanguage ?? "未知"}）"
                  + $" 原文“{Preview(_source)}” → 译文“{Preview(result.Translation!)}”"
                : $"失败：{result.Error}"));

        if (result.Succeeded)
        {
            _translation = result.Translation!;
            ResultText.Text = _translation;
            ErrorText.Visibility = Visibility.Collapsed;
            RetryButton.Visibility = Visibility.Collapsed;
            var detected = string.IsNullOrWhiteSpace(result.SourceLanguage)
                ? string.Empty
                : $"检测语言：{result.SourceLanguage} · ";
            HintText.Text = $"{detected}已复制到剪贴板" + "（可在设置里关闭自动复制）";
            if (TranslationSettings.Current.AutoCopy)
            {
                CopyToClipboard(_translation);
            }
            else
            {
                HintText.Text = detected.TrimEnd(' ', '·');
            }
            // 结果出来后按内容长度微调高度。
            AppWindow.Resize(new SizeInt32(420, Math.Clamp(200 + _translation.Length / 2, 240, 520)));
            UpdateActionButtons(enabled: true);
        }
        else
        {
            ErrorText.Text = result.Error ?? "翻译失败。";
            ErrorText.Visibility = Visibility.Visible;
            RetryButton.Visibility = Visibility.Visible;
            HintText.Text = "可在 设置 → 翻译 中切换提供方或配置大模型。";
            UpdateActionButtons(enabled: false);
        }
    }

    private static string Preview(string text)
    {
        var clean = text.Replace("\r", " ").Replace("\n", " ").Trim();
        return clean.Length <= 40 ? clean : clean[..40] + "…";
    }

    private void UpdateActionButtons(bool enabled)
    {
        CopyButton.IsEnabled = enabled;
        SaveButton.IsEnabled = enabled;
    }

    private static void CopyToClipboard(string text)
    {
        try
        {
            var package = new DataPackage();
            package.SetText(text);
            Clipboard.SetContent(package);
        }
        catch (Exception)
        {
            // 剪贴板占用时忽略。
        }
    }

    private void OnCopyClick(object sender, RoutedEventArgs e)
    {
        if (_translation.Length > 0)
        {
            CopyToClipboard(_translation);
            HintText.Text = "已复制译文。";
        }
    }

    private async void OnSaveClick(object sender, RoutedEventArgs e)
    {
        if (_translation.Length == 0)
        {
            return;
        }
        SaveButton.IsEnabled = false;
        var body = $"{_source}\n\n{_translation}";
        var error = await _state.CreateIdeaAsync(body);
        HintText.Text = error ?? "已收藏为灵感。";
        SaveButton.IsEnabled = error is not null;
    }

    private async void OnRetryClick(object sender, RoutedEventArgs e) =>
        await TranslateAsync(_source);

    private void OnCloseClick(object sender, RoutedEventArgs e) => Close();
}
