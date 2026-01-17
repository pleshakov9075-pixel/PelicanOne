from __future__ import annotations

from decimal import Decimal

from app.config import settings
from app.models import Price


TEXT_INPUT_CODE = "text_input_1k"
TEXT_OUTPUT_CODE = "text_output_1k"


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def calc_text_price(prices: dict[str, Price], prompt: str) -> int:
    input_tokens = estimate_tokens(prompt)
    output_tokens = settings.max_output_tokens
    input_price = prices[TEXT_INPUT_CODE].price_rub
    output_price = prices[TEXT_OUTPUT_CODE].price_rub
    total = (Decimal(input_tokens) / Decimal(1000)) * input_price
    total += (Decimal(output_tokens) / Decimal(1000)) * output_price
    return int(total.to_integral_value(rounding="ROUND_HALF_UP"))


def calc_image_price(prices: dict[str, Price], size_code: str, quality: str) -> int:
    code = f"image_{size_code}_{quality}"
    return int(Decimal(prices[code].price_rub).to_integral_value(rounding="ROUND_HALF_UP"))


def calc_image_upscale(prices: dict[str, Price], megapixels: Decimal) -> int:
    price_per_mp = prices["image_upscale_mp"].price_rub
    total = price_per_mp * megapixels
    return int(total.to_integral_value(rounding="ROUND_HALF_UP"))


def calc_video_price(prices: dict[str, Price], seconds: int, with_audio: bool) -> int:
    code = "video_sec_audio" if with_audio else "video_sec_silent"
    price_per_sec = prices[code].price_rub
    total = price_per_sec * Decimal(seconds)
    return int(total.to_integral_value(rounding="ROUND_HALF_UP"))


def calc_video_upscale(prices: dict[str, Price], megapixels: Decimal) -> int:
    price_per_mp = prices["video_upscale_mp"].price_rub
    total = price_per_mp * megapixels
    return int(total.to_integral_value(rounding="ROUND_HALF_UP"))


def calc_audio_music(prices: dict[str, Price]) -> int:
    return int(Decimal(prices["audio_music"].price_rub).to_integral_value(rounding="ROUND_HALF_UP"))


def calc_audio_tts(prices: dict[str, Price], chars: int) -> int:
    price_per_1k = prices["audio_tts_1k"].price_rub
    total = (Decimal(chars) / Decimal(1000)) * price_per_1k
    return int(total.to_integral_value(rounding="ROUND_HALF_UP"))


def calc_audio_transcribe(prices: dict[str, Price], mode: str) -> int:
    code = "audio_transcribe_text" if mode == "text" else "audio_transcribe_summary"
    return int(Decimal(prices[code].price_rub).to_integral_value(rounding="ROUND_HALF_UP"))


def calc_three_d(prices: dict[str, Price], quality: str) -> int:
    code = f"three_d_{quality}"
    return int(Decimal(prices[code].price_rub).to_integral_value(rounding="ROUND_HALF_UP"))
