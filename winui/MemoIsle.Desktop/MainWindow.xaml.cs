using System.Linq;
using MemoIsle.Desktop.Models;
using MemoIsle.Desktop.Services;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Windows.ApplicationModel.DataTransfer;

namespace MemoIsle.Desktop;

/// <summary>主窗口：承载登录、资料库、复习与回收站界面。</summary>
public sealed partial class MainWindow : Window
{
    private readonly AppState _state = new();
    private string _navTag = "all";
    private string _search = string.Empty;
    private bool _starOnly;
    private string? _categoryCode;
    private string? _reviewFilter;
    private string? _healthFilter;
    private bool _cardView;
    private bool _registerMode;
    private string? _error;
    private bool _dialogOpen;
    private DispatcherQueueTimer? _searchTimer;
    private DispatcherQueueTimer? _pendingTimer;
    private readonly Dictionary<HotkeyAction, GlobalHotkey> _globalHotkeys = new();
    private readonly List<HotkeyAction> _failedGlobalHotkeys = new();
    private TrayIcon? _tray;
    private WindowMessageHook? _messageHook;
    private QuickCapture? _quickCapture;
    private TranslatePopupWindow? _translatePopup;
    private IntPtr _hwnd;
    private bool _exiting;

    public MainWindow()
    {
        InitializeComponent();
        _state.PropertyChanged += (_, _) => UpdateStatus();
        RootGrid.Loaded += OnRootLoaded;
        RestoreWindowState();
        Closed += (_, _) =>
        {
            SaveWindowState();
            // 退出时注销全部全局热键，避免继续占用系统组合键。
            foreach (var hotkey in _globalHotkeys.Values)
            {
                hotkey.Dispose();
            }
            _globalHotkeys.Clear();
            _tray?.Dispose();
            _messageHook?.Dispose();
        };
        ApplyHotkeys();
        RegisterGlobalHotkeys();
        SetUpTray();
    }

    /// <summary>托盘图标：关闭窗口时驻留后台，保证全局收藏热键继续可用。</summary>
    private void SetUpTray()
    {
        try
        {
            var iconPath = Path.Combine(AppContext.BaseDirectory, "Assets", "icon.ico");
            var tray = new TrayIcon(_hwnd);
            _tray = tray;
            tray.AddMenuItem("显示主窗口", RestoreFromTray);
            tray.AddMenuItem("快速收藏剪贴板单词", () =>
            {
                _ = Task.Run(async () =>
                {
                    if (_quickCapture is null)
                    {
                        return;
                    }
                    var message = await _quickCapture.CaptureWordAsync();
                    QuickCapture.ShowToast(message);
                });
            });
            tray.AddSeparator();
            tray.AddMenuItem("退出 MemoIsle", () =>
            {
                _exiting = true;
                Close();
            });
            tray.DoubleClicked += RestoreFromTray;
            _messageHook?.AddHandler((msg, wParam, lParam) => tray.HandleMessage(msg, wParam, lParam));
            if (!tray.Create(iconPath, "MemoIsle · 后台运行中，全局快捷键可用"))
            {
                tray.Dispose();
                _tray = null;
                return;
            }
            // 关闭窗口改为隐藏到托盘；托盘菜单"退出"才真正结束进程。
            AppWindow.Closing += (_, args) =>
            {
                if (_exiting || _tray is null)
                {
                    return;
                }
                args.Cancel = true;
                AppWindow.Hide();
                _tray.UpdateTooltip("MemoIsle 在后台运行 · 双击打开 · 全局快捷键可用");
            };
        }
        catch (Exception)
        {
            _tray?.Dispose();
            _tray = null;
        }
    }

