from __future__ import annotations

import asyncio
import uuid

from aiogram import F, Router
from aiogram.enums import ContentType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, ErrorEvent, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.bot import keyboards
from app.config import settings
from app.crud import (
    activate_draft,
    add_balance,
    add_balance_transaction,
    clear_draft,
    deactivate_other_drafts,
    find_active_draft,
    get_or_create_draft,
    get_or_create_user,
    get_price,
    list_prices,
    list_recent_jobs,
    set_price,
    update_draft_payload,
    update_job_delivery_failure,
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
from app.services.tasks_api import TasksAPIClient
from app.services.diagnostics import db_status, get_recent_errors, queue_length, record_error, redis_status
from app.services.delivery import deliver_result
from app.text_utils import split_text, summarize_placeholder
from app.worker.queue import enqueue_broadcast

logger = get_logger()
router = Router()
broadcast_cache: dict[int, str] = {}


@router.errors()
async def handle_handler_error(event: ErrorEvent) -> bool:
    request_id = uuid.uuid4().hex
    update = event.update
    user_id = None
    if update.message and update.message.from_user:
        user_id = update.message.from_user.id
    elif update.callback_query and update.callback_query.from_user:
        user_id = update.callback_query.from_user.id
    exc = event.exception
    if isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc).lower():
        logger.debug(
            "handler_exception_message_not_modified",
            error=str(exc),
            update_type=getattr(update, "event_type", None),
            user_id=user_id,
            request_id=request_id,
        )
        try:
            if update.callback_query:
                await update.callback_query.answer()
        except Exception:
            logger.debug("handler_exception_reply_failed", request_id=request_id)
        return True
    logger.exception(
        "handler_exception",
        error=str(exc),
        update_type=getattr(update, "event_type", None),
        user_id=user_id,
        request_id=request_id,
    )
    try:
        if update.message:
            await update.message.answer(
                "Произошла ошибка. Попробуйте ещё раз.",
                reply_markup=keyboards.main_reply_keyboard(),
            )
            await update.message.answer(MAIN_PROMPT, reply_markup=keyboards.main_menu())
        elif update.callback_query and update.callback_query.message:
            await update.callback_query.answer("Произошла ошибка. Попробуйте ещё раз.", show_alert=True)
            await update.callback_query.message.answer(MAIN_PROMPT, reply_markup=keyboards.main_menu())
    except Exception:
        logger.exception("handler_exception_reply_failed", request_id=request_id)
    return True


MAIN_PROMPT = """
Выберите раздел меню. Все параметры выбираются кнопками прямо здесь.
""".strip()

HELP_TEXT = """
Я умею:
• Создавать задачи по тексту, изображениям, видео и аудио.
• Показывать баланс и историю задач.

Примеры:
• Отправьте текст и нажмите «Подтвердить».
• Перейдите в «🖼 Изображения» и выберите параметры.

Команды:
/menu — открыть главное меню
/balance — показать баланс
/tasks — список задач
/task <id> — статус задачи
""".strip()

RETRY_DELAYS = [0.5, 1.5, 3]


async def set_fsm_context(
    state: FSMContext | None,
    *,
    user_id: int,
    source_message_id: int | None,
    input_type: str | None,
    mode: str | None = None,
    preset: str | None = None,
) -> None:
    if state is None:
        return
    await state.update_data(
        user_id=user_id,
        source_message_id=source_message_id,
        input_type=input_type,
        mode=mode,
        preset=preset,
    )


async def create_task_with_retry(payload: dict) -> dict:
    client = TasksAPIClient()
    last_exc: httpx.HTTPError | None = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            return await client.create_task(payload)
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.exception("create_task_http_error", attempt=attempt, error=str(exc))
            if attempt == len(RETRY_DELAYS):
                raise
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc
    raise httpx.HTTPError("create_task_failed")


async def handle_task_creation(callback: CallbackQuery, state: FSMContext, request_id: str, reason: str) -> None:
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        draft = await find_active_draft(session, user.id)
        if not draft:
            await callback.answer("Сначала выберите раздел.", show_alert=True)
            return
        is_valid, error_message = validate_draft(draft)
        if not is_valid:
            await callback.answer(error_message, show_alert=True)
            return
        price_rub = await calculate_price(session, user, draft)
        if user.balance_rub < price_rub:
            await safe_edit_message(
                callback.message,
                f"Баланс недостаточен.\n\n{render_price_block(price_rub, user.balance_rub)}\n\nПополните баланс.",
                reply_markup=keyboards.balance_options(),
            )
            await callback.answer()
            return
        task_payload, options = split_payload_and_options(draft)
        logger.info(
            "action_start_request",
            user_id=user.id,
            section=draft.section.value,
            reason=reason,
            request_id=request_id,
        )
        source_message_id = draft.payload.get("source_message_id")
        mode = draft.payload.get("mode") or draft.section.value
        idempotency_key = f"{user.id}:{source_message_id}:{mode}"
        try:
            response = await create_task_with_retry(
                {
                    "section": draft.section.value,
                    "payload": task_payload,
                    "options": options,
                    "user_id": user.id,
                    "telegram_id": user.telegram_id,
                    "price_rub": price_rub,
                    "idempotency_key": idempotency_key,
                }
            )
        except httpx.HTTPStatusError as exc:
            logger.exception(
                "action_start_failed",
                status_code=exc.response.status_code,
                response_text=exc.response.text,
            )
            record_error("action_start_failed", context={"status_code": exc.response.status_code, "request_id": request_id})
            await callback.message.answer(
                "Не удалось создать задачу. Попробуйте ещё раз.",
                reply_markup=keyboards.retry_create_button(),
            )
            await callback.answer()
            return
        except httpx.HTTPError:
            logger.exception("action_start_failed")
            record_error("action_start_failed", context={"status_code": "network", "request_id": request_id})
            await callback.message.answer(
                "Не удалось создать задачу. Попробуйте ещё раз.",
                reply_markup=keyboards.retry_create_button(),
            )
            await callback.answer()
            return
        await session.refresh(user)
        await clear_draft(session, draft)
        updated_balance = user.balance_rub
        task_id = response.get("task_id")
        job_id = response.get("job_id")
        logger.info(
            "action_start_success",
            user_id=user.id,
            section=draft.section.value,
            task_id=task_id,
            job_id=job_id,
            request_id=request_id,
        )
    updated = await safe_edit_message(
        callback.message,
        f"{section_title(draft.section)}\n\n{render_price_block(price_rub, updated_balance)}\n\n"
        f"✅ Задача поставлена в очередь: #{task_id}\njob_id: {job_id}\nСтатус: queued",
        reply_markup=keyboards.confirm_buttons(False),
    )
    if not updated:
        await callback.message.answer(f"✅ Задача поставлена в очередь: #{task_id}\njob_id: {job_id}\nСтатус: queued")
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="task_created",
    )
    await callback.answer()


