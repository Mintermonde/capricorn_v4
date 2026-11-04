"""Менеджер игровых режимов и макросов DirectInput (War Thunder и другие игры)."""
import json
import logging
import os
import re
import time
import direct_input

log = logging.getLogger("capri")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAMES_JSON_PATH = os.path.join(BASE_DIR, "games.json")

NUM_WORDS = {
    "один": 1, "одну": 1, "одно": 1, "раз": 1, "одиночный": 1,
    "два": 2, "две": 2, "пару": 2, "пара": 2, "парочку": 2, "дважды": 2,
    "три": 3, "трое": 3, "трижды": 3,
    "четыре": 4, "четверку": 4, "четверо": 4,
    "пять": 5, "пятерку": 5, "пятеро": 5,
    "шесть": 6, "шестерку": 6, "шестеро": 6,
    "семь": 7, "семерку": 7,
    "восемь": 8, "восьмерку": 8,
    "девять": 9, "девятку": 9,
    "десять": 10, "десяток": 10,
    "двенадцать": 12,
    "пятнадцать": 15,
    "двадцать": 20,
    "тридцать": 30
}

FLARE_TRIGGERS = (
    "лтц", "ловушк", "от отца", "отцы", "от отса", "отце",
    "элтэцэ", "эл тэ цэ", "л т ц", "лт цэ", "л тэ цэ", "илтэцэ",
    "флер", "флейр", "флэр", "фларес", "дипол", "flare"
)

GAME_PHRASE_TRIGGERS = (
    "лтц", "ловушк", "от отца", "отцы", "флер", "флейр", "дипол",
    "закрылк", "шасси", "шоссе", "радар", "захват", "запад цели", "парл",
    "рлс", "олс", "ракет", "бомб", "тормоз", "урвв", "вооружен"
)


def extract_count(text):
    """Извлекает количество повторений из команды (цифрой или словом)."""
    m = re.search(r"\b(\d+)\b", text)
    if m:
        try:
            return max(1, min(int(m.group(1)), 30))
        except ValueError:
            pass
    for w in text.split():
        if w in NUM_WORDS:
            return NUM_WORDS[w]
    return 1


def format_keys_str(keys):
    """Красиво форматирует клавиши, комбинации или цепочки действий."""
    if isinstance(keys, (list, tuple)):
        if any(isinstance(x, (list, tuple, int, float, dict)) for x in keys):
            parts = []
            for item in keys:
                if isinstance(item, (int, float)):
                    parts.append(f"{int(item * 1000)}ms")
                elif isinstance(item, dict) and "delay" in item:
                    parts.append(f"{int(item['delay'] * 1000)}ms")
                elif isinstance(item, (list, tuple)):
                    parts.append(" + ".join(str(k).upper() for k in item))
                else:
                    parts.append(str(item).upper())
            return " -> ".join(parts)
        return " + ".join(str(k).upper() for k in keys)
    return str(keys).upper()


