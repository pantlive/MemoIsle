using MemoIsle.Desktop.Models;
using MemoIsle.Desktop.Services;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace MemoIsle.Desktop;

/// <summary>书签批量导入：预览去重 → 后台导入 → 进度 / 失败重试 / 整批撤销。</summary>
internal sealed class BookmarkImportDialog
{
    private readonly AppState _state;
    private readonly IReadOnlyList<BookmarkInput> _items;
    private readonly ContentDialog _dialog;
    private readonly TextBlock _summary = new() { TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _status = new()
    {
        FontSize = 12,
        TextWrapping = TextWrapping.Wrap,
        Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
    };
    private readonly ProgressBar _progress = new() { Minimum = 0, Maximum = 100, Value = 0 };
    private readonly ListView _previewList = new()
    {
        MaxHeight = 220,
        SelectionMode = ListViewSelectionMode.None,
        Visibility = Visibility.Collapsed,
    };
    private readonly Button _importButton = new() { Content = "确认导入", IsEnabled = false };
    private readonly Button _retryButton = new() { Content = "重试失败项", Visibility = Visibility.Collapsed };
    private readonly Button _undoButton = new() { Content = "撤销本次导入", Visibility = Visibility.Collapsed };

    private DispatcherQueueTimer? _pollTimer;
    private string? _batchId;
    private bool _finishedObserved;

    public BookmarkImportDialog(AppState state, IReadOnlyList<BookmarkInput> items)
    {
        _state = state;
        _items = items;

        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        actions.Children.Add(_importButton);
        actions.Children.Add(_retryButton);
        actions.Children.Add(_undoButton);

        var panel = new StackPanel { Spacing = 10, Width = 460 };
        panel.Children.Add(_summary);
        panel.Children.Add(_previewList);
        panel.Children.Add(_progress);
        panel.Children.Add(_status);
        panel.Children.Add(actions);

        _dialog = new ContentDialog
        {
            Title = "导入浏览器书签",
            PrimaryButtonText = "关闭",
            DefaultButton = ContentDialogButton.Primary,
            Content = new ScrollViewer { Content = panel, MaxHeight = 520 },
        };

        _importButton.Click += async (_, _) => await StartImportAsync();
        _retryButton.Click += async (_, _) =>
        {
            if (_batchId is null)
            {
                return;
            }
            var error = await _state.RetryBookmarkImportAsync(_batchId);
            if (error is not null)
            {
                _status.Text = error;
                return;
            }
            _retryButton.Visibility = Visibility.Collapsed;
            await PollOnceAsync();
            StartPolling();
        };
        _undoButton.Click += async (_, _) =>
        {
            if (_batchId is null)
            {
                return;
            }
            var error = await _state.UndoBookmarkImportAsync(_batchId);
            _status.Text = error ?? "已撤销本次导入，未编辑的条目已移入回收站。";
            _retryButton.Visibility = Visibility.Collapsed;
            _undoButton.Visibility = Visibility.Collapsed;
        };
    }

    public async Task ShowAsync(XamlRoot root)
    {
        _dialog.XamlRoot = root;
        _summary.Text = $"准备导入 {_items.Count} 条书签，正在生成去重预览…";

        var previewTask = _state.PreviewBookmarksAsync(_items);
        var showTask = _dialog.ShowAsync();

        var (preview, error) = await previewTask;
        if (error is not null)
        {
            _status.Text = error;
        }
        else if (preview is not null)
        {
            _summary.Text =
                $"共 {preview.TotalCount} 条：可导入 {preview.ValidCount} 条 · "
                + $"资料库已有 {preview.DuplicateCount} 条 · 链接无效 {preview.InvalidCount} 条";
            _previewList.ItemsSource = preview.Items
                .Take(50)
                .Select(item => $"{item.StatusLabel} · {item.Title} · {item.Url}")
                .ToList();
            _previewList.Visibility = preview.Items.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
            _importButton.IsEnabled = preview.ValidCount > 0;
            _status.Text = preview.ValidCount == 0 ? "没有可导入的书签。" : "点击「确认导入」开始后台导入。";
        }

        await showTask;
        _pollTimer?.Stop();
        _pollTimer = null;
    }

    private async Task StartImportAsync()
    {
        _importButton.IsEnabled = false;
        _status.Text = "正在创建导入任务…";
        var (batch, error) = await _state.StartBookmarkImportAsync(_items);
        if (batch is null)
        {
            _status.Text = error ?? "导入失败，请稍后重试。";
            _importButton.IsEnabled = true;
            return;
        }
        _batchId = batch.Id;
        UpdateFromBatch(batch);
        if (batch.IsRunning)
        {
            StartPolling();
        }
    }

    private void StartPolling()
    {
        if (_pollTimer is null)
        {
            _pollTimer = _dialog.DispatcherQueue.CreateTimer();
            _pollTimer.Interval = TimeSpan.FromMilliseconds(900);
            _pollTimer.IsRepeating = true;
            _pollTimer.Tick += async (_, _) => await PollOnceAsync();
        }
        _pollTimer.Start();
    }

    private async Task PollOnceAsync()
    {
        if (_batchId is null)
        {
            return;
        }
        var batch = await _state.GetBookmarkImportAsync(_batchId);
        if (batch is not null)
        {
            UpdateFromBatch(batch);
        }
    }

    private void UpdateFromBatch(BookmarkImportBatch batch)
    {
        var processed = batch.ImportedCount + batch.DuplicateCount + batch.InvalidCount + batch.FailedCount;
        _progress.Value = batch.TotalCount == 0
            ? 0
            : Math.Min(100, processed * 100.0 / batch.TotalCount);
        _status.Text = batch.ProgressLabel + (batch.IsRunning ? "（处理中…）" : string.Empty);
        if (batch.IsRunning)
        {
            _finishedObserved = false;
            return;
        }

        _pollTimer?.Stop();
        if (!_finishedObserved)
        {
            _finishedObserved = true;
            _status.Text += batch.FailedCount > 0
                ? " · 可点击「重试失败项」继续处理"
                : " · 导入完成";
        }
        _retryButton.Visibility = batch.FailedCount > 0 && string.IsNullOrEmpty(batch.UndoneAt)
            ? Visibility.Visible
            : Visibility.Collapsed;
        _undoButton.Visibility = string.IsNullOrEmpty(batch.UndoneAt)
            ? Visibility.Visible
            : Visibility.Collapsed;
    }
}
