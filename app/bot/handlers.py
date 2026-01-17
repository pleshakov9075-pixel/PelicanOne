from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ContentType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.bot import keyboards
from app.config import settings
from app.crud import (
    add_balance,
    charge_balance,
    clear_draft,
    create_job_if_not_exists,
    get_or_create_draft,
    get_or_create_user,
    get_price,
    list_prices,
    list_recent_jobs,
    set_price,
    update_draft_payload,
)
from app.db import async_session_factory
from app.models import Draft, Job, JobStatus, Section, User, Voice
from app.pricing import (
    calc_audio_music,
    calc_audio_transcribe,
    calc_audio_tts,
    calc_image_price,
    calc_image_upscale,
    calc_text_price,
    calc_three_d,
    calc_video_price,
    calc_video_upscale,
)
from app.services.payments import PaymentsClient
from app.text_utils import split_text, summarize_placeholder
from app.worker.queue import enqueue_broadcast, enqueue_job

logger = get_logger()
router = Router()
broadcast_cache: dict[int, str] = {}


MAIN_PROMPT = """
Выберите раздел меню. Все параметры выбираются кнопками прямо здесь.
""".strip()


def section_title(section: Section) -> str:
    titles = {
        Section.text: "🧠 Текст",
        Section.image: "🖼 Изображения",
        Section.video: "🎬 Видео",
        Section.audio: "🎧 Аудио",
        Section.three_d: "🧊 3D",
        Section.balance: "💳 Баланс",
    }
    return titles.get(section, "")


async def load_prices(session: AsyncSession, codes: list[str]) -> dict[str, object]:
    prices = {}
    for code in codes:
        price = await get_price(session, code)
        if price:
            prices[code] = price
    return prices


async def find_active_draft(session: AsyncSession, user_id: int) -> Draft | None:
    result = await session.execute(select(Draft).where(Draft.user_id == user_id))
    drafts = result.scalars().all()
    active = [draft for draft in drafts if draft.payload.get("awaiting_input")]
    if len(active) == 1:
        return active[0]
    return None


def render_price_block(price_rub: int, balance_rub: int) -> str:
    return f"Стоимость: {price_rub} ₽\nБаланс: {balance_rub} ₽"


def draft_ready(draft: Draft) -> bool:
    payload = draft.payload or {}
    if draft.section == Section.text:
        return bool(payload.get("prompt"))
    if draft.section == Section.image:
        if payload.get("mode") == "upscale":
            return bool(payload.get("file_id")) and bool(payload.get("upscale"))
        return bool(payload.get("prompt"))
    if draft.section == Section.video:
        if payload.get("mode") == "upscale":
            return bool(payload.get("file_id")) and bool(payload.get("upscale"))
        return bool(payload.get("prompt"))
    if draft.section == Section.audio:
        mode = payload.get("mode", "music")
        if mode == "transcribe":
            return bool(payload.get("file_id")) and bool(payload.get("transcribe_mode"))
        if mode == "tts":
            return bool(payload.get("prompt")) and bool(payload.get("voice_id"))
        return bool(payload.get("prompt"))
    if draft.section == Section.three_d:
        return bool(payload.get("file_id")) and bool(payload.get("quality"))
    return True


@router.message(F.text == "/start")
async def start(message: Message) -> None:
    async with async_session_factory() as session:
        await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
    await message.answer(MAIN_PROMPT, reply_markup=keyboards.main_menu())


