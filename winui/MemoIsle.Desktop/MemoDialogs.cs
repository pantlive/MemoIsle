using MemoIsle.Desktop.Models;
using MemoIsle.Desktop.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace MemoIsle.Desktop;

/// <summary>新建 / 编辑资料的对话框（按类型动态构建表单）。</summary>
internal static class MemoDialogs
{
    public static async Task ShowAsync(
        XamlRoot root,
        AppState state,
        string type,
        Memo? existing,
        Action<Memo>? onLocate = null,
        IntPtr hwnd = default)
    {
        var resolvedType = existing?.Type ?? (type is MemoTypes.Word or MemoTypes.Resource or MemoTypes.Image
            ? type
            : MemoTypes.Idea);

        var panel = new StackPanel { Spacing = 10, Width = 420 };
        var errorText = new TextBlock
        {
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.OrangeRed),
            TextWrapping = TextWrapping.Wrap,
            Visibility = Visibility.Collapsed,
        };
        panel.Children.Add(errorText);

        // 自动压缩等非错误提示：与错误分开显示，避免被当成失败原因（仅图片对话框使用）。
        var noticeText = new TextBlock
        {
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.SeaGreen),
            TextWrapping = TextWrapping.Wrap,
            Visibility = Visibility.Collapsed,
        };

        var dialog = new ContentDialog
        {
            XamlRoot = root,
            Title = existing is null ? "新建" : "编辑",
            PrimaryButtonText = "保存",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Primary,
        };

        Func<Task<string?>> submit;
        Func<Task<AppState.WordCreateOutcome>>? wordCreateSubmit = null;
        StackPanel? duplicateActions = null;
        Memo? currentDuplicate = null;
        string? pendingImageNotice = null;
        // 上传后后台 OCR 仍在排队时：保持对话框打开，等轮询拿到结果。
        bool pendingOcrPoll = false;

        if (resolvedType == MemoTypes.Idea)
        {
            var bodyBox = new TextBox
            {
                Header = "内容",
                Text = existing?.Body ?? string.Empty,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                Height = 140,
            };
            panel.Children.Add(bodyBox);
            submit = () => existing is null
                ? state.CreateIdeaAsync(bodyBox.Text)
                : state.UpdateIdeaAsync(existing, bodyBox.Text);
        }
        else if (resolvedType == MemoTypes.Word)
        {
            var lemmaBox = new TextBox
            {
                Header = "单词或短语",
                Text = existing?.Title ?? string.Empty,
            };
            var phoneticBox = new TextBox
            {
                Header = "音标（可选）",
                Text = existing?.WordPhonetic ?? string.Empty,
            };
            var meaningBox = new TextBox
            {
                Header = "中文释义",
                Text = existing?.WordMeaning ?? string.Empty,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                Height = 100,
            };
            var exampleBox = new TextBox
            {
                Header = "例句（可选）",
                Text = existing?.WordExample ?? string.Empty,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                Height = 70,
            };
            var duplicateCheck = new CheckBox
            {
                Content = "若已收藏相同词形，仍然保存为重复词条",
                Visibility = existing is null ? Visibility.Visible : Visibility.Collapsed,
            };

            var lookupButton = new Button { Content = "查询释义" };
            var pronounceButton = new Button { Content = "发音" };
            var clipboardButton = new Button { Content = "从剪贴板填入" };
            clipboardButton.Click += async (_, _) =>
            {
                var draft = await ReadClipboardDraftAsync();
                if (draft is null)
                {
                    errorText.Text = "剪贴板里没有识别到可用的单词或短语。";
                    errorText.Visibility = Visibility.Visible;
                    return;
                }
                lemmaBox.Text = draft.Lemma;
                if (!string.IsNullOrWhiteSpace(draft.Phonetic))
                {
                    phoneticBox.Text = draft.Phonetic!;
                }
                if (!string.IsNullOrWhiteSpace(draft.Meaning))
                {
                    meaningBox.Text = draft.Meaning!;
                }
                errorText.Visibility = Visibility.Collapsed;
            };
            // 词典多义项：查询后勾选需要保留的释义，再一键填入。
            var sensesPanel = new StackPanel { Spacing = 2, Visibility = Visibility.Collapsed };
            var senseBoxes = new List<(CheckBox Box, string Text)>();
            var useSelectedButton = new Button
            {
                Content = "使用所选释义",
                HorizontalAlignment = HorizontalAlignment.Left,
                Visibility = Visibility.Collapsed,
            };
            lookupButton.Click += async (_, _) =>
            {
                var result = await state.LookupWordAsync(lemmaBox.Text);
                if (result is null)
                {
                    return;
                }
                if (string.IsNullOrWhiteSpace(phoneticBox.Text))
                {
                    phoneticBox.Text = result.Phonetic ?? string.Empty;
                }
                if (string.IsNullOrWhiteSpace(exampleBox.Text))
                {
                    exampleBox.Text = result.Senses
                        .FirstOrDefault(s => !string.IsNullOrWhiteSpace(s.Example))?.Example ?? string.Empty;
                }
                sensesPanel.Children.Clear();
                senseBoxes.Clear();
                foreach (var sense in result.Senses.Take(6))
                {
                    var text = $"{sense.Index}. {sense.Definition}";
                    var box = new CheckBox { Content = text };
                    senseBoxes.Add((box, text));
                    sensesPanel.Children.Add(box);
                }
                sensesPanel.Visibility = senseBoxes.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
                useSelectedButton.Visibility = sensesPanel.Visibility;
                // 保留原来的自动填充体验：释义为空时默认勾选首条并填入。
                if (string.IsNullOrWhiteSpace(meaningBox.Text) && senseBoxes.Count > 0)
                {
                    senseBoxes[0].Box.IsChecked = true;
                    meaningBox.Text = senseBoxes[0].Text;
                }
            };
            useSelectedButton.Click += (_, _) =>
            {
                var selected = senseBoxes
                    .Where(pair => pair.Box.IsChecked == true)
                    .Select(pair => pair.Text)
                    .ToList();
                if (selected.Count > 0)
                {
                    meaningBox.Text = string.Join("\n", selected);
                }
            };
            pronounceButton.Click += async (_, _) =>
            {
                var error = await state.SpeakAsync(lemmaBox.Text);
                if (error is not null)
                {
                    errorText.Text = error;
                    errorText.Visibility = Visibility.Visible;
                }
            };

            var actionRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            actionRow.Children.Add(lookupButton);
            actionRow.Children.Add(pronounceButton);
            actionRow.Children.Add(clipboardButton);

            if (existing is null)
            {
                // 同词形冲突时的三个动作，对齐 Web 端行为。
                var viewButton = new Button { Content = "查看原条目" };
                var mergeButton = new Button { Content = "合并例句" };
                var keepButton = new Button { Content = "仍然保存" };
                viewButton.Click += (_, _) =>
                {
                    if (currentDuplicate is not null)
                    {
                        onLocate?.Invoke(currentDuplicate);
                        dialog.Hide();
                    }
                };
                mergeButton.Click += async (_, _) =>
                {
                    if (currentDuplicate is null)
                    {
                        return;
                    }
                    var error = await state.MergeWordAsync(
                        currentDuplicate,
                        phoneticBox.Text,
                        meaningBox.Text,
                        exampleBox.Text);
                    if (error is null)
                    {
                        dialog.Hide();
                        return;
                    }
                    errorText.Text = error;
                    errorText.Visibility = Visibility.Visible;
                };
                keepButton.Click += async (_, _) =>
                {
                    var outcome = await state.CreateWordDetailedAsync(
                        lemmaBox.Text,
                        phoneticBox.Text,
                        meaningBox.Text,
                        exampleBox.Text,
                        allowDuplicate: true);
                    if (outcome.Error is null)
                    {
                        dialog.Hide();
                        return;
                    }
                    errorText.Text = outcome.Error;
                    errorText.Visibility = Visibility.Visible;
                };
                duplicateActions = new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    Spacing = 6,
                    Visibility = Visibility.Collapsed,
                };
                duplicateActions.Children.Add(viewButton);
                duplicateActions.Children.Add(mergeButton);
                duplicateActions.Children.Add(keepButton);
            }

            panel.Children.Add(lemmaBox);
            panel.Children.Add(actionRow);
            panel.Children.Add(phoneticBox);
            panel.Children.Add(meaningBox);
            panel.Children.Add(sensesPanel);
            panel.Children.Add(useSelectedButton);
            panel.Children.Add(exampleBox);
            panel.Children.Add(duplicateCheck);
            if (duplicateActions is not null)
            {
                panel.Children.Add(duplicateActions);
            }

            submit = () => existing is null
                ? state.CreateWordAsync(
                    lemmaBox.Text,
                    phoneticBox.Text,
                    meaningBox.Text,
                    exampleBox.Text,
                    duplicateCheck.IsChecked == true)
                : state.UpdateWordAsync(
                    existing,
                    lemmaBox.Text,
                    phoneticBox.Text,
                    meaningBox.Text,
                    exampleBox.Text);

            if (existing is null)
            {
                wordCreateSubmit = () => state.CreateWordDetailedAsync(
                    lemmaBox.Text,
                    phoneticBox.Text,
                    meaningBox.Text,
                    exampleBox.Text,
                    duplicateCheck.IsChecked == true);
            }
        }
        else if (resolvedType == MemoTypes.Image)
        {
            // 图片压缩提示放在错误提示下方，避免影响其他类型的对话框布局。
            panel.Children.Add(noticeText);
            var titleBox = new TextBox
            {
                Header = "标题（可选）",
                Text = existing?.Title ?? string.Empty,
            };
            var noteBox = new TextBox
            {
                Header = "备注（可选）",
                Text = existing?.Body ?? string.Empty,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                Height = 80,
            };

            // ---- 图片文字（OCR）：状态、识别文本、自动标签，可在对话框内手动（重新）识别 ----
            Memo? ocrMemo = existing;
            var ocrBusy = false;
            // 上传后只启动一次后台轮询，避免重复请求。
            var ocrPolling = false;
            var ocrStatusText = new TextBlock
            {
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
            };
            var ocrMetaText = new TextBlock
            {
                FontSize = 12,
                Opacity = 0.6,
                TextWrapping = TextWrapping.Wrap,
                Visibility = Visibility.Collapsed,
            };
            var ocrErrorText = new TextBlock
            {
                Foreground = new SolidColorBrush(Microsoft.UI.Colors.OrangeRed),
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
                Visibility = Visibility.Collapsed,
            };
            var ocrHintText = new TextBlock
            {
                Text = "保存并上传图片后即可识别文字。",
                FontSize = 12,
                Opacity = 0.6,
                TextWrapping = TextWrapping.Wrap,
                Visibility = Visibility.Collapsed,
            };
            var ocrTextBox = new TextBox
            {
                IsReadOnly = true,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                Height = 110,
                Visibility = Visibility.Collapsed,
            };
            var ocrEmptyText = new TextBlock
            {
                Text = "没有识别到文字",
                FontSize = 12,
                Opacity = 0.6,
                TextWrapping = TextWrapping.Wrap,
                Visibility = Visibility.Collapsed,
            };
            var ocrTagsPanel = new StackPanel { Spacing = 2, Visibility = Visibility.Collapsed };
            ocrTagsPanel.Children.Add(new TextBlock
            {
                Text = "自动标签",
                FontSize = 12,
                Opacity = 0.6,
            });
            var ocrTagsText = new TextBlock
            {
                FontSize = 12,
                TextWrapping = TextWrapping.Wrap,
            };
            ocrTagsPanel.Children.Add(ocrTagsText);
            var ocrButton = new Button
            {
                Content = "识别文字",
                HorizontalAlignment = HorizontalAlignment.Left,
            };

            void RenderOcr(Memo? memo)
            {
                ocrMemo = memo;
                var status = string.IsNullOrWhiteSpace(memo?.ImageOcrStatus)
                    ? "none"
                    : memo!.ImageOcrStatus;
                ocrStatusText.Text = $"图片文字：{Memo.DescribeImageOcrStatus(status)}";

                var meta = memo?.ImageOcrMetaLabel ?? string.Empty;
                ocrMetaText.Text = meta;
                ocrMetaText.Visibility = string.IsNullOrWhiteSpace(meta)
                    ? Visibility.Collapsed
                    : Visibility.Visible;

                var error = memo?.ImageOcrErrorText ?? string.Empty;
                ocrErrorText.Text = error;
                ocrErrorText.Visibility = string.IsNullOrWhiteSpace(error)
                    ? Visibility.Collapsed
                    : Visibility.Visible;

                var hasImage = memo is { HasImage: true };
                ocrHintText.Visibility = hasImage ? Visibility.Collapsed : Visibility.Visible;

                var hasText = memo?.HasImageOcrText == true;
                ocrTextBox.Text = hasText ? memo!.ImageOcrText! : string.Empty;
                ocrTextBox.Visibility = hasText ? Visibility.Visible : Visibility.Collapsed;
                ocrEmptyText.Visibility = status == "ready" && !hasText
                    ? Visibility.Visible
                    : Visibility.Collapsed;

                var hasTags = memo?.HasImageAutoTags == true;
                ocrTagsText.Text = hasTags ? string.Join(" · ", memo!.ImageAutoTags) : string.Empty;
                ocrTagsPanel.Visibility = hasTags ? Visibility.Visible : Visibility.Collapsed;

                ocrButton.Content = status == "ready" || hasText ? "重新识别" : "识别文字";
                ocrButton.IsEnabled = memo is { Id: not null, HasImage: true } &&
                    status is not ("pending" or "processing") &&
                    !ocrBusy;
            }

            ocrButton.Click += async (_, _) =>
            {
                if (ocrMemo is not { Id: not null })
                {
                    ShowError("请先保存图片，再识别文字。");
                    return;
                }
                ocrBusy = true;
                RenderOcr(ocrMemo);
                errorText.Visibility = Visibility.Collapsed;
                var ocrError = await state.RecognizeImageOcrAsync(ocrMemo);
                ocrBusy = false;
                RenderOcr(state.FindMemo(ocrMemo.Id) ?? ocrMemo);
                if (ocrError is not null)
                {
                    ocrErrorText.Text = ocrError;
                    ocrErrorText.Visibility = Visibility.Visible;
                }
            };

            var ocrPanel = new StackPanel { Spacing = 6 };
            ocrPanel.Children.Add(new TextBlock
            {
                Text = "图片文字（OCR）",
                FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
            });
            ocrPanel.Children.Add(ocrStatusText);
            ocrPanel.Children.Add(ocrMetaText);
            ocrPanel.Children.Add(ocrHintText);
            ocrPanel.Children.Add(ocrErrorText);
            ocrPanel.Children.Add(ocrButton);
            ocrPanel.Children.Add(ocrTextBox);
            ocrPanel.Children.Add(ocrEmptyText);
            ocrPanel.Children.Add(ocrTagsPanel);
            var ocrSection = new Border
            {
                Padding = new Thickness(10),
                CornerRadius = new CornerRadius(8),
                BorderThickness = new Thickness(1),
                BorderBrush = new SolidColorBrush(Windows.UI.Color.FromArgb(28, 128, 128, 128)),
                Child = ocrPanel,
            };
            RenderOcr(existing);
            var preview = new Image
            {
                Height = 220,
                Stretch = Stretch.Uniform,
                Source = existing?.MemoImageSource,
            };
            var previewBorder = new Border
            {
                Height = 236,
                Padding = new Thickness(6),
                CornerRadius = new CornerRadius(8),
                BorderThickness = new Thickness(1),
                BorderBrush = new SolidColorBrush(Windows.UI.Color.FromArgb(40, 128, 128, 128)),
                Child = preview,
            };
            if (existing is { HasImage: true } && existing.MemoImageSource is null)
            {
                _ = LoadExistingPreviewAsync(state, existing, preview);
            }

            string? selectedPath = null;
            string? selectedMime = null;
            void ShowError(string message)
            {
                errorText.Text = message;
                errorText.Visibility = Visibility.Visible;
            }

            var pickButton = new Button
            {
                Content = existing is { HasImage: true } ? "替换图片" : "选择图片",
            };
            var viewButton = new Button { Content = "查看原图", IsEnabled = existing is not null };
            var saveButton = new Button { Content = "保存原图", IsEnabled = existing is not null };

            pickButton.Click += async (_, _) =>
            {
                var picker = new Windows.Storage.Pickers.FileOpenPicker();
                foreach (var extension in MemoImageFiles.Extensions)
                {
                    picker.FileTypeFilter.Add(extension);
                }
                if (hwnd != IntPtr.Zero)
                {
                    WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
                }
                var file = await picker.PickSingleFileAsync();
                if (file is null)
                {
                    return;
                }
                var mime = MemoImageFiles.MimeTypeFor(file.Path);
                if (mime is null)
                {
                    ShowError("仅支持 PNG / JPG / WebP / GIF 图片。");
                    return;
                }
                selectedPath = file.Path;
                selectedMime = mime;
                try
                {
                    preview.Source = new BitmapImage(new Uri(file.Path)) { DecodePixelWidth = 480 };
                }
                catch (Exception)
                {
                    // 本地预览失败不影响上传：上传时后端仍会做图片解码校验。
                }
                pickButton.Content = "替换图片";
                errorText.Visibility = Visibility.Collapsed;
                // 超过后端限制的图片保存时会自动压缩，这里先提前告知用户。
                if (MemoImageCompressor.ShouldCompress(new FileInfo(file.Path).Length, 0, 0))
                {
                    noticeText.Text = "图片超过 20 MB，保存时会自动压缩后再上传。";
                    noticeText.Visibility = Visibility.Visible;
                }
                else
                {
                    noticeText.Visibility = Visibility.Collapsed;
                }
            };

            viewButton.Click += async (_, _) =>
            {
                if (existing is null)
                {
                    return;
                }
                var bytes = await state.DownloadImageAsync(existing, thumbnail: false);
                if (bytes is null || bytes.Length == 0)
                {
                    ShowError("无法下载原图，请稍后重试。");
                    return;
                }
                try
                {
                    var extension = MemoImageFiles.ExtensionForMime(existing.ImageMimeType);
                    var tempPath = Path.Combine(Path.GetTempPath(), $"memoisle-{existing.Id}{extension}");
                    await File.WriteAllBytesAsync(tempPath, bytes);
                    var file = await Windows.Storage.StorageFile.GetFileFromPathAsync(tempPath);
                    await Windows.System.Launcher.LaunchFileAsync(file);
                    errorText.Visibility = Visibility.Collapsed;
                }
                catch (Exception ex)
                {
                    ShowError($"打开原图失败：{ex.Message}");
                }
            };

            saveButton.Click += async (_, _) =>
            {
                if (existing is null)
                {
                    return;
                }
                var bytes = await state.DownloadImageAsync(existing, thumbnail: false);
                if (bytes is null || bytes.Length == 0)
                {
                    ShowError("无法下载原图，请稍后重试。");
                    return;
                }
                var rawName = Path.GetFileNameWithoutExtension(existing.Title);
                var suggested = string.IsNullOrWhiteSpace(rawName)
                    ? "memoisle-image"
                    : new string(rawName
                        .Select(ch => Path.GetInvalidFileNameChars().Contains(ch) ? '_' : ch)
                        .ToArray());
                var picker = new Windows.Storage.Pickers.FileSavePicker
                {
                    SuggestedFileName = suggested,
                };
                picker.FileTypeChoices.Add(
                    "图片",
                    new List<string> { MemoImageFiles.ExtensionForMime(existing.ImageMimeType) });
                if (hwnd != IntPtr.Zero)
                {
                    WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
                }
                var target = await picker.PickSaveFileAsync();
                if (target is null)
                {
                    return;
                }
                try
                {
                    await File.WriteAllBytesAsync(target.Path, bytes);
                    errorText.Visibility = Visibility.Collapsed;
                }
                catch (Exception ex)
                {
                    ShowError($"保存原图失败：{ex.Message}");
                }
            };

            var actionRow = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            actionRow.Children.Add(pickButton);
            actionRow.Children.Add(viewButton);
            actionRow.Children.Add(saveButton);

            panel.Children.Add(previewBorder);
            if (!string.IsNullOrWhiteSpace(existing?.ImageDetailLabel))
            {
                panel.Children.Add(new TextBlock
                {
                    Text = existing!.ImageDetailLabel,
                    FontSize = 12,
                    Opacity = 0.7,
                });
            }
            panel.Children.Add(actionRow);
            panel.Children.Add(titleBox);
            panel.Children.Add(noteBox);
            panel.Children.Add(ocrSection);

            Memo? pending = existing;
            submit = async () =>
            {
                if (pending is null)
                {
                    if (selectedPath is null)
                    {
                        return "请先选择一张图片";
                    }
                    var (created, createError) = await state.CreateImageAsync(titleBox.Text, noteBox.Text);
                    if (createError is not null)
                    {
                        return createError;
                    }
                    if (created is null)
                    {
                        return "图片条目创建失败";
                    }
                    pending = created;
                }
                else
                {
                    var updateError = await state.UpdateImageAsync(pending, titleBox.Text, noteBox.Text);
                    if (updateError is not null)
                    {
                        return updateError;
                    }
                    // 更新会推进版本号：从列表取最新引用，避免随后上传时 409 冲突。
                    pending = state.FindMemo(pending.Id) ?? pending;
                }

                if (selectedPath is not null)
                {
                    var uploadError = await state.UploadImageAsync(
                        pending,
                        selectedPath,
                        selectedMime ?? MemoImageFiles.MimeTypeFor(selectedPath) ?? string.Empty);
                    if (uploadError is not null)
                    {
                        return uploadError;
                    }
                    // 已上传成功，重试时不再重复上传同一文件。
                    selectedPath = null;
                    pending = state.FindMemo(pending.Id) ?? pending;
                    // 发生自动压缩时把提示留给对话框展示，确认后才会关闭。
                    pendingImageNotice = state.LastImageCompressionNotice;

                    // 上传成功即触发后台识别（服务端启用时返回 pending）：
                    // 先展示排队中/识别中，再有界轮询单条 memo 直到结果就绪。
                    if (!ocrPolling && pending.IsImageOcrBusy)
                    {
                        ocrPolling = true;
                        var waiting = pending;
                        RenderOcr(waiting);
                        _ = PollImageOcrAsync(
                            state,
                            waiting,
                            updated => RenderOcr(updated),
                            status =>
                            {
                                noticeText.Text = status == "ready"
                                    ? "图片文字识别完成"
                                    : "图片文字识别已结束";
                                noticeText.Visibility = Visibility.Visible;
                            });
                        pendingOcrPoll = true;
                    }
                }
                return null;
            };
        }
        else
        {
            var urlBox = new TextBox
            {
                Header = "网址",
                Text = existing?.SourceUrl ?? string.Empty,
            };
            var titleBox = new TextBox
            {
                Header = "标题（可选）",
                Text = existing?.SourceTitle ?? existing?.Title ?? string.Empty,
            };
            var noteBox = new TextBox
            {
                Header = "备注（可选）",
                Text = existing is null
                    ? string.Empty
                    : existing.Body == existing.SourceUrl ? string.Empty : existing.Body,
                AcceptsReturn = true,
                TextWrapping = TextWrapping.Wrap,
                Height = 80,
            };
            panel.Children.Add(urlBox);
            panel.Children.Add(titleBox);
            panel.Children.Add(noteBox);
            submit = () => existing is null
                ? state.CreateResourceAsync(urlBox.Text, titleBox.Text, noteBox.Text)
                : state.UpdateResourceAsync(existing, urlBox.Text, titleBox.Text, noteBox.Text);
        }

        dialog.Content = new ScrollViewer { Content = panel, MaxHeight = 520 };

        while (true)
        {
            var result = await dialog.ShowAsync();
            if (result != ContentDialogResult.Primary)
            {
                return;
            }

            string? error;
            currentDuplicate = null;
            if (wordCreateSubmit is not null)
            {
                var outcome = await wordCreateSubmit();
                error = outcome.Error;
                currentDuplicate = outcome.Duplicate;
            }
            else
            {
                error = await submit();
            }

            if (error is null)
            {
                if (pendingImageNotice is not null)
                {
                    // 自动压缩提示需要用户确认：展示提示并把按钮改成「完成」，再点一次才关闭。
                    noticeText.Text = pendingImageNotice;
                    noticeText.Visibility = Visibility.Visible;
                    pendingImageNotice = null;
                    pendingOcrPoll = false;
                    dialog.PrimaryButtonText = "完成";
                    continue;
                }
                if (pendingOcrPoll)
                {
                    // 后台识别还没结束：重新打开对话框展示「排队中 / 识别中」，
                    // 轮询任务会在拿到结果后原地刷新 OCR 区块与主列表。
                    pendingOcrPoll = false;
                    noticeText.Text = "图片已保存，正在识别图片文字…";
                    noticeText.Visibility = Visibility.Visible;
                    dialog.PrimaryButtonText = "完成";
                    continue;
                }
                return;
            }
            errorText.Text = error;
            errorText.Visibility = Visibility.Visible;
            if (currentDuplicate is not null && duplicateActions is not null)
            {
                duplicateActions.Visibility = Visibility.Visible;
            }
        }
    }

    /// <summary>编辑图片收藏时若列表尚未缓存缩略图，这里补拉一次用于对话框预览。</summary>
    private static async Task LoadExistingPreviewAsync(AppState state, Memo memo, Image preview)
    {
        var bytes = await state.DownloadImageAsync(memo, thumbnail: true);
        if (bytes is null || bytes.Length == 0)
        {
            return;
        }
        try
        {
            var bitmap = new BitmapImage { DecodePixelWidth = 480 };
            using var stream = new MemoryStream(bytes);
            await bitmap.SetSourceAsync(stream.AsRandomAccessStream());
            preview.Source = bitmap;
        }
        catch (Exception)
        {
            // 预览加载失败时保留空白占位，不影响编辑与保存。
        }
    }

    /// <summary>
    /// 上传后等待后台 OCR：每 ~2 秒重新拉取一次单条 memo（GET memos/{id}），
    /// 最多 10 次；拿到结果后回调刷新对话框 OCR 区块，并已同步主列表引用。
    /// </summary>
    private static async Task PollImageOcrAsync(
        AppState state,
        Memo memo,
        Action<Memo> onUpdated,
        Action<string> onFinished)
    {
        if (memo.Id is null)
        {
            return;
        }
        var memoId = memo.Id;
        const int maxAttempts = 10;
        for (var attempt = 0; attempt < maxAttempts; attempt++)
        {
            await Task.Delay(TimeSpan.FromSeconds(2));
            Memo? updated;
            try
            {
                updated = await state.RefreshMemoAsync(memoId);
            }
            catch (Exception)
            {
                return;
            }
            if (updated is null)
            {
                continue;
            }
            onUpdated(updated);
            if (!updated.IsImageOcrBusy)
            {
                onFinished(updated.ImageOcrStatus);
                return;
            }
        }
    }

    /// <summary>读取剪贴板文本并解析为单词草稿（识别失败返回 null）。</summary>
    private static async Task<ClipboardWordDraft?> ReadClipboardDraftAsync()
    {
        try
        {
            var content = Windows.ApplicationModel.DataTransfer.Clipboard.GetContent();
            if (!content.Contains(Windows.ApplicationModel.DataTransfer.StandardDataFormats.Text))
            {
                return null;
            }
            var text = await content.GetTextAsync();
            return ClipboardWordParser.Parse(text);
        }
        catch (Exception)
        {
            return null;
        }
    }
}