    private void RestoreFromTray()
    {
        AppWindow.Show();
        Activate();
        if (_hwnd != IntPtr.Zero)
        {
            SetForegroundWindow(_hwnd);
        }
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    /// <summary>
    /// 注册全局热键（任意应用内生效）：复制内容后按键即可直接收藏，无需切回窗口。
    /// 若组合已被其他程序占用，会在状态栏提示，不影响其他功能。
    /// </summary>
    private void RegisterGlobalHotkeys()
    {
        try
        {
            _hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
            _quickCapture = new QuickCapture(_state);
            // 统一的消息钩子：同时分发全局热键与托盘事件。
            _messageHook = new WindowMessageHook(_hwnd);
            AddGlobalHotkey(HotkeyAction.QuickCaptureWord, 0x4D49, () => _quickCapture.CaptureWordAsync());
            AddGlobalHotkey(HotkeyAction.QuickCaptureResource, 0x4D4A, () => _quickCapture.CaptureResourceAsync());
            AddGlobalHotkey(HotkeyAction.QuickCaptureIdea, 0x4D4B, () => _quickCapture.CaptureIdeaAsync());
            // 划词翻译：单独注册，走独立的小窗流程。
            var translateHotkey = new GlobalHotkey(_hwnd, 0x4D4C);
            translateHotkey.Pressed += () =>
                DispatcherQueue.TryEnqueue(() => _ = HandleTranslateHotkeyAsync());
            _messageHook?.AddHandler((msg, wParam, _) => translateHotkey.HandleMessage(msg, wParam));
            _globalHotkeys[HotkeyAction.TranslateSelection] = translateHotkey;
            ApplyGlobalHotkeys();
        }
        catch (Exception)
        {
            _globalHotkeys.Clear();
        }
    }

    private void AddGlobalHotkey(HotkeyAction action, int id, Func<Task<string>> capture)
    {
        var hotkey = new GlobalHotkey(_hwnd, id);
        hotkey.Pressed += () => _ = HandleGlobalCaptureAsync(capture);
        _messageHook?.AddHandler((msg, wParam, _) => hotkey.HandleMessage(msg, wParam));
        _globalHotkeys[action] = hotkey;
    }

    /// <summary>按设置中的绑定注册全部全局热键（重复调用会先注销旧的）。</summary>
    private void ApplyGlobalHotkeys()
    {
        if (_globalHotkeys.Count == 0)
        {
            return;
        }
        _failedGlobalHotkeys.Clear();
        var lines = new List<string> { $"[{DateTime.Now:HH:mm:ss}] 注册全局热键" };
        foreach (var (action, hotkey) in _globalHotkeys)
        {
            var binding = HotkeySettings.Current(action);
            var ok = hotkey.TryRegister(binding);
            if (!ok)
            {
                _failedGlobalHotkeys.Add(action);
            }
            lines.Add($"  {(ok ? "OK  " : "FAIL")} {HotkeySettings.Describe(binding)} {HotkeySettings.ActionLabel(action)}");
        }
        DiagnosticsLog.Write(lines);
        _error = _failedGlobalHotkeys.Count == 0
            ? null
            : "全局快捷键注册失败（可能被其他程序占用）："
              + string.Join(
                  "、",
                  _failedGlobalHotkeys.Select(action =>
                      $"{HotkeySettings.Describe(HotkeySettings.Current(action))} {HotkeySettings.ActionLabel(action)}"))
              + "。可在设置里改绑。";
        UpdateStatus();
    }

    /// <summary>全局热键触发：读剪贴板 → 收藏 → 弹系统通知。</summary>
    private async Task HandleGlobalCaptureAsync(Func<Task<string>> capture)
    {
        if (_state.CurrentUser is null)
        {
            return;
        }
        var message = await capture();
        QuickCapture.ShowToast(message);
        // 窗口可能不在前台，仅更新内存列表与状态栏。
        RefreshLists();
        UpdateStatus();
    }

    /// <summary>
    /// 划词翻译：选中文字后直接按快捷键即可——自动模拟 Ctrl+C 取词，
    /// 翻译完再还原用户原来的剪贴板内容（可在设置里关闭自动取词）。
    /// </summary>
    private async Task HandleTranslateHotkeyAsync()
    {
        var autoCopySelection = TranslationSettings.Current.AutoCopySelection;
        string? text;
        string? clipboardBackup = null;

        if (autoCopySelection)
        {
            // 备份原剪贴板 → 等修饰键松开 → 模拟 Ctrl+C → 读取选中文字。
            clipboardBackup = await ClipboardHelper.BackupTextAsync();
            await KeySender.WaitForModifiersReleasedAsync();
            KeySender.SendCopy();
            // 不同程序写入剪贴板的速度不同，轮询等待内容变化（最多约 700ms）。
            text = null;
            for (var attempt = 0; attempt < 7; attempt++)
            {
                await Task.Delay(100);
                text = await ClipboardHelper.ReadTextAsync();
                if (!string.IsNullOrWhiteSpace(text) && text != clipboardBackup)
                {
                    break;
                }
            }
            // 内容仍与原剪贴板一致，说明没有选中文字（Ctrl+C 没生效）。
            if (!string.IsNullOrWhiteSpace(text) && text == clipboardBackup)
            {
                text = null;
            }
            DiagnosticsLog.Write(
                $"[{DateTime.Now:HH:mm:ss}] 翻译热键（自动取词）："
                + (string.IsNullOrWhiteSpace(text) ? "未取到选中文字" : $"取到 {text.Length} 字"));
            if (string.IsNullOrWhiteSpace(text))
            {
                QuickCapture.ShowToast("没有取到选中文字：请先选中文字再按翻译快捷键（部分程序需手动 Ctrl+C）。");
                return;
            }
        }
        else
        {
            text = await ClipboardHelper.ReadTextAsync();
            DiagnosticsLog.Write(
                $"[{DateTime.Now:HH:mm:ss}] 翻译热键（读剪贴板）："
                + (string.IsNullOrWhiteSpace(text) ? "剪贴板为空" : $"文本长度 {text.Length}"));
            if (string.IsNullOrWhiteSpace(text))
            {
                QuickCapture.ShowToast("剪贴板没有文本：先选中文字并按 Ctrl+C，再按翻译快捷键。");
                return;
            }
        }

        // 复用同一个小窗，避免连按时堆叠多个窗口。
        try
        {
            _translatePopup?.Close();
        }
        catch (Exception)
        {
            // 上一个窗口可能已由用户关闭。
        }
        var popup = new TranslatePopupWindow(_state);
        _translatePopup = popup;
        popup.MoveNearCursor();
        popup.Activate();
        await popup.TranslateAsync(text);

        // 恢复用户原来的剪贴板内容（译文的复制由弹窗内的按钮负责）。
        ClipboardHelper.RestoreText(clipboardBackup);
    }

    /// <summary>把设置里的快捷键应用到窗口，并同步相关提示文案。</summary>
    private void ApplyHotkeys()
    {
        void Apply(KeyboardAccelerator accelerator, HotkeyAction action)
        {
            var binding = HotkeySettings.Current(action);
            accelerator.Key = binding.ToVirtualKey();
            accelerator.Modifiers = binding.ToVirtualModifiers();
        }

        Apply(AccelNewGeneral, HotkeyAction.NewGeneral);
        Apply(AccelNewIdea, HotkeyAction.NewIdea);
        Apply(AccelNewWord, HotkeyAction.NewWord);
        Apply(AccelNewResource, HotkeyAction.NewResource);
        Apply(AccelFocusSearch, HotkeyAction.FocusSearch);
        Apply(AccelRefresh, HotkeyAction.Refresh);

        var word = HotkeySettings.Describe(HotkeySettings.Current(HotkeyAction.NewWord));
        var resource = HotkeySettings.Describe(HotkeySettings.Current(HotkeyAction.NewResource));
        var idea = HotkeySettings.Describe(HotkeySettings.Current(HotkeyAction.NewIdea));
        ToolTipService.SetToolTip(QuickWordChip, $"收藏单词（{word}）");
        ToolTipService.SetToolTip(QuickResourceChip, $"收藏网页资料（{resource}）");
        QuickCaptureBox.PlaceholderText =
            $"记录一条灵感…（Ctrl+Enter 保存；{idea} 灵感 / {word} 单词 / {resource} 资料）";
    }

    private void RestoreWindowState()
    {
        var state = WindowStateStore.Load();
        if (state is null)
        {
            return;
        }
        try
        {
            AppWindow.Resize(new Windows.Graphics.SizeInt32(state.Width, state.Height));
            AppWindow.Move(new Windows.Graphics.PointInt32(state.X, state.Y));
        }
        catch (Exception)
        {
            // 显示器数量变化导致位置无效时使用系统默认。
        }
    }

    private void SaveWindowState()
    {
        try
        {
            var size = AppWindow.Size;
            var position = AppWindow.Position;
            WindowStateStore.Save(size.Width, size.Height, position.X, position.Y);
        }
        catch (Exception)
        {
            // 关闭阶段保存失败忽略。
        }
    }

    private async void OnRootLoaded(object sender, RoutedEventArgs e)
    {
        var authenticated = await _state.InitializeAsync();
        if (authenticated)
        {
            ShowLibrary();
            await RefreshAllAsync();
        }
        else
        {
            ShowLogin();
            EmailBox.Focus(FocusState.Programmatic);
        }
        StartPendingMetadataWatcher();
        UpdateStatus();
    }

    /// <summary>资料元数据后台处理中时每 5 秒静默刷新（对齐 Web 端行为）。</summary>
    private void StartPendingMetadataWatcher()
    {
        _pendingTimer ??= CreateTimer(
            TimeSpan.FromSeconds(5),
            async () =>
            {
                if (_state.Memos.Any(m => m.ResourceMetadataStatus is "pending" or "processing"))
                {
                    await RefreshAllAsync();
                }
            },
            repeating: true);
        _pendingTimer.Start();
    }

    // ---------- 认证 ----------

    private void ShowLogin()
    {
        LoginPanel.Visibility = Visibility.Visible;
        LibraryPanel.Visibility = Visibility.Collapsed;
    }

    private void ShowLibrary()
    {
        LoginPanel.Visibility = Visibility.Collapsed;
        LibraryPanel.Visibility = Visibility.Visible;
    }

    private void OnSwitchModeClick(object sender, RoutedEventArgs e)
    {
        _registerMode = !_registerMode;
        ApplyAuthModeUi();
    }

    private void ApplyAuthModeUi()
    {
        var registerVisibility = _registerMode ? Visibility.Visible : Visibility.Collapsed;
        ConfirmBox.Visibility = registerVisibility;
        DisplayNameBox.Visibility = registerVisibility;
        CodeRow.Visibility = registerVisibility;
        SubmitButton.Content = _registerMode ? "注册" : "登录";
        SwitchModeButton.Content = _registerMode ? "已有账号？返回登录" : "没有账号？注册一个";
    }

    private async void OnSubmitClick(object sender, RoutedEventArgs e) =>
        await SubmitCredentialsAsync();

    private async void OnLoginFieldKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == Windows.System.VirtualKey.Enter)
        {
            e.Handled = true;
            await SubmitCredentialsAsync();
        }
    }

    private async Task SubmitCredentialsAsync()
    {
        LoginMessage.Text = string.Empty;
        var email = EmailBox.Text.Trim();
        string? error;
        if (_registerMode)
        {
            error = await _state.RegisterAsync(
                email,
                PasswordBox.Password,
                ConfirmBox.Password,
                CodeBox.Text.Trim(),
                DisplayNameBox.Text.Trim());
            if (error is null)
            {
                _registerMode = false;
                ApplyAuthModeUi();
                LoginMessage.Text = "注册成功，请使用邮箱登录。";
            }
            else
            {
                LoginMessage.Text = error;
            }
            return;
        }

        error = await _state.LoginAsync(email, PasswordBox.Password);
        if (error is not null)
        {
            LoginMessage.Text = error;
            return;
        }
        PasswordBox.Password = string.Empty;
        ShowLibrary();
        await RefreshAllAsync();
    }

    private async void OnDevLoginClick(object sender, RoutedEventArgs e)
    {
        LoginMessage.Text = string.Empty;
        var error = await _state.DevLoginAsync();
        if (error is not null)
        {
            LoginMessage.Text = error;
            return;
        }
        ShowLibrary();
        await RefreshAllAsync();
    }

    private async void OnSendCodeClick(object sender, RoutedEventArgs e)
    {
        var error = await _state.RequestVerificationCodeAsync(EmailBox.Text.Trim());
        LoginMessage.Text = error ?? _state.StatusMessage;
    }

    /// <summary>忘记密码：打开重置对话框（带入当前填写的邮箱）。</summary>
    private async void OnForgotPasswordClick(object sender, RoutedEventArgs e)
    {
        if (_dialogOpen)
        {
            return;
        }
        _dialogOpen = true;
        try
        {
            await new PasswordResetDialog(_state, EmailBox.Text.Trim()).ShowAsync(RootGrid.XamlRoot);
        }
        finally
        {
            _dialogOpen = false;
        }
        LoginMessage.Text = _state.StatusMessage;
    }

    /// <summary>已登录但邮箱未验证时：重新发送验证邮件。</summary>
    private async void OnResendVerificationClick(object sender, RoutedEventArgs e)
    {
        var error = await _state.ResendEmailVerificationAsync();
        LoginMessage.Text = error ?? _state.StatusMessage;
    }

    private async void OnLogoutClick(object sender, RoutedEventArgs e)
    {
        await _state.LogoutAsync();
        _navTag = "all";
        _search = string.Empty;
        _starOnly = false;
        SearchBox.Text = string.Empty;
        LoginMessage.Text = string.Empty;
        ShowLogin();
        UpdateStatus();
    }

    // ---------- 列表与导航 ----------

    private async Task RefreshAllAsync()
    {
        _error = null;
        await _state.RefreshAsync(_search, paged: _navTag == "resource");
        RefreshLists();
        UpdateStatus();
    }

    private async void OnSortChanged(object sender, SelectionChangedEventArgs e)
    {
        if (SortBox is null || !RootGrid.IsLoaded)
        {
            return;
        }
        if (SortBox.SelectedItem is not ComboBoxItem { Tag: string sort })
        {
            return;
        }
        _state.SetSortOrder(sort);
        _state.ResetResourcePage();
        _state.SetResourceFilters(_categoryCode, _starOnly);
        await RefreshAllAsync();
    }

    private async void OnPrevPageClick(object sender, RoutedEventArgs e)
    {
        if (_state.ResourcePage <= 1)
        {
            return;
        }
        _state.SetResourcePage(_state.ResourcePage - 1);
        await RefreshAllAsync();
    }

    private async void OnNextPageClick(object sender, RoutedEventArgs e)
    {
        if (_state.ResourcePage >= _state.ResourcePageCount)
        {
            return;
        }
        _state.SetResourcePage(_state.ResourcePage + 1);
        await RefreshAllAsync();
    }

    private bool MemoMatchesCategory(Memo memo, string categoryCode)
    {
        var codes = new HashSet<string> { categoryCode };
        foreach (var category in _state.Categories)
        {
            var parent = category.ParentCode;
            while (!string.IsNullOrEmpty(parent))
            {
                if (parent == categoryCode)
                {
                    codes.Add(category.Code);
                    break;
                }
                parent = _state.Categories.FirstOrDefault(item => item.Code == parent)?.ParentCode;
            }
        }
        if (!string.IsNullOrEmpty(memo.ResourceCategory) && codes.Contains(memo.ResourceCategory))
        {
            return true;
        }
        return memo.ResourceCategories.Any(codes.Contains);
    }

    private void RefreshLists()
    {
        // 搜索由服务端按 q= 执行（可命中描述、站点名等本地字段之外的列），
        // 因此搜索生效时不再做本地二次过滤，避免命中结果被筛掉。
        var serverSearchActive = !string.IsNullOrWhiteSpace(_state.ActiveSearchQuery);
        var items = _state.Memos
            .Where(m => _navTag is "all" || m.Type == _navTag)
            .Where(m => !_starOnly || m.Starred)
            .Where(m => _categoryCode is null || MemoMatchesCategory(m, _categoryCode))
            .Where(m => serverSearchActive || MatchesSearch(m))
            .OrderByDescending(m => m.UpdatedAt)
            .ToList();
        MemoList.ItemsSource = items;
        MemoCardList.ItemsSource = items;
        UpdateCardViewVisibility();
        UpdateEmptyState();
        UpdateListHeader();
    }

    /// <summary>资料视图可在列表/卡片两种呈现间切换（导入书签入口在侧边栏"资料"行）。</summary>
    private void UpdateCardViewVisibility()
    {
        var isResourceView = _navTag == "resource";
        CardViewToggle.Visibility = isResourceView ? Visibility.Visible : Visibility.Collapsed;
        var showCards = isResourceView && _cardView;
        MemoCardList.Visibility = showCards ? Visibility.Visible : Visibility.Collapsed;
        var showList = !showCards && _navTag is "all" or "idea" or "word" or "resource" or "image";
        MemoList.Visibility = showList ? Visibility.Visible : Visibility.Collapsed;
    }

    private void OnCardViewClick(object sender, RoutedEventArgs e)
    {
        _cardView = CardViewToggle.IsChecked == true;
        CardViewToggle.Content = _cardView ? "☷ 列表" : "▦ 卡片";
        RefreshLists();
    }

    /// <summary>资料列表为空时展示引导性的空状态。</summary>
    private void UpdateEmptyState()
    {
        var isList = _navTag is "all" or "idea" or "word" or "resource" or "image";
        var count = (MemoList.ItemsSource as System.Collections.ICollection)?.Count ?? 0;
        EmptyState.Visibility = isList && count == 0
            ? Visibility.Visible
            : Visibility.Collapsed;
    }

    /// <summary>资料视图的分类下拉：全部分类 + 后端返回的系统/自定义分类。</summary>
    private void PopulateCategoryFilter()
    {
        var previous = _categoryCode;
        CategoryFilter.Items.Clear();
        CategoryFilter.Items.Add(new ComboBoxItem { Content = "全部分类", Tag = null });
        foreach (var category in _state.Categories)
        {
            CategoryFilter.Items.Add(new ComboBoxItem { Content = category.Name, Tag = category.Code });
        }
        var index = 0;
        if (previous is not null)
        {
            for (var i = 0; i < CategoryFilter.Items.Count; i++)
            {
                if (CategoryFilter.Items[i] is ComboBoxItem { Tag: string code } && code == previous)
                {
                    index = i;
                    break;
                }
            }
        }
        CategoryFilter.SelectedIndex = index;
    }

    private void OnCategoryFilterChanged(object sender, SelectionChangedEventArgs e)
    {
        _categoryCode = (CategoryFilter.SelectedItem as ComboBoxItem)?.Tag as string;
        _state.SetResourceFilters(_categoryCode, _starOnly);
        _state.ResetResourcePage();
        _ = RefreshAllAsync();
    }

    private bool MatchesSearch(Memo memo)
    {
        var query = _search.Trim();
        if (query.Length == 0)
        {
            return true;
        }
        var values = new[]
        {
            memo.Title, memo.Body, memo.SourceUrl, memo.SourceTitle,
            memo.WordPhonetic, memo.WordMeaning, memo.WordExample,
        }.Concat(memo.Tags);
        return values.Any(value =>
            value is not null && value.Contains(query, StringComparison.OrdinalIgnoreCase));
    }

    private async void OnNavSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (NavList.SelectedItem is ListViewItem { Tag: string tag })
        {
            _navTag = tag;
        }
        await NavigateAsync();
    }

    private async Task NavigateAsync()
    {
        // MemoList / MemoCardList 的可见性由 UpdateCardViewVisibility 统一处理。
        ReviewList.Visibility = _navTag == "review" ? Visibility.Visible : Visibility.Collapsed;
        TrashList.Visibility = _navTag == "trash" ? Visibility.Visible : Visibility.Collapsed;
        HealthList.Visibility = _navTag == "health" ? Visibility.Visible : Visibility.Collapsed;

        // 快速捕获只在资料库列表视图出现；复习/巡检各有自己的工具条。
        var isListView = _navTag is "all" or "idea" or "word" or "resource" or "image";
        QuickCapturePanel.Visibility = isListView ? Visibility.Visible : Visibility.Collapsed;
        ReviewToolbar.Visibility = _navTag == "review" ? Visibility.Visible : Visibility.Collapsed;
        LinkHealthToolbar.Visibility = _navTag == "health" ? Visibility.Visible : Visibility.Collapsed;
        EmptyTrashButton.Visibility = _navTag == "trash" ? Visibility.Visible : Visibility.Collapsed;
        MultiSelectToggle.Visibility = isListView || _navTag == "trash"
            ? Visibility.Visible
            : Visibility.Collapsed;
        if (_navTag is not ("all" or "idea" or "word" or "resource" or "image" or "trash"))
        {
            ApplyMultiSelectMode();
        }

        // 分类过滤只在资料视图出现，并确保分类列表已加载。
        var isResourceView = _navTag == "resource";
        CategoryFilter.Visibility = isResourceView ? Visibility.Visible : Visibility.Collapsed;
        if (isResourceView)
        {
            if (_state.Categories.Count == 0)
            {
                await _state.LoadCategoriesAsync();
            }
            PopulateCategoryFilter();
        }
        else
        {
            _categoryCode = null;
            // 离开资料视图时重置分页，避免切回时页码越界。
            _state.ResetResourcePage();
        }

        switch (_navTag)
        {
            case "review":
                await _state.LoadReviewAsync(_reviewFilter);
                ReviewList.ItemsSource = _state.ReviewItems.ToList();
                UpdateReviewSummary();
                break;
            case "trash":
                await _state.LoadTrashAsync();
                TrashList.ItemsSource = _state.TrashedMemos.ToList();
                break;
            case "health":
                await _state.LoadLinkHealthAsync(_healthFilter);
                HealthList.ItemsSource = _state.LinkHealthItems.ToList();
                UpdateHealthSummary();
                break;
            case "resource":
                // 资料视图使用服务端分页 + 服务端筛选，进入时按当前条件重新拉取。
                _state.SetResourceFilters(_categoryCode, _starOnly);
                await RefreshAllAsync();
                break;
            default:
                RefreshLists();
                break;
        }
        UpdateCardViewVisibility();
        UpdateEmptyState();
        UpdateBulkBar();
        UpdateStatus();
    }

    private void OnSearchChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason == AutoSuggestionBoxTextChangeReason.SuggestionChosen)
        {
            return;
        }
        _search = sender.Text;
        RefreshLists();
        // 输入停顿 250ms 后走服务端搜索，避免只过滤本地已加载的部分数据。
        _searchTimer ??= CreateTimer(
            TimeSpan.FromMilliseconds(250),
            async () => await RefreshAllAsync());
        _searchTimer.Stop();
        _searchTimer.Start();
    }

    private DispatcherQueueTimer CreateTimer(TimeSpan interval, Func<Task> onTick, bool repeating = false)
    {
        var timer = DispatcherQueue.CreateTimer();
        timer.Interval = interval;
        timer.IsRepeating = repeating;
        timer.Tick += async (_, _) => await onTick();
        return timer;
    }

    private async void OnStarFilterClick(object sender, RoutedEventArgs e)
    {
        _starOnly = StarFilterToggle.IsChecked == true;
        StarFilterToggle.Content = _starOnly ? "★ 仅星标" : "☆ 仅星标";
        _state.SetResourceFilters(_categoryCode, _starOnly);
        _state.ResetResourcePage();
        await RefreshAllAsync();
    }

    private async void OnRefreshClick(object sender, RoutedEventArgs e) => await RefreshAllAsync();

    private readonly Windows.Media.Playback.MediaPlayer _audioPlayer = new();

    private async void OnVoiceCaptureClick(object sender, RoutedEventArgs e)
    {
        if (_dialogOpen)
        {
            return;
        }
        _dialogOpen = true;
        try
        {
            await new VoiceCaptureDialog(_state).ShowAsync(RootGrid.XamlRoot);
        }
        finally
        {
            _dialogOpen = false;
        }
        await AfterWriteAsync();
    }

    private async void OnMeetingCaptureClick(object sender, RoutedEventArgs e)
    {
        if (_dialogOpen)
        {
            return;
        }
        _dialogOpen = true;
        try
        {
            await new MeetingCaptureDialog(_state).ShowAsync(RootGrid.XamlRoot);
        }
        finally
        {
            _dialogOpen = false;
        }
        await AfterWriteAsync();
    }

    /// <summary>播放灵感条目的录音（下载后交给系统媒体播放器）。</summary>
    private async void OnPlayAudioClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        var bytes = await _state.DownloadAudioAsync(memo);
        if (bytes is null || bytes.Length == 0)
        {
            _error = "无法下载该录音，请稍后重试。";
            UpdateStatus();
            return;
        }
        _error = null;
        var stream = new MemoryStream(bytes).AsRandomAccessStream();
        _audioPlayer.Source = Windows.Media.Core.MediaSource.CreateFromStream(stream, "audio/mp4");
        _audioPlayer.Play();
        UpdateStatus();
    }

    private async void OnCategorySettingsClick(object sender, RoutedEventArgs e)
    {
        if (_dialogOpen)
        {
            return;
        }
        _dialogOpen = true;
        try
        {
            await new SettingsDialog(_state).ShowAsync(RootGrid.XamlRoot);
        }
        finally
        {
            _dialogOpen = false;
        }
        // 设置里可能改过快捷键或分类：重新应用并按需刷新列表与分类下拉。
        ApplyHotkeys();
        ApplyGlobalHotkeys();
        await RefreshAllAsync();
        if (_navTag == "resource")
        {
            PopulateCategoryFilter();
        }
    }

    private async void OnImportBookmarksClick(object sender, RoutedEventArgs e)
    {
        if (_dialogOpen)
        {
            return;
        }
        var picker = new Windows.Storage.Pickers.FileOpenPicker();
        picker.FileTypeFilter.Add(".html");
        picker.FileTypeFilter.Add(".htm");
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var file = await picker.PickSingleFileAsync();
        if (file is null)
        {
            return;
        }

        var info = new FileInfo(file.Path);
        if (!info.Exists || info.Length > BookmarkFileParser.MaxFileBytes)
        {
            _error = "书签文件无法读取或超过 10MB 上限。";
            UpdateStatus();
            return;
        }

        List<Models.BookmarkInput> items;
        try
        {
            var html = await File.ReadAllTextAsync(file.Path);
            items = BookmarkFileParser.Parse(html);
        }
        catch (Exception ex)
        {
            _error = $"读取书签文件失败：{ex.Message}";
            UpdateStatus();
            return;
        }
        if (items.Count == 0)
        {
            _error = "没有解析到书签，请确认选择的是 Chrome/Edge 导出的 HTML 书签文件。";
            UpdateStatus();
            return;
        }

        _error = null;
        _dialogOpen = true;
        try
        {
            await new BookmarkImportDialog(_state, items).ShowAsync(RootGrid.XamlRoot);
        }
        finally
        {
            _dialogOpen = false;
        }
        await AfterWriteAsync();
    }

    private async void OnUndoClick(object sender, RoutedEventArgs e)
    {
        _error = null;
        var error = await _state.UndoLastCreateAsync();
        _error = error;
        await RefreshAllAsync();
    }

    private async void OnCreateClick(object sender, RoutedEventArgs e) =>
        await ShowMemoDialogAsync(_navTag, null);

    private async void OnEditClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is { } memo)
        {
            await ShowMemoDialogAsync(memo.Type, memo);
        }
    }

    /// <summary>查看条目的会议转写内容；同一时间只允许一个弹窗。</summary>
    private async void OnTranscriptClick(object sender, RoutedEventArgs e)
    {
        if (_dialogOpen || MemoOf(sender) is not { } memo)
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(memo.Transcript))
        {
            _error = "该录音没有可用转写。";
            UpdateStatus();
            return;
        }

        _dialogOpen = true;
        try
        {
            var transcriptBox = new TextBox
            {
                Text = memo.Transcript,
                IsReadOnly = true,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                Height = 420,
                Width = 620,
            };
            var dialog = new ContentDialog
            {
                Title = string.IsNullOrWhiteSpace(memo.Title) ? "会议转写" : $"会议转写 - {memo.Title}",
                Content = transcriptBox,
                CloseButtonText = "关闭",
                DefaultButton = ContentDialogButton.Close,
                XamlRoot = RootGrid.XamlRoot,
            };
            await dialog.ShowAsync();
        }
        finally
        {
            _dialogOpen = false;
        }
    }

    /// <summary>条目"更多操作"菜单：修改分类、设置阅读状态。</summary>
    private void OnMemoMenuClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo || sender is not FrameworkElement anchor)
        {
            return;
        }
        var menu = new MenuFlyout();

        if (memo.IsResource)
        {
            var categoryMenu = new MenuFlyoutSubItem { Text = $"分类（当前：{memo.CategoryDisplay}）" };
            var clearItem = new MenuFlyoutItem { Text = "清除分类" };
            clearItem.Click += async (_, _) =>
            {
                if (await HandleAsync(() => _state.SetResourceCategoryAsync(memo, null)))
                {
                    await AfterWriteAsync();
                }
            };
            categoryMenu.Items.Add(clearItem);
            foreach (var category in _state.Categories)
            {
                var item = new MenuFlyoutItem { Text = category.Name };
                item.Click += async (_, _) =>
                {
                    if (await HandleAsync(() => _state.SetResourceCategoryAsync(memo, category.Code)))
                    {
                        await AfterWriteAsync();
                    }
                };
                categoryMenu.Items.Add(item);
            }
            menu.Items.Add(categoryMenu);

            var readingMenu = new MenuFlyoutSubItem { Text = $"阅读状态（当前：{memo.ReadingStatusDisplay}）" };
            foreach (var (label, code) in new[]
                     {
                         ("未读", "unread"),
                         ("阅读中", "reading"),
                         ("已完成", "completed"),
                         ("已归档", "archived"),
                     })
            {
                var item = new MenuFlyoutItem { Text = label };
                item.Click += async (_, _) =>
                {
                    if (await HandleAsync(() => _state.SetReadingStatusAsync(memo, code)))
                    {
                        await AfterWriteAsync();
                    }
                };
                readingMenu.Items.Add(item);
            }
            menu.Items.Add(readingMenu);
        }

        var speakItem = new MenuFlyoutItem
        {
            Text = memo.IsWord ? "朗读单词" : "朗读正文",
        };
        speakItem.Click += async (_, _) =>
        {
            _error = await _state.SpeakAsync(memo.IsWord ? memo.Title : memo.Body);
            UpdateStatus();
        };
        menu.Items.Add(speakItem);

        menu.ShowAt(anchor);
    }

    /// <summary>朗读单词：优先服务端 TTS，回退系统语音。</summary>
    private async void OnPronounceClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is { } memo)
        {
            _error = await _state.SpeakAsync(memo.Title);
            UpdateStatus();
        }
    }

    /// <summary>用系统默认浏览器打开资料链接；仅在复习队列中打开时标记为"阅读中"。</summary>
    private async void OnOpenResourceClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { SourceUrl: { Length: > 0 } url } memo ||
            !Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            return;
        }
        var opened = await Windows.System.Launcher.LaunchUriAsync(uri);
        if (!opened)
        {
            _error = "无法打开默认浏览器，请检查系统默认应用设置。";
            UpdateStatus();
            return;
        }
        _error = null;
        // 与 Web 一致：只有从"复习"里打开待读资料才标记阅读中，资料库中打开不改状态。
        var fromReviewQueue = _state.ReviewItems.Any(item => item.Id == memo.Id);
        if (fromReviewQueue && memo.IsResource && memo.Id is not null)
        {
            await HandleAsync(() => _state.MarkResourceReadingAsync(memo));
            ReviewList.ItemsSource = _state.ReviewItems.ToList();
        }
    }

    private async void OnReviewStarClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (await HandleAsync(() => _state.ToggleReviewStarAsync(memo)))
        {
            ReviewList.ItemsSource = _state.ReviewItems.ToList();
        }
    }

    private async void OnOrganizeIdeaClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (await HandleAsync(() => _state.OrganizeIdeaAsync(memo)))
        {
            ReviewList.ItemsSource = _state.ReviewItems.ToList();
            RefreshLists();
            UpdateReviewSummary();
        }
    }

    private async void OnArchiveIdeaClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (await HandleAsync(() => _state.ArchiveIdeaAsync(memo)))
        {
            ReviewList.ItemsSource = _state.ReviewItems.ToList();
            UpdateReviewSummary();
        }
    }

    private async void OnReviewFilterClick(object sender, RoutedEventArgs e)
    {
        if (sender is not ToggleButton { Tag: string tag })
        {
            return;
        }
        _reviewFilter = tag == "all" ? null : tag;
        ReviewFilterAll.IsChecked = _reviewFilter is null;
        ReviewFilterWord.IsChecked = _reviewFilter == "word";
        ReviewFilterResource.IsChecked = _reviewFilter == "resource";
        ReviewFilterIdea.IsChecked = _reviewFilter == "idea";
        await _state.LoadReviewAsync(_reviewFilter);
        ReviewList.ItemsSource = _state.ReviewItems.ToList();
        UpdateReviewSummary();
        UpdateStatus();
    }

    private void UpdateReviewSummary()
    {
        var total = _state.ReviewWordCount + _state.ReviewResourceCount + _state.ReviewIdeaCount;
        ReviewSummary.Text = total == 0
            ? "今天的回顾已完成 🎉"
            : $"今天有 {total} 条值得回顾：{_state.ReviewWordCount} 个单词 · "
              + $"{_state.ReviewResourceCount} 篇待读 · {_state.ReviewIdeaCount} 条待整理";
    }

    // ---------- 列表键盘导航 ----------

    /// <summary>列表内键盘操作：↑↓ 移动选择、Enter 打开、Delete 移入回收站、Esc 取消选择。</summary>
    private async void OnMemoListKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (sender is not ListView list)
        {
            return;
        }
        switch (e.Key)
        {
            case Windows.System.VirtualKey.Up:
                e.Handled = true;
                MoveSelection(list, -1);
                break;
            case Windows.System.VirtualKey.Down:
                e.Handled = true;
                MoveSelection(list, 1);
                break;
            case Windows.System.VirtualKey.Enter:
                e.Handled = true;
                if (CurrentMemo(list) is { } current)
                {
                    await ShowMemoDialogAsync(current.Type, current);
                }
                break;
            case Windows.System.VirtualKey.Delete:
                e.Handled = true;
                if (CurrentMemo(list) is { } deleting)
                {
                    await ConfirmAndTrashAsync(deleting);
                }
                break;
            case Windows.System.VirtualKey.Escape:
                e.Handled = true;
                list.SelectedItems.Clear();
                UpdateBulkBar();
                break;
        }
    }

    /// <summary>上下移动选择（单选语义：始终保留一条选中项）。</summary>
    private static void MoveSelection(ListView list, int delta)
    {
        var items = list.Items.OfType<object>().ToList();
        if (items.Count == 0)
        {
            return;
        }
        var currentIndex = list.SelectedIndex;
        var nextIndex = currentIndex < 0
            ? (delta > 0 ? 0 : items.Count - 1)
            : Math.Clamp(currentIndex + delta, 0, items.Count - 1);
        list.SelectedIndex = nextIndex;
        list.ScrollIntoView(items[nextIndex]);
    }

    private static Memo? CurrentMemo(ListView list) =>
        list.SelectedItem as Memo ?? (list.Items.Count > 0 ? list.Items[0] as Memo : null);

    private async Task ConfirmAndTrashAsync(Memo memo)
    {
        if (!await ConfirmAsync(
                "移入回收站？",
                $"「{memo.Title}」将进入回收站，30 天后永久删除。",
                "移入回收站"))
        {
            return;
        }
        if (await HandleAsync(() => _state.TrashAsync(memo)))
        {
            await AfterWriteAsync();
        }
    }

    // ---------- 批量操作 ----------

    private bool _multiSelect;

    private void OnMultiSelectClick(object sender, RoutedEventArgs e)
    {
        _multiSelect = MultiSelectToggle.IsChecked == true;
        ApplyMultiSelectMode();
    }

    private void ApplyMultiSelectMode()
    {
        var mode = _multiSelect ? ListViewSelectionMode.Multiple : ListViewSelectionMode.None;
        MemoList.SelectionMode = mode;
        TrashList.SelectionMode = mode;
        if (!_multiSelect)
        {
            MemoList.SelectedItems.Clear();
            TrashList.SelectedItems.Clear();
        }
        UpdateBulkBar();
    }

    private void OnListSelectionChanged(object sender, SelectionChangedEventArgs e) => UpdateBulkBar();

    private List<Memo> SelectedMemos()
    {
        var source = _navTag == "trash" ? TrashList.SelectedItems : MemoList.SelectedItems;
        return source.OfType<Memo>().ToList();
    }

    private void UpdateBulkBar()
    {
        var selected = SelectedMemos();
        var visible = _multiSelect && _navTag is "all" or "idea" or "word" or "resource" or "image" or "trash";
        BulkActionBar.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
        BulkCountLabel.Text = $"已选 {selected.Count} 条";
        var inTrash = _navTag == "trash";
        BulkRestoreButton.Visibility = inTrash ? Visibility.Visible : Visibility.Collapsed;
        foreach (var child in BulkActionBar.Children.OfType<Button>())
        {
            child.IsEnabled = selected.Count > 0;
        }
    }

    private async void OnBulkStarClick(object sender, RoutedEventArgs e) =>
        await RunBulkAsync(() => _state.StarManyAsync(SelectedMemos(), true));

    private async void OnBulkUnstarClick(object sender, RoutedEventArgs e) =>
        await RunBulkAsync(() => _state.StarManyAsync(SelectedMemos(), false));

    private async void OnBulkTrashClick(object sender, RoutedEventArgs e)
    {
        var selected = SelectedMemos();
        if (selected.Count == 0)
        {
            return;
        }
        if (!await ConfirmAsync(
                "批量移入回收站？",
                $"选中的 {selected.Count} 条内容将进入回收站，30 天后永久删除。",
                "移入回收站"))
        {
            return;
        }
        await RunBulkAsync(() => _state.TrashManyAsync(selected));
    }

    private async void OnBulkRestoreClick(object sender, RoutedEventArgs e) =>
        await RunBulkAsync(() => _state.RestoreManyAsync(SelectedMemos()));

    private void OnBulkClearClick(object sender, RoutedEventArgs e)
    {
        MemoList.SelectedItems.Clear();
        TrashList.SelectedItems.Clear();
        UpdateBulkBar();
    }

    private async Task RunBulkAsync(Func<Task<string?>> action)
    {
        _error = await action();
        MemoList.SelectedItems.Clear();
        TrashList.SelectedItems.Clear();
        RefreshLists();
        TrashList.ItemsSource = _state.TrashedMemos.ToList();
        UpdateBulkBar();
        UpdateStatus();
    }

    private async void OnEmptyTrashClick(object sender, RoutedEventArgs e)
    {
        if (!await ConfirmAsync(
                "清空回收站？",
                $"回收站中的 {_state.TrashTotal} 条内容将被永久删除，且无法恢复。",
                "永久删除"))
        {
            return;
        }
        _error = await _state.EmptyTrashAsync();
        TrashList.ItemsSource = _state.TrashedMemos.ToList();
        UpdateStatus();
    }

    // ---------- 网页巡检 ----------

    private async void OnHealthFilterClick(object sender, RoutedEventArgs e)
    {
        if (sender is not ToggleButton { Tag: string tag })
        {
            return;
        }
        _healthFilter = string.IsNullOrWhiteSpace(tag) ? null : tag;
        HealthFilterPending.IsChecked = _healthFilter is null;
        HealthFilterFailed.IsChecked = _healthFilter == "failed";
        HealthFilterRedirected.IsChecked = _healthFilter == "redirected";
        HealthFilterChanged.IsChecked = _healthFilter == "changed";
        HealthFilterTemporary.IsChecked = _healthFilter == "temporary_failure";
        HealthFilterAuth.IsChecked = _healthFilter == "auth_required";
        HealthFilterIgnored.IsChecked = _healthFilter == "ignored";
        await _state.LoadLinkHealthAsync(_healthFilter);
        HealthList.ItemsSource = _state.LinkHealthItems.ToList();
        UpdateHealthSummary();
        UpdateStatus();
    }

    private void UpdateHealthSummary()
    {
        var counts = _state.LinkHealthCounts;
        string Count(string key) => counts.TryGetValue(key, out var value) ? value.ToString() : "0";
        LinkHealthSummary.Text =
            $"确认失效 {Count("failed")} · 网址跳转 {Count("redirected")} · "
            + $"信息变化 {Count("changed")} · 暂时失败 {Count("temporary_failure")}"
            + $" · 需要登录 {Count("auth_required")}";
    }

    private async void OnHealthRetryClick(object sender, RoutedEventArgs e) =>
        await ApplyHealthActionAsync(sender, "retry");

    private async void OnHealthAdoptClick(object sender, RoutedEventArgs e) =>
        await ApplyHealthActionAsync(sender, "adopt_redirect");

    private async void OnHealthUpdateMetadataClick(object sender, RoutedEventArgs e) =>
        await ApplyHealthActionAsync(sender, "update_metadata");

    private async void OnHealthIgnoreClick(object sender, RoutedEventArgs e) =>
        await ApplyHealthActionAsync(sender, "ignore");

    private async void OnHealthResumeClick(object sender, RoutedEventArgs e) =>
        await ApplyHealthActionAsync(sender, "resume");

    private async Task ApplyHealthActionAsync(object sender, string action)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (await HandleAsync(() => _state.ApplyLinkHealthActionAsync(memo, action)))
        {
            HealthList.ItemsSource = _state.LinkHealthItems.ToList();
            UpdateHealthSummary();
        }
    }

    private async void OnHealthUpdateUrlClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo || _dialogOpen)
        {
            return;
        }
        _dialogOpen = true;
        string? newUrl;
        try
        {
            var input = new TextBox
            {
                Text = memo.SourceUrl ?? string.Empty,
                PlaceholderText = "https://example.com/article",
            };
            var dialog = new ContentDialog
            {
                XamlRoot = RootGrid.XamlRoot,
                Title = "更新网址",
                Content = input,
                PrimaryButtonText = "保存",
                CloseButtonText = "取消",
                DefaultButton = ContentDialogButton.Primary,
            };
            if (await dialog.ShowAsync() != ContentDialogResult.Primary)
            {
                return;
            }
            newUrl = AppState.NormalizeUrl(input.Text);
        }
        finally
        {
            _dialogOpen = false;
        }

        if (newUrl is null)
        {
            _error = "请输入有效的网址，例如 https://example.com/article";
            UpdateStatus();
            return;
        }
        if (await HandleAsync(() => _state.ApplyLinkHealthActionAsync(memo, "update_url", newUrl)))
        {
            HealthList.ItemsSource = _state.LinkHealthItems.ToList();
            UpdateHealthSummary();
        }
    }

    private async void OnHealthDeleteClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (!await ConfirmAsync(
                "移入回收站？",
                $"「{memo.Title}」将从巡检列表移除并进入回收站。",
                "移入回收站"))
        {
            return;
        }
        if (await HandleAsync(() => _state.ApplyLinkHealthActionAsync(memo, "delete")))
        {
            HealthList.ItemsSource = _state.LinkHealthItems.ToList();
            UpdateHealthSummary();
        }
    }

    private async void OnStarClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        await HandleAsync(() => _state.ToggleStarAsync(memo));
        await AfterWriteAsync();
    }

    private async void OnDeleteClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (!await ConfirmAsync("移入回收站？", $"「{memo.Title}」将进入回收站，30 天后永久删除。", "移入回收站"))
        {
            return;
        }
        await HandleAsync(() => _state.TrashAsync(memo));
        await AfterWriteAsync();
    }

    private async void OnReviewForgotClick(object sender, RoutedEventArgs e) =>
        await SubmitReviewAsync(sender, "forgot");

    private async void OnReviewFuzzyClick(object sender, RoutedEventArgs e) =>
        await SubmitReviewAsync(sender, "fuzzy");

    private async void OnReviewRememberedClick(object sender, RoutedEventArgs e) =>
        await SubmitReviewAsync(sender, "remembered");

    private async Task SubmitReviewAsync(object sender, string feedback)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (await HandleAsync(() => _state.SubmitReviewAsync(memo, feedback)))
        {
            ReviewList.ItemsSource = _state.ReviewItems.ToList();
        }
    }

    private async void OnReviewSkipClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (await HandleAsync(() => _state.SkipReviewAsync(memo)))
        {
            ReviewList.ItemsSource = _state.ReviewItems.ToList();
        }
    }

    private async void OnRestoreClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (await HandleAsync(() => _state.RestoreAsync(memo)))
        {
            TrashList.ItemsSource = _state.TrashedMemos.ToList();
            RefreshLists();
        }
    }

    private async void OnPurgeClick(object sender, RoutedEventArgs e)
    {
        if (MemoOf(sender) is not { } memo)
        {
            return;
        }
        if (!await ConfirmAsync("永久删除？", $"「{memo.Title}」将被永久删除，无法恢复。", "永久删除"))
        {
            return;
        }
        if (await HandleAsync(() => _state.PurgeAsync(memo)))
        {
            TrashList.ItemsSource = _state.TrashedMemos.ToList();
        }
    }

    // ---------- 拖拽收藏 ----------

    private void OnDragOver(object sender, DragEventArgs e)
    {
        if (e.DataView.Contains(StandardDataFormats.StorageItems) ||
            e.DataView.Contains(StandardDataFormats.WebLink) ||
            e.DataView.Contains(StandardDataFormats.Text))
        {
            e.AcceptedOperation = DataPackageOperation.Copy;
            e.DragUIOverride.Caption = "收藏到 MemoIsle";
        }
    }

    private async void OnDrop(object sender, DragEventArgs e)
    {
        // 优先处理拖入的图片文件（PNG / JPG / WebP / GIF）。
        if (e.DataView.Contains(StandardDataFormats.StorageItems))
        {
            IReadOnlyList<Windows.Storage.IStorageItem> dropped;
            try
            {
                dropped = await e.DataView.GetStorageItemsAsync();
            }
            catch (Exception)
            {
                return;
            }
            var image = dropped
                .OfType<Windows.Storage.StorageFile>()
                .FirstOrDefault(file => MemoImageFiles.IsSupported(file.Path));
            if (image is not null)
            {
                await CreateImageFromFileAsync(image.Path);
                return;
            }
            _error = "仅支持拖入 PNG / JPG / WebP / GIF 图片，或网页链接。";
            UpdateStatus();
            return;
        }

        string? url = null;
        try
        {
            if (e.DataView.Contains(StandardDataFormats.WebLink))
            {
                var link = await e.DataView.GetWebLinkAsync();
                url = link?.ToString();
            }
            else if (e.DataView.Contains(StandardDataFormats.Text))
            {
                url = ExtractUrl(await e.DataView.GetTextAsync());
            }
        }
        catch (Exception)
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(url))
        {
            _error = "没有识别到可收藏的网址，请拖入网页链接或文本中的 URL。";
            UpdateStatus();
            return;
        }

        _error = null;
        var error = await _state.CreateResourceAsync(url, string.Empty, string.Empty);
        _error = error;
        await RefreshAllAsync();
    }

    private static string? ExtractUrl(string text)
    {
        var match = System.Text.RegularExpressions.Regex.Match(text, @"https?://\S+");
        return match.Success ? match.Value.TrimEnd('.', ',', '，', '。') : null;
    }

    // ---------- 快速捕获 ----------

    private async void OnQuickSaveClick(object sender, RoutedEventArgs e) =>
        await SaveQuickCaptureAsync();

    private async void OnQuickCaptureKeyDown(object sender, KeyRoutedEventArgs e)
    {
        var ctrlDown = Microsoft.UI.Input.InputKeyboardSource
            .GetKeyStateForCurrentThread(Windows.System.VirtualKey.Control)
            .HasFlag(Windows.UI.Core.CoreVirtualKeyStates.Down);
        if (e.Key == Windows.System.VirtualKey.Enter && ctrlDown)
        {
            e.Handled = true;
            await SaveQuickCaptureAsync();
        }
    }

    private async Task SaveQuickCaptureAsync()
    {
        var body = QuickCaptureBox.Text.Trim();
        if (body.Length == 0)
        {
            return;
        }
        _error = null;
        var error = await _state.CreateIdeaAsync(body);
        _error = error;
        if (error is null)
        {
            QuickCaptureBox.Text = string.Empty;
        }
        await RefreshAllAsync();
    }

    private async void OnQuickWordClick(object sender, RoutedEventArgs e) =>
        await ShowMemoDialogAsync(MemoTypes.Word, null);

    private async void OnQuickResourceClick(object sender, RoutedEventArgs e) =>
        await ShowMemoDialogAsync(MemoTypes.Resource, null);

    // ---------- 图片收藏 ----------

    /// <summary>「收藏图片」：选本地图片 → 建图片条目 → 上传原图。</summary>
    private async void OnQuickImageClick(object sender, RoutedEventArgs e)
    {
        if (_dialogOpen)
        {
            return;
        }
        var file = await PickImageFileAsync();
        if (file is null)
        {
            return;
        }
        await CreateImageFromFileAsync(file.Path);
    }

    /// <summary>打开图片选择器（限制为后端支持的四种格式）。</summary>
    private async Task<Windows.Storage.StorageFile?> PickImageFileAsync()
    {
        var picker = new Windows.Storage.Pickers.FileOpenPicker();
        foreach (var extension in MemoImageFiles.Extensions)
        {
            picker.FileTypeFilter.Add(extension);
        }
        if (WindowHandle != IntPtr.Zero)
        {
            WinRT.Interop.InitializeWithWindow.Initialize(picker, WindowHandle);
        }
        return await picker.PickSingleFileAsync();
    }

    /// <summary>
    /// 从本地文件收藏图片：先建条目，再以裸字节上传原图（超出后端限制时自动压缩），最后跳到图片视图。
    /// </summary>
    private async Task CreateImageFromFileAsync(string path)
    {
        var mime = MemoImageFiles.MimeTypeFor(path);
        if (mime is null)
        {
            _error = "仅支持 PNG / JPG / WebP / GIF 图片。";
            UpdateStatus();
            return;
        }
        var info = new FileInfo(path);
        if (!info.Exists)
        {
            _error = "图片文件不存在或无法读取。";
            UpdateStatus();
            return;
        }

        _error = null;
        var (created, createError) = await _state.CreateImageAsync(
            Path.GetFileNameWithoutExtension(path),
            string.Empty);
        if (createError is not null || created is null)
        {
            _error = createError ?? "图片条目创建失败。";
            UpdateStatus();
            return;
        }

        var uploadError = await _state.UploadImageAsync(created, path, mime);
        _error = uploadError;
        await SwitchToImageAsync(created.Id);
        // 列表刷新会覆盖状态栏文本：刷新后再取回压缩提示，重新写回状态栏并弹一次通知。
        var compressionNotice = _state.ConsumeImageCompressionNotice();
        if (uploadError is null)
        {
            QuickCapture.ShowToast(
                compressionNotice is null ? "图片已收藏" : $"图片已收藏；{compressionNotice}");
        }
    }

    /// <summary>切到图片视图并刷新列表，尽量滚动/选中刚收藏的条目。</summary>
    private async Task SwitchToImageAsync(string? memoId)
    {
        if (_navTag != "image")
        {
            _navTag = "image";
            if (NavList.SelectedIndex != 4)
            {
                NavList.SelectedIndex = 4;
            }
        }
        await RefreshAllAsync();
        if (memoId is null)
        {
            return;
        }
        var target = (MemoList.ItemsSource as IEnumerable<Memo>)?
            .FirstOrDefault(memo => memo.Id == memoId);
        if (target is not null)
        {
            MemoList.ScrollIntoView(target);
            try
            {
                MemoList.SelectedItem = target;
            }
            catch (Exception)
            {
                // SelectionMode.None 时无法程序化选中，滚动到可见即可。
            }
        }
        UpdateStatus();
    }

    // ---------- 快捷键 ----------

    private void OnNewAccelerator(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        args.Handled = true;
        OnCreateClick(sender, new RoutedEventArgs());
    }

    private void OnFocusSearchAccelerator(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        args.Handled = true;
        SearchBox.Focus(FocusState.Programmatic);
    }

    private void OnRefreshAccelerator(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        args.Handled = true;
        OnRefreshClick(sender, new RoutedEventArgs());
    }

    /// <summary>Ctrl+I：直接新建灵感（不依赖当前视图）。</summary>
    private async void OnIdeaAccelerator(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        args.Handled = true;
        await ShowMemoDialogAsync(MemoTypes.Idea, null);
    }

    /// <summary>Ctrl+W：直接收藏单词。</summary>
    private async void OnWordAccelerator(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        args.Handled = true;
        await ShowMemoDialogAsync(MemoTypes.Word, null);
    }

    /// <summary>Ctrl+L：直接收藏网页资料。</summary>
    private async void OnResourceAccelerator(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        args.Handled = true;
        await ShowMemoDialogAsync(MemoTypes.Resource, null);
    }

    // ---------- 辅助 ----------

    private static Memo? MemoOf(object sender) =>
        (sender as FrameworkElement)?.DataContext as Memo;

    /// <summary>当前窗口句柄：WinUI 3 的 FileOpenPicker / FileSavePicker 必须先绑定窗口。</summary>
    private IntPtr WindowHandle
    {
        get
        {
            if (_hwnd != IntPtr.Zero)
            {
                return _hwnd;
            }
            try
            {
                return WinRT.Interop.WindowNative.GetWindowHandle(this);
            }
            catch (Exception)
            {
                return IntPtr.Zero;
            }
        }
    }

    /// <summary>执行写操作并显示错误；返回是否成功。</summary>
    private async Task<bool> HandleAsync(Func<Task<string?>> action)
    {
        var error = await action();
        _error = error;
        UpdateStatus();
        return error is null;
    }

    private async Task AfterWriteAsync()
    {
        // 写操作后从服务端重新拉取，确保编辑/星标等结果立即反映到列表。
        await RefreshAllAsync();
    }

    /// <summary>打开新建/编辑对话框；同一时间只允许一个对话框，避免快速连点冲突。</summary>
    private async Task ShowMemoDialogAsync(string type, Memo? existing)
    {
        if (_dialogOpen)
        {
            return;
        }
        _dialogOpen = true;
        try
        {
            await MemoDialogs.ShowAsync(
                RootGrid.XamlRoot,
                _state,
                type,
                existing,
                onLocate: LocateWord,
                hwnd: WindowHandle);
        }
        finally
        {
            _dialogOpen = false;
        }
        await AfterWriteAsync();
        // 图片对话框里的压缩提示在刷新后重新写回状态栏，避免刚提示就被同步文案覆盖。
        if (_state.ConsumeImageCompressionNotice() is not null)
        {
            _error = null;
            UpdateStatus();
        }
    }

    /// <summary>重复词形冲突时定位到单词视图中的原条目。</summary>
    private void LocateWord(Memo memo)
    {
        if (NavList.SelectedIndex != 2)
        {
            NavList.SelectedIndex = 2;
        }
        _search = memo.Title;
        SearchBox.Text = memo.Title;
        RefreshLists();
        UpdateStatus();
    }

    private async Task<bool> ConfirmAsync(string title, string message, string primaryText)
    {
        if (_dialogOpen)
        {
            return false;
        }
        _dialogOpen = true;
        try
        {
            var dialog = new ContentDialog
            {
                XamlRoot = RootGrid.XamlRoot,
                Title = title,
                Content = new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap },
                PrimaryButtonText = primaryText,
                CloseButtonText = "取消",
                DefaultButton = ContentDialogButton.Close,
            };
            return await dialog.ShowAsync() == ContentDialogResult.Primary;
        }
        finally
        {
            _dialogOpen = false;
        }
    }

    private void UpdateStatus()
    {
        StatusText.Text = _error ?? _state.StatusMessage;
        BusyRing.IsActive = _state.IsBusy;
        SideUserLabel.Text = _state.CurrentUser?.DisplayName is { Length: > 0 } name
            ? name
            : _state.CurrentUser?.Email ?? string.Empty;
        // 邮箱未验证时，登录页显示"重新发送验证邮件"入口。
        ResendVerificationButton.Visibility = _state.CurrentUser is { EmailVerified: false, Email.Length: > 0 }
            ? Visibility.Visible
            : Visibility.Collapsed;
        DevLoginButton.Visibility = _state.DevLoginAvailable ? Visibility.Visible : Visibility.Collapsed;
        UndoButton.Visibility = _state.UndoableMemo is not null
            ? Visibility.Visible
            : Visibility.Collapsed;
        SetNavCount(0, _state.TotalCountTotal);
        SetNavCount(1, _state.IdeaCountTotal);
        SetNavCount(2, _state.WordCountTotal);
        SetNavCount(3, _state.ResourceCountTotal);
        SetNavCount(4, _state.ImageCountTotal);
        SetNavCount(5, _state.ReviewTotal);
        SetNavCount(6, _state.TrashTotal);
        SetNavCount(7, _state.HealthIssueCount);
        UpdateListHeader();
    }

    private void SetNavCount(int index, int count)
    {
        var target = index switch
        {
            0 => NavCount0,
            1 => NavCount1,
            2 => NavCount2,
            3 => NavCount3,
            4 => NavCount4,
            5 => NavCount5,
            6 => NavCount6,
            _ => NavCount7,
        };
        target.Text = count.ToString();
    }

    /// <summary>列表头：当前视图名称、条目数与排序说明。</summary>
    private void UpdateListHeader()
    {
        var label = _navTag switch
        {
            "idea" => "灵感",
            "word" => "单词",
            "resource" => "资料",
            "image" => "图片",
            "review" => "复习",
            "trash" => "回收站",
            _ => "全部备忘",
        };
        var count = _navTag switch
        {
            "review" => _state.ReviewTotal,
            "trash" => _state.TrashTotal,
            _ => (MemoList.ItemsSource as System.Collections.ICollection)?.Count ?? 0,
        };
        var sortLabel = SortBox?.SelectedItem is ComboBoxItem { Content: string sortText }
            ? sortText
            : "最近更新";
        ListHeader.Text = $"{label} · {count} 条 · {sortLabel}";

        // 资料视图显示服务端分页条。
        var isResource = _navTag == "resource";
        PagerBar.Visibility = isResource ? Visibility.Visible : Visibility.Collapsed;
        if (isResource)
        {
            PageLabel.Text = $"第 {_state.ResourcePage} / {_state.ResourcePageCount} 页 · 共 {_state.ResourceTotalCount} 条";
            PrevPageButton.IsEnabled = _state.ResourcePage > 1;
            NextPageButton.IsEnabled = _state.ResourcePage < _state.ResourcePageCount;
        }
    }
}