@router.callback_query(F.data == "menu:home")
@router.callback_query(F.data == "back:menu")
async def back_to_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(MAIN_PROMPT, reply_markup=keyboards.main_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("section:"))
async def open_section(callback: CallbackQuery) -> None:
    section_key = callback.data.split(":", 1)[1]
    section = Section(section_key)
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        if user.is_banned:
            await callback.answer("Доступ ограничен.")
            return
        draft = await get_or_create_draft(session, user.id, section)
        if section in {Section.text, Section.image, Section.video, Section.audio, Section.three_d}:
            draft.payload["awaiting_input"] = True
        else:
            draft.payload["awaiting_input"] = False
        await update_draft_payload(session, draft, draft.payload)

    if section == Section.text:
        text = f"{section_title(section)}\n\nВведите текст ниже."
        markup = keyboards.text_options()
    elif section == Section.image:
        text = f"{section_title(section)}\n\nВведите текст. Если прикрепите изображение — будет редактирование."
        markup = keyboards.image_options("square", "standard")
    elif section == Section.video:
        text = f"{section_title(section)}\n\nВведите текст. Можно прикрепить изображение."
        markup = keyboards.video_options()
    elif section == Section.audio:
        text = f"{section_title(section)}\n\nВыберите режим работы."
        markup = keyboards.audio_options()
    elif section == Section.three_d:
        text = f"{section_title(section)}\n\nПрикрепите изображение для 3D."
        markup = keyboards.three_d_options()
    else:
        text = f"{section_title(section)}\n\nБаланс: {user.balance_rub} ₽"
        markup = keyboards.balance_options()
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.message(F.content_type == ContentType.TEXT)
async def handle_text(message: Message) -> None:
    if message.text.startswith("/"):
        return
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        draft = await find_active_draft(session, user.id)
        if not draft:
            draft = await get_or_create_draft(session, user.id, Section.text)
        payload = draft.payload or {}
        payload["prompt"] = message.text
        payload["awaiting_input"] = False
        await update_draft_payload(session, draft, payload)
        price_rub = await calculate_price(session, user, draft)
    text = f"{section_title(draft.section)}\n\n{render_price_block(price_rub, user.balance_rub)}\n\nНажмите «Запустить»."
    await message.answer(text, reply_markup=keyboards.confirm_buttons(True))


@router.message(F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT, ContentType.VIDEO}))
async def handle_media(message: Message) -> None:
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        draft = await find_active_draft(session, user.id)
        if not draft:
            draft = await get_or_create_draft(session, user.id, Section.image)
        payload = draft.payload or {}
        payload["awaiting_input"] = False
        if message.photo:
            payload["file_id"] = message.photo[-1].file_id
        if message.document:
            payload["file_id"] = message.document.file_id
        if message.video:
            payload["file_id"] = message.video.file_id
        await update_draft_payload(session, draft, payload)
        price_rub = await calculate_price(session, user, draft)
    text = f"{section_title(draft.section)}\n\n{render_price_block(price_rub, user.balance_rub)}\n\nНажмите «Запустить»."
    await message.answer(text, reply_markup=keyboards.confirm_buttons(True))


@router.callback_query(F.data.startswith("image:size:"))
async def image_size(callback: CallbackQuery) -> None:
    size = callback.data.split(":")[-1]
    await update_draft_option(callback, Section.image, "size", size)


