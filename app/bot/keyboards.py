from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Главное меню"), KeyboardButton(text="💰 Баланс")],
            [KeyboardButton(text="📦 Мои задачи"), KeyboardButton(text="⬅️ Назад")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🧠 Текст", callback_data="section:text")],
        [InlineKeyboardButton(text="🖼 Изображения", callback_data="section:image")],
        [InlineKeyboardButton(text="🎬 Видео", callback_data="section:video")],
        [InlineKeyboardButton(text="🎧 Аудио", callback_data="section:audio")],
        [InlineKeyboardButton(text="🧊 3D", callback_data="section:three_d")],
        [InlineKeyboardButton(text="💳 Баланс", callback_data="section:balance")],
        [InlineKeyboardButton(text="📋 Мои задачи", callback_data="jobs:list")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
            ]
        ]
    )


def back_and_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:home")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel")],
        ]
    )


def balance_options() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пополнить 500 ₽", callback_data="balance:topup:500")],
            [InlineKeyboardButton(text="Пополнить 1000 ₽", callback_data="balance:topup:1000")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
            ],
        ]
    )


def confirm_buttons(ready: bool) -> InlineKeyboardMarkup:
    if ready:
        row = [InlineKeyboardButton(text="✅ Запустить", callback_data="action:start")]
    else:
        row = [InlineKeyboardButton(text="⏳ Запускаю…", callback_data="noop")]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
            ],
        ]
    )


def text_options() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Запустить", callback_data="action:start")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
            ],
        ]
    )


def image_options(size: str, quality: str, show_start: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Повышение качества", callback_data="image:mode:upscale")],
        [
            InlineKeyboardButton(text="Квадрат", callback_data="image:size:square"),
            InlineKeyboardButton(text="Вертикально", callback_data="image:size:vertical"),
            InlineKeyboardButton(text="Горизонтально", callback_data="image:size:horizontal"),
        ],
        [
            InlineKeyboardButton(text="Стандарт", callback_data="image:quality:standard"),
            InlineKeyboardButton(text="Высокое", callback_data="image:quality:high"),
            InlineKeyboardButton(text="Максимум", callback_data="image:quality:max"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
        ],
    ]
    if show_start:
        rows.insert(-1, [InlineKeyboardButton(text="✅ Запустить", callback_data="action:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_upscale_options(show_start: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="x2", callback_data="image:upscale:2")],
        [InlineKeyboardButton(text="x4", callback_data="image:upscale:4")],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
        ],
    ]
    if show_start:
        rows.insert(-1, [InlineKeyboardButton(text="✅ Запустить", callback_data="action:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def video_options(show_start: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Повышение качества", callback_data="video:mode:upscale")],
        [
            InlineKeyboardButton(text="Квадрат", callback_data="video:size:square"),
            InlineKeyboardButton(text="Вертикально", callback_data="video:size:vertical"),
            InlineKeyboardButton(text="Горизонтально", callback_data="video:size:horizontal"),
        ],
        [
            InlineKeyboardButton(text="5 сек", callback_data="video:duration:5"),
            InlineKeyboardButton(text="10 сек", callback_data="video:duration:10"),
        ],
        [
            InlineKeyboardButton(text="Со звуком", callback_data="video:audio:yes"),
            InlineKeyboardButton(text="Без звука", callback_data="video:audio:no"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
        ],
    ]
    if show_start:
        rows.insert(-1, [InlineKeyboardButton(text="✅ Запустить", callback_data="action:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def video_upscale_options(show_start: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="x2", callback_data="video:upscale:2")],
        [InlineKeyboardButton(text="x4", callback_data="video:upscale:4")],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
        ],
    ]
    if show_start:
        rows.insert(-1, [InlineKeyboardButton(text="✅ Запустить", callback_data="action:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def audio_options() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Расшифровка", callback_data="audio:mode:transcribe")],
            [InlineKeyboardButton(text="Музыка", callback_data="audio:mode:music")],
            [InlineKeyboardButton(text="Озвучка текста", callback_data="audio:mode:tts")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
            ],
        ]
    )


def audio_transcribe_options() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Только текст", callback_data="audio:transcribe:text")],
            [InlineKeyboardButton(text="Текст + кратко", callback_data="audio:transcribe:summary")],
            [InlineKeyboardButton(text="✅ Запустить", callback_data="action:start")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
            ],
        ]
    )


def audio_tts_options(voices: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title, callback_data=f"audio:voice:{voice_id}")] for voice_id, title in voices]
    rows.append([InlineKeyboardButton(text="✅ Запустить", callback_data="action:start")])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def three_d_options(show_start: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="512", callback_data="three_d:quality:512")],
        [InlineKeyboardButton(text="1024", callback_data="three_d:quality:1024")],
        [InlineKeyboardButton(text="1536", callback_data="three_d:quality:1536")],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
        ],
    ]
    if show_start:
        rows.insert(-1, [InlineKeyboardButton(text="✅ Запустить", callback_data="action:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def job_list_buttons(job_id: int | None) -> InlineKeyboardMarkup:
    rows = []
    if job_id:
        rows.append([InlineKeyboardButton(text="🔄 Повторить", callback_data=f"jobs:repeat:{job_id}")])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def summarize_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сделать кратко", callback_data="text:summarize")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel")],
        ]
    )


def retry_task_button(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Повторить доставку", callback_data=f"delivery:retry:{task_id}")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
            ],
        ]
    )


def retry_create_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Попробовать ещё раз", callback_data="action:retry")],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back:menu"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
            ],
        ]
    )