def log_handler_entry(handler: str, user_id: int, request_id: str | None = None, **context: object) -> None:
    logger.info("handler_entry", handler=handler, user_id=user_id, request_id=request_id, **context)


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


def render_section_prompt(section: Section, user: User, draft: Draft | None = None) -> str:
    payload = draft.payload if draft else {}
    if section == Section.text:
        return f"{section_title(section)}\n\nВведите текст ниже."
    if section == Section.image:
        if payload.get("mode") == "upscale":
            return f"{section_title(section)}\n\nПрикрепите изображение для повышения качества."
        return f"{section_title(section)}\n\nВведите текст. Если прикрепите изображение — будет редактирование."
    if section == Section.video:
        if payload.get("mode") == "upscale":
            return f"{section_title(section)}\n\nПрикрепите видео документом для повышения качества."
        return f"{section_title(section)}\n\nВведите текст. Можно прикрепить изображение."
    if section == Section.audio:
        mode = payload.get("mode")
        if mode == "transcribe":
            return f"{section_title(section)}\n\nПрикрепите mp3 документом и выберите формат результата."
        if mode == "music":
            return f"{section_title(section)}\n\nВведите тему или текст для музыки."
        if mode == "tts":
            return f"{section_title(section)}\n\nВведите текст и выберите голос ниже."
        return f"{section_title(section)}\n\nВыберите режим работы."
    if section == Section.three_d:
        return f"{section_title(section)}\n\nПрикрепите изображение для 3D."
    return f"{section_title(section)}\n\nБаланс: {user.balance_rub} ₽"


async def load_prices(session: AsyncSession, codes: list[str]) -> dict[str, object]:
    prices = {}
    for code in codes:
        price = await get_price(session, code)
        if price:
            prices[code] = price
    return prices


def render_price_block(price_rub: int, balance_rub: int) -> str:
    return f"Стоимость: {price_rub} ₽\nБаланс: {balance_rub} ₽"


def job_status_label(status: JobStatus) -> str:
    return {
        JobStatus.queued: "queued",
        JobStatus.processing: "started",
        JobStatus.done: "finished",
        JobStatus.error: "failed",
    }[status]


def validate_draft(draft: Draft) -> tuple[bool, str]:
    payload = draft.payload or {}
    if draft.section == Section.text:
        if not payload.get("prompt"):
            return False, "Введите текст для генерации."
        return True, ""
    if draft.section == Section.image:
        if payload.get("mode") == "upscale":
            if not payload.get("file_id"):
                return False, "Загрузите изображение для апскейла."
            if not payload.get("upscale"):
                return False, "Выберите коэффициент апскейла."
            return True, ""
        if not (payload.get("prompt") or payload.get("file_id")):
            return False, "Введите текст или загрузите изображение."
        if not payload.get("size"):
            return False, "Выберите размер изображения."
        if not payload.get("quality"):
            return False, "Выберите качество изображения."
        return True, ""
    if draft.section == Section.video:
        if payload.get("mode") == "upscale":
            if not payload.get("file_id"):
                return False, "Загрузите видео для апскейла."
            if not payload.get("upscale"):
                return False, "Выберите коэффициент апскейла."
            return True, ""
        if not (payload.get("prompt") or payload.get("file_id")):
            return False, "Введите текст или загрузите изображение."
        if not payload.get("size"):
            return False, "Выберите размер видео."
        if not payload.get("duration"):
            return False, "Выберите длительность видео."
        if payload.get("with_audio") is None:
            return False, "Выберите наличие звука."
        return True, ""
    if draft.section == Section.audio:
        mode = payload.get("mode")
        if not mode:
            return False, "Выберите режим аудио."
        if mode == "transcribe":
            if not payload.get("file_id"):
                return False, "Загрузите аудио для расшифровки."
            if not payload.get("transcribe_mode"):
                return False, "Выберите формат расшифровки."
            return True, ""
        if mode == "tts":
            if not payload.get("prompt"):
                return False, "Введите текст для озвучки."
            if not payload.get("voice_id"):
                return False, "Выберите голос."
            return True, ""
        if not payload.get("prompt"):
            return False, "Введите текст для генерации."
        return True, ""
    if draft.section == Section.three_d:
        if not payload.get("file_id"):
            return False, "Загрузите изображение для 3D."
        if not payload.get("quality"):
            return False, "Выберите качество 3D."
        return True, ""
    return True, ""