class GameModeManager:
    def __init__(self, games_path=GAMES_JSON_PATH):
        self.games_path = games_path
        self._mtime = 0.0
        self.config = {
            "auto_detect": True,
            "active_game": "war_thunder",
            "games": {}
        }
        self.last_detected_game = None
        self.last_switch_time = 0.0
        self.load()

    def load(self):
        try:
            if os.path.exists(self.games_path):
                self._mtime = os.path.getmtime(self.games_path)
                with open(self.games_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                log.info("Games config loaded (%d games registered, active=%s)",
                         len(self.config.get("games", {})), self.config.get("active_game"))
        except Exception as e:
            log.warning("Could not load games.json: %s", e)

    def reload_if_changed(self):
        try:
            if not os.path.exists(self.games_path):
                return
            mtime = os.path.getmtime(self.games_path)
            if mtime > self._mtime:
                self.load()
        except Exception:
            pass

    def save(self):
        try:
            with open(self.games_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            self._mtime = os.path.getmtime(self.games_path)
        except Exception as e:
            log.warning("Could not save games.json: %s", e)

    def get_current_game(self, foreground_proc=None, foreground_title=None):
        """
        Возвращает (game_id, game_data) для активной в данный момент игры.
        Строго проверяет, что игра запущена и (по умолчанию) находится в фокусе.
        """
        self.reload_if_changed()

        if not self.config.get("auto_detect", True):
            manual = self.config.get("active_game")
            if manual and manual in self.config.get("games", {}):
                gdata = self.config["games"][manual]
                # Даже при ручном выборе проверяем, запущен ли процесс
                import automation
                for p in gdata.get("processes", []):
                    clean_p = p.replace(".exe", "")
                    if automation.is_process_running(clean_p):
                        return manual, gdata
            return None, None

        if not foreground_proc:
            try:
                import automation
                foreground_proc = automation.foreground_process()
            except Exception:
                foreground_proc = ""

        if not foreground_title:
            try:
                import automation
                foreground_title = automation.foreground_title()
            except Exception:
                foreground_title = ""

        proc_lower = (foreground_proc or "").lower()
        title_lower = (foreground_title or "").lower()

        # 1. Проверка активного окна на переднем плане (приоритет)
        for gid, gdata in self.config.get("games", {}).items():
            if not gdata.get("enabled", True):
                continue

            procs = [p.lower() for p in gdata.get("processes", [])]
            if proc_lower and any(proc_lower == p or proc_lower.endswith(p) for p in procs):
                return gid, gdata

            patterns = [pat.lower() for pat in gdata.get("window_patterns", [])]
            if patterns and any(pat in title_lower for pat in patterns):
                return gid, gdata

        # 2. Проверка запущенных процессов ТОЛЬКО для игр с режимом focus_mode == "running"
        try:
            import automation
            for gid, gdata in self.config.get("games", {}).items():
                if not gdata.get("enabled", True):
                    continue
                # По умолчанию focus_mode == "foreground", макросы не посылаются в фоновые окна
                if gdata.get("focus_mode") != "running":
                    continue
                for p in gdata.get("processes", []):
                    clean_p = p.replace(".exe", "")
                    if automation.is_process_running(clean_p):
                        return gid, gdata
        except Exception:
            pass

        return None, None

    def match_and_execute(self, text, foreground_proc=None, foreground_title=None):
        """
        Проверяет фразу на соответствие макросам активной игры.
        Возвращает dict с результатом (ok, game_name, phrase, keys, message) или None.
        Строго требует, чтобы игра была запущена и активна!
        """
        clean = text.lower().strip()
        clean = re.sub(r"[,.!?]+", "", clean).strip()

        gid, gdata = self.get_current_game(foreground_proc, foreground_title)

        # Если игра НЕ запущена или окно не в фокусе — макросы НЕ выполняются!
        if not gid or not gdata:
            return None

        # Оповещение при смене игры
        now = time.time()
        if self.last_detected_game != gid and now - self.last_switch_time > 10.0:
            self.last_detected_game = gid
            self.last_switch_time = now
            log.info("Game mode active: %s (%s)", gdata.get("name", gid), gid)

        bindings = gdata.get("bindings", {})

        matched_keys = None
        matched_cmd = clean

        # 1. Прямое совпадение
        if clean in bindings:
            matched_keys = bindings[clean]
            matched_cmd = clean

        # 2. Поиск по фразам из bindings (от длинных к коротким)
        if not matched_keys:
            sorted_phrases = sorted(bindings.items(), key=lambda x: len(x[0]), reverse=True)
            words_count = len(clean.split())
            for phrase, keys in sorted_phrases:
                p_norm = phrase.lower().strip()
                if clean == p_norm:
                    matched_keys = keys
                    matched_cmd = phrase
                    break
                if words_count <= 4:
                    if clean.endswith(f" {p_norm}") or clean.startswith(f"{p_norm} ") or f" {p_norm} " in f" {clean} ":
                        matched_keys = keys
                        matched_cmd = phrase
                        break
                else:
                    if len(p_norm.split()) >= 2 and f" {p_norm} " in f" {clean} ":
                        matched_keys = keys
                        matched_cmd = phrase
                        break

        # 3. Интеллектуальный поиск ключевых игровых действий
        if not matched_keys:
            # ЛТЦ / тепловые ловушки (включая все акустические ослышки Vosk)
            if any(w in clean for w in FLARE_TRIGGERS):
                matched_keys = bindings.get("лтц") or bindings.get("ловушки") or bindings.get("от отца") or ["mouse4"]
                matched_cmd = "ЛТЦ"
            # Смена ракет / переключение вооружения (ПАРЛ <-> ИК через Alt + W)
            elif any(w in clean for w in (
                "парл на ик", "ик на парл", "смени ракету", "сменить ракету", "смена ракет",
                "переключи ракету", "переключить ракету", "переключение ракет",
                "следующая ракета", "другая ракета", "переключение основного вооружения", "переключение вооружения"
            )):
                matched_keys = bindings.get("парл на ик") or ["alt", "w"]
                matched_cmd = "смена ракеты"
            # Режим захвата / переключение РЛС-ОЛС + ракета ПАРЛ (Alt + A -> 80ms -> Alt + W)
            elif any(w in clean for w in ("захват", "парл", "рлс-олс", "рлс олс", "за хват", "запад", "захвати")):
                matched_keys = bindings.get("режим захвата") or bindings.get("захват цели") or [["alt", "a"], 0.08, ["alt", "w"]]
                matched_cmd = "режим захвата"
            # Закрылки
            elif "закрылк" in clean:
                matched_keys = bindings.get("закрылки") or ["f"]
                matched_cmd = "закрылки"
            # Шасси
            elif any(w in clean for w in ("шасси", "шоссе")):
                matched_keys = bindings.get("шасси") or ["g"]
                matched_cmd = "шасси"
            # Тормоз
            elif "тормоз" in clean:
                matched_keys = bindings.get("тормоз") or ["h"]
                matched_cmd = "тормоз"
            # Радар
            elif "радар" in clean:
                matched_keys = bindings.get("радар") or ["alt", "r"]
                matched_cmd = "радар"

        if not matched_keys:
            return None

        # Проверка на выпуск серии ЛТЦ
        is_flare = any(w in clean for w in FLARE_TRIGGERS)
        flare_count = extract_count(clean) if is_flare else 1

        # Выполняем DirectInput ввод мгновенно без задержек и переключения фокуса
        keys_str = format_keys_str(matched_keys)
        game_name = gdata.get("name", gid)
        action_name = matched_cmd.upper()

        if is_flare:
            if flare_count > 1:
                ok = direct_input.press_repeat(matched_keys, count=flare_count, interval=0.09)
                action_name = f"ВЫПУСТИЛА {flare_count} ЛТЦ"
                keys_str = f"MOUSE4 x{flare_count}"
            else:
                ok = direct_input.press_combo(matched_keys)
                action_name = "ВЫПУСТИЛА ЛТЦ"
                keys_str = "MOUSE4"
        else:
            ok = direct_input.press_sequence(matched_keys)
            if any(w in clean for w in ("захват", "парл", "за хват", "запад", "захвати")) and not any(w in clean for w in ("парл на ик", "ик на парл", "смени ракету", "смена ракет", "переключи ракету")):
                action_name = "РЕЖИМ ЗАХВАТА"
            elif any(w in clean for w in ("парл на ик", "ик на парл", "ракет", "вооружен")):
                action_name = "СМЕНА РАКЕТЫ (ПАРЛ <-> ИК)"

        return {
            "ok": ok,
            "game_id": gid,
            "game_name": game_name,
            "command": matched_cmd,
            "keys": matched_keys,
            "keys_str": keys_str,
            "reply_text": f"[{game_name}] {action_name} ({keys_str})"
        }


game_manager = GameModeManager()
