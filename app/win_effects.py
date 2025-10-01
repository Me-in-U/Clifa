import sys


def enable_windows_blur(widget, acrylic=True, opacity=200, color=(255, 255, 255)):
    """Windows 10+ Acrylic/Blur 효과 적용."""
    if sys.platform != "win32":
        return
    from ctypes import Structure, byref, c_int, c_uint, c_void_p, cast, sizeof, windll
    from ctypes.wintypes import BOOL, HWND

    class ACCENT_POLICY(Structure):
        _fields_ = [
            ("AccentState", c_int),
            ("AccentFlags", c_int),
            ("GradientColor", c_uint),
            ("AnimationId", c_int),
        ]

    class WINDOWCOMPOSITIONATTRIBDATA(Structure):
        _fields_ = [("Attribute", c_int), ("Data", c_void_p), ("SizeOfData", c_int)]

    ACCENT_ENABLE_BLURBEHIND = 3
    ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
    WCA_ACCENT_POLICY = 19

    r, g, b = color
    a = max(0, min(255, int(opacity)))
    gradient = (a << 24) | (b << 16) | (g << 8) | r

    accent = ACCENT_POLICY()
    accent.AccentState = (
        ACCENT_ENABLE_ACRYLICBLURBEHIND if acrylic else ACCENT_ENABLE_BLURBEHIND
    )
    accent.AccentFlags = 0
    accent.GradientColor = gradient
    accent.AnimationId = 0

    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = WCA_ACCENT_POLICY
    data.Data = cast(byref(accent), c_void_p)
    data.SizeOfData = sizeof(accent)

    hwnd = HWND(int(widget.winId()))
    f = windll.user32.SetWindowCompositionAttribute
    f.argtypes = [HWND, c_void_p]
    f.restype = BOOL
    f(hwnd, byref(data))