def action_keyboard_for_draft(draft: Draft) -> InlineKeyboardMarkup:
    payload = draft.payload or {}
    is_valid, _ = validate_draft(draft)
    if draft.section == Section.text:
        return keyboards.review_buttons(is_valid)
    if draft.section == Section.image:
        if payload.get("mode") == "upscale":
            return keyboards.image_upscale_options(payload.get("upscale"), is_valid)
        return keyboards.image_options(payload.get("size"), payload.get("quality"), is_valid)
    if draft.section == Section.video:
        if payload.get("mode") == "upscale":
            return keyboards.video_upscale_options(payload.get("upscale"), is_valid)
        return keyboards.video_options(payload.get("size"), payload.get("duration"), payload.get("with_audio"), is_valid)
    if draft.section == Section.audio:
        mode = payload.get("mode")
        if not mode:
            return keyboards.audio_options(None)
        if mode == "transcribe":
            return keyboards.audio_transcribe_options(payload.get("transcribe_mode"))
        return keyboards.review_buttons(is_valid)
    if draft.section == Section.three_d:
        return keyboards.three_d_options(payload.get("quality"), is_valid)
    return keyboards.review_buttons(is_valid)


def render_action_text(draft: Draft, price_rub: int, balance_rub: int) -> str:
    base = f"{section_title(draft.section)}\n\n{render_price_block(price_rub, balance_rub)}"
    is_valid, _ = validate_draft(draft)
    if is_valid:
        return f"{base}\n\nНажмите «Подтвердить»."
    return f"{base}\n\nВыберите параметры для запуска."


def _truncate_text(value: str, limit: int = 500) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}…"


def render_confirmation_text(draft: Draft, price_rub: int, balance_rub: int) -> str:
    payload = draft.payload or {}
    lines = [section_title(draft.section), "", "Проверьте параметры:"]
    if draft.section == Section.text:
        prompt = payload.get("prompt") or ""
        lines.append(f"• Текст: {_truncate_text(prompt)}")
    elif draft.section == Section.image:
        if payload.get("mode") == "upscale":
            lines.append("• Режим: апскейл")
            lines.append(f"• Коэффициент: x{payload.get('upscale') or '—'}")
        else:
            lines.append(f"• Размер: {payload.get('size') or '—'}")
            lines.append(f"• Качество: {payload.get('quality') or '—'}")
        lines.append("• Файл: прикреплён" if payload.get("file_id") else "• Файл: нет")
        if payload.get("prompt"):
            lines.append(f"• Текст: {_truncate_text(payload.get('prompt') or '')}")
    elif draft.section == Section.video:
        if payload.get("mode") == "upscale":
            lines.append("• Режим: апскейл")
            lines.append(f"• Коэффициент: x{payload.get('upscale') or '—'}")
        else:
            lines.append(f"• Формат: {payload.get('size') or '—'}")
            lines.append(f"• Длительность: {payload.get('duration') or '—'} сек")
            audio_flag = payload.get("with_audio")
            lines.append(f"• Звук: {'да' if audio_flag else 'нет'}" if audio_flag is not None else "• Звук: —")
        lines.append("• Файл: прикреплён" if payload.get("file_id") else "• Файл: нет")
        if payload.get("prompt"):
            lines.append(f"• Текст: {_truncate_text(payload.get('prompt') or '')}")
    elif draft.section == Section.audio:
        mode = payload.get("mode") or "—"
        lines.append(f"• Режим: {mode}")
        if mode == "transcribe":
            lines.append(f"• Формат: {payload.get('transcribe_mode') or '—'}")
            lines.append("• Файл: прикреплён" if payload.get("file_id") else "• Файл: нет")
        elif mode == "tts":
            lines.append(f"• Голос: {payload.get('voice_id') or '—'}")
            lines.append(f"• Текст: {_truncate_text(payload.get('prompt') or '')}")
        else:
            lines.append(f"• Текст: {_truncate_text(payload.get('prompt') or '')}")
    elif draft.section == Section.three_d:
        lines.append(f"• Качество: {payload.get('quality') or '—'}")
        lines.append("• Файл: прикреплён" if payload.get("file_id") else "• Файл: нет")
    lines.append("")
    lines.append(render_price_block(price_rub, balance_rub))
    lines.append("")
    lines.append("Нажмите «Запустить», чтобы поставить задачу в очередь.")
    return "\n".join(lines)


def _serialize_markup(markup: InlineKeyboardMarkup | None) -> object | None:
    if markup is None:
        return None
    if hasattr(markup, "model_dump"):
        return markup.model_dump()
    if hasattr(markup, "to_python"):
        return markup.to_python()
    return markup


