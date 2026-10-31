"""Мост между ассистентом Капри и средой Antigravity Agent.
Позволяет Капри делегировать задачи (создание файлов, написание кода, запуск команд)
нативному агенту Antigravity с полным набором инструментов."""
import asyncio
import json
import logging
import os
import re

log = logging.getLogger("capri")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def _get_api_key():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
    except Exception as e:
        log.warning("Could not load api key from config: %s", e)
    return os.environ.get("GEMINI_API_KEY", "")


def _get_workspaces():
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    user_home = os.path.expanduser("~")
    workspaces = [desktop, user_home, "C:\\Capri"]
    return [w for w in workspaces if os.path.exists(w)]


async def _execute_task_async(task_prompt: str) -> str:
    from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig

    api_key = _get_api_key()
    if not api_key:
        return "Не найден API-ключ Gemini для запуска Antigravity. Проверь gemini_api_key в config.json."

    workspaces = _get_workspaces()
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")

    system_instructions = (
        "Ты Antigravity Agent, умный исполнитель задач в связке с ассистентом Капри. "
        "Пользователь просит тебя выполнить практическую задачу на его компьютере (создать файл, написать скрипт, изменить код и т.д.). "
        f"Рабочий стол пользователя находится по пути: {desktop}. "
        "Используй доступные инструменты (CREATE_FILE, EDIT_FILE, RUN_COMMAND, VIEW_FILE и др.) для реального выполнения задачи. "
        "После выполнения дай краткий, понятный ответ на русском языке (1-2 предложения), объясняя что именно было создано или сделано."
    )

    models_to_try = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.6-flash"]
    last_err = None

    for model_name in models_to_try:
        try:
            cfg = LocalAgentConfig(
                api_key=api_key,
                model=model_name,
                workspaces=workspaces,
                system_instructions=system_instructions,
                capabilities=CapabilitiesConfig()
            )
            async with Agent(cfg) as agent:
                resp = await agent.chat(task_prompt)
                tokens = []
                async for token in resp:
                    tokens.append(token)
                result_text = "".join(tokens).strip()
                if result_text:
                    return result_text
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()
            log.warning("Antigravity agent model %s failed: %s, trying fallback...", model_name, e)
            if "quota" in err_msg or "429" in err_msg:
                continue
            if "timeout" in err_msg or "unavailable" in err_msg or "503" in err_msg:
                continue

    if last_err:
        log.exception("Antigravity task execution failed: %s", last_err)
        err_msg = str(last_err).lower()
        if "quota" in err_msg or "429" in err_msg:
            return "Лимит бесплатных запросов к этой модели исчерпан, попробуй позже или смени ключ."
        return f"Не удалось выполнить задачу через Antigravity: {last_err}"

    return "Antigravity завершил задачу, но не вернул описания."


def run_task(prompt: str) -> str:
    """Синхронная точка входа для вызова из actions.py."""
    try:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(lambda: asyncio.run(_execute_task_async(prompt)))
                return fut.result(timeout=60)
        else:
            return loop.run_until_complete(_execute_task_async(prompt))
    except Exception as e:
        log.exception("Error in run_task: %s", e)
        return f"Произошла ошибка при выполнении в Antigravity: {e}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        task = sys.argv[1]
        out = run_task(task)
        sys.stdout.buffer.write((out + "\n").encode("utf-8"))
    else:
        print("Usage: py -3.14 antigravity_bridge.py <task_prompt>")
