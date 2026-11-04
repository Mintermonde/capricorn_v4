"""Команды: сайты, приложения, громкость, яркость, диагностика ПК и т.д."""
import ctypes
import datetime
import difflib
import json
import logging
import os
import random
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass

import psutil

import automation
import media
from persona import line

log = logging.getLogger("capri")
NO_WINDOW = 0x08000000


@dataclass
class Reply:
    text: str
    action: str | None = None    # "hide" / "quit"


def strip_note(text):
    if not text:
        return ""
    return re.sub(r"\s*\(Note for you[\s\S]*?\)", "", text, flags=re.IGNORECASE).strip()


def norm(s):
    if not s:
        return ""
    s = strip_note(s)
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[^\w\s\.\-:/]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


TR = dict(zip("абвгдезийклмнопрстуфхцы", "abvgdeziyklmnoprstufhcy"))
TR.update({"ё": "e", "ж": "zh", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ь": "", "э": "e",
           "ю": "yu", "я": "ya"})


def translit(s):
    return "".join(TR.get(c, c) for c in s)


NUM = {"ноль": 0, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
       "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11,
       "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
       "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
       "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
       "семьдесят": 70, "восемьдесят": 80, "девяносто": 90, "сто": 100}


def parse_number(text):
    m = re.search(r"\d+", text)
    if m:
        return int(m.group())
    total = None
    for w in text.split():
        if w in NUM:
            total = (total or 0) + NUM[w]
        elif total is not None:
            break
    if total is not None:
        return total
    if re.search(r"максимум|на полную|на всю", text):
        return 100
    if re.search(r"половин", text):
        return 50
    if re.search(r"минимум", text):
        return 0
    return None


def run_ps(cmd, timeout=60):
    full = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
            "$ErrorActionPreference='SilentlyContinue'; " + cmd)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", full],
                       capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    return r.stdout.decode("utf-8", "replace").strip()


def ps_json(cmd):
    out = run_ps(cmd + " | ConvertTo-Json -Depth 3 -Compress")
    try:
        data = json.loads(out) if out else []
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else [data]


# ---------------- громкость / яркость ----------------

def _endpoint():
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    dev = AudioUtilities.GetSpeakers()
    if hasattr(dev, "EndpointVolume"):
        return dev.EndpointVolume
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))


def get_volume():
    return round(_endpoint().GetMasterVolumeLevelScalar() * 100)


def set_volume(v):
    ep = _endpoint()
    ep.SetMasterVolumeLevelScalar(max(0, min(100, v)) / 100, None)
    if v > 0:
        ep.SetMute(0, None)


def set_mute(on):
    _endpoint().SetMute(1 if on else 0, None)


def get_brightness():
    import screen_brightness_control as sbc
    return sbc.get_brightness()[0]


def set_brightness(v):
    import screen_brightness_control as sbc
    sbc.set_brightness(max(0, min(100, v)))


# ---------------- поиск приложений ----------------

PROTECTED_PROCS = {"explorer", "python", "pythonw", "svchost", "csrss", "winlogon", "dwm", "lsass", "services",
                   "system", "smss", "wininit", "fontdrvhost", "sihost", "taskhostw", "ctfmon", "runtimebroker",
                   "searchhost", "startmenuexperiencehost", "shellexperiencehost", "textinputhost", "ollama",
                   "ollama app", "conhost", "audiodg"}
SKIP_WORDS = ("uninstall", "удален", "удалить", "деинсталл", "readme", "help", "справка", "documentation",
              "license")


class AppIndex:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()
        self.ready = threading.Event()

    def build(self):
        items = {}
        try:
            for app in ps_json("Get-StartApps | Select-Object Name,AppID"):
                name = norm(app.get("Name") or "")
                if name and not any(w in name for w in SKIP_WORDS):
                    items[name] = ("appid", app.get("AppID"))
        except Exception:
            log.exception("Get-StartApps")
        home = os.path.expanduser("~")
        dirs = [os.path.join(os.environ.get("ProgramData", ""), r"Microsoft\Windows\Start Menu\Programs"),
                os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
                os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop"),
                os.path.join(os.environ.get("PUBLIC", ""), "Desktop")]
        for d in dirs:
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith((".lnk", ".url", ".appref-ms")):
                        name = norm(os.path.splitext(f)[0])
                        if name and not any(w in name for w in SKIP_WORDS):
                            # ярлык надёжнее идентификатора из Get-StartApps: у программ вроде Discord
                            # (установщик Squirrel) запуск по идентификатору ничего не открывает
                            if items.get(name, ("appid",))[0] != "file":
                                items[name] = ("file", os.path.join(root, f))
        with self.lock:
            self.items = items
        self.ready.set()
        log.info("Найдено приложений: %d", len(items))

    @staticmethod
    def _skeleton(s):
        """Согласные без гласных: «cloud», «claude», «клод» → «kld». Ловит созвучные названия."""
        s = translit(s.lower())
        for a, b in (("ph", "f"), ("ck", "k"), ("c", "k"), ("q", "k"), ("w", "v"), ("x", "ks"), ("z", "s")):
            s = s.replace(a, b)
        return re.sub(r"[aeiouy\s]", "", s)

    def candidates(self, query, aliases, limit=4):
        """Подходящие приложения, лучшие первыми: [(оценка, название, цель)]."""
        q = norm(query)
        variants = {q, translit(q), q.replace(" ", ""), translit(q.replace(" ", ""))}
        if q in aliases:
            al = norm(aliases[q])
            variants.add(al)
            variants.add(al.replace(" ", ""))
            variants.add(translit(al))
            variants.add(translit(al.replace(" ", "")))
        with self.lock:
            items = list(self.items.items())
        scored = {}
        for name, target in items:
            best = 0.0
            for v in variants:
                if v == name:
                    score = 1.0
                elif len(v) >= 3 and re.search(r"(^|\s)" + re.escape(v), name):
                    score = 0.93 - 0.003 * len(name)
                else:
                    score = difflib.SequenceMatcher(None, v, name).ratio()
                    first = name.split()[0] if name.split() else name
                    sk = self._skeleton(v)
                    if len(sk) >= 3 and sk == self._skeleton(name):
                        score = max(score, 0.97)  # звучит как всё название: «роблокс» = «roblox»
                    elif len(sk) >= 3 and sk == self._skeleton(first):
                        score = max(score, 0.86)  # звучит так же: «клод/cloud» ~ «claude»
                best = max(best, score)
            if best >= 0.72 and best > scored.get(name, (0,))[0]:
                scored[name] = (best, target)
        ranked = sorted(((s, n, t) for n, (s, t) in scored.items()), key=lambda x: -x[0])
        return ranked[:limit]

    def find(self, query, aliases):
        found = self.candidates(query, aliases, 1)
        return (found[0][1], found[0][2]) if found else None

    @staticmethod
    def launch(target):
        kind, value = target
        if kind == "appid":
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{value}"], creationflags=NO_WINDOW)
            return
        os.startfile(value)

    def launch_best(self, query, options):
        """Запустить лучший вариант; если Windows его не открыла (например, Roblox.lnk — «операция
        отменена»), пробуем похожие ярлыки с тем же началом (Roblox Player), а в конце — через проводник,
        как при двойном клике. options: [(оценка, имя, цель)]. Возвращает имя запущенного или None."""
        first = options[0]
        q = first[1].split()[0] if first[1].split() else ""  # «roblox» из найденного «roblox», а не «роблокс»
        with self.lock:
            similar = [(1.0, n, t) for n, t in self.items.items() if n != first[1] and q and n.startswith(q)
                       and not re.search(r"studio|uninstall|update", n)]
        for _, name, target in [first] + sorted(similar, key=lambda x: len(x[1])):
            try:
                self.launch(target)
                return name
            except OSError as e:
                log.info("%s не запустился (%s)", name, e)
        if first[2][0] == "file":
            subprocess.Popen(["explorer.exe", first[2][1]], creationflags=NO_WINDOW)
            return first[1]
        return None


# ---------------- диагностика ----------------

def _dir_size(path, limit=200000):
    total, n = 0, 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
            n += 1
            if n > limit:
                return total
    return total


def analyze_pc():
    """Возвращает (список проблем, полный текстовый отчёт)."""
    issues, lines = [], []
    add = lines.append
    now = datetime.datetime.now()
    add(f"ДИАГНОСТИКА ПК — {now:%d.%m.%Y %H:%M}")
    add("=" * 60)

    cpu = psutil.cpu_percent(interval=1.5)
    mem = psutil.virtual_memory()
    add(f"Процессор: загрузка {cpu:.0f}% ({psutil.cpu_count()} потоков)")
    add(f"Память: занято {mem.percent:.0f}% ({mem.used / 2**30:.1f} из {mem.total / 2**30:.1f} ГБ)")
    if cpu > 85:
        issues.append(f"процессор загружен на {cpu:.0f} процентов")
    if mem.percent > 85:
        issues.append(f"оперативная память занята на {mem.percent:.0f} процентов")

    up = now - datetime.datetime.fromtimestamp(psutil.boot_time())
    add(f"Время работы без перезагрузки: {up.days} д {up.seconds // 3600} ч")
    if up.days >= 7:
        issues.append(f"компьютер не перезагружался {up.days} дней")

    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if bat:
        add(f"Батарея: {bat.percent:.0f}% {'(заряжается)' if bat.power_plugged else ''}")

    add("\nДИСКИ:")
    for part in psutil.disk_partitions():
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        free_gb = u.free / 2**30
        add(f"  {part.mountpoint} {part.fstype}: свободно {free_gb:.1f} ГБ из {u.total / 2**30:.0f} ГБ ({100 - u.percent:.0f}%)")
        if u.percent > 90 or free_gb < 10:
            issues.append(f"на диске {part.mountpoint[0]} мало места — {free_gb:.0f} гигабайт")

    for d in ps_json("Get-PhysicalDisk | Select-Object FriendlyName,MediaType,HealthStatus,OperationalStatus"):
        add(f"  Накопитель {d.get('FriendlyName')}: здоровье {d.get('HealthStatus')}, состояние {d.get('OperationalStatus')}")
        if str(d.get("HealthStatus")) not in ("Healthy", "0"):
            issues.append(f"накопитель {d.get('FriendlyName')} сообщает о проблемах со здоровьем")

    tmp = os.environ.get("TEMP", "")
    if tmp:
        size = _dir_size(tmp) / 2**30
        add(f"  Временные файлы (%TEMP%): {size:.1f} ГБ")
        if size > 3:
            issues.append(f"временные файлы занимают {size:.0f} гигабайт")

    add("\nУСТРОЙСТВА С ОШИБКАМИ:")
    bad = ps_json("Get-PnpDevice -PresentOnly | Where-Object {$_.Status -eq 'Error'} | Select-Object FriendlyName,Class")
    for d in bad:
        add(f"  {d.get('FriendlyName')} ({d.get('Class')})")
    if not bad:
        add("  нет")
    else:
        issues.append(f"устройств с ошибкой драйвера: {len(bad)}")

    add("\nОШИБКИ В ЖУРНАЛАХ WINDOWS ЗА 24 ЧАСА (по источникам):")
    groups = ps_json("Get-WinEvent -FilterHashtable @{LogName='System','Application';Level=1,2;"
                     "StartTime=(Get-Date).AddDays(-1)} | Group-Object ProviderName | "
                     "Sort-Object Count -Descending | Select-Object -First 12 Count,Name")
    total_err = sum(int(g.get("Count", 0)) for g in groups)
    for g in groups:
        add(f"  {g.get('Count'):>4}  {g.get('Name')}")
    if not groups:
        add("  нет")
    if total_err > 30:
        issues.append(f"в журналах {total_err} ошибок за сутки")

    add("\nПОСЛЕДНИЕ ОШИБКИ:")
    for e in ps_json("Get-WinEvent -FilterHashtable @{LogName='System','Application';Level=1,2;"
                     "StartTime=(Get-Date).AddDays(-1)} -MaxEvents 8 | Select-Object "
                     "@{n='T';e={$_.TimeCreated.ToString('dd.MM HH:mm')}},ProviderName,Id,"
                     "@{n='M';e={if($_.Message){$_.Message.Substring(0,[Math]::Min(220,$_.Message.Length))}}}"):
        msg = re.sub(r"\s+", " ", str(e.get("M") or ""))
        add(f"  [{e.get('T')}] {e.get('ProviderName')} #{e.get('Id')}: {msg}")

    crashes = run_ps("(Get-WinEvent -FilterHashtable @{LogName='System';Id=41;"
                     "StartTime=(Get-Date).AddDays(-7)} | Measure-Object).Count")
    bsod = run_ps("(Get-WinEvent -FilterHashtable @{LogName='System';Id=1001;"
                  "ProviderName='Microsoft-Windows-WER-SystemErrorReporting';"
                  "StartTime=(Get-Date).AddDays(-7)} | Measure-Object).Count")
    crashes = int(crashes) if crashes.isdigit() else 0
    bsod = int(bsod) if bsod.isdigit() else 0
    add(f"\nАварийные выключения за 7 дней: {crashes}; синие экраны (BSOD): {bsod}")
    if crashes:
        issues.append(f"аварийных выключений за неделю: {crashes}")
    if bsod:
        issues.append(f"синих экранов за неделю: {bsod}")

    add("\nТОП ПРОЦЕССОВ ПО ПАМЯТИ:")
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["memory_info"].rss, p.info["name"]))
        except Exception:
            pass
    for rss, name in sorted(procs, reverse=True)[:8]:
        add(f"  {rss / 2**20:>7.0f} МБ  {name}")

    add("\nПРОГРАММЫ В АВТОЗАГРУЗКЕ:")
    for s in ps_json("Get-CimInstance Win32_StartupCommand | Select-Object Name,Location"):
        add(f"  {s.get('Name')}  [{s.get('Location')}]")

    add("\n" + "=" * 60)
    add("НАЙДЕННЫЕ ПРОБЛЕМЫ:" if issues else "Серьёзных проблем не найдено.")
    for i in issues:
        add(f"  • {i}")
    return issues, "\n".join(lines)


# ---------------- ютуб ----------------

BROWSERS = ("firefox", "chrome", "msedge", "opera", "browser", "brave", "vivaldi", "yandex")


def browser_playing():
    """True, если из браузера сейчас реально идёт звук (по индикатору громкости в микшере Windows)."""
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    for s in AudioUtilities.GetAllSessions():
        try:
            name = (s.Process.name() if s.Process else "").lower()
            if any(b in name for b in BROWSERS):
                meter = s._ctl.QueryInterface(IAudioMeterInformation)
                if meter.GetPeakValue() > 0.001:
                    return True
        except Exception:
            continue
    return False