async def safe_edit_message(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    if message.text == text:
        current_markup = _serialize_markup(message.reply_markup)
        target_markup = _serialize_markup(reply_markup)
        if current_markup == target_markup:
            return False
    try:
        await message.edit_text(text, reply_markup=reply_markup)
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            logger.debug("message_not_modified", message_id=message.message_id)
            return False
        raise


def split_payload_and_options(draft: Draft) -> tuple[dict, dict]:
    payload = draft.payload or {}
    if draft.section == Section.text:
        return {"prompt": payload.get("prompt")}, {}
    if draft.section == Section.image:
        content = {"prompt": payload.get("prompt"), "file_id": payload.get("file_id")}
        options = {
            "mode": payload.get("mode"),
            "size": payload.get("size"),
            "quality": payload.get("quality"),
            "upscale": payload.get("upscale"),
            "megapixels": payload.get("megapixels"),
        }
        return content, {k: v for k, v in options.items() if v is not None}
    if draft.section == Section.video:
        content = {"prompt": payload.get("prompt"), "file_id": payload.get("file_id")}
        options = {
            "mode": payload.get("mode"),
            "size": payload.get("size"),
            "duration": payload.get("duration"),
            "with_audio": payload.get("with_audio"),
            "upscale": payload.get("upscale"),
            "megapixels": payload.get("megapixels"),
        }
        return content, {k: v for k, v in options.items() if v is not None}
    if draft.section == Section.audio:
        content = {"prompt": payload.get("prompt"), "file_id": payload.get("file_id")}
        options = {
            "mode": payload.get("mode"),
            "transcribe_mode": payload.get("transcribe_mode"),
            "voice_id": payload.get("voice_id"),
        }
        return content, {k: v for k, v in options.items() if v is not None}
    if draft.section == Section.three_d:
        content = {"file_id": payload.get("file_id")}
        options = {"quality": payload.get("quality")}
        return content, {k: v for k, v in options.items() if v is not None}
    return payload, {}


async def render_section_menu(
    section: Section,
    user: User,
    draft: Draft,
    session: AsyncSession | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    text = render_section_prompt(section, user, draft)
    payload = draft.payload or {}
    if section == Section.audio and payload.get("mode") == "tts":
        if session is None:
            async with async_session_factory() as voice_session:
                voices = await load_voices(voice_session)
        else:
            voices = await load_voices(session)
        markup = keyboards.audio_tts_options(voices, payload.get("voice_id"))
    elif section == Section.audio and payload.get("mode") == "transcribe":
        markup = keyboards.audio_transcribe_options(payload.get("transcribe_mode"))
    elif section == Section.balance:
        markup = keyboards.balance_options()
    else:
        markup = action_keyboard_for_draft(draft)
    return text, markup


@router.message(F.text == "/start")
async def start(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("start", message.from_user.id, request_id=request_id, payload=message.text)
    async with async_session_factory() as session:
        await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="command",
        mode="menu",
    )
    await message.answer(MAIN_PROMPT, reply_markup=keyboards.main_menu())
    await message.answer("Главное меню", reply_markup=keyboards.main_reply_keyboard())


@router.message(F.text == "/menu")
async def menu(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("menu", message.from_user.id, request_id=request_id, payload=message.text)
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="command",
        mode="menu",
    )
    await message.answer(MAIN_PROMPT, reply_markup=keyboards.main_menu())
    await message.answer("Главное меню", reply_markup=keyboards.main_reply_keyboard())


@router.message(F.text == "/help")
async def help_command(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("help", message.from_user.id, request_id=request_id, payload=message.text)
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="command",
        mode="help",
    )
    await message.answer(HELP_TEXT, reply_markup=keyboards.main_reply_keyboard())


@router.message(F.text == "🏠 Меню")
async def menu_button(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("menu_button", message.from_user.id, request_id=request_id, payload=message.text)
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="button",
        mode="menu",
    )
    await message.answer(MAIN_PROMPT, reply_markup=keyboards.main_menu())
    await message.answer("Главное меню", reply_markup=keyboards.main_reply_keyboard())


@router.message(F.text == "💰 Баланс")
async def balance_button(message: Message, state: FSMContext) -> None:
    await balance_command(message, state)


@router.message(F.text == "📦 Мои задачи")
async def tasks_button(message: Message, state: FSMContext) -> None:
    await tasks_command(message, state)


@router.message(F.text == "⬅️ Назад")
async def back_button(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("back_button", message.from_user.id, request_id=request_id, payload=message.text)
    await menu(message, state)


@router.message(F.text == "❌ Отмена")
async def cancel_button(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("cancel_button", message.from_user.id, request_id=request_id, payload=message.text)
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        draft = await find_active_draft(session, user.id)
        if draft:
            await clear_draft(session, draft)
    await state.clear()
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="button",
        mode="cancel",
    )
    await message.answer("Отменено. Возвращаю в меню.", reply_markup=keyboards.main_reply_keyboard())
    await message.answer(MAIN_PROMPT, reply_markup=keyboards.main_menu())


@router.message(F.text == "/balance")
async def balance_command(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("balance_command", message.from_user.id, request_id=request_id, payload=message.text)
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="command",
        mode="balance",
    )
    await message.answer(
        f"💰 Баланс: {user.balance_rub} ₽",
        reply_markup=keyboards.balance_options(),
    )


@router.message(F.text == "/tasks")
async def tasks_command(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("tasks_command", message.from_user.id, request_id=request_id, payload=message.text)
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        jobs = await list_recent_jobs(session, user.id)
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="command",
        mode="tasks",
    )
    if not jobs:
        await message.answer("📦 Мои задачи\n\nПока нет задач.", reply_markup=keyboards.back_and_home())
        return
    lines = ["📦 Мои задачи"]
    for job in jobs:
        lines.append(
            f"• #{job.id} • {section_title(job.section)} • {job.created_at:%Y-%m-%d %H:%M} • {job_status_label(job.status)}"
        )
    await message.answer("\n".join(lines), reply_markup=keyboards.job_list_buttons([job.id for job in jobs]))


@router.message(F.text.regexp(r"^/task\\s+\\d+"))
async def task_command(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("task_command", message.from_user.id, request_id=request_id, payload=message.text)
    task_id = int(message.text.split(maxsplit=1)[1])
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        job = await session.get(Job, task_id)
        if not job or job.user_id != user.id:
            await message.answer("Задача не найдена.", reply_markup=keyboards.back_and_home())
            return
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="command",
        mode="task",
    )
    status_text = job_status_label(job.status)
    extra = " (доставка не удалась)" if job.delivery_failed else ""
    await message.answer(
        f"#{job.id} • {section_title(job.section)}\n"
        f"Статус: {status_text}{extra}\n"
        f"Стоимость: {job.price_rub} ₽\n"
        f"Создана: {job.created_at:%Y-%m-%d %H:%M}",
        reply_markup=keyboards.job_detail_buttons(job.id),
    )
    if job.status == JobStatus.done:
        delivered = await deliver_result(message.bot, user, job)
        async with async_session_factory() as session:
            await update_job_delivery_failure(session, job.id, not delivered)
        if not delivered:
            await message.answer("Не удалось доставить результат.", reply_markup=keyboards.retry_task_button(job.id))


@router.callback_query(F.data == "menu:home")
@router.callback_query(F.data == "back:menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("back_to_menu", callback.from_user.id, request_id=request_id, payload=callback.data)
    await safe_edit_message(callback.message, MAIN_PROMPT, reply_markup=keyboards.main_menu())
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="menu",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("section:"))
async def open_section(callback: CallbackQuery, state: FSMContext) -> None:
    section_key = callback.data.split(":", 1)[1]
    section = Section(section_key)
    request_id = uuid.uuid4().hex
    log_handler_entry("open_section", callback.from_user.id, request_id=request_id, payload=callback.data, section=section.value)
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
        payload = draft.payload or {}
        payload["awaiting_input"] = section in {Section.text, Section.image, Section.video, Section.audio, Section.three_d}
        payload.setdefault("source_message_id", callback.message.message_id if callback.message else None)
        payload.setdefault("input_type", "callback")
        draft = await update_draft_payload(session, draft, payload)
        if payload["awaiting_input"]:
            await activate_draft(session, user.id, draft.id)
        else:
            await deactivate_other_drafts(session, user.id, None)
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode=section.value,
    )
    text, markup = await render_section_menu(section, user, draft, session)
    await safe_edit_message(callback.message, text, reply_markup=markup)
    await callback.answer()


@router.message(F.content_type == ContentType.TEXT, ~F.text.startswith("/"))
async def handle_text(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("handle_text", message.from_user.id, request_id=request_id, payload=message.text)
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
            await activate_draft(session, user.id, draft.id)
        payload = draft.payload or {}
        payload["prompt"] = message.text
        payload["awaiting_input"] = False
        payload["source_message_id"] = message.message_id
        payload["input_type"] = "text"
        await update_draft_payload(session, draft, payload)
        price_rub = await calculate_price(session, user, draft)
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="text",
        mode=draft.section.value,
    )
    text = render_action_text(draft, price_rub, user.balance_rub)
    await message.answer(text, reply_markup=action_keyboard_for_draft(draft))


@router.message(F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT, ContentType.VIDEO}))
async def handle_media(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("handle_media", message.from_user.id, request_id=request_id, payload=message.content_type)
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )
        draft = await find_active_draft(session, user.id)
        if not draft:
            await message.answer(
                "Не удалось распознать запрос. Откройте меню.",
                reply_markup=keyboards.main_reply_keyboard(),
            )
            await message.answer(MAIN_PROMPT, reply_markup=keyboards.main_menu())
            await set_fsm_context(
                state,
                user_id=message.from_user.id,
                source_message_id=message.message_id,
                input_type="fallback",
                mode="menu",
            )
            return
        payload = draft.payload or {}
        payload["awaiting_input"] = False
        if message.photo:
            payload["file_id"] = message.photo[-1].file_id
        if message.document:
            payload["file_id"] = message.document.file_id
        if message.video:
            payload["file_id"] = message.video.file_id
        payload["source_message_id"] = message.message_id
        payload["input_type"] = str(message.content_type)
        await update_draft_payload(session, draft, payload)
        price_rub = await calculate_price(session, user, draft)
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type=str(message.content_type),
        mode=draft.section.value,
    )
    text = render_action_text(draft, price_rub, user.balance_rub)
    await message.answer(text, reply_markup=action_keyboard_for_draft(draft))


