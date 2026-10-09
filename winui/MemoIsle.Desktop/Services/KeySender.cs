using System.Runtime.InteropServices;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// 模拟按键（SendInput）：划词翻译用合成 Ctrl+C 自动取词，用户无需手动复制。
/// </summary>
internal static class KeySender
{
    private const uint InputKeyboard = 1;
    private const uint KeyEventKeyUp = 0x0002;
    private const ushort VkControl = 0x11;
    private const ushort VkMenu = 0x12;
    private const ushort VkShift = 0x10;
    private const ushort VkC = 0x43;

    [StructLayout(LayoutKind.Sequential)]
    private struct Input
    {
        public uint Type;
        public InputUnion Union;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct InputUnion
    {
        [FieldOffset(0)]
        public MouseInput Mouse;

        [FieldOffset(0)]
        public KeyboardInput Keyboard;
    }

    /// <summary>
    /// 鼠标输入占位：Win32 的 INPUT 联合体按最大成员（MOUSEINPUT，x64 下 32 字节）计算大小，
    /// 只声明键盘成员会让 INPUT 变成 32 字节（正确应为 40），SendInput 会以错误码 87 拒绝。
    /// </summary>
    [StructLayout(LayoutKind.Sequential)]
    private struct MouseInput
    {
        public int Dx;
        public int Dy;
        public uint MouseData;
        public uint Flags;
        public uint Time;
        public IntPtr ExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KeyboardInput
    {
        public ushort VirtualKey;
        public ushort ScanCode;
        public uint Flags;
        public uint Time;
        public IntPtr ExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint SendInput(uint count, Input[] inputs, int size);

    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int virtualKey);

    /// <summary>
    /// 等待用户松开 Ctrl / Alt / Shift。
    /// 关键点：按热键时修饰键仍按着，若立刻合成 Ctrl+C，目标程序会收到 Ctrl+Alt+C 而复制失败。
    /// </summary>
    public static async Task WaitForModifiersReleasedAsync(int timeoutMs = 900)
    {
        var deadline = Environment.TickCount64 + timeoutMs;
        while (Environment.TickCount64 < deadline)
        {
            var ctrlDown = (GetAsyncKeyState(VkControl) & 0x8000) != 0;
            var altDown = (GetAsyncKeyState(VkMenu) & 0x8000) != 0;
            var shiftDown = (GetAsyncKeyState(VkShift) & 0x8000) != 0;
            if (!ctrlDown && !altDown && !shiftDown)
            {
                return;
            }
            await Task.Delay(30);
        }
    }

    /// <summary>发送一次合成的 Ctrl+C，返回是否发送成功（用于诊断）。</summary>
    public static bool SendCopy()
    {
        var inputs = new[]
        {
            CreateKey(VkControl, down: true),
            CreateKey(VkC, down: true),
            CreateKey(VkC, down: false),
            CreateKey(VkControl, down: false),
        };
        var sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<Input>());
        var error = Marshal.GetLastWin32Error();
        DiagnosticsLog.Write(
            $"[{DateTime.Now:HH:mm:ss}] SendInput: 发送 {sent}/{inputs.Length} 条，"
            + $"结构大小 {Marshal.SizeOf<Input>()}，错误码 {error}");
        return sent == inputs.Length;
    }

    private static Input CreateKey(ushort virtualKey, bool down) => new()
    {
        Type = InputKeyboard,
        Union = new InputUnion
        {
            Keyboard = new KeyboardInput
            {
                VirtualKey = virtualKey,
                ScanCode = 0,
                Flags = down ? 0u : KeyEventKeyUp,
                Time = 0,
                ExtraInfo = IntPtr.Zero,
            },
        },
    };
}
