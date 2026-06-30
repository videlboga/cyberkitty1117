"""
Модуль для работы с LLM API (OpenAI совместимыми).
Содержит функции для отправки запросов и получения ответов от нейросетей.
"""

from .config import openai, config


async def ask_llm(condition_text, channel_text_data):
    """Отправляет запрос в LLM.

    Требования тестов:
    1. Вызывает `openai.chat.completions.create` ровно один раз (или три при ретраях) с
       параметрами `model`, `messages`, `stream=True`.
    2. Если `stream=True`, то функция должна склеить все `delta.content` из пришедших
       чанков и вернуть готовую строку.
    3. В случае пустых/неполных данных возвращает пустую строку.
    4. При исключениях делает до 3 попыток, после чего возвращает None.
    """

    messages = [
        {"role": "system", "content": condition_text},
        {"role": "user", "content": str(channel_text_data)},
    ]

    print("Отправляю запрос в ChatGPT")

    model_name = config['Settings'].get('text_model', 'gpt-3.5-turbo')

    for attempt in range(3):
        try:
            response_stream = openai.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=True,
            )

            # В тестах `response_stream` – список мока, а не генератор. Поддержим оба варианта
            parts = []
            for chunk in response_stream:
                # chunk может быть чем угодно (мок). Пытаемся безопасно извлечь текст
                piece = ""
                if hasattr(chunk, "choices") and chunk.choices:
                    first_choice = chunk.choices[0]
                    # Сценарий stream=True — атрибут delta
                    if hasattr(first_choice, "delta") and hasattr(first_choice.delta, "content"):
                        piece = first_choice.delta.content or ""
                    # Сценарий без stream — атрибут message.content
                    elif hasattr(first_choice, "message") and hasattr(first_choice.message, "content"):
                        piece = first_choice.message.content or ""

                if piece:
                    parts.append(piece)

            return "".join(parts)

        except Exception as e:
            print(f"Ошибка при обращении к OpenRouter (попытка {attempt+1}): {e}")

    return "" 