@router.callback_query(F.data.startswith("image:size:"))
async def image_size(callback: CallbackQuery, state: FSMContext) -> None:
    size = callback.data.split(":")[-1]
    request_id = uuid.uuid4().hex
    log_handler_entry("image_size", callback.from_user.id, request_id=request_id, payload=callback.data, size=size)
    await update_draft_option(callback, Section.image, "size", size, state)


@router.callback_query(F.data == "image:mode:upscale")
async def image_mode_upscale(callback: CallbackQuery, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("image_mode_upscale", callback.from_user.id, request_id=request_id, payload=callback.data)
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
        payload.setdefault("source_message_id", callback.message.message_id if callback.message else None)
        payload.setdefault("input_type", "callback")
        draft = await update_draft_payload(session, draft, payload)
        await activate_draft(session, user.id, draft.id)
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="image:upscale",
    )
    text, markup = await render_section_menu(Section.image, user, draft, session)
    await safe_edit_message(callback.message, text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("image:quality:"))
async def image_quality(callback: CallbackQuery, state: FSMContext) -> None:
    quality = callback.data.split(":")[-1]
    request_id = uuid.uuid4().hex
    log_handler_entry("image_quality", callback.from_user.id, request_id=request_id, payload=callback.data, quality=quality)
    await update_draft_option(callback, Section.image, "quality", quality, state)