def youtube_window():
    """Окно браузера с открытым YouTube (по заголовку активной вкладки)."""
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if u.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, buf, 512)
            if "youtube" in buf.value.lower():
                found.append(hwnd)
        return True
    u.EnumWindows(cb, 0)
    return found[0] if found else None


_ensure_token = [0]  # номер последней проверки «заиграло ли видео»; новая команда отменяет старую


def cancel_ensure():
    _ensure_token[0] += 1


def ensure_playing(wait_load=7.0):
    """Браузеры блокируют автозапуск со звуком у вкладок, открытых программой. Ждём звук;
    если тишина — переключаемся на окно YouTube и жмём K (пуск/пауза в плеере), затем проверяем.
    Если за это время пришла новая команда — тихо выходим, чтобы не кликнуть посреди её работы."""
    _ensure_token[0] += 1
    token = _ensure_token[0]
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    deadline = time.time() + wait_load
    while time.time() < deadline:  # может, запустилось само (или идёт реклама)
        if _ensure_token[0] != token:
            return
        if browser_playing():
            log.info("Видео играет само")
            return
        time.sleep(0.5)
    if _ensure_token[0] != token:
        return
    hwnd = None
    for _ in range(10):  # заголовок вкладки может ещё не смениться на «… - YouTube»
        hwnd = youtube_window()
        if hwnd:
            break
        time.sleep(0.5)
    if not hwnd:
        log.info("Окно YouTube не найдено, не нажимаю пуск")
        return
    u = ctypes.windll.user32
    u.keybd_event(0x12, 0, 0, 0)       # «пустой» Alt — без него Windows не даёт сменить активное окно
    u.keybd_event(0x12, 0, 2, 0)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.4)

    # Клик мышью по плееру — настоящее действие пользователя: и окно активирует, и фокус ставит в плеер,
    # и браузер считает это разрешением на звук. Точка (30% ширины, 35% высоты) попадает в плеер
    # и в обычном, и в широком режиме YouTube.
    from ctypes import wintypes
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    x, y = r.left + int((r.right - r.left) * 0.30), r.top + int((r.bottom - r.top) * 0.35)
    old = wintypes.POINT()
    u.GetCursorPos(ctypes.byref(old))
    u.SetCursorPos(x, y)
    u.mouse_event(0x0002, 0, 0, 0, 0)  # левая кнопка вниз
    u.mouse_event(0x0004, 0, 0, 0, 0)  # вверх
    time.sleep(0.05)
    u.SetCursorPos(old.x, old.y)
    for _ in range(6):
        time.sleep(0.5)
        if browser_playing():
            log.info("Видео запущено кликом по плееру")
            return
    send_keys(["k"])  # запасной вариант: фокус уже в плеере
    for _ in range(6):
        time.sleep(0.5)
        if browser_playing():
            log.info("Видео запущено клавишей K")
            return
    log.info("Не удалось запустить видео: звука нет")

def youtube_first(query):
    """(id, название) первого обычного видео (не шортс) в поиске YouTube или None."""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            page = r.read().decode("utf-8", "replace")
    except Exception as e:
        log.info("Поиск на YouTube не удался: %s", e)
        return None
    m = re.search(r'"videoRenderer"\s*:\s*\{\s*"videoId"\s*:\s*"([\w-]{11})"', page)
    if not m:
        m = re.search(r'/watch\?v=([\w-]{11})', page)
    if not m:
        return None
    title = ""
    t = re.search(r'"title"\s*:\s*\{(?:\s*"runs"\s*:\s*\[\s*\{\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"|\s*"simpleText"\s*:\s*"((?:[^"\\]|\\.)*)")', page[m.end():m.end() + 6000])
    if t:
        raw = t.group(1) or t.group(2)
        try:
            title = json.loads(f'"{raw}"')
        except Exception:
            title = raw
    return m.group(1), title


def youtube_channel_search(query):
    """(url, название) канала на YouTube или None."""
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}&sp=EgIQAg%253D%253D"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            page = r.read().decode("utf-8", "replace")
    except Exception as e:
        log.info("Поиск канала на YouTube не удался: %s", e)
        return None

    m_handle = re.search(r'"channelRenderer"\s*:\s*\{.*?"canonicalBaseUrl"\s*:\s*"(/(?:@|channel/|c/)[\w.-]+)"', page)
    if m_handle:
        handle = m_handle.group(1)
        t = re.search(r'"title"\s*:\s*\{(?:\s*"runs"\s*:\s*\[\s*\{\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"|\s*"simpleText"\s*:\s*"((?:[^"\\]|\\.)*)")', page[m_handle.start():m_handle.start() + 2500])
        title = ""
        if t:
            raw = t.group(1) or t.group(2)
            try:
                title = json.loads(f'"{raw}"')
            except Exception:
                title = raw
        return "https://www.youtube.com" + handle, title

    m_handle2 = re.search(r'"canonicalBaseUrl"\s*:\s*"(/@[\w.-]+)"', page)
    if m_handle2:
        return "https://www.youtube.com" + m_handle2.group(1), ""

    m_id = re.search(r'"channelRenderer"\s*:\s*\{.*?"channelId"\s*:\s*"([\w-]{24})"', page)
    if m_id:
        return f"https://www.youtube.com/channel/{m_id.group(1)}", ""

    return None


_desc_cache = {}


def file_description(path):
    """Описание программы из свойств exe-файла (то, что показывает диспетчер задач),
    например «Steam Client WebHelper». Пустая строка, если описания нет."""
    if not path:
        return ""
    if path in _desc_cache:
        return _desc_cache[path]
    desc = ""
    try:
        v = ctypes.windll.version
        size = v.GetFileVersionInfoSizeW(path, None)
        if size:
            buf = ctypes.create_string_buffer(size)
            if v.GetFileVersionInfoW(path, 0, size, buf):
                ptr, ln = ctypes.c_void_p(), ctypes.c_uint()
                if v.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(ln)) and ln.value:
                    lang, cp = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ushort * 2)).contents
                    key = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription"
                    sptr = ctypes.c_wchar_p()
                    if v.VerQueryValueW(buf, key, ctypes.byref(sptr), ctypes.byref(ln)) and ln.value:
                        desc = sptr.value or ""
    except Exception:
        pass
    _desc_cache[path] = desc
    return desc


def stem_name(name):
    """«с мамой» → «мам», «лёху» → «лёх», «шахтеров» → «шахтер»: поиск Telegram ищет по началу слова, а падежные
    окончания из речи мешают найти «Лёха», «Мама» или «Шахтёры»."""
    out = []
    for w in name.split():
        if len(w) >= 4:
            s = re.sub(r"(ами|ями|ого|его|ому|ему|ов|ев|ей|ой|ом|ем|ым|им|ою|ею|ах|ях|ам|ям|ую|юю|ая|яя|ые|ие|"
                       r"ы|и|а|я|у|ю|е)$", "", w, flags=re.IGNORECASE)
            w = s if len(s) >= 3 else w
        out.append(w)
    return " ".join(out)


