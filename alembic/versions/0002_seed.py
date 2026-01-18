"""seed prices and voices

Revision ID: 0002
Revises: 0001
Create Date: 2024-10-01 00:05:00
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    prices_table = sa.table(
        "prices",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("cost_rub", sa.Numeric),
        sa.column("price_rub", sa.Numeric),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    voices_table = sa.table(
        "voices",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("is_active", sa.Boolean),
    )

    now = datetime.utcnow()

    op.bulk_insert(
        prices_table,
        [
            {
                "code": "text_input_1k",
                "title": "Текст: вход 1K",
                "cost_rub": 0.5,
                "price_rub": 1.5,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "text_output_1k",
                "title": "Текст: выход 1K",
                "cost_rub": 0.125,
                "price_rub": 0.375,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_square_standard",
                "title": "Изображение 1024x1024 стандарт",
                "cost_rub": 2.25,
                "price_rub": 6.75,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_square_high",
                "title": "Изображение 1024x1024 высокое",
                "cost_rub": 8.5,
                "price_rub": 25.5,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_square_max",
                "title": "Изображение 1024x1024 максимум",
                "cost_rub": 33.25,
                "price_rub": 99.75,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_vertical_standard",
                "title": "Изображение 1024x1536 стандарт",
                "cost_rub": 3.25,
                "price_rub": 9.75,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_vertical_high",
                "title": "Изображение 1024x1536 высокое",
                "cost_rub": 12.75,
                "price_rub": 38.25,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_vertical_max",
                "title": "Изображение 1024x1536 максимум",
                "cost_rub": 50.0,
                "price_rub": 150.0,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_horizontal_standard",
                "title": "Изображение 1536x1024 стандарт",
                "cost_rub": 3.25,
                "price_rub": 9.75,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_horizontal_high",
                "title": "Изображение 1536x1024 высокое",
                "cost_rub": 12.5,
                "price_rub": 37.5,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_horizontal_max",
                "title": "Изображение 1536x1024 максимум",
                "cost_rub": 49.75,
                "price_rub": 149.25,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "image_upscale_mp",
                "title": "Повышение качества изображения за Мп",
                "cost_rub": 0.25,
                "price_rub": 1.25,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "video_sec_silent",
                "title": "Видео сек без звука",
                "cost_rub": 17.5,
                "price_rub": 52.5,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "video_sec_audio",
                "title": "Видео сек со звуком",
                "cost_rub": 35.0,
                "price_rub": 105.0,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "video_upscale_mp",
                "title": "Повышение качества видео за Мп",
                "cost_rub": 3.75,
                "price_rub": 18.75,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "audio_music",
                "title": "Музыка",
                "cost_rub": 17.0,
                "price_rub": 51.0,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "audio_tts_1k",
                "title": "Озвучка 1K",
                "cost_rub": 25.0,
                "price_rub": 75.0,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "audio_transcribe_text",
                "title": "Расшифровка текст",
                "cost_rub": 10.0,
                "price_rub": 30.0,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "audio_transcribe_summary",
                "title": "Расшифровка текст + кратко",
                "cost_rub": 12.0,
                "price_rub": 36.0,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "three_d_512",
                "title": "3D 512",
                "cost_rub": 62.5,
                "price_rub": 187.5,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "three_d_1024",
                "title": "3D 1024",
                "cost_rub": 75.0,
                "price_rub": 225.0,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "three_d_1536",
                "title": "3D 1536",
                "cost_rub": 87.5,
                "price_rub": 262.5,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )

    op.bulk_insert(
        voices_table,
        [
            {"code": "voice_1", "title": "Арина", "is_active": True},
            {"code": "voice_2", "title": "Максим", "is_active": True},
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM voices")
    op.execute("DELETE FROM prices")