@router.callback_query(F.data.startswith("image:upscale:"))
async def image_upscale(callback: CallbackQuery, state: FSMContext) -> None:
    factor = int(callback.data.split(":")[-1])
    request_id = uuid.uuid4().hex
    log_handler_entry("image_upscale", callback.from_user.id, request_id=request_id, payload=callback.data, factor=factor)
    await update_draft_option(callback, Section.image, "upscale", factor, state)


@router.callback_query(F.data.startswith("video:size:"))
async def video_size(callback: CallbackQuery, state: FSMContext) -> None:
    size = callback.data.split(":")[-1]
    request_id = uuid.uuid4().hex
    log_handler_entry("video_size", callback.from_user.id, request_id=request_id, payload=callback.data, size=size)
    await update_draft_option(callback, Section.video, "size", size, state)


@router.callback_query(F.data == "video:mode:upscale")
async def video_mode_upscale(callback: CallbackQuery, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("video_mode_upscale", callback.from_user.id, request_id=request_id, payload=callback.data)
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
        payload.setdefault("source_message_id", callback.message.message_id if callback.message else None)
        payload.setdefault("input_type", "callback")
        draft = await update_draft_payload(session, draft, payload)
        await activate_draft(session, user.id, draft.id)
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="video:upscale",
    )
    text, markup = await render_section_menu(Section.video, user, draft, session)
    await safe_edit_message(callback.message, text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("video:duration:"))
async def video_duration(callback: CallbackQuery, state: FSMContext) -> None:
    duration = int(callback.data.split(":")[-1])
    request_id = uuid.uuid4().hex
    log_handler_entry("video_duration", callback.from_user.id, request_id=request_id, payload=callback.data, duration=duration)
    await update_draft_option(callback, Section.video, "duration", duration, state)


@router.callback_query(F.data.startswith("video:audio:"))
async def video_audio(callback: CallbackQuery, state: FSMContext) -> None:
    audio = callback.data.split(":")[-1] == "yes"
    request_id = uuid.uuid4().hex
    log_handler_entry("video_audio", callback.from_user.id, request_id=request_id, payload=callback.data, with_audio=audio)
    await update_draft_option(callback, Section.video, "with_audio", audio, state)


@router.callback_query(F.data.startswith("video:upscale:"))
async def video_upscale(callback: CallbackQuery, state: FSMContext) -> None:
    factor = int(callback.data.split(":")[-1])
    request_id = uuid.uuid4().hex
    log_handler_entry("video_upscale", callback.from_user.id, request_id=request_id, payload=callback.data, factor=factor)
    await update_draft_option(callback, Section.video, "upscale", factor, state)


@router.callback_query(F.data.startswith("audio:mode:"))
async def audio_mode(callback: CallbackQuery, state: FSMContext) -> None:
    mode = callback.data.split(":")[-1]
    request_id = uuid.uuid4().hex
    log_handler_entry("audio_mode", callback.from_user.id, request_id=request_id, payload=callback.data, mode=mode)
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
        payload.setdefault("source_message_id", callback.message.message_id if callback.message else None)
        payload.setdefault("input_type", "callback")
        draft = await update_draft_payload(session, draft, payload)
        await activate_draft(session, user.id, draft.id)
        text, markup = await render_section_menu(Section.audio, user, draft, session)
        await safe_edit_message(callback.message, text, reply_markup=markup)
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode=f"audio:{mode}",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("audio:transcribe:"))
async def audio_transcribe(callback: CallbackQuery, state: FSMContext) -> None:
    mode = callback.data.split(":")[-1]
    request_id = uuid.uuid4().hex
    log_handler_entry("audio_transcribe", callback.from_user.id, request_id=request_id, payload=callback.data, mode=mode)
    await update_draft_option(callback, Section.audio, "transcribe_mode", mode, state)


@router.callback_query(F.data.startswith("audio:voice:"))
async def audio_voice(callback: CallbackQuery, state: FSMContext) -> None:
    voice_id = int(callback.data.split(":")[-1])
    request_id = uuid.uuid4().hex
    log_handler_entry("audio_voice", callback.from_user.id, request_id=request_id, payload=callback.data, voice_id=voice_id)
    await update_draft_option(callback, Section.audio, "voice_id", voice_id, state)


@router.callback_query(F.data.startswith("three_d:quality:"))
async def three_d_quality(callback: CallbackQuery, state: FSMContext) -> None:
    quality = callback.data.split(":")[-1]
    request_id = uuid.uuid4().hex
    log_handler_entry("three_d_quality", callback.from_user.id, request_id=request_id, payload=callback.data, quality=quality)
    await update_draft_option(callback, Section.three_d, "quality", quality, state)


@router.callback_query(F.data == "action:start")
async def action_start(callback: CallbackQuery, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("action_start", callback.from_user.id, request_id=request_id, payload=callback.data)
    await handle_task_creation(callback, state, request_id, "start")


@router.callback_query(F.data == "action:confirm")
async def action_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("action_confirm", callback.from_user.id, request_id=request_id, payload=callback.data)
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        draft = await find_active_draft(session, user.id)
        if not draft:
            await callback.answer("Сначала выберите раздел.", show_alert=True)
            return
        is_valid, error_message = validate_draft(draft)
        if not is_valid:
            await callback.answer(error_message, show_alert=True)
            return
        price_rub = await calculate_price(session, user, draft)
        if user.balance_rub < price_rub:
            await safe_edit_message(
                callback.message,
                f"Баланс недостаточен.\n\n{render_price_block(price_rub, user.balance_rub)}\n\nПополните баланс.",
                reply_markup=keyboards.balance_options(),
            )
            await callback.answer()
            return
        confirmation_text = render_confirmation_text(draft, price_rub, user.balance_rub)
        await safe_edit_message(callback.message, confirmation_text, reply_markup=keyboards.confirm_buttons(True))
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="confirm",
    )
    await callback.answer()