def youtube_search_in_tab(text):
    """Поиск на YouTube в текущей вкладке через адресную строку (Ctrl+L): срабатывает, даже если страница
    ещё грузится и поле поиска не в фокусе."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    before = automation.window_title(hwnd)
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(text)
    for attempt in range(2):
        # адрес вводится, только если адресная строка действительно получила фокус (иначе буквы ушли бы
        # в страницу YouTube, где это горячие клавиши)
        if not media.navigate(hwnd, url):
            time.sleep(0.6)
            continue
        for _ in range(10):  # ждём, что вкладка ушла на страницу результатов
            time.sleep(0.4)
            title = automation.window_title(hwnd)
            if title != before and "youtube" in title.lower() and title.lower().startswith(text.lower()[:4]):
                return True
        log.info("Поиск на YouTube не сработал с %d-й попытки, заголовок: %s", attempt + 1, title)
        if not automation.is_foreground(hwnd):
            break  # окно потеряло фокус — второй раз вслепую не печатаем
    return False


def wiki_summary(query, sentences=2):
    """Первые предложения статьи русской Википедии по запросу, подготовленные для озвучки. None — не нашлось."""
    headers = {"User-Agent": "CapriAssistant/1.0 (personal voice assistant)"}

    def get(url):
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=6) as r:
            return json.loads(r.read().decode("utf-8"))
    try:
        found = get("https://ru.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=1&srsearch="
                    + urllib.parse.quote(query))["query"]["search"]
        if not found:
            return None
        page = get("https://ru.wikipedia.org/api/rest_v1/page/summary/"
                   + urllib.parse.quote(found[0]["title"].replace(" ", "_")))
    except Exception as e:
        log.info("Википедия недоступна: %s", e)
        return None
    if page.get("type") == "disambiguation":
        return None
    text = page.get("extract", "").replace("́", "")  # знаки ударения
    text = re.sub(r"\s*\([^()]*\)", "", text)       # транскрипции, даты и пр. в скобках — не для озвучки
    text = re.sub(r"\s*\[[^\]]*\]", "", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z])", text.strip())
    out = " ".join(parts[:sentences]).strip()
    if len(out) > 300:
        out = out[:300].rsplit(" ", 1)[0] + "…"
    return out or None


# ---------------- папки ----------------

SHELL_FOLDERS = {  # имена значений в реестре User Shell Folders (учитывают перенос в OneDrive)
    "desktop": "Desktop", "documents": "Personal", "pictures": "My Pictures", "music": "My Music",
    "videos": "My Video", "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
}
KNOWN_FOLDERS = [  # (регулярка по названию, ключ папки или shell:-путь, как назвать вслух)
    (r"фото(графи\w*)?|фотк\w*|изображени\w*|картинк\w*|снимк\w*", "pictures", "Изображения"),
    (r"документ\w*", "documents", "Документы"),
    (r"загрузк\w*|скачанн\w*|закачк\w*", "downloads", "Загрузки"),
    (r"рабоч\w+ стол\w*", "desktop", "Рабочий стол"),
    (r"музык\w*", "music", "Музыка"),
    (r"видео\w*", "videos", "Видео"),
    (r"скриншот\w*", "screenshots", "Скриншоты"),
    (r"(этот|мой) компьютер|компьютер", "shell:MyComputerFolder", "Этот компьютер"),
    (r"корзин\w*", "shell:RecycleBinFolder", "Корзина"),
]
DRIVE_LETTERS = {"ц": "C", "си": "C", "с": "C", "д": "D", "ди": "D", "де": "D", "е": "E", "и": "E",
                 "ф": "F", "эф": "F", "джи": "G", "г": "G", "же": "G"}


def known_dir(key):
    if key == "screenshots":
        return os.path.join(known_dir("pictures"), "Screenshots")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return os.path.expandvars(winreg.QueryValueEx(k, SHELL_FOLDERS[key])[0])
    except Exception:
        return os.path.join(os.path.expanduser("~"), {"documents": "Documents", "pictures": "Pictures",
                                                      "music": "Music", "videos": "Videos",
                                                      "downloads": "Downloads"}.get(key, "Desktop"))


def find_folder(name, search=False):
    """(путь, название) по сказанному имени папки или None. search=True — искать и среди своих папок."""
    name = norm(name)
    drive = re.fullmatch(r"(диск|раздел) (?P<l>\S+)", name)
    if drive:
        letter = DRIVE_LETTERS.get(drive.group("l"), drive.group("l").upper())
        if len(letter) == 1 and os.path.exists(f"{letter}:\\"):
            return f"{letter}:\\", f"диск {letter}"
    for pattern, key, label in KNOWN_FOLDERS:
        if re.fullmatch(pattern, name):
            path = key if key.startswith("shell:") else known_dir(key)
            if key.startswith("shell:") or os.path.isdir(path):
                return path, label
    if not search:
        return None
    return search_folder(name)


def search_folder(name, limit=40000):
    """Ищем папку по имени (с транслитом и нечётким сравнением) в домашних папках, до 4 уровней вглубь."""
    targets = {name, translit(name)}
    roots = [known_dir(k) for k in ("desktop", "documents", "downloads", "pictures", "videos", "music")]
    roots.append(os.path.expanduser("~"))
    best, best_score, seen = None, 0.0, 0
    for root in dict.fromkeys(roots):
        base_depth = root.rstrip("\\").count("\\")
        for cur, dirs, _ in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith((".", "$")) and d.lower() not in
                       ("appdata", "node_modules", "__pycache__", "site-packages", "windows")]
            if cur.count("\\") - base_depth >= 4:
                dirs[:] = []
            for d in dirs:
                seen += 1
                dn = norm(d)
                for t in targets:
                    score = 1.0 if dn == t else (0.9 if t in dn.split() or dn.startswith(t)
                                                 else difflib.SequenceMatcher(None, t, dn).ratio())
                    if score > best_score:
                        best, best_score = (os.path.join(cur, d), d), score
            if best_score == 1.0 or seen > limit:
                break
        if best_score == 1.0:
            break
    return best if best_score >= 0.8 else None


# ---------------- клавиши ----------------

VK = {"win": 0x5B, "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "tab": 0x09, "enter": 0x0D, "esc": 0x1B,
      "space": 0x20, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
      "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
      "printscreen": 0x2C, "capslock": 0x14, "menu": 0x5D}
EXTENDED = {"win", "delete", "insert", "home", "end", "pageup", "pagedown", "left", "up", "right", "down", "menu"}
KEY_WORDS = {  # как клавиши произносят (Vosk пишет кириллицей, Google — часто латиницей)
    "win": "вин винд винда виндовс виндоус виндоуз виндос виндус виндо windows window win wind винды "
           "виндоуса виндовса",
    "ctrl": "контрол контроль контрл кнтрл ктрл контр ctrl control ctl",
    "alt": "альт алт alt", "shift": "шифт shift", "tab": "таб табуляция tab",
    "enter": "энтер ентер enter ввод return", "esc": "эскейп искейп эскейф эск esc escape",
    "space": "пробел space спейс", "backspace": "бэкспейс бекспейс backspace",
    "delete": "делит дилит делейт delete del дел", "insert": "инсерт insert", "home": "хоум home",
    "end": "энд end", "printscreen": "принтскрин printscreen prtsc", "capslock": "капслок capslock",
    "left": "влево лево налево left", "right": "вправо право направо right",
    "up": "вверх наверх up", "down": "вниз down", "menu": "меню",
}
WORD_TO_KEY = {w: k for k, ws in KEY_WORDS.items() for w in ws.split()}
LETTER_NAMES = {"эй": "a", "би": "b", "си": "c", "ди": "d", "и": "e", "эф": "f", "джи": "g", "эйч": "h",
                "ай": "i", "джей": "j", "кей": "k", "эл": "l", "эм": "m", "эн": "n", "оу": "o", "пи": "p",
                "кью": "q", "ар": "r", "эс": "s", "ти": "t", "ю": "u", "ви": "v", "дабл ю": "w",
                "дабл-ю": "w", "экс": "x", "икс": "x", "уай": "y", "игрек": "y", "зед": "z", "зет": "z",
                # по-русски: «контрол цэ», «вин дэ», и одиночные буквы «вин д»
                "а": "a", "бэ": "b", "б": "b", "цэ": "c", "ц": "c", "дэ": "d", "д": "d", "е": "e",
                "гэ": "g", "г": "g", "ха": "h", "ка": "k", "к": "k", "эль": "l", "л": "l", "м": "m",
                "н": "n", "о": "o", "пэ": "p", "п": "p", "эр": "r", "р": "r", "с": "s", "тэ": "t", "т": "t",
                "у": "u", "вэ": "v", "в": "v", "зэ": "z", "з": "z"}
SKIP_WORDS_KEYS = {"и", "плюс", "кнопку", "кнопка", "кнопки", "клавишу", "клавиши", "клавиша", "клавиш",
                   "сочетание", "сочетания", "комбинацию", "комбинация", "стрелку", "стрелка", "стрелочку",
                   "на", "клавиатуре", "одновременно", "мне", "пожалуйста", "plus", "and"}


def split_glued(word):
    """Google иногда склеивает сочетание в одно слово: «wintab», «альттаб», «ctrlshiftesc».
    Режем на известные названия клавиш (одиночная буква/цифра допустима только последней)."""
    names = sorted((w for w in WORD_TO_KEY if len(w) > 1), key=len, reverse=True)

    def go(rest):
        if not rest:
            return []
        for n in names:
            if rest.startswith(n):
                tail = go(rest[len(n):])
                if tail is not None:
                    return [WORD_TO_KEY[n]] + tail
        f = re.match(r"[fф](1[0-2]|[1-9])", rest)
        if f:
            tail = go(rest[f.end():])
            if tail is not None:
                return ["f" + f.group(1)] + tail
        if len(rest) == 1 and re.fullmatch(r"[a-z0-9]", rest):
            return [rest]
        return None
    return go(word)


def parse_keys(text):
    """«вин таб» / «ctrl shift esc» / «эф пять» → ['win', 'tab'] ... Возвращает (клавиши, нераспознанное)."""
    t = re.sub(r"[+\-_,.]", " ", norm(text))
    for a, b in (("пейдж ап", "pageup"), ("page up", "pageup"), ("пейдж даун", "pagedown"),
                 ("page down", "pagedown"), ("принт скрин", "printscreen"), ("print screen", "printscreen"),
                 ("капс лок", "capslock"), ("caps lock", "capslock"), ("дабл ю", "дабл-ю"),
                 ("бэк спейс", "backspace"), ("back space", "backspace")):
        t = t.replace(a, b)
    words = t.split()
    keys, i = [], 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if w in WORD_TO_KEY or w in VK:
            keys.append(WORD_TO_KEY.get(w, w))
        elif re.fullmatch(r"[fф]\d{1,2}", w):
            keys.append("f" + w[1:])
        elif w in ("эф", "ф", "f") and (nxt.isdigit() or nxt in NUM):
            keys.append(f"f{int(nxt) if nxt.isdigit() else NUM[nxt]}")
            i += 1
        elif w in LETTER_NAMES and not (w == "и" and keys and i + 1 < len(words)):
            keys.append(LETTER_NAMES[w])
        elif re.fullmatch(r"[a-z0-9]", w):
            keys.append(w)
        elif w in NUM and NUM[w] < 10:
            keys.append(str(NUM[w]))
        elif w not in SKIP_WORDS_KEYS:
            glued = split_glued(w)
            if not glued:
                return [], w
            keys += glued
        i += 1
    return keys, None


def send_keys(keys):
    """Зажимает клавиши по порядку и отпускает в обратном — так работают сочетания вроде Win+Tab."""
    u = ctypes.windll.user32
    codes = []
    for k in keys:
        if k in VK:
            code = VK[k]
        elif re.fullmatch(r"f\d{1,2}", k) and 1 <= int(k[1:]) <= 12:
            code = 0x6F + int(k[1:])
        else:
            code = ord(k.upper())
        codes.append((code, 1 if k in EXTENDED else 0))
    for code, ext in codes:
        u.keybd_event(code, 0, ext, 0)
        time.sleep(0.02)
    for code, ext in reversed(codes):
        u.keybd_event(code, 0, ext | 2, 0)  # 2 = KEYEVENTF_KEYUP
        time.sleep(0.02)


# ---------------- веб-сайты и домены ----------------

DEFAULT_SITES = {
    # Поисковики и порталы
    "яндекс": "https://ya.ru",
    "яндекс ру": "https://ya.ru",
    "ya ru": "https://ya.ru",
    "гугл": "https://www.google.com",
    "google": "https://www.google.com",
    "майл": "https://mail.ru",
    "майл ру": "https://mail.ru",
    "рамблер": "https://www.rambler.ru",
    "дзен": "https://dzen.ru",
    "википедия": "https://ru.wikipedia.org",
    "вики": "https://ru.wikipedia.org",
    "wikipedia": "https://ru.wikipedia.org",

    # Видео, стриминг, кино, аниме, манга
    "ютуб": "https://www.youtube.com",
    "ютубчик": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "рутуб": "https://rutube.ru",
    "rutube": "https://rutube.ru",
    "твич": "https://www.twitch.tv",
    "twitch": "https://www.twitch.tv",
    "тик ток": "https://www.tiktok.com",
    "тикток": "https://www.tiktok.com",
    "tiktok": "https://www.tiktok.com",
    "кинопоиск": "https://www.kinopoisk.ru",
    "иви": "https://www.ivi.ru",
    "окко": "https://okko.tv",
    "премьер": "https://premier.one",
    "кинокрад": "https://kinokrad.now/",
    "резка": "https://hdrezka.ag/",
    "хдрезка": "https://hdrezka.ag/",
    "hdrezka": "https://hdrezka.ag/",
    "лордфильм": "https://lordfilm.lu/",
    "анимего": "https://animego.org/",
    "animego": "https://animego.org/",
    "анилибрия": "https://anilibria.tv/",
    "мангалиб": "https://mangalib.me/",
    "mangalib": "https://mangalib.me/",
    "реманга": "https://remanga.org/",
    "шикимори": "https://shikimori.one",
    "shikimori": "https://shikimori.one",

    # Музыка
    "яндекс музыка": "https://music.yandex.ru",
    "спотифай": "https://open.spotify.com",
    "spotify": "https://open.spotify.com",
    "саундклауд": "https://soundcloud.com",
    "soundcloud": "https://soundcloud.com",

    # Соцсети, мессенджеры, сообщества
    "вк": "https://vk.com",
    "вконтакте": "https://vk.com",
    "vk": "https://vk.com",
    "телеграм веб": "https://web.telegram.org/",
    "тг веб": "https://web.telegram.org/",
    "ватсап веб": "https://web.whatsapp.com/",
    "whatsapp web": "https://web.whatsapp.com/",
    "дискорд веб": "https://discord.com/app",
    "реддит": "https://www.reddit.com",
    "reddit": "https://www.reddit.com",
    "пикабу": "https://pikabu.ru",
    "pikabu": "https://pikabu.ru",
    "одноклассники": "https://ok.ru",
    "ок": "https://ok.ru",
    "инстаграм": "https://www.instagram.com",
    "инста": "https://www.instagram.com",
    "instagram": "https://www.instagram.com",
    "твиттер": "https://x.com",
    "twitter": "https://x.com",
    "пинтерест": "https://www.pinterest.com",
    "pinterest": "https://www.pinterest.com",
    "дтф": "https://dtf.ru",
    "dtf": "https://dtf.ru",
    "хабр": "https://habr.com",
    "habr": "https://habr.com",
    "стим": "https://store.steampowered.com",
    "steam": "https://store.steampowered.com",
    "рутрекер": "https://rutracker.org",
    "rutracker": "https://rutracker.org",
    "фикбук": "https://ficbook.net",
    "ficbook": "https://ficbook.net",
    "автор тудей": "https://author.today",
    "author today": "https://author.today",

    # Покупки и маркетплейсы
    "авито": "https://www.avito.ru",
    "avito": "https://www.avito.ru",
    "озон": "https://www.ozon.ru",
    "ozon": "https://www.ozon.ru",
    "вайлдберриз": "https://www.wildberries.ru",
    "вайлдбериз": "https://www.wildberries.ru",
    "вб": "https://www.wildberries.ru",
    "wildberries": "https://www.wildberries.ru",
    "яндекс маркет": "https://market.yandex.ru",
    "маркет": "https://market.yandex.ru",
    "мегамаркет": "https://megamarket.ru",
    "алиэкспресс": "https://aliexpress.ru",
    "алик": "https://aliexpress.ru",
    "aliexpress": "https://aliexpress.ru",
    "днс": "https://www.dns-shop.ru",
    "dns": "https://www.dns-shop.ru",
    "ситилинк": "https://www.citilink.ru",
    "citilink": "https://www.citilink.ru",
    "мвидео": "https://www.mvideo.ru",
    "эльдорадо": "https://www.eldorado.ru",

    # Гос и банки
    "госуслуги": "https://www.gosuslugi.ru",
    "gosuslugi": "https://www.gosuslugi.ru",
    "сбербанк": "https://www.sberbank.ru",
    "сбер онлайн": "https://www.sberbank.ru",
    "сбер": "https://www.sberbank.ru",
    "тинькофф": "https://www.tbank.ru",
    "т банк": "https://www.tbank.ru",
    "т-банк": "https://www.tbank.ru",
    "альфа банк": "https://alfabank.ru",
    "втб": "https://www.vtb.ru",

    # Сервисы, карты, инструменты
    "почта": "https://mail.google.com",
    "карты": "https://yandex.ru/maps",
    "гугл карты": "https://maps.google.com",
    "погода": "https://yandex.ru/pogoda",
    "переводчик": "https://translate.google.com",
    "гугл переводчик": "https://translate.google.com",
    "дипл": "https://www.deepl.com/ru/translator",
    "deepl": "https://www.deepl.com/ru/translator",
    "speedtest": "https://www.speedtest.net",
    "спидтест": "https://www.speedtest.net",
    "2ip": "https://2ip.ru",
    "2ип": "https://2ip.ru",
    "гитхаб": "https://github.com",
    "github": "https://github.com",
    "гитлаб": "https://gitlab.com",
    "gitlab": "https://gitlab.com",
    "стек оверфлоу": "https://stackoverflow.com",
    "stackoverflow": "https://stackoverflow.com",
    "chatgpt": "https://chatgpt.com",
    "чатгпт": "https://chatgpt.com",
    "чат гпт": "https://chatgpt.com",
    "клод": "https://claude.ai",
    "claude": "https://claude.ai",
    "дипсик": "https://chat.deepseek.com",
    "deepseek": "https://chat.deepseek.com",
    "фигма": "https://www.figma.com",
    "figma": "https://www.figma.com",
    "нотион": "https://www.notion.so",
    "notion": "https://www.notion.so",
}

TLD_MAP = {
    "ком": "com",
    "com": "com",
    "ру": "ru",
    "ru": "ru",
    "рф": "рф",
    "нет": "net",
    "net": "net",
    "орг": "org",
    "org": "org",
    "тв": "tv",
    "tv": "tv",
    "ми": "me",
    "me": "me",
    "ио": "io",
    "io": "io",
    "дев": "dev",
    "dev": "dev",
    "апп": "app",
    "app": "app",
    "ай": "ai",
    "ai": "ai",
    "су": "su",
    "su": "su",
    "бай": "by",
    "by": "by",
    "кз": "kz",
    "kz": "kz",
    "юа": "ua",
    "ua": "ua",
    "де": "de",
    "de": "de",
    "онлайн": "online",
    "online": "online",
    "клуб": "club",
    "club": "club",
    "инфо": "info",
    "info": "info",
    "про": "pro",
    "pro": "pro",
    "ко": "co",
    "co": "co",
}


def parse_spoken_domain(text):
    """Распознаёт сказанный домен («хабр точка ком», «mangalib.me», «vk.com», «твич точка тв») -> URL или None."""
    s = text.strip().lower()
    if s.startswith(("http://", "https://")):
        return s

    s_dots = re.sub(r"\s*(?:точка|точки|dot|\.)\s*", ".", s)
    if "." in s_dots:
        parts = s_dots.split(".")
        if len(parts) >= 2:
            base_parts = parts[:-1]
            tld = parts[-1].strip()
            mapped_tld = TLD_MAP.get(tld, tld)
            if re.fullmatch(r"[a-zа-я]{2,12}", mapped_tld):
                domain_parts = []
                for p in base_parts:
                    p_clean = re.sub(r"\s+", "", p)
                    if mapped_tld != "рф":
                        p_clean = translit(p_clean)
                    domain_parts.append(p_clean)
                final_tld = mapped_tld if mapped_tld == "рф" else translit(mapped_tld)
                domain = ".".join(domain_parts) + "." + final_tld
                if re.fullmatch(r"[a-z0-9а-я\-]+(\.[a-z0-9а-я\-]+)*\.[a-zа-я]{2,12}", domain):
                    return f"https://{domain}"
    return None


def resolve_site_url(query):
    """Определяет URL любого сайта по названию через Google Suggest (быстро) или Google Feeling Lucky."""
    q = query.strip()
    if not q:
        return "https://www.google.com"

    # 1. Google Chrome Suggest (150-250ms) — возвращает официальные NAVIGATION URL для брендов и сайтов
    try:
        url = f"https://suggestqueries.google.com/complete/search?client=chrome&q={urllib.parse.quote(q)}&hl=ru"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            queries = data[1] if len(data) > 1 else []
            meta = data[4] if len(data) > 4 else {}
            types = meta.get("google:suggesttype", []) if isinstance(meta, dict) else []
            for item, stype in zip(queries, types):
                if stype == "NAVIGATION" and item.startswith(("http://", "https://")):
                    return item
            for item in queries:
                if item.startswith(("http://", "https://")):
                    return item
    except Exception:
        pass

    # 2. Google «Мне повезёт» (302 redirect) — точное перенаправление на главный результат
    try:
        url = f"https://www.google.com/search?q={urllib.parse.quote(q)}&btnI=1"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        class _RedirectCatcher(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                self.redirect_url = newurl
                return None
        handler = _RedirectCatcher()
        opener = urllib.request.build_opener(handler)
        try:
            opener.open(req, timeout=3.0)
        except urllib.error.HTTPError as e:
            redir = getattr(handler, "redirect_url", None) or e.headers.get("Location")
            if redir:
                if "url?q=" in redir:
                    m = re.search(r"url\?q=([^&]+)", redir)
                    if m:
                        return urllib.parse.unquote(m.group(1))
                elif redir.startswith("http"):
                    return redir
    except Exception:
        pass

    # 3. Надёжный запасной вариант — браузер сам перейдёт по «Мне повезёт»
    return f"https://www.google.com/search?q={urllib.parse.quote(q)}&btnI=1"


# ---------------- обработчик команд ----------------

class Actions:
    def __init__(self, cfg, base_dir, ai):
        self.cfg = cfg
        self.base_dir = base_dir
        self.ai = ai
        self.sites = {norm(k): v for k, v in DEFAULT_SITES.items()}
        self.sites.update({norm(k): v for k, v in cfg.get("sites", {}).items()})
        self.apps = {norm(k): v for k, v in cfg.get("apps", {}).items()}
        self.aliases = {norm(k): v for k, v in cfg.get("app_aliases", {}).items()}
        self.index = AppIndex()
        threading.Thread(target=self.index.build, daemon=True).start()
        self.pending = None
        self.choice = None  # варианты приложений, из которых пользователь сейчас выбирает
        self.youtube_opened_at = 0.0  # когда Капри последний раз открывала YouTube
        self.telegram_opened_at = 0.0  # когда Капри последний раз открывала Telegram
        self.last_chat_target = ""     # имя контакта/чата, с которым сейчас работаем
        self.media_paused = None      # какой плеер Капри поставила на паузу
        self.local = None
        self._last_opened_url = None   # debounce для предотвращения двойного открытия сайтов
        self._last_opened_time = 0.0
        self.routes = [
            (r"^(выход|выключись|отключись|заверши работу|завершить работу)$", self.quit),
            (r"^(спрячься|скройся|исчезни|пока|отбой|свободна)\b|"
             r"^(уйди|уходи|убирайся|свали|сгинь|испарись|скрой себя|убери себя)\b|"
             r"(уйди|уходи|убирайся|свали|пропади|исчезни) (с|из) (экрана|монитора|глаз)", self.hide),
            (r"помаши|помахай|махни|помаши ручкой|поздоровайся", self.wave),
            (r"погуляй|прогуляйся|пройдись|прогулк", self.roam),
            (r"что ты (умеешь|можешь)|как\w* (у тебя )?команд|(назови|перечисли|скажи) (\S+ )?команд|"
             r"список команд|помощь$", self.help),
            (r"(перемест|подвин|сдвин|переди|встань|иди|отойди|переберись)\w*\s.*(угол|влево|вправо|лев|прав|"
             r"верх|низ|центр|середин|другую сторону)", self.move),
            (r"(выключи|перезагрузи|перезапусти) (компьютер|пк|комп|систему)", self.power),
            (r"заблокируй (компьютер|пк|комп|экран)", self.lock),
            # --- микрофон (выполняет main: там живёт слушатель) ---
            (r"(отключи|выключи|заглуши|замьють|замуть)\s+(микрофон|звук микрофона)|не слушай( меня)?|перестань слушать|помолчи немного",
             lambda c, m: Reply("", "mic_mute")),
            (r"(включи|размьють|размуть)\s+(микрофон|звук микрофона)|слушай( меня)?",
             lambda c, m: Reply("", "mic_unmute")),
            (r"(какой|какое) (сейчас )?(микрофон|устройство ввода)|что за микрофон|(через )?какой микрофон",
             lambda c, m: Reply("", "mic_info")),
            (r"(смени|поменяй|переключи|следующий|другой) (\S+ )?(микрофон|устройство ввода)",
             lambda c, m: Reply("", "mic_next")),
            (r"громкост|громче|тише|(вкл|выкл|отключ|убер|верни|включ)\w* звук|звук (на|в) |без звука|замуть", self.volume),
            (r"яркост|ярче|темнее", self.brightness),
            (r"(проанализ|анализ|диагност|провер|просканир|сканир)\w*.*(пк|компьютер|комп|систем|ошибк)", self.analyze),
            # --- прокрутка страниц ---
            (r"\b(прокрут|пролист|листай|листани|полистай|скролл|скроль|спустись|поднимись|крути (вниз|вверх))\w*|"
             r"^(в |на |до )?(самый |самую |самого )?(низ|верх|конец страницы|начало страницы|низа|верха)$|"
             r"^(еще |ещё )?(ниже|выше)$", self.scroll),
            # --- мультимедиа: что сейчас играет (музыка, YouTube, плееры) ---
            (r"^(поставь |поставить )?(на )?пауз\w*( музык\w*| видео| трек| песн\w*| ролик)?$|"
             r"^(останови|приостанови|тормозни|стопни)( музык\w*| видео| трек| песн\w*| воспроизведение| ролик)?$|"
             r"^(выключи|стоп) (музык\w*|видео|трек|песн\w*|ролик)$", self.media_pause),
            (r"^(продолжи|продолжай|играй|воспроизведи|сними( с)? пауз\w*|сними)( музык\w*| видео| трек| песн\w*|"
             r" воспроизведение| ролик)?$|^(включи|запусти) (дальше|обратно|снова)$|"
             r"^(включи|запусти) (музык\w*|видео|трек|песн\w*) (обратно|снова|дальше)$", self.media_play),
            (r"^(следующ\w*|дальше|переключи|скипни|пропусти)( трек| песн\w*| видео| композици\w*| ролик)?$|"
             r"^(включи|давай) следующ\w*( трек| песн\w*| видео| ролик)?$", self.media_next),
            (r"^(предыдущ\w*|прошл\w*)( трек| песн\w*| видео| композици\w*| ролик)?$|"
             r"^(включи|верни) (предыдущ|прошл)\w*( трек| песн\w*| видео| ролик)?$", self.media_prev),
            (r"что (сейчас )?(играет|звучит|за (песн|трек|музык|видео)\w*)", self.media_info),
            (r"^(поставь|включи|начни|запусти|давай|играй|воспроизведи)( видео| музык\w*| трек| песн\w*| ролик)? "
             r"(на|с|со) "
             r"(\d|полминут|полтор|начал|сначала|момент|отметк|тайминг|(\S+ ){0,2}(секунд|минут|час)|"
             r"(\S+ )?(ноль|один|одна|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|\S+дцать|сорок|"
             r"пятьдесят))", self.media_seek),
            (r"^(перемотай|перемотать|промотай|мотни|отмотай|прокрути|верни\w*|вернись|пропусти|скипни|"
             r"перемотка|поставь|включи)( видео| музык\w*| трек| песн\w*| ролик)?( на| в| к| с)?"
             r"( тайминг\w*| отметк\w*| момент\w*| время| позици\w*)?\s*"
             r"(\d|полминут|полтор|начал|сначала|заново|вперед|назад|(\S+ ){0,2}(секунд|минут|час))", self.media_seek),
            (r"^(включи|начни|поставь|запусти|давай|перемотай|верни|играй)( видео| музык\w*| трек| песн\w*| ролик)?"
             r"( с| на| в)?( самого)? ?(сначала|начало|начала|заново|снова)$", self.media_seek),
            (r"^(нажми на поиск|нажми поиск|перейди в поиск|в поиск|поиск|поставь курсор в поиск)$",
             self.search_field),
            (r"^(нажми|нажать|зажми|жми|набери сочетание) (?P<k>.+)$", self.press),
            # --- Telegram: прямая отправка сообщений одной фразой («напиши в тг лехе привет», «отправь в телеграм маме я дома») ---
            # 1. Формат: напиши в тг [кому] [текст]
            (r"(?i)^(напиши|отправь|скинь|ответь|передай)( мне)?\s+"
             r"(в\s+|на\s+)(телеграм\w*|telegram|телег\w*|тг)\s+"
             r"(?P<name>[а-яёa-z0-9_\s-]+?)\s*[:,-]?\s+(?P<text>.+)$", self.direct_send),
            # 2. Формат: напиши [кому] в тг [текст]
            (r"(?i)^(напиши|отправь|скинь|ответь|передай)( мне)?\s+"
             r"(?P<name>[а-яёa-z0-9_-]+)\s+"
             r"(в\s+|на\s+)(телеграм\w*|telegram|телег\w*|тг)\s*[:,-]?\s+(?P<text>.+)$", self.direct_send),
            # --- Яндекс Музыка: открытие плейлистов («открой плейлист мне понравилось и включи первый трек») ---
            (r"(?i)^(открой|включи|поставь|запусти)( мне)?\s+"
             r"плейлист\s+(?P<pl>.+?)"
             r"(\s+и\s+(включи|поставь|запусти|играй)\s+(?P<play>первый трек|трек|музыку|его)?)?"
             r"(\s+(в|на)\s+(яндекс\s*музык\w*|yandex\s*music))?$", self.yandex_music_playlist),
            (r"(?i)^(открой|перейди на|зайди в|запусти)\s+(яндекс\s*музык\w*|yandex\s*music)\s+"
             r"(и\s+)?(открой|включи|поставь)?\s*плейлист\s+(?P<pl>.+)$", self.yandex_music_playlist),
            (r"(?i)^(включи|поставь|запусти|играй)( мне)?\s+"
             r"(яндекс\s*музык\w*|yandex\s*music)\s*(?P<pl>.*)$", self.yandex_music_play),
            # --- Игровой режим (War Thunder / DirectInput макросы) ---
            (r"(?i)^(включи|активируй|переключи на)?\s*игровой режим\s*(для\s+(?P<game>.+))?$", self.game_mode_cmd),
            (r"(?i)^(выключи|отключи|выйди из)\s+игрово(го|й)\s+режим\w*$", self.game_mode_cmd),
            (r"(?i)^(какие|покажи|список)?\s*(бинды|макросы|кнопки)\s*(в\s+игре|для\s+игры)?$", self.game_mode_cmd),
            (r"(?i)\b(лтц|ловушк\w*|теплов\w*\s+ловушк\w*|от\s+отца|элтэцэ)\b", self.game_action_cmd),
            (r"(?i)\b(закрылк\w*|шасси)\b", self.game_action_cmd),
            (r"(?i)\b(захват\w*|парл|радар\w*|рлс\w*|олс|вооружен\w*)\b", self.game_action_cmd),
            (rf"^({automation.TYPE_VERBS})\s+\S", self.type_cmd),
            # --- YouTube каналы (например: «найди на ютубе канал мармок», «открой ютуб канал mrbeast», «канал куплинов на ютубе») ---
            (r"^(открой|запусти|включи|найди|поищи|покажи|перейди на|зайди на|ищи)( мне)?\s+"
             r"(на|в)\s+(ютуб\w*|youtube)\s+"
             r"канал\w*\s+"
             r"(?P<q>.+)$", self.youtube_channel),
            (r"^(открой|запусти|включи|найди|поищи|покажи|перейди на|зайди на|ищи)( мне)?\s+"
             r"(ютуб\w*|youtube)[-\s]+"
             r"канал\w*\s+"
             r"(?P<q>.+)$", self.youtube_channel),
            (r"^(открой|запусти|включи|найди|поищи|покажи|перейди на|зайди на|ищи)( мне)?\s+"
             r"канал\w*\s+"
             r"(?P<q>.+?)\s+"
             r"(на|в)\s+(ютуб\w*|youtube)$", self.youtube_channel),
            # --- Telegram: поиск контактов и открытие чатов ---
            # 1. С явным указанием мессенджера («открой в тг лёха», «найди в телеграме сашу», «перейди в тг к лехе»)
            (r"(?i)^(открой|найди|поищи|зайди|перейди|выбери)( мне)?\s+"
             r"(в\s+|на\s+|к\s+|ко\s+)?(телеграм\w*|telegram|телег\w*|тг)\s+"
             r"(контакт\w*|чат\w*|диалог\w*|переписк\w*)?\s*(с\s+|со\s+|к\s+|ко\s+)?(?P<name>.+)$", self.chat),
            # 2. Инвертированный порядок («найди сашу в тг», «открой леху в телеграме»)
            (r"(?i)^(открой|найди|поищи|выбери)( мне)?\s+"
             r"(контакт\w*|чат\w*|диалог\w*|переписк\w*)?\s*(с\s+|со\s+|к\s+|ко\s+)?(?P<name>.+?)\s+"
             r"(в\s+|на\s+)(телеграм\w*|telegram|телег\w*|тг)$", self.chat),
            # 3. По слову чат/диалог/контакт или номеру («первый чат», «чат с мамой», «открой контакт леха»)
            (r"(?i)^(открой |зайди в |перейди в |выбери |найди )?(в )?(телеграм\w*|telegram|телег\w*|тг )?\s*"
             r"((?P<ord>{}) )?(чат\w*|chat|диалог\w*|переписк\w*|контакт\w*|беседу|беседа|группу|канал)"
             r"( с| со| к| ко)?( (?P<name>.+))?$".format("|".join(automation.ORDINALS)), self.chat),
            # 4. «открой телеграм папа» — запустить Telegram и сразу открыть чат с этим именем
            (r"^(открой|зайди в|перейди в|напиши в|запусти) (телеграм\w*|telegram|телег\w*|тг) (?P<name>(?!и |"
             r"напиши|первый|второй|третий).+)$", self.chat),
            (r"сверни (все|всё)|покажи рабочий стол", self.minimize_all),
            (r"\bсверни\b", self.minimize),
            (r"(закрой|закрыть|убери) (эту |текущую |\S+ )?вкладк", self.tab),
            (r"нов(ую|ая) вкладк|\b(верни|восстанови) (закрыт\w* )?вкладк|(следующ|предыдущ)\w* вкладк", self.tab),
            (r"^(создай|сделай|создать) (?P<what>.*(папк|файл|документ|таблиц).*)$", self.create),
            (r"^(найди|покажи|открой|загугли|погугли|поищи)( мне)?( в интернете| в гугле)? (фото\w*|фотк\w*|"
             r"картинк\w*|изображени\w*|пикч\w*|обои)( (с|со|про|о|об|на тему))? (?P<q>.+)$", self.images),
            (r"^(найди|поищи|загугли|погугли|расскажи|узнай|посмотри)( мне)?( в интернете| в гугле| в сети)? "
             r"(информаци\w*|инфу|инфо|что-нибудь|что нибудь|всё|все|сведения|данные|статью)( (о|об|про|по))? "
             r"(?P<q>.+)$", self.info),
            # --- YouTube и видео (первое/трендовое/любое видео, конкретный ролик/клип/песня) ---
            (r"(?i)^(открой|запусти|включи|найди|поищи|покажи|поставь|вруби|врубай)?\s*"
             r"(мне\s+)?"
             r"((на|в)\s+(ютуб\w*|youtube)\s+)?"
             r"(?P<ord>перв\w*|втор\w*|трет\w*|четверт\w*|четвёрт\w*|пят\w*|лучш\w*|топ\w*|свеж\w*|нов\w*|случайн\w*|люб\w*|како\w*-нибудь)\s+"
             r"(?P<kind>видео\w*|видос\w*|ролик\w*|клип\w*|песн\w*|трек\w*|музык\w*)"
             r"(\s+(на|в)\s+(главн\w*|главной страниц\w*|тренд\w*|рекомендац\w*|ютуб\w*|youtube))?"
             r"(\s+(с|со|про|о|об|где|на тему)\s+(?P<q>.+))?$", self.video),
            (r"(?i)^(?P<ord>перв\w*|втор\w*|трет\w*|лучш\w*|топ\w*)\s+"
             r"(?P<kind>видео\w*|видос\w*|ролик\w*|клип\w*|песн\w*|трек\w*|музык\w*)"
             r"(\s+(на|в)\s+(главн\w*|главной страниц\w*|тренд\w*|ютуб\w*|youtube))?$", self.video),
            (r"^(открой|запусти|включи|найди|поищи|покажи|поставь|вруби|врубай|ищи)( мне)?\s+"
             r"((на|в)\s+)?(ютуб\w*|youtube)"
             r"(\s+(с|со))?"
             r"(\s+(видео\w*|видос\w*|ролик\w*|клип\w*|песн\w*|трек\w*|музык\w*))?"
             r"(\s+(и|давай)?\s*(найди|включи|покажи|поставь|запусти|вруби))?"
             r"(\s+(с|со|про|о|об|где|на тему))?"
             r"\s+(?P<q>.+)$", self.video),
            (r"^(открой|включи|покажи|найди|запусти|поставь|врубай|вруби|поищи)( мне)?\s+"
             r"(?P<q>.+?)\s+(на|в)\s+(ютуб\w*|youtube)$", self.video),
            (r"^(открой|включи|покажи|найди|запусти|поставь|врубай|вруби|поищи)( мне)?"
             r"(\s+(какое-нибудь|какой-нибудь|какое нибудь|любое|любой|одно))?"
             r"\s+(?P<kind>видео\w*|видос\w*|ролик\w*|клип\w*|песн\w*|трек\w*|музык\w*)"
             r"(\s+(на|в)\s+(ютуб\w*|youtube))?"
             r"(\s+(с|со|про|о|об|где|на тему))?"
             r"\s+(?P<q>.+)$", self.video),
            (r"^(попроси антигравити|задача для антигравити|антигравити|antigravity)\b\s*(?P<task>.+)?", self.antigravity_task),
            (r"^(создай|сделай|напиши|сгенерируй|отредактируй|измени|почини|удали)\b.*?(файл\w*|папк\w*|скрипт\w*|код|программ\w*|проект\w*|документ\w*|на рабочем столе|на десктопе)", self.antigravity_task),
            (r"^(найди|поищи|загугли|погугли|ищи)( в интернете| в гугле| в google)? (?P<q>.+)$", self.search),
            (r"^(открой|запусти|включи|зайди( на| в)?|перейди( на| в)?|покажи) (?P<t>.+)$", self.open),
            (r"^((сними|снять) (задачу|процесс\w*)|(заверши|завершить|убей|убить|останови|закрой) "
             r"(все )?(процесс\w*|задачу|задачи)|кильни|килльни|грохни|прибей) (?P<t>.+)$", self.kill_process),
            (r"что (сейчас )?(грузит|нагружает|жрет|ест|тормозит)|(какие|какой) процесс\w* (грузят|нагружают|жрут|"
             r"тормозят)|самые (тяжелые|прожорливые) процессы", self.top_processes),
            (r"^(закрой|заверши|выключи|убей) (?P<t>.+)$", self.close),
            (r"который час|сколько времени|сколько сейчас времени|время сейчас", self.time),
            (r"какое (сегодня )?число|какая (сегодня )?дата|какой сегодня день", self.date),
            (r"посмотри на экран|что на экране|взгляни на экран|что на мониторе|что тут открыто|что за ошибка|проанализируй экран|что у меня на экране|посмотри что тут|глянь на экран", self.look_at_screen),
            (r"скриншот|скрин экрана|сделай скрин", self.screenshot),
        ]

    def handle(self, cmd):
        c = norm(cmd)
        cancel_ensure()  # новая команда — старая проверка «заиграло ли видео» больше не нужна
        try:
            from games import game_manager
            game_res = game_manager.match_and_execute(c)
            if game_res and game_res.get("ok"):
                return Reply(game_res.get("reply_text", "Выполнила игровое действие"))
        except Exception as e:
            log.warning("Game mode match error in actions.handle: %s", e)
        if self.pending:
            action, self.pending = self.pending, None
            if re.match(r"^(да|давай|подтверждаю|конечно|ага)\b", c):
                return action()
            if re.match(r"^(нет|не надо|отмена|стоп)\b", c):
                return Reply(line("cancel"))
        if self.stop_background():  # любая новая команда останавливает автопрокрутку
            if re.match(r"^(стоп|хватит|стой|остановись|достаточно|перестань|харэ|все|всё)\b", c):
                return Reply(line("scroll_stop"))
        if self.choice:  # ждём ответ на «какое открыть / закрыть?»
            options, self.choice = self.choice, None
            pick = self.resolve_choice(c, options)
            if pick is not None:
                name, act = options[pick]
                if callable(act):
                    return act()
                started = self.index.launch_best(name, [(1.0, name, act)])
                return Reply(line("launch", t=started) if started else line("app_missing", t=name))
            if re.match(r"^(никак\w*|ни одно|ни то|отмена|не надо|нет|ничего)\b", c):
                return Reply(line("cancel"))
            # ответ не про выбор — значит, это новая команда
        if re.search(r"\b(ютуб\w*|youtube)\b", c) and re.search(r"\b(видео|видос|ролик|клип|песн|трек|музык|найди|включи|покажи|поставь|про|с видео|канал|аккаунт)\b", c):
            r = self.handle_one(c)
            if r is not None:
                return r
        steps = automation.split_chain(c)
        if steps:
            try:
                return self.run_chain(steps)
            except Exception as e:
                log.exception("Цепочка %s", steps)
                return Reply(line("error", e=e))
        return self.handle_one(c)

    @staticmethod
    def resolve_choice(c, options):
        """«второе», «два», «клод», «первую» → номер варианта или None."""
        ords = [(r"перв\w*|один|одну|1", 0), (r"втор\w*|два|две|2", 1), (r"трет\w*|три|3", 2),
                (r"последн\w*", len(options) - 1)]
        for pattern, idx in ords:
            if re.search(rf"(^|\s)({pattern})(\s|$)", c) and idx < len(options):
                return idx
        words = re.sub(r"^(открой|запусти|давай|вот|это|ну)\s+", "", c)
        best, best_i = 0.0, None
        for i, (name, _) in enumerate(options):
            for v in {words, translit(words)}:
                s = 1.0 if v and v in name else difflib.SequenceMatcher(None, v, name).ratio()
                sk = AppIndex._skeleton(v)
                if len(sk) >= 3 and sk == AppIndex._skeleton(name.split()[0]):
                    s = max(s, 0.86)
                if s > best:
                    best, best_i = s, i
        return best_i if best >= 0.6 else None

    def handle_one(self, c):
        for pattern, fn in self.routes:
            m = re.search(pattern, c)
            if m:
                try:
                    r = fn(c, m)
                except Exception as e:
                    log.exception("Команда %s", c)
                    return Reply(line("error", e=e))
                if r:
                    return r
        return None

    def open_url(self, url):
        """Безопасное открытие URL в браузере с защитой от дублирующих срабатываний."""
        if not url:
            return
        now = time.time()
        norm_url = str(url).strip()
        last_url = getattr(self, "_last_opened_url", None)
        last_time = getattr(self, "_last_opened_time", 0.0)
        if last_url == norm_url and (now - last_time) < 3.5:
            log.info("Дублирующий вызов открытия сайта проигнорирован (debounce %.2fs): %s", now - last_time, norm_url)
            return
        self._last_opened_url = norm_url
        self._last_opened_time = now
        log.info("Открытие сайта в браузере: %s", norm_url)
        try:
            webbrowser.open(norm_url)
        except Exception as e:
            log.error("Ошибка при открытии URL %s: %s", norm_url, e)

    def fallback(self, cmd, force_search=False):
        """Без ИИ: вопрос ищем в Google, остальное — «не знаю команды»."""
        c = norm(cmd)
        if force_search or re.match(r"^(что|кто|как|какой|какая|какое|какие|почему|зачем|сколько|где|когда|куда|"
                     r"откуда|чем|чей|расскажи|объясни|скажи)\b", c):
            self.open_url("https://www.google.com/search?q=" + urllib.parse.quote(cmd))
            return Reply(line("search_q"))
        return Reply(line("unknown"))

    # --- команды ---
    def quit(self, c, m):
        return Reply(line("quit"), "quit")

    def hide(self, c, m):
        return Reply(line("hide"), "hide")

    def wave(self, c, m):
        return Reply(line("wave"), "wave")

    def roam(self, c, m):
        return Reply(line("roam"), "roam")

    # --- прокрутка ---
    def scroll(self, c, m):
        up = bool(re.search(r"\b(вверх|наверх|выше|верх\w*|начал\w*|поднимись|назад)\b", c))
        down = bool(re.search(r"\b(вниз|ниже|низ\w*|конец|дальше|спустись|вперед)\b", c))
        auto = re.search(r"\b(медленно|плавно|автоматически|сама|постепенно|прокручивай|листай сама)\b", c) \
            or re.fullmatch(r"(листай|полистай|прокручивай|скроль|скролль)( медленно| плавно)?", c)
        if not (up or down or auto) or re.search(r"секунд|минут|\bчас|\d[:.]\d\d|полминут", c):
            return None  # «прокрути на 30 секунд вперёд» — это перемотка видео, не страницы
        direction = -1 if up and not down else 1
        self.stop_background()
        if auto:
            fast = bool(re.search(r"быстр", c))
            self._autoscroll_stop = threading.Event()
            threading.Thread(target=self._autoscroll, args=(direction, 0.25 if fast else 0.6,
                                                             self._autoscroll_stop), daemon=True).start()
            return Reply(line("scroll_auto"))
        if re.search(r"\b(самый|самую|самого|до конца|в конец|в начало|до низа|до верха|конец страницы|"
                     r"начало страницы)\b|^(в |на |до )?(низ|верх|низа|верха)$", c):
            automation.scroll(200 * direction, delay=0.008)  # слишком быстро — щелчки колеса теряются
            return Reply(line("scroll_end" if direction > 0 else "scroll_top"))
        n = parse_number(c)
        screen = automation.screen_notches()
        if re.search(r"\b(немного|чуть|чуть-чуть|слегка|капельку)\b|^(еще )?(ниже|выше)$", c):
            notches = 3
        elif n and re.search(r"экран|страниц|раз", c):
            notches = min(n, 20) * screen
        else:
            notches = screen
        automation.scroll(notches * direction)
        return Reply(line("scroll"))

    def _autoscroll(self, direction, interval, stop):
        """Плавная прокрутка в окне, которое было активно в момент команды, — пока не скажут «стоп»."""
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        end = time.time() + 300
        while not stop.is_set() and time.time() < end:
            if ctypes.windll.user32.GetForegroundWindow() != hwnd:
                break  # пользователь ушёл в другое окно — не крутим чужое
            automation.scroll(direction, hwnd=hwnd)
            stop.wait(interval)

    def autoscroll_active(self):
        ev = getattr(self, "_autoscroll_stop", None)
        return bool(ev and not ev.is_set())

    def stop_background(self):
        """Остановить фоновые действия (автопрокрутку). Вызывается и на «стоп» из main."""
        ev = getattr(self, "_autoscroll_stop", None)
        if ev and not ev.is_set():
            ev.set()
            return True
        return False

    # --- мультимедиа ---
    def _youtube_keys(self, keys_list):
        """Нажать горячие клавиши плеера YouTube в его окне (k — пауза, j/l — ±10 с, стрелки — ±5 с)."""
        hwnd = automation.find_window(("youtube",))
        if not hwnd or not automation.focus(hwnd):
            return False
        for keys in keys_list:
            send_keys(keys)
            time.sleep(0.12)
        return True

    def media_pause(self, c, m):
        if browser_playing() and automation.find_window(("youtube",)):
            # YouTube в браузере: системная пауза не всегда доходит — проверяем по звуку и жмём K
            media.control("pause")
            time.sleep(0.8)
            if browser_playing():
                self._youtube_keys([["k"]])
                time.sleep(0.8)
            if not browser_playing():
                self.media_paused = "youtube"
                return Reply(line("media_paused"))
        ok, desc, src = media.control("pause")
        if not ok:
            return Reply(line("media_none"))
        self.media_paused = src  # «продолжи» вернёт именно это, а не другой плеер
        return Reply(line("media_paused"))

    def media_play(self, c, m):
        if self.media_paused == "youtube" or (not self.media_paused and automation.find_window(("youtube",))
                                              and not media.now_playing()):
            def started():
                for _ in range(8):  # у трансляций звук появляется не сразу
                    time.sleep(0.5)
                    if browser_playing():
                        return True
                return False
            for b in BROWSERS:  # сначала системной командой — без переключения окон
                if media.control("play", source=f"{b}.exe")[0]:
                    break
            if started() or (self._youtube_keys([["k"]]) and started()):
                return Reply(line("media_play"))
            if self.media_paused == "youtube":  # не включаем вместо YouTube какой-то другой плеер
                return Reply(line("media_play_fail"))
        ok, desc, src = media.control("play", source=self.media_paused)
        if not ok:
            return Reply(line("media_none"))
        return Reply(line("media_play"))

    def media_next(self, c, m):
        ok, desc, _ = media.control("next")
        if not ok:
            return Reply(line("media_none"))
        time.sleep(0.8)  # даём плееру переключиться, чтобы назвать новый трек
        info = media.now_playing()
        return Reply(line("media_next", t=info[0]) if info and info[0] else line("done"))

    def media_prev(self, c, m):
        ok, desc, _ = media.control("prev")
        return Reply(line("done") if ok else line("media_none"))

    def media_info(self, c, m):
        info = media.now_playing()
        if not info or not info[0]:
            return Reply(line("media_none"))
        return Reply(line("media_info", t=info[0]))

    def media_seek(self, c, m):
        back = re.search(r"\bназад\b|\bотмотай|\bверни|\bвернись", c)
        fwd = re.search(r"\bвперед|\bпромотай|\bпропусти|\bскипни|\bмотни", c)
        text = re.sub(r"^(поставь|включи|начни|запусти|давай|играй|воспроизведи|перемотай|перемотать|промотай|"
                      r"мотни|отмотай|прокрути|верни\w*|вернись|пропусти|скипни|перемотка)\s+", "", c)
        text = re.sub(r"\b(вперед|назад|на|с|со|в|к|видео|музык\w*|трек|песн\w*|ролик|момент\w*|отметк\w*|"
                      r"тайминг)\b", " ", text)
        secs = media.parse_time(text)
        groups = media.number_groups(text)
        to_start = re.search(r"начал|сначала|заново", c)
        if to_start:
            back = fwd = None  # «верни сначала» — это не «назад», а в самое начало
        absolute = to_start or not (back or fwd) and (
            re.match(r"^(поставь|включи|начни|запусти|давай|играй|воспроизведи)", c)
            or re.search(r"\d[:.]\d\d|момент|отметк|тайминг|позици|\bс (\S+ )?\S+ (минут|секунд|час)", c)
            or len(groups) >= 2
            or (groups and groups[0] >= 100 and not re.search(r"секунд|минут|час", c)))  # «на 314» = 3:14
        if secs is None:
            if not (back or fwd):
                return None
            secs = 10  # «перемотай вперёд» без числа — на 10 секунд
        delta = None if absolute else (-secs if back else secs)
        yt = automation.find_window(("youtube",))
        np = media.now_playing()
        if yt and (browser_playing() or not np or any(b in (np[1] or "").lower() for b in BROWSERS)):
            # YouTube в браузере: Firefox не даёт перематывать через систему — клавиши плеера или ссылка с &t=
            if absolute:
                if media.youtube_url_seek(secs):
                    threading.Thread(target=ensure_playing, args=(5.0,), daemon=True).start()
                    return Reply(line("media_seek", t=media.fmt(secs)))
                return Reply(line("media_seek_fail"))
            n10, rest = divmod(int(abs(delta)), 10)
            keys = [["l" if delta > 0 else "j"]] * n10 + [["right" if delta > 0 else "left"]] * round(rest / 5)
            if self._youtube_keys(keys or [["right" if delta > 0 else "left"]]):
                return Reply(line("media_skip", t=media.fmt(abs(delta)), d="вперёд" if delta > 0 else "назад"))
            return Reply(line("media_seek_fail"))
        ok, target, src = media.seek(seconds=secs) if absolute else media.seek(delta=delta)
        if target is None:
            return Reply(line("media_none"))
        return Reply(line("media_seek", t=media.fmt(target)) if ok else line("media_seek_fail"))

    # --- печать и цепочки ---
    def direct_send(self, c, m):
        """«напиши в тг лехе привет» — открывает чат и отправляет сообщение."""
        name = m.group("name").strip()
        text = m.group("text").strip()
        text = re.sub(r"^[:,-]\s*", "", text).strip()
        chat_rep = self.chat(c, re.match(r"(?P<name>.+)", name))
        if chat_rep and chat_rep.action == "fail":
            return chat_rep
        time.sleep(0.5)
        if automation.find_window(("telegram",)):
            automation.wait_and_focus(("telegram",), timeout=3)
            time.sleep(0.15)
        automation.input_text(text)
        time.sleep(0.2)
        send_keys(["enter"])
        return Reply(f"Отправила сообщение в Telegram для {name.capitalize()}: «{text}»")

    def yandex_music_playlist(self, c, m):
        """Открытие плейлистов в Яндекс Музыке: «открой плейлист мне понравилось и включи первый трек»."""
        pl = (m.groupdict().get("pl") or "").strip().lower()
        should_play = bool(m.groupdict().get("play") or "включи" in c.lower() or "поставь" in c.lower() or "запусти" in c.lower())

        pl = re.sub(r"^(плейлист|альбом|сборник)\s+", "", pl).strip()
        pl = re.sub(r"\s+(в|на)\s+(яндекс\s*музык\w*|yandex\s*music)$", "", pl).strip()
        pl = pl.strip("\"'«» ")

        is_favorite = any(w in pl for w in ("мне понравилось", "понравилось", "понравивш", "любим", "моя музык", "мои трек"))

        if is_favorite or not pl:
            url = "https://music.yandex.ru/collection/favorite"
            display_name = "Мне понравилось"
        elif "дня" in pl or "плейлист дня" in pl:
            url = "https://music.yandex.ru/users/yamusic-daily/playlists/1"
            display_name = "Плейлист дня"
        elif "дежавю" in pl:
            url = "https://music.yandex.ru/users/yamusic-daily/playlists/2"
            display_name = "Дежавю"
        elif "премьера" in pl:
            url = "https://music.yandex.ru/users/yamusic-daily/playlists/3"
            display_name = "Премьера"
        elif "чарт" in pl:
            url = "https://music.yandex.ru/chart"
            display_name = "Чарт"
        else:
            url = f"https://music.yandex.ru/search?text={urllib.parse.quote(pl)}&type=playlists"
            display_name = pl.capitalize()

        webbrowser.open(url)

        if should_play:
            def auto_play():
                time.sleep(3.2)
                media.control("play")
                time.sleep(0.3)
                send_keys(["space"])
            threading.Thread(target=auto_play, daemon=True).start()
            return Reply(f"Открыла плейлист «{display_name}» в Яндекс Музыке и включила воспроизведение!")

        return Reply(f"Открыла плейлист «{display_name}» в Яндекс Музыке.")

    def yandex_music_play(self, c, m):
        """«включи яндекс музыку», «поставь яндекс музыку», «запусти яндекс музыку»."""
        pl = (m.groupdict().get("pl") or "").strip()
        if pl and "плейлист" in pl.lower():
            return self.yandex_music_playlist(c, m)

        # 1. Приоритет: открываем десктопное приложение Яндекс Музыки
        ym_target = self.apps.get("яндекс музыка") or self.apps.get("яндекс музыку") or self.apps.get("yandex music")
        if not ym_target:
            found = self.index.find("яндекс музыка", self.aliases)
            if found:
                ym_target = found[1]

        if ym_target:
            self._run(ym_target)
            def auto_play_app():
                time.sleep(2.5)
                media.control("play")
            threading.Thread(target=auto_play_app, daemon=True).start()
            return Reply("Запустила приложение Яндекс Музыка и включила воспроизведение!")

        # 2. Если десктопное приложение не установлено — открываем браузер
        webbrowser.open("https://music.yandex.ru/collection/favorite")
        def auto_play_web():
            time.sleep(3.2)
            media.control("play")
            time.sleep(0.3)
            send_keys(["space"])
        threading.Thread(target=auto_play_web, daemon=True).start()
        return Reply("Открыла Яндекс Музыку в браузере и включила воспроизведение!")

    def game_mode_cmd(self, c, m):
        """Управление игровым режимом и макросами."""
        from games import game_manager
        c_low = c.lower()
        if any(w in c_low for w in ("выключи", "отключи", "выйди")):
            game_manager.config["auto_detect"] = False
            game_manager.config["active_game"] = None
            game_manager.save()
            return Reply("Игровой режим отключен.")

        if any(w in c_low for w in ("какие бинды", "список биндов", "бинды", "макросы", "кнопки")):
            gid, gdata = game_manager.get_current_game()
            if not gid:
                return Reply("Игровой режим не активен. Запустите игру (например War Thunder) или включите режим командой «игровой режим War Thunder».")
            b_list = [f"• {phrase} -> {' + '.join(keys).upper()}" for phrase, keys in list(gdata.get("bindings", {}).items())[:12]]
            return Reply(f"Бинды для {gdata.get('name', gid)}:\n" + "\n".join(b_list))

        # Включение режима
        game = m.groupdict().get("game") if hasattr(m, "groupdict") else None
        target_gid = "war_thunder"
        if game and "war" in game.lower():
            target_gid = "war_thunder"
        game_manager.config["auto_detect"] = True
        game_manager.config["active_game"] = target_gid
        game_manager.save()
        gdata = game_manager.config["games"].get(target_gid, {})
        return Reply(f"Игровой режим активирован: {gdata.get('name', target_gid)}. Голосовые макросы (ЛТЦ, закрылки, шасси и др.) готовы!")

    def game_action_cmd(self, c, m=None):
        """Прямой вызов игрового действия / макроса (ЛТЦ, ловушки, закрылки и т.д.)."""
        from games import game_manager
        res = game_manager.match_and_execute(c)
        if res and res.get("ok"):
            return Reply(res.get("reply_text", "Выполнила игровое действие"))
        return None

    def type_cmd(self, c, m):
        """«напиши привет», «напиши ему привет» — печатает в активное окно и жмёт Enter (в чате это отправка)."""
        parsed = automation.parse_type(c)
        if not parsed:
            return None  # «напиши стих» — это просьба к нейросети, а не печать
        text, send = parsed
        title = automation.foreground_title().lower()
        proc = automation.foreground_process()
        recent_yt = time.time() - self.youtube_opened_at < 120
        recent_tg = time.time() - self.telegram_opened_at < 180

        if ("youtube" in title or (recent_yt and automation.find_window(("youtube",)))) and proc != "telegram.exe" and not recent_tg:
            # на YouTube «напиши X» = поиск X (печатать в саму страницу бессмысленно)
            if "youtube" not in title and not automation.wait_and_focus(("youtube",), timeout=4):
                return Reply(line("focus_fail"))
            youtube_search_in_tab(text)
            return Reply(line("yt", q=text))

        # Если активно или недавно использовалось окно Telegram, либо фраза содержит адресацию человеку
        has_tg_target = any(w in c.lower().split() for w in ("ему", "ей", "им", "чат", "тг", "телеграм", "контакт"))
        if proc == "telegram.exe" or (recent_tg or has_tg_target) and automation.find_window(("telegram",)):
            if proc != "telegram.exe":
                automation.wait_and_focus(("telegram",), timeout=4)
            time.sleep(0.15)

        if send is None:
            send = self.cfg.get("type_press_enter", True)
        automation.input_text(text)
        if send:
            time.sleep(0.15)
            send_keys(["enter"])
        return Reply(line("sent" if send else "typed", t=text))

    def search_field(self, c, m):
        automation.focus_search(automation.foreground_title())
        return Reply(line("search_ready"))

    def chat(self, c, m):
        """«первый чат», «чат мама», «открой в тг лёха» — открывает чат в Telegram (запускает его, если надо)."""
        if not automation.find_window(("telegram",)):
            found = self.index.find("телеграм", {"телеграм": "telegram"}) if self.index.ready.wait(8) else None
            if not found:
                tg_path = self.apps.get("telegram") or self.apps.get("телеграм")
                if tg_path and os.path.exists(tg_path):
                    self._run(tg_path)
                else:
                    return Reply(line("app_missing", t="Telegram"), "fail")
            else:
                self.index.launch(found[1])
            time.sleep(1.0)
        index = automation.ORDINALS.get(m.groupdict().get("ord") or "", None)
        raw_name = (m.groupdict().get("name") or "").strip() or None
        name = raw_name
        if name:
            name = re.sub(r"^(с|со|к|ко|контакт\w*|чат\w*|chat|диалог\w*|переписк\w*|с контактом|к контакту)\s+", "", name, flags=re.IGNORECASE).strip()
            name = re.sub(r"\s+(в|на)\s+(тг|телеграм\w*|telegram|телег\w*)$", "", name, flags=re.IGNORECASE).strip()
            name = re.sub(r"^(в|на)\s+(тг|телеграм\w*|telegram|телег\w*)\s+", "", name, flags=re.IGNORECASE).strip()
            raw_name = name
            search_name = stem_name(name)
        else:
            search_name = None
        opened = automation.telegram_open_chat(index=index or (None if search_name else 1), name=search_name)
        if not opened and search_name and raw_name and search_name.lower() != raw_name.lower():
            opened = automation.telegram_open_chat(name=raw_name)
        if not opened:
            # чат не открылся — дальше по цепочке ничего не печатаем, чтобы не написать не туда
            return Reply(line("chat_not_found", t=raw_name or f"номер {index or 1}"), "fail")
        self.telegram_opened_at = time.time()
        self.last_chat_target = raw_name or f"чат номер {index or 1}"
        display_name = raw_name.capitalize() if raw_name else f"чат номер {index or 1}"
        return Reply(line("chat_open", t=display_name))

    def run_chain(self, steps):
        """Выполняет шаги по очереди, держа в уме, в каком окне мы сейчас (Telegram, YouTube, браузер…)."""
        log.info("Цепочка: %s", steps)
        context = None   # ключевые слова заголовка окна, с которым работаем
        kind = None      # telegram / youtube / browser / None
        said = []
        in_search = False  # курсор уже стоит в поле поиска
        for step in steps:
            s = norm(step)
            typed = automation.parse_type(s)
            if typed:
                text, send = typed
                if context and not automation.wait_and_focus(context, timeout=6):
                    # не смогли переключиться — ничего не печатаем, чтобы не написать в чужое окно
                    return Reply(" ".join(said + [line("focus_fail")]))
                if kind == "youtube":
                    youtube_search_in_tab(text)
                    said.append(line("yt", q=text))
                    continue
                if kind in ("youtube", "browser"):
                    # на сайте «напиши X» = поиск X: сначала курсор в строку поиска, потом Enter
                    if not in_search:
                        automation.focus_search(automation.foreground_title())
                        time.sleep(0.4)
                    automation.input_text(text)
                    if send is not False:
                        time.sleep(0.1)
                        send_keys(["enter"])
                    said.append(line("web", q=text))
                    continue
                if send is None:
                    send = self.cfg.get("type_press_enter", True)
                automation.input_text(text)
                if send:
                    time.sleep(0.1)
                    send_keys(["enter"])
                said.append(line("sent" if send else "typed", t=text))
                continue
            q = re.match(r"^(найди|поищи)\s+(?P<q>.+)$", s)
            if q and kind in ("youtube", "telegram"):
                if kind == "telegram":  # поиск в Telegram = открыть чат по имени
                    raw = q.group("q").strip()
                    raw = re.sub(r"^(в|на)?\s*(тг|телеграм\w*)\s*", "", raw, flags=re.IGNORECASE).strip()
                    raw = re.sub(r"^(контакт\w*|чат\w*|диалог\w*|с\s+|со\s+|к\s+|ко\s+)\s*", "", raw, flags=re.IGNORECASE).strip()
                    stemmed = stem_name(raw)
                    if not automation.telegram_open_chat(name=stemmed):
                        return Reply(" ".join(said + [line("focus_fail")]))
                    self.telegram_opened_at = time.time()
                    self.last_chat_target = raw
                    said.append(line("chat_open", t=raw.capitalize()))
                    continue
                else:
                    if not automation.wait_and_focus(context, timeout=6):
                        return Reply(" ".join(said + [line("focus_fail")]))
                    youtube_search_in_tab(q.group("q"))
                    said.append(line("yt", q=q.group("q")))
                continue
            if re.match(r"^(нажми на поиск|нажми поиск|поиск|в поиск|перейди в поиск)$", s):
                if context and not automation.wait_and_focus(context, timeout=6):
                    return Reply(" ".join(said + [line("focus_fail")]))
                automation.focus_search(automation.foreground_title())
                time.sleep(0.3)
                in_search = True
                continue
            r = self.handle_one(s)
            if r is None:
                said.append(line("chain_skip", t=step))
                continue
            if r.action in ("fail", "ask"):  # шаг не удался или нужно уточнить — дальше не идём
                return Reply(" ".join(said + [r.text]))
            words = s.split()
            for w in words:
                if w in automation.APP_WINDOWS:
                    context = automation.APP_WINDOWS[w]
                    kind = {"telegram": "telegram", "телеграм": "telegram", "телега": "telegram", "тг": "telegram",
                            "ютуб": "youtube", "youtube": "youtube"}.get(w, "browser" if w == "браузер" else None)
            if re.search(r"\b(чат|диалог|переписк|контакт|тг|телеграм)", s):
                context, kind = ("telegram",), "telegram"
            if context and re.match(r"^(открой|запусти|зайди|перейди)\b", s):
                automation.wait_and_focus(context, timeout=10)
                time.sleep(2.5 if kind in ("youtube", "browser") else 0.4)  # сайту нужно загрузиться
                in_search = False
        return Reply(" ".join(said) if said else line("done"))

    def help(self, c, m):
        return Reply(line("help"))

    def move(self, c, m):
        """Куда переместиться: «в левый нижний угол», «вправо», «в центр», «в другую сторону»."""
        if re.search(r"другую сторону|в другую", c):
            where = "other"
        elif re.search(r"центр|середин", c):
            where = "center"
        else:
            h = "left" if re.search(r"лев|влево", c) else "right" if re.search(r"прав|вправо", c) else ""
            v = "top" if re.search(r"верх|наверх", c) else "bottom" if re.search(r"низ|вниз", c) else ""
            where = "-".join(x for x in (v, h) if x) or "other"
        return Reply(line("move"), "move:" + where)

    def power(self, c, m):
        restart = m.group(1).startswith("перезаг") or m.group(1).startswith("перезап")
        flag = "/r" if restart else "/s"

        def do():
            subprocess.Popen(["shutdown", flag, "/t", "10"], creationflags=NO_WINDOW)
            return Reply(line("power_do", what_noun="перезагрузка" if restart else "выключение"))
        self.pending = do
        verb = "перезагрузить" if restart else "выключить"
        return Reply(line("power_ask", what=verb, what_cap=verb.capitalize()))

    def lock(self, c, m):
        ctypes.windll.user32.LockWorkStation()
        return Reply(line("lock"))

    def volume(self, c, m):
        if re.search(r"(выключи|выключить|отключи|убери|убрать)\w* звук|без звука|замуть", c):
            set_mute(True)
            return Reply(line("mute"))
        if re.search(r"(включи|включить|верни)\w* звук", c) and parse_number(c) is None:
            set_mute(False)
            return Reply(line("unmute"))
        n = parse_number(c)
        cur = get_volume()
        if re.search(r"громче|прибав|увелич|повыс|выше", c):
            new = cur + (n or 10)
        elif re.search(r"тише|убав|уменьш|пониз|ниже", c):
            new = cur - (n or 10)
        elif n is not None:
            new = n
        else:
            return Reply(line("vol_now", n=cur))
        new = max(0, min(100, new))
        set_volume(new)
        return Reply(line("vol_set", n=new))

    def brightness(self, c, m):
        try:
            cur = get_brightness()
        except Exception:
            return Reply(line("bright_fail"))
        n = parse_number(c)
        if re.search(r"ярче|прибав|увелич|повыс|выше", c):
            new = cur + (n or 15)
        elif re.search(r"темнее|убав|уменьш|пониз|ниже", c):
            new = cur - (n or 15)
        elif n is not None:
            new = n
        else:
            return Reply(line("bright_now", n=cur))
        new = max(0, min(100, new))
        try:
            set_brightness(new)
        except Exception:
            return Reply(line("bright_reject"))
        return Reply(line("bright_set", n=new))

    def analyze(self, c, m):
        issues, report = analyze_pc()
        folder = os.path.join(self.base_dir, "reports")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"report_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(report)
        os.startfile(path)
        use_ai = self.cfg.get("enable_ai") and self.ai and self.ai.available
        spoken = self.ai.summarize_report(report) if use_ai else None
        if not spoken and self.local:
            spoken = self.local.summarize_report(report)
        if spoken:
            return Reply(spoken)
        if not issues:
            return Reply(line("scan_ok"))
        head = "; ".join(issues[:4])
        return Reply(line("scan_bad", n=len(issues), head=head))

    def _get_known_site(self, t):
        """Возвращает URL известного сайта по названию или близкому совпадению, либо None."""
        qn = norm(t)
        if qn in self.sites:
            return self.sites[qn]
        close = difflib.get_close_matches(qn, list(self.sites), n=1, cutoff=0.82)
        if close:
            return self.sites[close[0]]
        return None

    def search(self, c, m):
        q = m.group("q").strip()
        is_web_explicit = bool(re.search(r"\b(интернет\w*|гугл\w*|google|сети|сеть|браузер\w*)\b", c, re.IGNORECASE))
        # Перенаправляем в поиск Telegram ТОЛЬКО если Telegram сейчас активен на экране И запрос похож на имя человека
        NON_CONTACT_WORDS = re.compile(
            r"\b(видео|видос|ролик|клип|фильм|сериал|песн\w*|трек|музык\w*|ютуб\w*|youtube|сайт\w*|страниц\w*|"
            r"вкладк\w*|как|что|где|почему|зачем|сколько|рецепт\w*|погод\w*)\b",
            re.IGNORECASE
        )
        if not is_web_explicit and automation.foreground_process() == "telegram.exe" and not NON_CONTACT_WORDS.search(q) and len(q.split()) <= 2:
            fake_m = re.match(r"(?P<name>.+)", q)
            if fake_m:
                return self.chat(c, fake_m)
        yt = re.search(r"(на|в) (ютубе|ютуб|youtube)", q)
        if yt:
            q = q.replace(yt.group(0), "").strip()
            webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q))
            return Reply(line("yt", q=q))

        # Если пользователь говорит «найди сайт хабр» или «поищи страницу днс» — сразу открываем нужный сайт
        if re.match(r"^(сайт|сайта|веб-сайт|вебсайт|страниц\w*|страничк\w*)\s+", q, re.IGNORECASE):
            fake_m = re.match(r"(?P<t>.+)", q)
            return self.open(c, fake_m)

        self.open_url("https://www.google.com/search?q=" + urllib.parse.quote(q))
        return Reply(line("web", q=q))

    def open(self, c, m):
        if re.search(r"ютуб|youtube", c):
            self.youtube_opened_at = time.time()  # следующее «напиши …» будет поиском на YouTube
        t = re.sub(r"^(мне |пожалуйста |программу |приложение |клиент |игру )", "", m.group("t"), flags=re.IGNORECASE)
        t = strip_note(t)
        t = re.sub(r" пожалуйста$", "", t).strip()
        if t in ("звук",):
            return None

        # Определение явного режима сайта / веб-страницы:
        # «открой сайт хабр», «зайди на сайт днс», «открой страницу кинокрад»,
        # «открой в браузере стим», «открой стим через браузер»
        site_prefixes = r"^(сайт|сайта|веб-сайт|вебсайт|страниц\w*|страничк\w*|вкладк\w*|браузер\w* (на сайте|на|с)|в браузере|через браузер)\s+"
        site_suffixes = r"\s+(в браузере|через браузер|сайт)$"

        explicit_site_mode = False
        if re.search(site_prefixes, t, re.IGNORECASE):
            t = re.sub(site_prefixes, "", t, flags=re.IGNORECASE).strip()
            explicit_site_mode = True
        elif re.search(site_suffixes, t, re.IGNORECASE):
            t = re.sub(site_suffixes, "", t, flags=re.IGNORECASE).strip()
            explicit_site_mode = True
        elif re.match(r"^(зайди|перейди)\s+(на|в)\s+", c):
            explicit_site_mode = bool(re.search(r"\b(сайт\w*|страниц\w*|вкладк\w*|веб\w*)\b", c))

        # Если режим сайта НЕ явный, проверяем локальные папки
        if not explicit_site_mode:
            explicit = re.match(r"^(папк\w*|каталог\w*|директори\w*)\s+(?P<n>.+)$", t)
            found = find_folder(explicit.group("n") if explicit else t, search=bool(explicit))
            if found:
                os.startfile(found[0])
                return Reply(line("folder_open", t=found[1]))
            if explicit:
                return Reply(line("folder_missing", t=explicit.group("n")))

        # Если указан домен голосом («хабр точка ком», «vk.com», «reddit.com») — сразу открываем в браузере
        spoken_url = parse_spoken_domain(t)
        if spoken_url:
            self.open_url(spoken_url)
            return Reply(line("open", t=t))

        # Явный запрос сайта («открой сайт ...», «в браузере ...»):
        if explicit_site_mode:
            target_url = self._get_known_site(t)
            if not target_url:
                target_url = resolve_site_url(t)
            self.open_url(target_url)
            return Reply(line("open", t=t.title() if t else "сайт"))

        # --- ПРИОРИТЕТ 1: ЛОКАЛЬНЫЕ ДЕСКТОПНЫЕ ПРИЛОЖЕНИЯ ---
        t_norm = norm(t)
        # 1.1 Прямой поиск в self.apps (включая алиасы)
        app_target = self.apps.get(t_norm) or self.apps.get(t)
        if not app_target and t_norm in self.aliases:
            alias_val = self.aliases[t_norm]
            app_target = self.apps.get(alias_val) or self.apps.get(norm(alias_val))

        if app_target:
            self._run(app_target)
            return Reply(line("open", t=t.title()))

        self.index.ready.wait(timeout=8)
        options = self.index.candidates(t, self.aliases)

        # 1.2 Если локальное приложение найдено — запускаем его
        if options and (options[0][0] >= 0.70 or (options[0][0] >= 0.65 and (len(options) == 1 or options[0][0] - options[1][0] >= 0.08))):
            top = options[0]
            close = [o for o in options[1:] if top[0] - o[0] < 0.1]
            if top[0] >= 0.95 or not close:  # одно явно подходит — запускаем
                started = self.index.launch_best(t, [top])
                return Reply(line("launch", t=started) if started else line("app_missing", t=t))
            # несколько похожих — спрашиваем, какое открыть
            self.choice = [(n, tg) for _, n, tg in [top] + close[:2]]
            names = [n.title() for n, _ in self.choice]
            ords = ["первое", "второе", "третье"]
            listed = ", ".join(f"{ords[i]} — {nm}" for i, nm in enumerate(names))
            return Reply(line("choose_app", t=listed), "ask")

        # 1.3 Проверяем, не контакт ли это активного окна Telegram
        NON_CONTACT_WORDS = re.compile(
            r"\b(видео|видос|ролик|клип|фильм|сериал|песн\w*|трек|музык\w*|"
            r"ютуб\w*|youtube|сайт\w*|страниц\w*|вкладк\w*|браузер\w*|гугл\w*|google|"
            r"поиск|окно|папк\w*|файл\w*|документ\w*|таблиц\w*|настройк\w*|игр\w*|камер\w*|погод\w*)\b",
            re.IGNORECASE
        )
        is_name_like = len(t.split()) <= 2 and not NON_CONTACT_WORDS.search(t) and bool(re.fullmatch(r"[а-яa-z\s-]+", t, re.IGNORECASE))
        if is_name_like and automation.foreground_process() == "telegram.exe":
            fake_m = re.match(r"(?P<name>.+)", t)
            if fake_m:
                res = self.chat(c, fake_m)
                if res and res.action != "fail":
                    return res

        # --- ПРИОРИТЕТ 2: ЕСЛИ ДЕСКТОПНОГО ПРИЛОЖЕНИЯ НЕТ ---
        # 2.1 Проверяем, не сайт ли это из списка известных сайтов (self.sites)
        target_url = self._get_known_site(t)
        if target_url:
            self.open_url(target_url)
            return Reply(line("open", t=t.title()))

        # 2.2 Если запрос явно был про запуск программы/игры («запусти ...», «открой игру ...», «открой программу ...») —
        # сообщаем, что такое приложение не найдено на компьютере, вместо открытия случайного сайта!
        is_explicit_app_request = bool(
            re.search(r"^(запусти|вруби|врубай|поиграем в|сыграем в)\b", c)
            or re.search(r"\b(игр\w*|программ\w*|приложени\w*|клиент|лаунчер\w*)\b", m.group(0), re.IGNORECASE)
            or t_norm in self.aliases
        )
        if is_explicit_app_request:
            return Reply(line("app_missing", t=t))

        # 2.3 Если это поисковый/навигационный запрос к известному веб-ресурсу через Google Suggest:
        target_url = resolve_site_url(t)
        if target_url and not target_url.startswith("https://www.google.com/search"):
            self.open_url(target_url)
            return Reply(line("open", t=t.title()))

        # 2.4 Иначе говорим, что приложение не найдено
        return Reply(line("app_missing", t=t))

    def kill_process(self, c, m):
        """«сними задачу steam client helper», «заверши процесс хром принудительно», «кильни дискорд»."""
        t = re.sub(r"^(все |всех )?(процесс\w*|задач\w*)\s+", "", m.group("t").strip())
        return self.close(c, None, target=t, force=bool(re.search(r"принудительн|насильн|жестк|совсем", c)))

    def close(self, c, m, target=None, force=False):
        t = target if target is not None else m.group("t").strip()
        force = force or bool(re.search(r"принудительн|насильн|жестк", c))
        t = re.sub(r"\s+(принудительно|насильно|жестко|совсем)$", "", t).strip()
        if re.fullmatch(r"(окно|это|это окно)", t):
            u = ctypes.windll.user32
            u.keybd_event(0x12, 0, 0, 0)
            u.keybd_event(0x73, 0, 0, 0)
            u.keybd_event(0x73, 0, 2, 0)
            u.keybd_event(0x12, 0, 2, 0)
            return Reply(line("closed_window"))
        q = norm(t)
        variants = {q, translit(q)}
        if q in self.aliases:
            variants.add(norm(self.aliases[q]))
        if q in self.apps:
            variants.add(os.path.splitext(os.path.basename(self.apps[q]))[0].lower())
        if self.index.ready.is_set():  # «закрой клод» → приложение Claude → процесс claude
            for _, app_name, _ in self.index.candidates(q, self.aliases, 2):
                variants.add(app_name.split()[0])
        variants = {v.replace(" ", "") for v in variants if len(v.replace(" ", "")) >= 3}

        words = [w for w in translit(q).split() if len(w) >= 3]  # для сравнения с описанием из диспетчера задач
        me = psutil.Process().username()
        best = {}  # имя процесса → (оценка, [процессы])
        for p in psutil.process_iter(["name", "pid", "username", "exe"]):
            name = (p.info["name"] or "").lower().removesuffix(".exe")
            # только свои программы: системные процессы и службы не трогаем никогда
            if not name or name in PROTECTED_PROCS or p.info["username"] != me or p.pid == os.getpid():
                continue
            score = 0.0
            for v in variants:
                if name == v:
                    s = 1.0
                elif name.startswith(v) or (len(name) >= 4 and v.startswith(name) and len(name) >= len(v) * 0.6):
                    s = 0.9  # «steam» не считается совпадением для «steamclienthelper»
                else:
                    s = difflib.SequenceMatcher(None, v, name).ratio()
                    if len(AppIndex._skeleton(v)) >= 3 and AppIndex._skeleton(v) == AppIndex._skeleton(name):
                        s = max(s, 0.86)
                score = max(score, s)
            if score < 0.95 and words:
                # «steam client helper» → описание «Steam Client WebHelper» у steamwebhelper.exe
                desc = norm(file_description(p.info["exe"]))
                if desc:
                    if desc == " ".join(words):
                        score = 1.0
                    elif len(words) >= 2 and all(any(w in d for d in desc.split()) for w in words):
                        score = max(score, 0.92)
            if score >= 0.85:
                prev = best.get(name, (0.0, []))
                best[name] = (max(prev[0], score), prev[1] + [p])
        if not best:
            return Reply(line("not_running", t=t))
        ranked = sorted(best.items(), key=lambda kv: -kv[1][0])
        top_name, (top_score, _) = ranked[0]
        close = [kv for kv in ranked[1:] if top_score - kv[1][0] < 0.1]
        if top_score < 1.0 and close:  # несколько похожих — спрашиваем, что закрыть
            self.choice = [(n, (lambda procs=procs, n=n: self._kill(n, procs, force))) for n, (_, procs) in
                           [ranked[0]] + close[:2]]
            ords = ["первое", "второе", "третье"]
            listed = ", ".join(f"{ords[i]} — {n}" for i, (n, _) in enumerate(self.choice))
            return Reply(line("choose_close", t=listed), "ask")
        return self._kill(top_name, best[top_name][1], force)

    @staticmethod
    def _kill(name, procs, force=False):
        """Завершить процессы: сначала вежливо (как «Снять задачу»), а если не закрылись за 3 секунды
        или просили принудительно — жёстко."""
        alive = []
        for p in procs:
            try:
                p.kill() if force else p.terminate()
                alive.append(p)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                return Reply(line("kill_denied", t=name))
        _, still = psutil.wait_procs(alive, timeout=3)
        if still:
            for p in still:
                try:
                    p.kill()
                except Exception:
                    pass
            _, still = psutil.wait_procs(still, timeout=2)
        if still:
            return Reply(line("kill_failed", t=name))
        return Reply(line("closed", names=name))

    def top_processes(self, c, m):
        """«Что грузит компьютер» — три процесса, которые больше всего едят процессор и память."""
        procs = list(psutil.process_iter(["name", "memory_info"]))
        for p in procs:
            try:
                p.cpu_percent(None)
            except Exception:
                pass
        time.sleep(1.0)
        cpu, mem = {}, {}
        for p in procs:
            try:
                n = (p.info["name"] or "").removesuffix(".exe")
                if n.lower() in ("system idle process", "idle", ""):
                    continue
                cpu[n] = cpu.get(n, 0) + p.cpu_percent(None) / psutil.cpu_count()
                mem[n] = mem.get(n, 0) + p.info["memory_info"].rss / 2**20
            except Exception:
                pass
        top_cpu = sorted(cpu.items(), key=lambda kv: -kv[1])[:3]
        top_mem = sorted(mem.items(), key=lambda kv: -kv[1])[:3]
        c_txt = ", ".join(f"{n} {v:.0f} процентов" for n, v in top_cpu if v >= 1) or "ничего особо не грузит"
        m_txt = ", ".join(f"{n} {v / 1024:.1f} гигабайта" if v >= 1024 else f"{n} {v:.0f} мегабайт"
                          for n, v in top_mem)
        return Reply(line("top_procs", cpu=c_txt, mem=m_txt))

    def create(self, c, m):
        what = m.group("what")
        place_m = re.search(r"\s(на|в|во)\s+(рабоч\w+ стол\w*|документ\w*|загрузк\w*|фото\w*|изображени\w*|"
                            r"картинк\w*|музык\w*|видео|папк\w* \S+)$", what)
        place, place_name = known_dir("desktop"), "на рабочем столе"
        if place_m:
            spot = find_folder(re.sub(r"^папк\w* ", "", place_m.group(2)), search=True)
            if not spot:
                return Reply(line("folder_missing", t=place_m.group(2)))
            place, place_name = spot[0], f"в папке «{spot[1]}»"
            what = what[:place_m.start()]
        kind = re.match(r"(нов\w+ )?(?P<kind>папк\w*|текстов\w+ файл\w*|текстов\w+ документ\w*|"
                        r"документ\w*|файл\w*|таблиц\w*)( (с )?(именем|названием))?\s*(?P<name>.*)$", what)
        if not kind:
            return None
        k, name = kind.group("kind"), kind.group("name").strip()
        ext = ""
        dot = re.search(r"\s*(точка|dot|\.)\s*(?P<e>[a-zа-я0-9]+)$", name)
        if dot:  # «файл заметки точка txt»
            ext, name = "." + translit(dot.group("e")), name[:dot.start()].strip()
        if k.startswith("папк"):
            default = "Новая папка"
        elif k.startswith("таблиц"):
            default, ext = "Новая таблица", ext or ".xlsx"
        elif k.startswith("документ") and not k.startswith("текст"):
            default, ext = "Новый документ", ext or ".docx"
        else:
            default, ext = "Новый файл", ext or ".txt"
        name = re.sub(r'[<>:"/\\|?*]', "", name).strip() or default
        name = name[:1].upper() + name[1:]
        path = os.path.join(place, name + ext)
        n = 2
        while os.path.exists(path):  # ничего не перезаписываем
            path = os.path.join(place, f"{name} ({n}){ext}")
            n += 1
        if k.startswith("папк"):
            os.makedirs(path)
        else:
            open(path, "x", encoding="utf-8").close()  # пустые .docx/.xlsx Office открывает как новые
        return Reply(line("created", t=os.path.basename(path), where=place_name))

    def images(self, c, m):
        q = m.group("q").strip()
        if re.search(r"\bобои\b", c):
            q = "обои " + q
        webbrowser.open("https://www.google.com/search?tbm=isch&q=" + urllib.parse.quote(q))
        return Reply(line("images", q=q))

    def info(self, c, m):
        """Открывает поиск Google и вслух пересказывает начало статьи из Википедии, если она нашлась."""
        q = m.group("q").strip()
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(q))
        summary = wiki_summary(q)
        if summary:
            return Reply(line("info", t=summary))
        return Reply(line("web", q=q))

    def video(self, c, m):
        q = (m.groupdict().get("q") or "").strip()
        # Очищаем служебные фразы и мусорные предлоги
        q = re.sub(r"^(мне|пожалуйста)\s+", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"\s+пожалуйста$", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"\s+(на|в)\s+(ютуб\w*|youtube)$", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"^(на|в)\s+(ютуб\w*|youtube)\s*", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"^(и|давай)\s+(найди|включи|покажи|поставь|запусти|вруби|открой)\s+", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"^(видео\w*|видос\w*|ролик\w*|клип\w*|песн\w*|трек\w*|музык\w*)\s+", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"^(с|со|про|о|об|где|на тему)\s+", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"\s+(на|в)\s+(ютуб\w*|youtube)$", "", q, flags=re.IGNORECASE).strip()

        # Проверяем, не запрашивается ли первое видео на главной / в трендах / рекомендации
        is_home_or_trending = bool(re.search(
            r"\b(главн\w*|главной страниц\w*|тренд\w*|рекомендац\w*|популярн\w*)\b|"
            r"^(перв\w*|первое|первый|свеж\w*|лучш\w*|топ\w*)(\s+(видео\w*|ролик\w*|клип\w*))?$",
            c, re.IGNORECASE
        ))

        kind = (m.groupdict().get("kind") or "").lower()
        if is_home_or_trending or not q or q in ("на", "в", "с", "со", "про", "о", "об", "первое", "первый", "видео"):
            found = youtube_first("тренды") or youtube_first("популярное")
            if not found:
                webbrowser.open("https://www.youtube.com")
                return Reply(line("open", t="YouTube"))
            vid, title = found
            webbrowser.open(f"https://www.youtube.com/watch?v={vid}")
            threading.Thread(target=ensure_playing, daemon=True).start()
            self.youtube_opened_at = time.time()
            title = re.sub(r"\s+", " ", title).strip()
            if len(title) > 70:
                title = title[:67].rsplit(" ", 1)[0] + "…"
            return Reply(line("video", t=title) if title else "Включаю первое видео на YouTube.")

        search = q
        if re.match(r"песн|трек", kind) and not any(w in q.lower() for w in ("песн", "трек", "клип", "музык")):
            search = q + " песня"

        found = youtube_first(search)
        if not found:  # не вышло достать первое видео напрямую — открываем страницу поиска YouTube
            webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(search))
            return Reply(line("yt", q=q))
        vid, title = found
        webbrowser.open(f"https://www.youtube.com/watch?v={vid}")
        threading.Thread(target=ensure_playing, daemon=True).start()
        self.youtube_opened_at = time.time()
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) > 70:
            title = title[:67].rsplit(" ", 1)[0] + "…"
        return Reply(line("video", t=title) if title else line("video_untitled"))

    def youtube_channel(self, c, m):
        q = m.group("q").strip()
        q = re.sub(r"^(мне|пожалуйста)\s+", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"\s+пожалуйста$", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"\s+(на|в)\s+(ютуб\w*|youtube)$", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"^(на|в)\s+(ютуб\w*|youtube)\s*", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"^(канал\w*|аккаунт\w*|блогер\w*|автор\w*)\s+", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"\s+(канал\w*|аккаунт\w*)$", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"^(с|со|про|о|об|под названием)\s+", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"\s+(на|в)\s+(ютуб\w*|youtube)$", "", q, flags=re.IGNORECASE).strip()

        if not q:
            webbrowser.open("https://www.youtube.com")
            return Reply(line("open", t="YouTube"))

        found = youtube_channel_search(q)
        if found:
            url, title = found
            webbrowser.open(url)
            channel_name = title or q
            return Reply(f"Открываю канал {channel_name} на YouTube.")

        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}&sp=EgIQAg%253D%253D"
        webbrowser.open(search_url)
        return Reply(f"Ищу канал {q} на YouTube.")

    def tab(self, c, m):
        if re.search(r"нов(ую|ая) вкладк", c):
            send_keys(["ctrl", "t"])
            return Reply(line("tab_new"))
        if re.search(r"\b(верни|восстанови)", c):
            send_keys(["ctrl", "shift", "t"])
            return Reply(line("tab_restore"))
        if re.search(r"следующ", c):
            send_keys(["ctrl", "tab"])
            return Reply(line("done"))
        if re.search(r"предыдущ", c):
            send_keys(["ctrl", "shift", "tab"])
            return Reply(line("done"))
        n = max(1, min(20, parse_number(c) or 1))
        for _ in range(n):
            send_keys(["ctrl", "w"])
            time.sleep(0.12)
        return Reply(line("tab_closed", n=n) if n > 1 else line("tab_closed_one"))

    def minimize_all(self, c, m):
        send_keys(["win", "d"])
        return Reply(line("done"))

    def minimize(self, c, m):
        """«Сверни окно / вкладку / браузер» — сворачивает активное окно."""
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if hwnd:
            u.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        return Reply(line("done"))

    def press(self, c, m):
        text = m.group("k")
        times = 1
        rep = re.search(r"\s(\S+) раз\w*$", text)
        if rep and parse_number(rep.group(1)):
            times, text = min(30, parse_number(rep.group(1))), text[:rep.start()]
        keys, unknown = parse_keys(text)
        if unknown:
            return Reply(line("key_unknown", t=unknown))
        if not keys:
            return None
        for _ in range(times):
            send_keys(keys)
            time.sleep(0.08)
        return Reply(line("pressed", t=" + ".join(k.upper() if len(k) == 1 else k.capitalize() for k in keys)))

    def time(self, c, m):
        return Reply(line("time", t=f"{datetime.datetime.now():%H:%M}"))

    def date(self, c, m):
        months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
                  "сентября", "октября", "ноября", "декабря"]
        days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        d = datetime.date.today()
        return Reply(line("date", t=f"{days[d.weekday()]}, {d.day} {months[d.month - 1]}"))

    def screenshot(self, c, m):
        from PIL import ImageGrab
        folder = os.path.join(os.path.expanduser("~"), "Pictures", "Capri")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"screen_{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
        ImageGrab.grab(all_screens=True).save(path)
        return Reply(line("screenshot"))

    def look_at_screen(self, c, m):
        if self.local:
            import bridge_client
            bridge_client.send_say_async("Сканирую экран...", face="look", action="curious", hold=3000)
            answer = self.local.ask_screen(c)
            return Reply(answer, action="curious")
        return Reply("Локальная нейросеть сейчас недоступна.")

    def antigravity_task(self, c, m):
        import bridge_client
        import antigravity_bridge
        task_text = m.group("task") if "task" in m.groupdict() and m.group("task") else c
        task_text = task_text.strip()
        bridge_client.send_say_async("Подключаю Antigravity, выполняю задачу...", face="look", action="curious", hold=5000)
        answer = antigravity_bridge.run_task(task_text)
        return Reply(answer, action="wave")

    def _run(self, target):
        if target.startswith(("http://", "https://")):
            self.open_url(target)
            return
        try:
            os.startfile(target)
        except OSError:
            subprocess.Popen(target, shell=True, creationflags=NO_WINDOW)
