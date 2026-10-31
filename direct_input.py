"""DirectInput hardware scancode & mouse button sender for DirectX / Vulkan games (War Thunder, etc.)."""
import ctypes
from ctypes import wintypes
import time
import logging

log = logging.getLogger("capri")

PUL = ctypes.POINTER(ctypes.c_ulong)

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL)
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD)
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL)
    ]

class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUTUNION)
    ]

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# Mouse flags
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100

XBUTTON1 = 0x0001  # Mouse 4 (back / thumb 1)
XBUTTON2 = 0x0002  # Mouse 5 (forward / thumb 2)

MOUSE_BUTTONS = {
    "mouse1": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "lmb": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "left_click": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "лкм": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),

    "mouse2": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "rmb": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "right_click": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "пкм": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),

    "mouse3": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "mmb": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "скм": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),

    "mouse4": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
    "mouse_4": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
    "xbutton1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
    "боковая1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
    "боковая_1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),

    "mouse5": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
    "mouse_5": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
    "xbutton2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
    "боковая2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
    "боковая_2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
}

# Hardware scancodes (Set 1 / DirectInput)
SCANCODES = {
    # Letters
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12, "f": 0x21,
    "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24, "k": 0x25, "l": 0x26,
    "m": 0x32, "n": 0x31, "o": 0x18, "p": 0x19, "q": 0x10, "r": 0x13,
    "s": 0x1F, "t": 0x14, "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D,
    "y": 0x15, "z": 0x2C,
    # Russian letters map to same physical keys
    "ф": 0x1E, "и": 0x30, "с": 0x2E, "в": 0x20, "у": 0x12, "а": 0x21,
    "п": 0x22, "р": 0x23, "ш": 0x17, "о": 0x24, "л": 0x25, "д": 0x26,
    "ь": 0x32, "т": 0x31, "щ": 0x18, "з": 0x19, "й": 0x10, "к": 0x13,
    "ы": 0x1F, "е": 0x14, "г": 0x16, "м": 0x2F, "ц": 0x11, "ч": 0x2D,
    "н": 0x15, "я": 0x2C,
    # Numbers
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    # Function keys
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F, "f6": 0x40,
    "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44, "f11": 0x57, "f12": 0x58,
    # Control keys
    "escape": 0x01, "esc": 0x01, "space": 0x39, "пробел": 0x39, "tab": 0x0F,
    "enter": 0x1C, "энтер": 0x1C, "backspace": 0x0E, "capslock": 0x3A,
    "shift": 0x2A, "lshift": 0x2A, "rshift": 0x36,
    "ctrl": 0x1D, "lctrl": 0x1D, "rctrl": 0x1D,
    "alt": 0x38, "lalt": 0x38, "ralt": 0x38,
    # Navigation / arrows (extended)
    "up": (0x48, True), "down": (0x50, True), "left": (0x4B, True), "right": (0x4D, True),
    "стрелка вверх": (0x48, True), "стрелка вниз": (0x50, True),
    "стрелка влево": (0x4B, True), "стрелка вправо": (0x4D, True),
    "insert": (0x52, True), "delete": (0x53, True), "del": (0x53, True),
    "home": (0x47, True), "end": (0x4F, True),
    "pageup": (0x49, True), "pagedown": (0x51, True),
}


def _resolve_input(key_or_mouse):
    """
    Разбирает клавишу или кнопку мыши:
    - ('mouse', down_flag, up_flag, data, name)
    - ('key', scancode, extended, name)
    """
    k = str(key_or_mouse).strip().lower()
    if k in MOUSE_BUTTONS:
        down_f, up_f, data = MOUSE_BUTTONS[k]
        return ("mouse", down_f, up_f, data, k)

    if k in SCANCODES:
        val = SCANCODES[k]
        if isinstance(val, tuple):
            return ("key", val[0], val[1], k)
        return ("key", val, False, k)

    if len(k) == 1:
        u = ctypes.windll.user32
        vsc = u.MapVirtualKeyW(ord(k.upper()), 0)  # MAPVK_VK_TO_VSC
        if vsc:
            return ("key", vsc, False, k)

    log.warning("Неизвестная клавиша/кнопка для DirectInput: %s", key_or_mouse)
    return None


_desktop_handle = None

def ensure_desktop():
    """
    Привязывает текущий поток к интерактивному рабочему столу 'Default' WinSta0.
    Это критически необходимо для того, чтобы SendInput и mouse_event не блокировались
    Windows (код ошибки 5 / ERROR_ACCESS_DENIED) при отправке ввода в DirectX/Vulkan игры.
    """
    global _desktop_handle
    try:
        u = ctypes.windll.user32
        cur_desk = u.GetThreadDesktop(ctypes.windll.kernel32.GetCurrentThreadId())
        if cur_desk:
            buf = ctypes.create_unicode_buffer(256)
            if u.GetUserObjectInformationW(cur_desk, 2, buf, 256, None):
                if buf.value.lower() == "default":
                    return True
        if not _desktop_handle:
            _desktop_handle = u.OpenDesktopW("Default", 0, False, 0x01FF)
        if _desktop_handle:
            return bool(u.SetThreadDesktop(_desktop_handle))
    except Exception:
        pass
    return False


