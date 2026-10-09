using MemoIsle.Desktop.Models;
using MemoIsle.Desktop.Services;
using Microsoft.UI.Input;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.System;
using Windows.UI.Core;

namespace MemoIsle.Desktop;

/// <summary>设置面板：快捷键自定义 + 分类模板与规则。</summary>
internal sealed class SettingsDialog
{
    private readonly AppState _state;
    private readonly ContentDialog _dialog;

    // 分类相关控件
    private readonly ListView _categoryList = new()
    {
        MaxHeight = 200,
        SelectionMode = ListViewSelectionMode.None,
    };
    private readonly ListView _ruleList = new()
    {
        MaxHeight = 200,
        SelectionMode = ListViewSelectionMode.None,
    };
    private readonly TextBlock _categoryStatus = new() { FontSize = 12, TextWrapping = TextWrapping.Wrap };
    private readonly TextBox _newCategoryName = new() { Header = "新分类名称", Width = 170 };
    private readonly TextBox _newCategoryDescription = new() { Header = "分类说明（给大模型参考）", Width = 230 };
    private readonly Button _createCategoryButton = new() { Content = "创建分类" };
    private ResourceCategoryOption? _editingCategory;
    private string? _newCategoryParentCode;
    private readonly ComboBox _ruleCategory = new() { Header = "分类", Width = 150 };
    private readonly ComboBox _ruleMatchType = new() { Header = "匹配范围", Width = 110 };
    private readonly TextBox _rulePattern = new() { Header = "匹配内容（域名 / 网址片段 / 正文关键词）", Width = 250 };
    private readonly NumberBox _rulePriority = new()
    {
        Header = "优先级",
        Value = 100,
        Width = 90,
        SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Inline,
    };

