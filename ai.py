"""Ответы на вопросы через Gemini API (Google GenAI) или Claude (Anthropic) с веб-поиском для свежих фактов."""
import datetime
import json
import logging
import os
import re
import urllib.error
import urllib.request

from persona import CHARACTER, SPEECH_RULES

log = logging.getLogger("capri")

SYSTEM = f"""{CHARACTER}

{SPEECH_RULES}
Для свежих фактов (погода, новости, курсы, расписания) используй веб-поиск.
Командами ПК (открыть сайт/приложение, громкость, яркость, диагностика) занимается отдельный модуль;
если просят то, чего ты сделать не можешь, скажи, какую команду произнести, например «Капри, открой ютуб»."""


def clean_for_speech(text: str) -> str:
    """Очищает текст от markdown-разметки и ссылок для естественного звучания в Edge TTS."""
    if not text:
        return ""
    # Удаляем блоки кода
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Заменяем [текст](url) на просто текст
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Удаляем чистые url ссылки
    text = re.sub(r"https?://\S+", "", text)
    # Удаляем маркеры списков в начале строк
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+[\.\)]\s+", "", text, flags=re.MULTILINE)
    # Удаляем markdown-символы: жирный, курсив, заголовки, тильды, пайпы, бэктики
    text = re.sub(r"[*_`#~|]", "", text)
    # Сжимаем лишние пробелы и переносы строк
    text = re.sub(r"\s+", " ", text).strip()
    return text