def send_direct_key(scancode, extended=False, up=False):
    """Посылает событие аппаратного сканкода клавиши (через keybd_event и SendInput)."""
    ensure_desktop()
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP

    # 1. user32.keybd_event со скан-кодом (надёжный способ для игр с DirectX/BattlEye)
    try:
        ctypes.windll.user32.keybd_event(0, scancode, flags, 0)
    except Exception:
        pass

    # 2. user32.SendInput
    try:
        extra = ctypes.c_ulong(0)
        ii = _INPUTUNION()
        ii.ki = KEYBDINPUT(0, scancode, flags, 0, ctypes.pointer(extra))
        inp = INPUT(1, ii)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    except Exception:
        pass


def send_direct_mouse(flag, data=0):
    """Посылает событие мыши (нажатие или отпускание) через mouse_event и SendInput."""
    ensure_desktop()
    # 1. user32.mouse_event (самый надёжный способ для мыши в DirectX играх)
    try:
        ctypes.windll.user32.mouse_event(flag, 0, 0, data, 0)
    except Exception:
        pass

    # 2. user32.SendInput
    try:
        extra = ctypes.c_ulong(0)
        ii = _INPUTUNION()
        ii.mi = MOUSEINPUT(0, 0, data, flag, 0, ctypes.pointer(extra))
        inp = INPUT(0, ii)  # type 0 = INPUT_MOUSE
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    except Exception:
        pass


def press_combo(keys, hold_time=0.10):
    """
    Нажимает комбинацию клавиш и кнопок мыши DirectInput (например ['mouse4'] или ['alt', 'a']).
    Если передан список шагов (последовательность), выполняет их по очереди через press_sequence.
    """
    if isinstance(keys, (list, tuple)) and any(isinstance(x, (list, tuple, dict, float)) for x in keys):
        return press_sequence(keys)

    if isinstance(keys, str):
        keys = [k.strip() for k in keys.split("+") if k.strip()]

    resolved = []
    for k in keys:
        res = _resolve_input(k)
        if res is not None:
            resolved.append(res)

    if not resolved:
        return False

    try:
        # Нажатие всех кнопок по очереди
        for item in resolved:
            kind = item[0]
            if kind == "key":
                send_direct_key(item[1], extended=item[2], up=False)
            elif kind == "mouse":
                send_direct_mouse(item[1], data=item[3])
            time.sleep(0.015)

        # Удержание в нажатом состоянии
        time.sleep(max(0.06, hold_time))

        # Отпускание в обратном порядке
        for item in reversed(resolved):
            kind = item[0]
            if kind == "key":
                send_direct_key(item[1], extended=item[2], up=True)
            elif kind == "mouse":
                send_direct_mouse(item[2], data=item[3])
            time.sleep(0.015)

        names = [r[3] if r[0] == "key" else r[4] for r in resolved]
        log.info("DirectInput combo executed: %s", " + ".join(names).upper())
        return True
    except Exception as e:
        log.exception("Ошибка отправки DirectInput: %s", e)
        # Гарантированное отпускание при сбое
        for item in resolved:
            try:
                if item[0] == "key":
                    send_direct_key(item[1], extended=item[2], up=True)
                elif item[0] == "mouse":
                    send_direct_mouse(item[2], data=item[3])
            except Exception:
                pass
        return False


def press_sequence(sequence, default_pause=0.08):
    """
    Выполняет последовательность действий (шагов) с микропаузами:
    sequence = [
        ["alt", "a"],         # шаг 1: переключение РЛС-ОЛС
        0.08,                 # микропауза 80 мс (50-100 мс)
        ["alt", "x"]          # шаг 2: переключение основного вооружения
    ]
    Либо список комбинаций: [["alt", "a"], ["alt", "x"]] — между ними выдерживается default_pause.
    """
    if not isinstance(sequence, (list, tuple)):
        return press_combo(sequence)

    # Если все элементы - строки (например ["alt", "a"]), это один комбо
    if all(isinstance(x, str) for x in sequence):
        return press_combo(sequence)

    success = True
    for idx, item in enumerate(sequence):
        if isinstance(item, (int, float)):
            time.sleep(max(0.01, float(item)))
        elif isinstance(item, dict) and "delay" in item:
            time.sleep(max(0.01, float(item["delay"])))
        elif isinstance(item, (list, tuple, str)):
            ok = press_combo(item)
            if not ok:
                success = False
            # Если следующий элемент не пауза, делаем дефолтную микропаузу
            if idx < len(sequence) - 1 and not isinstance(sequence[idx + 1], (int, float, dict)):
                time.sleep(default_pause)
    return success


def press_repeat(keys, count=1, interval=0.09):
    """
    Повторяет нажатие комбинации/клавиши DirectInput (например ЛТЦ) count раз подряд с интервалом interval.
    """
    count = max(1, min(int(count), 30))
    success = True
    for i in range(count):
        ok = press_combo(keys, hold_time=0.08)
        if not ok:
            success = False
        if i < count - 1:
            time.sleep(max(0.05, interval))
    log.info("DirectInput repeat executed: %d times", count)
    return success
