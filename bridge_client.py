"""Клиент моста между Python-бэкэндом (слушатель, автоматизация, поиск)
и визуальной оболочкой Electron (анимации, шейдеры, киберпанк-панель)."""
import json
import logging
import threading
import time
import urllib.request

log = logging.getLogger("capri")
BRIDGE_URL = "http://127.0.0.1:47823"


def _post(path, data, timeout=0.8, retries=5, retry_delay=0.5):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{BRIDGE_URL}{path}",
                data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception as e:
            if attempt < retries:
                time.sleep(retry_delay)
                continue
            # Если Electron ещё не запущен или закрыт — не падаем
            log.debug("Bridge %s error: %s", path, e)
            return False
    return False


def get_screen_snap(timeout=3.0):
    """Запрашивает у Electron нативный скриншот активного экрана (base64 JPEG)."""
    try:
        req = urllib.request.Request(f"{BRIDGE_URL}/capri/snap")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    return data.get("image")
    except Exception as e:
        log.debug("Bridge snap error: %s", e)
    return None


def send_say_async(text, face=None, action=None, hold=4500):
    """Асинхронно отправляет текст для отображения в визуальной панели Electron."""
    if not text:
        return
    # Автоподбор каноничного лица и действия, если не заданы вручную
    if not face or not action:
        auto_face, auto_action = map_face_and_action(text, action)
        face = face or auto_face
        action = action or auto_action

    payload = {
        "text": text,
        "face": face,
        "action": action,
        "hold": hold
    }
    threading.Thread(target=_post, args=("/capri/say", payload), daemon=True).start()


def send_status_async(state, text=None):
    """Отправляет статус (listening / thinking / idle) в Electron."""
    payload = {"state": state, "text": text}
    threading.Thread(target=_post, args=("/capri/status", payload), daemon=True).start()


def map_face_and_action(text, current_action=None):
    """Подбирает каноничное лицо (face-*) и жест персонажа по тексту и типу ответа."""
    if current_action == "curious":
        return "look", "curious"

    t = text.lower()
    
    # 0. Внимание к экрану / анализ изображения / Antigravity задачи
    if any(w in t for w in ("экран", "монитор", "вижу", "открыто", "смотрю", "сканирую", "антигравити", "antigravity")):
        return "look", "curious"

    # 1. Победные / радостные действия: открыт сайт, запущена программа, создан файл
    if any(w in t for w in ("открываю", "запускаю", "легко", "готово", "сделано", "сейчас будет", "ныряю", "создан", "создала", "сохранил", "написал")):
        return "laugh", "victory"

    # 2. Ошибки / не нашла / отказ: недовольный взгляд в сторону, отскок
    if any(w in t for w in ("не нашла", "не знаю", "ошибка", "не могу", "не получилось", "отказал")):
        return "aside", "flinch"

    # 3. Вопросы / выбор из нескольких вариантов / удивление
    if any(w in t for w in ("какое", "что", "?", "варианты", "выбери")):
        return "wide", "curious"

    # 4. Музыка, громкость, звук
    if any(w in t for w in ("звук", "громкость", "пауза", "играет", "трек", "песня")):
        return "smug", "talk"

    # 5. Telegram / сообщения
    if any(w in t for w in ("отправила", "напечатала", "чат")):
        return "smug", "point"

    return "smug", "talk"
