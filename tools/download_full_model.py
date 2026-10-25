"""Загрузка и установка полной русской модели Vosk (vosk-model-ru-0.42, ~1.8 ГБ)."""
import os
import shutil
import sys
import time
import urllib.request
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(BASE, "models")
NAME = "vosk-model-ru-0.42"
ZIP_NAME = f"{NAME}.zip"
URL = f"https://alphacephei.com/vosk/models/{ZIP_NAME}"
TARGET = os.path.join(MODELS, NAME)
ZIP_PATH = os.path.join(MODELS, ZIP_NAME)


def is_ready():
    if not os.path.isdir(TARGET):
        return False
    # Проверяем ключевые файлы модели
    has_am = os.path.isfile(os.path.join(TARGET, "am", "final.mdl"))
    has_conf = os.path.isfile(os.path.join(TARGET, "conf", "model.conf"))
    return has_am or has_conf


def download_with_progress(url, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    temp_dst = dst + ".part"
    downloaded = 0
    headers = {}

    if os.path.exists(temp_dst):
        downloaded = os.path.getsize(temp_dst)
        headers["Range"] = f"bytes={downloaded}-"

    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
    except Exception as e:
        # Если Range не поддерживается, начинаем заново
        downloaded = 0
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=30)

    total_size = int(resp.headers.get("Content-Length", 0)) + downloaded
    mode = "ab" if downloaded > 0 else "wb"

    print(f"[Capri] Скачиваем полную модель ({total_size / 1024 / 1024:.1f} МБ)...")
    last_print = time.time()
    chunk_size = 1024 * 1024  # 1 MB

    with open(temp_dst, mode) as f:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            now = time.time()
            if now - last_print > 0.5:
                pct = (downloaded / total_size * 100) if total_size else 0
                mb_cur = downloaded / 1024 / 1024
                mb_tot = total_size / 1024 / 1024
                print(f"\r  Прогресс: {pct:.1f}% ({mb_cur:.1f} / {mb_tot:.1f} МБ)", end="", flush=True)
                last_print = now

    print(f"\r  Прогресс: 100.0% ({downloaded / 1024 / 1024:.1f} МБ) - Загрузка завершена!   ")
    if os.path.exists(dst):
        os.remove(dst)
    os.rename(temp_dst, dst)


def extract_zip(src, dst_dir):
    print(f"[Capri] Распаковываем модель в {dst_dir}...")
    with zipfile.ZipFile(src, "r") as z:
        total_files = len(z.infolist())
        for idx, file in enumerate(z.infolist()):
            z.extract(file, dst_dir)
            if idx % 100 == 0 or idx == total_files - 1:
                pct = (idx + 1) / total_files * 100
                print(f"\r  Распаковка: {pct:.1f}%", end="", flush=True)
    print("\n[Capri] Распаковка успешно завершена.")


def update_config():
    config_path = os.path.join(BASE, "config.json")
    if os.path.exists(config_path):
        import json
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg["vosk_model"] = f"models/{NAME}"
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            print(f"[Capri] config.json обновлён: vosk_model = models/{NAME}")
        except Exception as e:
            print(f"[Capri] Не удалось обновить config.json: {e}")


def main():
    if is_ready():
        print(f"[Capri] Полная модель {NAME} уже установлена и готова к работе.")
        update_config()
        return 0

    try:
        download_with_progress(URL, ZIP_PATH)
        extract_zip(ZIP_PATH, MODELS)
        if os.path.exists(ZIP_PATH):
            os.remove(ZIP_PATH)

        if not is_ready():
            print("[Capri] Ошибка: модель не прошла проверку целостности после распаковки.")
            return 1

        update_config()
        print("[Capri] Установка полной модели успешно завершена!")
        return 0
    except Exception as e:
        print(f"\n[Capri] Ошибка при установке: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