@router.callback_query(F.data == "action:retry")
async def action_retry(callback: CallbackQuery, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("action_retry", callback.from_user.id, request_id=request_id, payload=callback.data)
    await handle_task_creation(callback, state, request_id, "retry")


@router.callback_query(F.data == "jobs:list")
async def jobs_list(callback: CallbackQuery, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("jobs_list", callback.from_user.id, request_id=request_id, payload=callback.data)
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        jobs = await list_recent_jobs(session, user.id)
    if not jobs:
        text = "📦 Мои задачи\n\nПока нет задач."
        await safe_edit_message(callback.message, text, reply_markup=keyboards.back_and_home())
        await callback.answer()
        return
    lines = ["📦 Мои задачи"]
    for job in jobs:
        lines.append(
            f"• #{job.id} • {section_title(job.section)} • {job.created_at:%Y-%m-%d %H:%M} • {job_status_label(job.status)}"
        )
    await safe_edit_message(
        callback.message,
        "\n".join(lines),
        reply_markup=keyboards.job_list_buttons([job.id for job in jobs]),
    )
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="tasks",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("balance:topup:"))
async def balance_topup(callback: CallbackQuery, state: FSMContext) -> None:
    amount = int(callback.data.split(":")[-1])
    request_id = uuid.uuid4().hex
    log_handler_entry("balance_topup", callback.from_user.id, request_id=request_id, payload=callback.data, amount=amount)
    client = PaymentsClient()
    link = await client.create_payment(amount, "Пополнение баланса", "https://t.me/")
    await safe_edit_message(
        callback.message,
        f"Для пополнения перейдите по ссылке:\n{link.url}",
        reply_markup=keyboards.back_and_home(),
    )
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="balance_topup",
        preset=str(amount),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("jobs:repeat:"))
async def jobs_repeat(callback: CallbackQuery, state: FSMContext) -> None:
    job_id = int(callback.data.split(":")[-1])
    request_id = uuid.uuid4().hex
    log_handler_entry("jobs_repeat", callback.from_user.id, request_id=request_id, payload=callback.data, job_id=job_id)
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
        logger.info("jobs_repeat_request", user_id=user.id, section=job.section.value, job_id=job.id)
        try:
            response = await create_task_with_retry(
                {
                    "section": job.section.value,
                    "payload": job.payload,
                    "options": {},
                    "user_id": user.id,
                    "telegram_id": user.telegram_id,
                    "price_rub": price_rub,
                    "idempotency_key": f"{user.id}:{job.id}:repeat",
                }
            )
        except httpx.HTTPStatusError as exc:
            logger.exception(
                "jobs_repeat_failed",
                status_code=exc.response.status_code,
                response_text=exc.response.text,
            )
            await callback.answer("Не удалось повторить.", show_alert=True)
            return
        except httpx.HTTPError:
            logger.exception("jobs_repeat_failed")
            await callback.answer("Не удалось повторить.", show_alert=True)
            return
    await callback.answer(f"Повтор отправлен. Задача #{response.get('task_id')}")
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="jobs_repeat",
        preset=str(job_id),
    )


@router.callback_query(F.data.startswith("jobs:open:"))
async def jobs_open(callback: CallbackQuery, state: FSMContext) -> None:
    job_id = int(callback.data.split(":")[-1])
    request_id = uuid.uuid4().hex
    log_handler_entry("jobs_open", callback.from_user.id, request_id=request_id, payload=callback.data, job_id=job_id)
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        job = await session.get(Job, job_id)
        if not user or not job or job.user_id != user.id:
            await callback.answer("Задача не найдена.", show_alert=True)
            return
    status_text = job_status_label(job.status)
    extra = " (доставка не удалась)" if job.delivery_failed else ""
    await safe_edit_message(
        callback.message,
        f"#{job.id} • {section_title(job.section)}\n"
        f"Статус: {status_text}{extra}\n"
        f"Стоимость: {job.price_rub} ₽\n"
        f"Создана: {job.created_at:%Y-%m-%d %H:%M}",
        reply_markup=keyboards.job_detail_buttons(job.id),
    )
    if job.status == JobStatus.done:
        delivered = await deliver_result(callback.message.bot, user, job)
        async with async_session_factory() as session:
            await update_job_delivery_failure(session, job.id, not delivered)
        if not delivered:
            await callback.message.answer("Не удалось доставить результат.", reply_markup=keyboards.retry_task_button(job.id))
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="job_detail",
        preset=str(job_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delivery:retry:"))
async def delivery_retry(callback: CallbackQuery, state: FSMContext) -> None:
    task_id = int(callback.data.split(":")[-1])
    request_id = uuid.uuid4().hex
    log_handler_entry("delivery_retry", callback.from_user.id, request_id=request_id, payload=callback.data, task_id=task_id)
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        job = await session.get(Job, task_id)
        if not user or not job or job.user_id != user.id:
            await callback.answer("Не удалось повторить.", show_alert=True)
            return
    delivered = await deliver_result(callback.message.bot, user, job)
    async with async_session_factory() as session:
        await update_job_delivery_failure(session, job.id, not delivered)
    if delivered:
        await callback.answer("Доставка выполнена.")
    else:
        await callback.message.answer("Не удалось доставить результат.", reply_markup=keyboards.retry_task_button(job.id))
        await callback.answer()
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="delivery_retry",
    )