    // 快捷键相关控件
    private readonly StackPanel _hotkeyRows = new() { Spacing = 6 };
    private readonly TextBlock _generalStatus = new() { FontSize = 12, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _hotkeyStatus = new() { FontSize = 12, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _translationStatus = new() { FontSize = 12, TextWrapping = TextWrapping.Wrap };
    private readonly TranslationService _translationService = new();
    private readonly Dictionary<HotkeyAction, TextBlock> _hotkeyLabels = new();
    private readonly Dictionary<HotkeyAction, Button> _hotkeyButtons = new();
    private HotkeyAction? _capturing;

    public SettingsDialog(AppState state)
    {
        _state = state;

        var tabs = new TabView
        {
            Width = 580,
            IsAddTabButtonVisible = false,
        };

        var hotkeyTab = new TabViewItem
        {
            Header = "快捷键",
            Content = new ScrollViewer { Content = BuildHotkeyPanel(), MaxHeight = 520 },
        };
        var generalTab = new TabViewItem
        {
            Header = "通用",
            Content = new ScrollViewer { Content = BuildGeneralPanel(), MaxHeight = 520 },
        };
        var categoryTab = new TabViewItem
        {
            Header = "分类与规则",
            Content = new ScrollViewer { Content = BuildCategoryPanel(), MaxHeight = 520 },
        };
        var translationTab = new TabViewItem
        {
            Header = "翻译",
            Content = new ScrollViewer { Content = BuildTranslationPanel(), MaxHeight = 520 },
        };
        tabs.TabItems.Add(generalTab);
        tabs.TabItems.Add(hotkeyTab);
        tabs.TabItems.Add(translationTab);
        tabs.TabItems.Add(categoryTab);

        _dialog = new ContentDialog
        {
            Title = "设置",
            PrimaryButtonText = "关闭",
            DefaultButton = ContentDialogButton.Primary,
            Content = tabs,
        };
    }

    public async Task ShowAsync(XamlRoot root)
    {
        _dialog.XamlRoot = root;
        RenderHotkeys();
        var showTask = _dialog.ShowAsync();
        await RefreshCategoriesAsync();
        await showTask;
        _capturing = null;
    }

    // ---------- 翻译 ----------

    private UIElement BuildTranslationPanel()
    {
        var config = TranslationSettings.Current;
        var panel = new StackPanel { Spacing = 10, Padding = new Thickness(4) };

        panel.Children.Add(new TextBlock
        {
            Text = "划词翻译：选中文字后直接按全局翻译快捷键即可（会自动复制选中内容）；"
                   + "若关闭下面的自动取词，则需要先手动 Ctrl+C 再按键。",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
        });

        var autoSelectToggle = new ToggleSwitch
        {
            Header = "选中文字后自动取词（模拟 Ctrl+C）",
            OnContent = "已开启",
            OffContent = "已关闭",
            IsOn = config.AutoCopySelection,
        };
        panel.Children.Add(autoSelectToggle);
        panel.Children.Add(new TextBlock
        {
            Text = "取词后会还原你原来的剪贴板内容；少数以管理员权限运行的程序可能拦截模拟按键，此时请手动 Ctrl+C。",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
        });

        var providerBox = new ComboBox { Header = "翻译提供方", Width = 300 };
        providerBox.Items.Add(new ComboBoxItem
        {
            Content = "自动（优先 Google，失败回退大模型）",
            Tag = "auto",
            IsSelected = config.ResolvedProvider == TranslationProvider.Auto,
        });
        providerBox.Items.Add(new ComboBoxItem
        {
            Content = "Google 免费接口（无需密钥）",
            Tag = "google",
            IsSelected = config.ResolvedProvider == TranslationProvider.Google,
        });
        providerBox.Items.Add(new ComboBoxItem
        {
            Content = "仅用自配大模型（OpenAI 兼容）",
            Tag = "llm",
            IsSelected = config.ResolvedProvider == TranslationProvider.Llm,
        });
        panel.Children.Add(providerBox);

        var languageBox = new ComboBox { Header = "目标语言", Width = 240 };
        foreach (var (code, label) in TranslationSettings.TargetLanguages)
        {
            languageBox.Items.Add(new ComboBoxItem
            {
                Content = label,
                Tag = code,
                IsSelected = code == config.TargetLanguage,
            });
        }
        panel.Children.Add(languageBox);

        var autoCopyToggle = new ToggleSwitch
        {
            Header = "翻译完成后自动复制译文",
            OnContent = "已开启",
            OffContent = "已关闭",
            IsOn = config.AutoCopy,
        };
        panel.Children.Add(autoCopyToggle);

        // 大模型配置区：选择 LLM 时才需要。
        var llmPanel = new StackPanel
        {
            Spacing = 8,
            Visibility = config.ResolvedProvider != TranslationProvider.Google
                ? Visibility.Visible
                : Visibility.Collapsed,
        };
        var apiBaseBox = new TextBox
        {
            Header = "接口地址（OpenAI 兼容，例如 https://api.openai.com/v1 或本地 http://127.0.0.1:11434/v1）",
            Text = config.ApiBase,
            Width = 460,
        };
        var apiKeyBox = new PasswordBox
        {
            Header = "API Key（本地服务可留空）",
            Password = config.ApiKey,
            Width = 460,
        };
        var modelBox = new TextBox
        {
            Header = "模型名（例如 gpt-4o-mini / qwen2.5:7b）",
            Text = config.Model,
            Width = 460,
        };
        var promptBox = new TextBox
        {
            Header = "系统提示词（{target} 会替换为目标语言）",
            Text = config.SystemPrompt,
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            Height = 70,
            Width = 460,
        };
        llmPanel.Children.Add(apiBaseBox);
        llmPanel.Children.Add(apiKeyBox);
        llmPanel.Children.Add(modelBox);
        llmPanel.Children.Add(promptBox);
        panel.Children.Add(llmPanel);

        providerBox.SelectionChanged += (_, _) =>
        {
            var isLlm = (providerBox.SelectedItem as ComboBoxItem)?.Tag as string == "llm";
            llmPanel.Visibility = isLlm ? Visibility.Visible : Visibility.Collapsed;
        };

        var saveButton = new Button { Content = "保存翻译设置" };
        saveButton.Click += (_, _) =>
        {
            var updated = TranslationSettings.Current.Clone();
            updated.Provider = (providerBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "google";
            updated.TargetLanguage = (languageBox.SelectedItem as ComboBoxItem)?.Tag as string ?? "zh-CN";
            updated.AutoCopy = autoCopyToggle.IsOn;
            updated.AutoCopySelection = autoSelectToggle.IsOn;
            updated.ApiBase = apiBaseBox.Text.Trim();
            updated.ApiKey = apiKeyBox.Password.Trim();
            updated.Model = modelBox.Text.Trim();
            updated.SystemPrompt = promptBox.Text.Trim();
            TranslationSettings.Save(updated);
            _translationStatus.Text = $"已保存：{updated.Provider switch
            {
                "llm" => $"大模型（{updated.Model}）",
                _ => "Google 免费接口",
            }} → {TranslationSettings.LanguageLabel(updated.TargetLanguage)}";
        };

        var testButton = new Button { Content = "测试翻译" };
        testButton.Click += async (_, _) =>
        {
            _translationStatus.Text = "正在测试翻译…";
            var (translation, language, error) = await _translationService.TranslateAsync("Hello, world.");
            _translationStatus.Text = error is null
                ? $"测试成功（源语言 {language ?? "未知"}）：{translation}"
                : $"测试失败：{error}";
        };

        var actionRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        actionRow.Children.Add(saveButton);
        actionRow.Children.Add(testButton);
        panel.Children.Add(actionRow);
        panel.Children.Add(_translationStatus);

        panel.Children.Add(new TextBlock
        {
            Text = "提示：Google 免费接口在部分网络环境下不可用，可改用大模型翻译（支持 OpenAI 兼容接口与本地 Ollama / vLLM）。",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
        });
        return panel;
    }

    // ---------- 通用 ----------

    private UIElement BuildGeneralPanel()
    {
        var panel = new StackPanel { Spacing = 12, Padding = new Thickness(4) };

        var startupToggle = new ToggleSwitch
        {
            Header = "开机自动启动",
            OnContent = "已开启",
            OffContent = "已关闭",
            IsOn = StartupSettings.IsEnabled(),
        };
        startupToggle.Toggled += (_, _) =>
        {
            var ok = StartupSettings.SetEnabled(startupToggle.IsOn);
            if (!ok)
            {
                _generalStatus.Text = "设置开机自启失败（可能被系统策略限制）。";
                startupToggle.IsOn = StartupSettings.IsEnabled();
            }
            else
            {
                _generalStatus.Text = startupToggle.IsOn
                    ? "已开启：开机后自动在托盘后台运行，全局收藏快捷键随即可用。"
                    : "已关闭开机自启。";
            }
        };
        panel.Children.Add(startupToggle);
        panel.Children.Add(new TextBlock
        {
            Text = "开启后 MemoIsle 会在登录 Windows 时自动启动并驻留托盘，"
                   + "这样 Ctrl+Shift+W / L / I 三个全局收藏热键在任何时候都可用。",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
        });

        panel.Children.Add(new TextBlock
        {
            Text = "关闭窗口的行为",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
            Margin = new Thickness(0, 12, 0, 0),
        });
        panel.Children.Add(new TextBlock
        {
            Text = "点击窗口右上角 ✕ 会最小化到系统托盘（全局热键继续可用）；"
                   + "要完全退出请使用托盘图标右键菜单中的「退出 MemoIsle」。",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
        });

        panel.Children.Add(new TextBlock
        {
            Text = "列表键盘操作",
            FontSize = 12,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
            Margin = new Thickness(0, 12, 0, 0),
        });
        panel.Children.Add(new TextBlock
        {
            Text = "↑ / ↓ 移动选择，Enter 打开编辑，Delete 移入回收站，Esc 取消选择。"
                   + "（提示：先用工具栏「☑ 批量」或直接点击条目即可进入选择状态）",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
        });

        panel.Children.Add(_generalStatus);
        return panel;
    }

    // ---------- 快捷键 ----------

    private UIElement BuildHotkeyPanel()
    {
        var panel = new StackPanel { Spacing = 12, Padding = new Thickness(4) };
        panel.Children.Add(new TextBlock
        {
            Text = "点击右侧按钮后按下新的组合键即可改绑；需包含 Ctrl 或 Alt，只支持字母与数字。"
                   + "带「全局」标记的快捷键在任何应用里都生效（会注册到系统）。",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
        });
        panel.Children.Add(_hotkeyRows);

        var resetButton = new Button { Content = "恢复默认快捷键" };
        resetButton.Click += (_, _) =>
        {
            HotkeySettings.ResetToDefaults();
            _capturing = null;
            RenderHotkeys();
            _hotkeyStatus.Text = "已恢复默认快捷键。";
        };
        panel.Children.Add(resetButton);
        panel.Children.Add(_hotkeyStatus);
        return panel;
    }

    private void RenderHotkeys()
    {
        _hotkeyRows.Children.Clear();
        _hotkeyLabels.Clear();
        _hotkeyButtons.Clear();

        foreach (var action in Enum.GetValues<HotkeyAction>())
        {
            var row = new Grid { ColumnSpacing = 10, Padding = new Thickness(0, 2, 0, 2) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            row.Children.Add(new TextBlock
            {
                Text = HotkeySettings.ActionLabel(action),
                VerticalAlignment = VerticalAlignment.Center,
            });

            var label = new TextBlock
            {
                Text = HotkeySettings.Describe(HotkeySettings.Current(action)),
                VerticalAlignment = VerticalAlignment.Center,
                FontFamily = new FontFamily("Consolas"),
                Foreground = new SolidColorBrush(Microsoft.UI.Colors.SteelBlue),
            };
            Grid.SetColumn(label, 1);
            row.Children.Add(label);
            _hotkeyLabels[action] = label;

            var button = new Button { Content = "修改", Width = 96 };
            button.Click += (_, _) => BeginCapture(action);
            button.KeyDown += OnCaptureKeyDown;
            Grid.SetColumn(button, 2);
            row.Children.Add(button);
            _hotkeyButtons[action] = button;

            _hotkeyRows.Children.Add(row);
        }
    }

    private void BeginCapture(HotkeyAction action)
    {
        _capturing = action;
        foreach (var (candidate, button) in _hotkeyButtons)
        {
            button.Content = candidate == action ? "请按键…" : "修改";
        }
        _hotkeyStatus.Text = $"正在为「{HotkeySettings.ActionLabel(action)}」录制快捷键，按 Esc 取消。";
        _hotkeyButtons[action].Focus(FocusState.Programmatic);
    }

    private void OnCaptureKeyDown(object sender, Microsoft.UI.Xaml.Input.KeyRoutedEventArgs e)
    {
        if (_capturing is not { } action)
        {
            return;
        }
        e.Handled = true;

        // Esc 取消录制。
        if (e.Key == VirtualKey.Escape)
        {
            _capturing = null;
            RenderHotkeys();
            _hotkeyStatus.Text = "已取消。";
            return;
        }

        // 单独按下修饰键时继续等待主键。
        if (e.Key is VirtualKey.Control or VirtualKey.Shift or VirtualKey.Menu
            or VirtualKey.LeftWindows or VirtualKey.RightWindows or VirtualKey.None)
        {
            return;
        }

        var modifiers = new List<string>();
        if (IsDown(VirtualKey.Control))
        {
            modifiers.Add("Control");
        }
        if (IsDown(VirtualKey.Shift))
        {
            modifiers.Add("Shift");
        }
        if (IsDown(VirtualKey.Menu))
        {
            modifiers.Add("Menu");
        }
        if (IsDown(VirtualKey.LeftWindows) || IsDown(VirtualKey.RightWindows))
        {
            modifiers.Add("Windows");
        }

        var binding = new HotkeyBinding { Key = e.Key.ToString(), Modifiers = modifiers };
        var invalidReason = HotkeySettings.Validate(binding);
        if (invalidReason is not null)
        {
            _hotkeyStatus.Text = invalidReason;
            return;
        }
        if (HotkeySettings.FindConflict(action, binding) is { } conflict)
        {
            _hotkeyStatus.Text = $"与「{HotkeySettings.ActionLabel(conflict)}」冲突，请换一个组合。";
            return;
        }

        HotkeySettings.Update(action, binding);
        _capturing = null;
        RenderHotkeys();
        _hotkeyStatus.Text = $"「{HotkeySettings.ActionLabel(action)}」已改为 {HotkeySettings.Describe(binding)}。";
    }

    private static bool IsDown(VirtualKey key) =>
        InputKeyboardSource.GetKeyStateForCurrentThread(key).HasFlag(CoreVirtualKeyStates.Down);

    // ---------- 分类与规则 ----------

    private UIElement BuildCategoryPanel()
    {
        _ruleMatchType.Items.Add(new ComboBoxItem { Content = "域名", Tag = "domain", IsSelected = true });
        _ruleMatchType.Items.Add(new ComboBoxItem { Content = "网址", Tag = "url" });
        _ruleMatchType.Items.Add(new ComboBoxItem { Content = "正文", Tag = "text" });

        _createCategoryButton.Click += async (_, _) =>
        {
            var name = _newCategoryName.Text.Trim();
            if (name.Length == 0)
            {
                _categoryStatus.Text = "请输入分类名称";
                return;
            }
            var description = _newCategoryDescription.Text.Trim();
            if (_editingCategory is { } editing)
            {
                await RunCategoryAsync(() => _state.RenameCategoryAsync(
                    editing,
                    name,
                    description.Length == 0 ? null : description));
                ClearCategoryEditor();
                return;
            }
            await RunCategoryAsync(() => _state.CreateCategoryAsync(
                name,
                description.Length == 0 ? null : description,
                _newCategoryParentCode));
            ClearCategoryEditor();
        };

        var createCategoryRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        createCategoryRow.Children.Add(_newCategoryName);
        createCategoryRow.Children.Add(_newCategoryDescription);
        createCategoryRow.Children.Add(_createCategoryButton);

        var addRuleButton = new Button { Content = "添加规则" };
        addRuleButton.Click += async (_, _) =>
        {
            if (_ruleCategory.SelectedItem is not ComboBoxItem { Tag: string categoryCode })
            {
                _categoryStatus.Text = "请选择规则命中的分类";
                return;
            }
            if (_ruleMatchType.SelectedItem is not ComboBoxItem { Tag: string matchType })
            {
                _categoryStatus.Text = "请选择匹配范围";
                return;
            }
            var pattern = _rulePattern.Text.Trim();
            if (pattern.Length == 0)
            {
                _categoryStatus.Text = "请输入匹配内容";
                return;
            }
            await RunCategoryAsync(() => _state.CreateCategoryRuleAsync(
                null,
                categoryCode,
                matchType,
                pattern,
                (int)_rulePriority.Value));
            _rulePattern.Text = string.Empty;
        };

        var createRuleRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        createRuleRow.Children.Add(_ruleCategory);
        createRuleRow.Children.Add(_ruleMatchType);
        createRuleRow.Children.Add(_rulePattern);
        createRuleRow.Children.Add(_rulePriority);
        createRuleRow.Children.Add(addRuleButton);

        var panel = new StackPanel { Spacing = 10, Padding = new Thickness(4) };
        panel.Children.Add(new TextBlock
        {
            Text = "系统分类固定不可修改；自定义分类可编辑、停用或删除（删除后相关规则一并去掉，已有资料会重新判断）。",
            FontSize = 12,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
            TextWrapping = TextWrapping.Wrap,
        });
        panel.Children.Add(_categoryList);
        panel.Children.Add(createCategoryRow);
        panel.Children.Add(new TextBlock
        {
            Text = "分类规则",
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 8, 0, 0),
        });
        panel.Children.Add(new TextBlock
        {
            Text = "先按你的规则分类，无法判断时再交给大模型；优先级数字越小越先匹配。",
            FontSize = 12,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
            TextWrapping = TextWrapping.Wrap,
        });
        panel.Children.Add(_ruleList);
        panel.Children.Add(createRuleRow);
        panel.Children.Add(_categoryStatus);
        return panel;
    }

    private async Task RefreshCategoriesAsync()
    {
        await _state.LoadCategoriesAsync();
        await _state.LoadCategoryRulesAsync();
        RenderCategories();
        RenderRules();
        PopulateRuleCategories();
    }

    private void StartEditCategory(ResourceCategoryOption category)
    {
        _editingCategory = category;
        _newCategoryName.Header = "分类名称";
        _newCategoryName.Text = category.Name;
        _newCategoryDescription.Text = category.Description ?? "";
        _createCategoryButton.Content = "保存修改";
        _categoryStatus.Text = $"正在编辑「{category.Name}」。";
    }

    private void ClearCategoryEditor()
    {
        _editingCategory = null;
        _newCategoryParentCode = null;
        _newCategoryName.Header = "新分类名称";
        _newCategoryName.Text = string.Empty;
        _newCategoryDescription.Text = string.Empty;
        _createCategoryButton.Content = "创建分类";
    }

    private async Task RunCategoryAsync(Func<Task<string?>> action)
    {
        var error = await action();
        _categoryStatus.Text = error ?? _state.StatusMessage;
        if (error is null)
        {
            await RefreshCategoriesAsync();
        }
    }

    private void RenderCategories()
    {
        var rows = new List<UIElement>();
        foreach (var category in _state.Categories)
        {
            var row = new Grid { ColumnSpacing = 8, Padding = new Thickness(0, 4, 0, 4) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var indent = Math.Max(0, category.Depth - 1) * 16;
            var info = new StackPanel { Spacing = 2, Margin = new Thickness(indent, 0, 0, 0) };
            info.Children.Add(new TextBlock
            {
                Text = category.IsSystem ? $"{category.Name}（系统）" : category.Name,
                FontWeight = FontWeights.SemiBold,
            });
            if (!string.IsNullOrWhiteSpace(category.Description))
            {
                info.Children.Add(new TextBlock
                {
                    Text = category.Description,
                    FontSize = 12,
                    Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
                });
            }
            row.Children.Add(info);

            var actions = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Spacing = 6,
            };
            if (category.Depth < 3)
            {
                var addChild = new Button { Content = "添加子分类" };
                addChild.Click += (_, _) =>
                {
                    _newCategoryParentCode = category.Code;
                    _newCategoryName.Header = "子分类名称";
                    _createCategoryButton.Content = "创建子分类";
                    _categoryStatus.Text = $"将在「{category.Path ?? category.Name}」下创建子分类。";
                };
                actions.Children.Add(addChild);
            }
            if (!category.IsSystem && category.Id is not null)
            {
                var edit = new Button { Content = "编辑" };
                edit.Click += (_, _) => StartEditCategory(category);
                var toggle = new Button { Content = category.IsActive ? "停用" : "启用" };
                toggle.Click += async (_, _) =>
                    await RunCategoryAsync(() => _state.SetCategoryActiveAsync(category, !category.IsActive));
                var remove = new Button { Content = "删除" };
                remove.Click += async (_, _) =>
                    await RunCategoryAsync(() => _state.DeleteCategoryAsync(category));
                actions.Children.Add(edit);
                actions.Children.Add(toggle);
                actions.Children.Add(remove);
            }
            if (actions.Children.Count > 0)
            {
                Grid.SetColumn(actions, 1);
                row.Children.Add(actions);
            }
            rows.Add(row);
        }
        _categoryList.ItemsSource = rows;
    }

    private void RenderRules()
    {
        var rows = new List<UIElement>();
        foreach (var rule in _state.CategoryRules)
        {
            var row = new Grid { ColumnSpacing = 8, Padding = new Thickness(0, 4, 0, 4) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            row.Children.Add(new TextBlock
            {
                Text = rule.Summary,
                TextWrapping = TextWrapping.Wrap,
                VerticalAlignment = VerticalAlignment.Center,
            });

            var remove = new Button { Content = "删除" };
            remove.Click += async (_, _) => await RunCategoryAsync(() => _state.DeleteCategoryRuleAsync(rule));
            Grid.SetColumn(remove, 1);
            row.Children.Add(remove);
            rows.Add(row);
        }
        _ruleList.ItemsSource = rows;
    }

    private void PopulateRuleCategories()
    {
        var previous = (_ruleCategory.SelectedItem as ComboBoxItem)?.Tag as string;
        _ruleCategory.Items.Clear();
        var restored = false;
        foreach (var category in _state.Categories)
        {
            var item = new ComboBoxItem
            {
                Content = category.Name,
                Tag = category.Code,
                IsSelected = previous is not null && previous == category.Code,
            };
            restored |= item.IsSelected;
            _ruleCategory.Items.Add(item);
        }
        if (!restored && _ruleCategory.Items.Count > 0)
        {
            ((ComboBoxItem)_ruleCategory.Items[0]).IsSelected = true;
        }
    }
}