@router.callback_query(F.data == "image:mode:upscale")
async def image_mode_upscale(callback: CallbackQuery) -> None:
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        draft = await get_or_create_draft(session, user.id, Section.image)
        payload = draft.payload or {}
        payload["mode"] = "upscale"
        payload["awaiting_input"] = True
        await update_draft_payload(session, draft, payload)
    await callback.message.edit_text(
        "🖼 Изображения\n\nПрикрепите изображение для повышения качества.",
        reply_markup=keyboards.image_upscale_options(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("image:quality:"))
async def image_quality(callback: CallbackQuery) -> None:
    quality = callback.data.split(":")[-1]
    await update_draft_option(callback, Section.image, "quality", quality)


@router.callback_query(F.data.startswith("image:upscale:"))
async def image_upscale(callback: CallbackQuery) -> None:
    factor = int(callback.data.split(":")[-1])
    await update_draft_option(callback, Section.image, "upscale", factor)


@router.callback_query(F.data.startswith("video:size:"))
async def video_size(callback: CallbackQuery) -> None:
    size = callback.data.split(":")[-1]
    await update_draft_option(callback, Section.video, "size", size)


@router.callback_query(F.data == "video:mode:upscale")
async def video_mode_upscale(callback: CallbackQuery) -> None:
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        draft = await get_or_create_draft(session, user.id, Section.video)
        payload = draft.payload or {}
        payload["mode"] = "upscale"
        payload["awaiting_input"] = True
        await update_draft_payload(session, draft, payload)
    await callback.message.edit_text(
        "🎬 Видео\n\nПрикрепите видео документом для повышения качества.",
        reply_markup=keyboards.video_upscale_options(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("video:duration:"))
async def video_duration(callback: CallbackQuery) -> None:
    duration = int(callback.data.split(":")[-1])
    await update_draft_option(callback, Section.video, "duration", duration)


@router.callback_query(F.data.startswith("video:audio:"))
async def video_audio(callback: CallbackQuery) -> None:
    audio = callback.data.split(":")[-1] == "yes"
    await update_draft_option(callback, Section.video, "with_audio", audio)


@router.callback_query(F.data.startswith("video:upscale:"))
async def video_upscale(callback: CallbackQuery) -> None:
    factor = int(callback.data.split(":")[-1])
    await update_draft_option(callback, Section.video, "upscale", factor)


@router.callback_query(F.data.startswith("audio:mode:"))
async def audio_mode(callback: CallbackQuery) -> None:
    mode = callback.data.split(":")[-1]
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        draft = await get_or_create_draft(session, user.id, Section.audio)
        payload = draft.payload or {}
        payload["mode"] = mode
        payload["awaiting_input"] = mode in {"music", "tts", "transcribe"}
        await update_draft_payload(session, draft, payload)
        if mode == "transcribe":
            await callback.message.edit_text(
                "🎧 Аудио\n\nПрикрепите mp3 документом и выберите формат результата.",
                reply_markup=keyboards.audio_transcribe_options(),
            )
        elif mode == "music":
            await callback.message.edit_text(
                "🎧 Аудио\n\nВведите тему или текст для музыки.",
                reply_markup=keyboards.confirm_buttons(True),
            )
        else:
            voices = await load_voices(session)
            await callback.message.edit_text(
                "🎧 Аудио\n\nВведите текст и выберите голос ниже.",
                reply_markup=keyboards.audio_tts_options(voices),
            )
    await callback.answer()


@router.callback_query(F.data.startswith("audio:transcribe:"))
async def audio_transcribe(callback: CallbackQuery) -> None:
    mode = callback.data.split(":")[-1]
    await update_draft_option(callback, Section.audio, "transcribe_mode", mode)


@router.callback_query(F.data.startswith("audio:voice:"))
async def audio_voice(callback: CallbackQuery) -> None:
    voice_id = int(callback.data.split(":")[-1])
    await update_draft_option(callback, Section.audio, "voice_id", voice_id)


@router.callback_query(F.data.startswith("three_d:quality:"))
async def three_d_quality(callback: CallbackQuery) -> None:
    quality = callback.data.split(":")[-1]
    await update_draft_option(callback, Section.three_d, "quality", quality)


@router.callback_query(F.data == "action:start")
async def action_start(callback: CallbackQuery) -> None:
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        draft = await find_active_draft(session, user.id)
        if not draft:
            await callback.answer("Сначала укажите параметры.")
            return
        if not draft_ready(draft):
            await callback.answer("Не хватает данных для запуска.")
            return
        price_rub = await calculate_price(session, user, draft)
        if user.balance_rub < price_rub:
            await callback.message.edit_text(
                f"Баланс недостаточен.\n\n{render_price_block(price_rub, user.balance_rub)}\n\nПополните баланс.",
                reply_markup=keyboards.balance_options(),
            )
            await callback.answer()
            return
        payload = draft.payload.copy()
        await charge_balance(session, user, price_rub, "job_start")
        updated_balance = user.balance_rub
        job = await create_job_if_not_exists(session, user.id, draft, draft.section, price_rub, payload)
        await clear_draft(session, draft)
        enqueue_job(job.id)
    try:
        await callback.message.edit_text(
            f"{section_title(job.section)}\n\n{render_price_block(price_rub, updated_balance)}\n\n⏳ Запускаю…",
            reply_markup=keyboards.confirm_buttons(False),
        )
    except TelegramBadRequest:
        await callback.message.answer("⏳ Запускаю…")
    await callback.answer()


@router.callback_query(F.data == "jobs:list")
async def jobs_list(callback: CallbackQuery) -> None:
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        jobs = await list_recent_jobs(session, user.id)
    if not jobs:
        text = "📋 Мои задачи\n\nПока нет задач."
        await callback.message.edit_text(text, reply_markup=keyboards.back_and_home())
        await callback.answer()
        return
    lines = ["📋 Мои задачи"]
    for job in jobs:
        status_text = {
            JobStatus.queued: "🕒 В очереди",
            JobStatus.processing: "⚙️ Обрабатывается",
            JobStatus.done: "✅ Готово",
            JobStatus.error: "❌ Ошибка",
        }[job.status]
        lines.append(f"• {section_title(job.section)} • {job.created_at:%Y-%m-%d %H:%M} • {status_text}")
    await callback.message.edit_text("\n".join(lines), reply_markup=keyboards.job_list_buttons(jobs[0].id))
    await callback.answer()


@router.callback_query(F.data.startswith("balance:topup:"))
async def balance_topup(callback: CallbackQuery) -> None:
    amount = int(callback.data.split(":")[-1])
    client = PaymentsClient()
    link = await client.create_payment(amount, "Пополнение баланса", "https://t.me/")
    await callback.message.edit_text(
        f"Для пополнения перейдите по ссылке:\n{link.url}",
        reply_markup=keyboards.back_and_home(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("jobs:repeat:"))
async def jobs_repeat(callback: CallbackQuery) -> None:
    job_id = int(callback.data.split(":")[-1])
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        job = await session.get(Job, job_id)
        if not user or not job or job.user_id != user.id:
            await callback.answer("Не удалось повторить.")
            return
        price_rub = job.price_rub
        if user.balance_rub < price_rub:
            await callback.answer("Недостаточно баланса.")
            return
        new_job = await create_job_if_not_exists(session, user.id, None, job.section, price_rub, job.payload)
        enqueue_job(new_job.id)
    await callback.answer("Повтор отправлен.")


async def update_draft_option(callback: CallbackQuery, section: Section, key: str, value: object) -> None:
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        draft = await get_or_create_draft(session, user.id, section)
        payload = draft.payload or {}
        payload[key] = value
        payload.setdefault("awaiting_input", True)
        await update_draft_payload(session, draft, payload)
    await callback.answer("Готово")


async def load_voices(session: AsyncSession) -> list[tuple[int, str]]:
    result = await session.execute(select(Voice).where(Voice.is_active.is_(True)))
    voices = result.scalars().all()
    return [(voice.id, voice.title) for voice in voices]


async def calculate_price(session: AsyncSession, user: User, draft: Draft) -> int:
    section = draft.section
    payload = draft.payload or {}
    if section == Section.text:
        prices = await load_prices(session, ["text_input_1k", "text_output_1k"])
        return calc_text_price(prices, payload.get("prompt", ""))
    if section == Section.image:
        if payload.get("mode") == "upscale":
            prices = await load_prices(session, ["image_upscale_mp"])
            megapixels = payload.get("megapixels", 1)
            return calc_image_upscale(prices, megapixels)
        prices = await load_prices(session, [
            "image_square_standard",
            "image_square_high",
            "image_square_max",
            "image_vertical_standard",
            "image_vertical_high",
            "image_vertical_max",
            "image_horizontal_standard",
            "image_horizontal_high",
            "image_horizontal_max",
        ])
        size = payload.get("size", "square")
        quality = payload.get("quality", "standard")
        return calc_image_price(prices, size, quality)
    if section == Section.video:
        if payload.get("mode") == "upscale":
            prices = await load_prices(session, ["video_upscale_mp"])
            megapixels = payload.get("megapixels", 1)
            return calc_video_upscale(prices, megapixels)
        prices = await load_prices(session, ["video_sec_audio", "video_sec_silent"])
        seconds = int(payload.get("duration", 5))
        with_audio = bool(payload.get("with_audio", False))
        return calc_video_price(prices, seconds, with_audio)
    if section == Section.audio:
        mode = payload.get("mode", "music")
        if mode == "transcribe":
            prices = await load_prices(session, ["audio_transcribe_text", "audio_transcribe_summary"])
            return calc_audio_transcribe(prices, payload.get("transcribe_mode", "text"))
        if mode == "tts":
            prices = await load_prices(session, ["audio_tts_1k"])
            prompt = payload.get("prompt", "")
            return calc_audio_tts(prices, len(prompt))
        prices = await load_prices(session, ["audio_music"])
        return calc_audio_music(prices)
    if section == Section.three_d:
        prices = await load_prices(session, ["three_d_512", "three_d_1024", "three_d_1536"])
        return calc_three_d(prices, payload.get("quality", "512"))
    return 0


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "text:summarize")
async def text_summarize(callback: CallbackQuery) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Нет текста для краткого варианта.")
            return
        result = await session.execute(
            select(Job)
            .where(Job.user_id == user.id, Job.section == Section.text, Job.status == JobStatus.done)
            .order_by(Job.created_at.desc())
        )
        job = result.scalars().first()
    if not job or not job.result:
        await callback.answer("Нет текста для краткого варианта.")
        return
    summary = summarize_placeholder(job.result.get("message", ""))
    await callback.message.answer(summary)
    await callback.answer()


@router.message(F.text.startswith("/price"))
async def admin_price(message: Message) -> None:
    async with async_session_factory() as session:
        await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        if message.from_user.id not in settings.admin_id_set():
            await message.answer("Недостаточно прав.")
            return
        if message.text.strip() == "/price list":
            prices = await list_prices(session)
            lines = ["Текущие цены:"]
            for price in prices:
                lines.append(f"{price.code}: {price.price_rub} ₽")
            for chunk in split_text("\n".join(lines)):
                await message.answer(chunk)
            return
        if message.text.startswith("/price set"):
            parts = message.text.split()
            if len(parts) != 4:
                await message.answer("Формат: /price set <код> <цена>")
                return
            _, _, code, value = parts
            if not await set_price(session, code, float(value)):
                await message.answer("Код не найден.")
                return
            await message.answer("Цена обновлена.")
            return
        await message.answer("Используйте: /price list или /price set")


@router.message(F.text.startswith("/give"))
async def admin_give(message: Message) -> None:
    if message.from_user.id not in settings.admin_id_set():
        await message.answer("Недостаточно прав.")
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Формат: /give <telegram_id> <сумма>")
        return
    telegram_id = int(parts[1])
    amount = int(parts[2])
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("Пользователь не найден.")
            return
        await add_balance(session, user, amount, "admin_give")
    await message.answer("Баланс пополнен.")


@router.message(F.text.startswith("/ban"))
async def admin_ban(message: Message) -> None:
    if message.from_user.id not in settings.admin_id_set():
        await message.answer("Недостаточно прав.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: /ban <telegram_id>")
        return
    telegram_id = int(parts[1])
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("Пользователь не найден.")
            return
        user.is_banned = True
        await session.commit()
    await message.answer("Пользователь заблокирован.")


@router.message(F.text.startswith("/unban"))
async def admin_unban(message: Message) -> None:
    if message.from_user.id not in settings.admin_id_set():
        await message.answer("Недостаточно прав.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Формат: /unban <telegram_id>")
        return
    telegram_id = int(parts[1])
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("Пользователь не найден.")
            return
        user.is_banned = False
        await session.commit()
    await message.answer("Пользователь разблокирован.")


@router.message(F.text.startswith("/jobs"))
async def admin_jobs(message: Message) -> None:
    if message.from_user.id not in settings.admin_id_set():
        await message.answer("Недостаточно прав.")
        return
    async with async_session_factory() as session:
        result = await session.execute(select(Job).order_by(Job.created_at.desc()).limit(20))
        jobs = result.scalars().all()
    lines = ["Последние задачи:"]
    for job in jobs:
        lines.append(f"#{job.id} {job.section} {job.status}")
    for chunk in split_text("\n".join(lines)):
        await message.answer(chunk)


@router.message(F.text.startswith("/broadcast"))
async def admin_broadcast(message: Message) -> None:
    if message.from_user.id not in settings.admin_id_set():
        await message.answer("Недостаточно прав.")
        return
    payload = message.text.replace("/broadcast", "").strip()
    if payload == "confirm":
        cached = broadcast_cache.pop(message.from_user.id, None)
        if not cached:
            await message.answer("Нет подготовленного сообщения.")
            return
        enqueue_broadcast(cached)
        await message.answer("Рассылка запущена.")
        return
    if not payload:
        await message.answer("Добавьте текст рассылки.")
        return
    broadcast_cache[message.from_user.id] = payload
    await message.answer("Превью сообщения:\n\n" + payload)
    await message.answer("Для отправки используйте: /broadcast confirm")
