using MemoIsle.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace MemoIsle.Desktop;

/// <summary>忘记密码：发送重置邮件 → 粘贴邮件中的令牌 → 设置新密码（两步在同一对话框中）。</summary>
internal sealed class PasswordResetDialog
{
    private readonly AppState _state;
    private ContentDialog? _dialog;
    private readonly TextBlock _status = new()
    {
        FontSize = 12,
        TextWrapping = TextWrapping.Wrap,
        Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
    };
    private readonly TextBox _emailBox = new() { Header = "注册邮箱", Width = 360 };
    private readonly TextBox _tokenBox = new() { Header = "邮件里的重置令牌", Width = 360 };
    private readonly PasswordBox _passwordBox = new() { Header = "新密码（至少 8 位）", Width = 360 };
    private readonly PasswordBox _confirmBox = new() { Header = "确认新密码", Width = 360 };
    private readonly Button _sendButton = new() { Content = "发送重置邮件" };
    private readonly Button _resetButton = new() { Content = "设置新密码", IsEnabled = false };
    private readonly StackPanel _resetPanel = new() { Spacing = 10, Visibility = Visibility.Collapsed };

    public PasswordResetDialog(AppState state, string initialEmail)
    {
        _state = state;

        _emailBox.Text = initialEmail;
        _sendButton.Click += async (_, _) =>
        {
            _status.Text = "正在发送…";
            var error = await _state.RequestPasswordResetAsync(_emailBox.Text);
            _status.Text = error ?? _state.StatusMessage;
            if (error is null)
            {
                // 邮件已发出：展开第二步，让用户粘贴令牌并设置新密码。
                _resetPanel.Visibility = Visibility.Visible;
                _resetButton.IsEnabled = true;
                _tokenBox.Focus(FocusState.Programmatic);
            }
        };

        _resetButton.Click += async (_, _) =>
        {
            _status.Text = "正在重置…";
            var error = await _state.ResetPasswordAsync(
                _tokenBox.Text,
                _passwordBox.Password,
                _confirmBox.Password);
            _status.Text = error ?? _state.StatusMessage;
            if (error is null)
            {
                _dialog?.Hide();
            }
        };

        _resetPanel.Children.Add(_tokenBox);
        _resetPanel.Children.Add(_passwordBox);
        _resetPanel.Children.Add(_confirmBox);
        _resetPanel.Children.Add(_resetButton);

        var panel = new StackPanel { Spacing = 10, Width = 380 };
        panel.Children.Add(new TextBlock
        {
            Text = "填写注册邮箱，我们会发送一封含重置令牌的邮件；把令牌粘贴到下方即可设置新密码。",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
        });
        panel.Children.Add(_emailBox);
        panel.Children.Add(_sendButton);
        panel.Children.Add(_resetPanel);
        panel.Children.Add(_status);

        _dialog = new ContentDialog
        {
            Title = "忘记密码",
            CloseButtonText = "关闭",
            DefaultButton = ContentDialogButton.Close,
            Content = new ScrollViewer { Content = panel, MaxHeight = 460 },
        };
    }

    public async Task ShowAsync(XamlRoot root)
    {
        if (_dialog is null)
        {
            return;
        }
        _dialog.XamlRoot = root;
        await _dialog.ShowAsync();
    }
}