class AI:
    def __init__(self, cfg):
        self.cfg = cfg
        self.history = []

        self.gemini_key = cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        self.anthropic_key = cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")

        # Определение провайдера: gemini или anthropic
        explicit_provider = cfg.get("ai_provider", "").lower()
        if explicit_provider in ("gemini", "anthropic"):
            self.provider = explicit_provider
        elif self.gemini_key:
            self.provider = "gemini"
        elif self.anthropic_key:
            self.provider = "anthropic"
        else:
            self.provider = "gemini"

        # Настройка модели по умолчанию
        cfg_model = cfg.get("model", "")
        if self.provider == "gemini":
            if not cfg_model or cfg_model.startswith("claude-"):
                self.model = "gemini-3.8-flash"
            else:
                self.model = cfg_model
        else:
            if not cfg_model or cfg_model.startswith("gemini-"):
                self.model = "claude-opus-5-5"
            else:
                self.model = cfg_model

        # Инициализация клиентов
        self.gemini_client = None
        self.anthropic_client = None

        if self.gemini_key:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=self.gemini_key)
            except Exception as e:
                log.warning("google-genai SDK не загружен, будет использоваться REST API: %s", e)

        if self.anthropic_key:
            try:
                import anthropic
                self.anthropic_client = anthropic.Anthropic(api_key=self.anthropic_key, timeout=60, max_retries=2)
            except Exception as e:
                log.warning("anthropic SDK не загружен: %s", e)

    @property
    def available(self):
        if self.provider == "gemini":
            return bool(self.gemini_key)
        return bool(self.anthropic_client)

    # ------------------ Запросы к Gemini ------------------
    def _call_gemini_sdk(self, system, messages, use_search=True):
        from google.genai import types

        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg["content"])]
            ))

        tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=tools,
            max_output_tokens=1000,
            temperature=0.7,
        )

        models_to_try = [self.model]
        for fb in ("gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"):
            if fb not in models_to_try:
                models_to_try.append(fb)

        last_err = None
        for m in models_to_try:
            try:
                resp = self.gemini_client.models.generate_content(
                    model=m,
                    contents=contents,
                    config=config,
                )
                return resp.text or ""
            except Exception as e:
                # Если сработал лимит на поиск (429 на бесплатном ключе) или сбой инструмента — пробуем без поиска
                if config.tools:
                    log.info("Запрос к %s с поиском не удался, пробуем без поиска: %s", m, e)
                    config.tools = None
                    try:
                        resp = self.gemini_client.models.generate_content(
                            model=m,
                            contents=contents,
                            config=config,
                        )
                        return resp.text or ""
                    except Exception as e2:
                        last_err = e2
                        continue
                last_err = e
                log.warning("Модель %s вернула ошибку (%s), пробуем резервную...", m, e)
                continue
        if last_err:
            raise last_err
        return ""

    def _call_gemini_rest(self, system, messages, use_search=True):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.gemini_key}"
        contents = [
            {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.7}
        }
        if use_search:
            payload["tools"] = [{"google_search": {}}]

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if use_search and e.code == 400:
                payload.pop("tools", None)
                req2 = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req2, timeout=30) as r2:
                    data = json.loads(r2.read().decode("utf-8"))
            else:
                raise

        cands = data.get("candidates", [])
        if cands and "content" in cands[0] and "parts" in cands[0]["content"]:
            return "".join(p.get("text", "") for p in cands[0]["content"]["parts"])
        return ""

    def _call_gemini(self, system, messages, use_search=True):
        if self.gemini_client:
            return self._call_gemini_sdk(system, messages, use_search=use_search)
        return self._call_gemini_rest(system, messages, use_search=use_search)

    # ------------------ Запросы к Claude ------------------
    def _call_claude(self, system, messages, tools):
        msgs = list(messages)
        extra = {"tools": tools} if tools else {}
        for _ in range(4):
            resp = self.anthropic_client.beta.messages.create(
                model=self.model,
                max_tokens=2000,
                system=system,
                messages=msgs,
                **extra,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            )
            if resp.stop_reason == "pause_turn":
                msgs.append({"role": "assistant", "content": resp.content})
                continue
            if resp.stop_reason == "refusal":
                return "На это я ответить не могу."
            text = " ".join(b.text for b in resp.content if b.type == "text").strip()
            return text or "Хм, пустой ответ. Спроси ещё раз."
        return "Поиск затянулся, попробуй переформулировать."

    # ------------------ Публичный интерфейс ------------------
    def ask(self, question):
        if not self.available:
            if self.provider == "gemini":
                return ("Чтобы я отвечала на вопросы через Gemini, впиши ключ API в config.json "
                        "в поле gemini_api_key.")
            return ("Чтобы я отвечала на вопросы через Claude, впиши ключ API в config.json "
                    "в поле anthropic_api_key.")

        now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        self.history.append({"role": "user", "content": f"[{now}] {question}"})
        self.history = self.history[-12:]
        while self.history and self.history[0]["role"] != "user":
            self.history.pop(0)

        answer = ""
        try:
            if self.provider == "gemini":
                raw_answer = self._call_gemini(SYSTEM, self.history, use_search=True)
                answer = clean_for_speech(raw_answer)
            else:
                raw_answer = self._call_claude(
                    SYSTEM,
                    self.history,
                    [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
                )
                answer = clean_for_speech(raw_answer)
        except Exception as e:
            self.history.pop()
            err_str = str(e).lower()
            log.exception("Ошибка при обращении к %s API: %s", self.provider, e)
            if "quota" in err_str or "rate" in err_str:
                return "Слишком много запросов или закончилась квота, подожди немного."
            if "key" in err_str or "auth" in err_str or "401" in err_str:
                return f"Ключ API не подходит. Проверь {self.provider}_api_key в config.json."
            if "connect" in err_str or "timed out" in err_str or "network" in err_str:
                return "Нет связи с сервером. Проверь интернет."
            return "Сервер ИИ вернул ошибку, попробуй позже."

        if not answer:
            answer = "Хм, пустой ответ. Спроси ещё раз."

        self.history.append({"role": "assistant", "content": answer})
        return answer

    def summarize_report(self, report):
        if not self.available:
            return None
        prompt = (
            "Вот отчёт диагностики моего ПК. Скажи голосом 2–4 предложения: общее состояние, "
            "главные проблемы и что конкретно сделать. Ошибки, которые обычно безвредны "
            "(например, DistributedCOM), не раздувай.\n\n" + report[:30000]
        )
        try:
            if self.provider == "gemini":
                msgs = [{"role": "user", "content": prompt}]
                raw = self._call_gemini(SYSTEM, msgs, use_search=False)
                return clean_for_speech(raw)
            else:
                raw = self._call_claude(SYSTEM, [{"role": "user", "content": prompt}], [])
                return clean_for_speech(raw)
        except Exception:
            log.exception("summarize_report error")
            return None
