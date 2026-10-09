using Microsoft.UI.Xaml;

namespace MemoIsle.Desktop;

/// <summary>应用入口：创建并激活主窗口。</summary>
public partial class App : Application
{
    private static Mutex? _singleInstanceMutex;
    private Window? _window;

    public App()
    {
        InitializeComponent();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        // 同一用户会话只允许一个实例，重复启动直接退出。
        _singleInstanceMutex = new Mutex(
            initiallyOwned: true,
            name: "MemoIsle.Desktop.SingleInstance",
            createdNew: out var createdNew);
        if (!createdNew)
        {
            // WinUI 的 Application.Exit() 在启动早期可能不生效，这里直接结束进程。
            Environment.Exit(0);
            return;
        }

        _window = new MainWindow();
        _window.Activate();
    }
}