async def update_draft_option(callback: CallbackQuery, section: Section, key: str, value: object, state: FSMContext | None = None) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry(
        "update_draft_option",
        callback.from_user.id,
        request_id=request_id,
        payload=callback.data,
        section=section.value,
        key=key,
    )
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        draft = await get_or_create_draft(session, user.id, section)
        payload = draft.payload or {}
        if payload.get(key) == value:
            await callback.answer("Уже выбрано ✅")
            return
        payload[key] = value
        payload.setdefault("awaiting_input", True)
        payload.setdefault("source_message_id", callback.message.message_id if callback.message else None)
        payload.setdefault("input_type", "callback")
        draft = await update_draft_payload(session, draft, payload)
        await activate_draft(session, user.id, draft.id)
        text, markup = await render_section_menu(section, user, draft, session)
        await safe_edit_message(callback.message, text, reply_markup=markup)
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode=section.value,
        preset=f"{key}:{value}",
    )
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
    request_id = uuid.uuid4().hex
    log_handler_entry("noop", callback.from_user.id, request_id=request_id, payload=callback.data)
    await callback.answer()


@router.callback_query(F.data == "action:cancel")
async def action_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("action_cancel", callback.from_user.id, request_id=request_id, payload=callback.data)
    async with async_session_factory() as session:
        user = await get_or_create_user(
            session,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
        )
        draft = await find_active_draft(session, user.id)
        if draft:
            await clear_draft(session, draft)
    await state.clear()
    await set_fsm_context(
        state,
        user_id=callback.from_user.id,
        source_message_id=callback.message.message_id if callback.message else None,
        input_type="callback",
        mode="cancel",
    )
    await safe_edit_message(callback.message, "Отменено.", reply_markup=keyboards.main_menu())
    await callback.message.answer("Главное меню", reply_markup=keyboards.main_reply_keyboard())
    await callback.answer()


@router.callback_query(F.data == "text:summarize")
async def text_summarize(callback: CallbackQuery) -> None:
    log_handler_entry("text_summarize", callback.from_user.id, payload=callback.data)
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
    log_handler_entry("admin_price", message.from_user.id, payload=message.text)
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
    log_handler_entry("admin_give", message.from_user.id, payload=message.text)
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


@router.message(F.text.startswith("/admin_topup"))
async def admin_topup(message: Message) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("admin_topup", message.from_user.id, request_id=request_id, payload=message.text)
    if message.from_user.id not in settings.admin_id_set():
        await message.answer("Доступ запрещён.")
        return
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.answer("Формат: /admin_topup <user_id|@username> <amount> [comment]")
        return
    user_ref = parts[1]
    try:
        amount = int(parts[2])
    except ValueError:
        await message.answer("Сумма должна быть числом.")
        return
    comment = parts[3] if len(parts) > 3 else None
    async with async_session_factory() as session:
        user: User | None = None
        if user_ref.startswith("@"):
            result = await session.execute(select(User).where(User.username == user_ref[1:]))
            user = result.scalar_one_or_none()
        else:
            result = await session.execute(select(User).where(User.telegram_id == int(user_ref)))
            user = result.scalar_one_or_none()
        if not user:
            await message.answer("Пользователь не найден.")
            return
        await add_balance_transaction(session, user, amount, message.from_user.id, comment)
    logger.info(
        "admin_topup_success",
        request_id=request_id,
        admin_id=message.from_user.id,
        user_id=user.id,
        amount=amount,
    )
    await message.answer(f"Баланс пополнен на {amount} ₽ для пользователя {user.telegram_id}.")


@router.message(F.text.startswith("/admin_diag"))
async def admin_diag(message: Message) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("admin_diag", message.from_user.id, request_id=request_id, payload=message.text)
    if message.from_user.id not in settings.admin_id_set():
        await message.answer("Доступ запрещён.")
        return
    async with async_session_factory() as session:
        db_state = await db_status(session)
    redis_state = redis_status()
    qlen = queue_length()
    errors = get_recent_errors()
    lines = [
        "🛠 Диагностика",
        f"Redis: {redis_state}",
        f"DB: {db_state}",
        f"Очередь: {qlen}",
        "Ошибки:",
    ]
    if not errors:
        lines.append("— нет")
    else:
        for item in errors:
            lines.append(f"• {item.get('timestamp', '')} {item.get('message', '')}")
    await message.answer("\n".join(lines))


@router.message(F.text.startswith("/ban"))
async def admin_ban(message: Message) -> None:
    log_handler_entry("admin_ban", message.from_user.id, payload=message.text)
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
    log_handler_entry("admin_unban", message.from_user.id, payload=message.text)
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
    log_handler_entry("admin_jobs", message.from_user.id, payload=message.text)
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
    log_handler_entry("admin_broadcast", message.from_user.id, payload=message.text)
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


@router.message()
async def fallback(message: Message, state: FSMContext) -> None:
    request_id = uuid.uuid4().hex
    log_handler_entry("fallback", message.from_user.id, request_id=request_id, payload=message.text)
    await set_fsm_context(
        state,
        user_id=message.from_user.id,
        source_message_id=message.message_id,
        input_type="fallback",
        mode="menu",
    )
    await message.answer("Не удалось распознать запрос. Откройте меню.", reply_markup=keyboards.main_reply_keyboard())
    await message.answer(MAIN_PROMPT, reply_markup=keyboards.main_menu())
