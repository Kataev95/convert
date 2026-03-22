import asyncio
import os
import subprocess
import uuid
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart

BOT_TOKEN = "8768265521:AAGdZFuAESGMN_vlQqUDApi-LAgYwpn2fj0"

TEMP_DIR = "temp_webm"
os.makedirs(TEMP_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def convert_to_sticker(input_path: str, output_path: str) -> tuple[bool, str]:
    passlog = os.path.join(TEMP_DIR, f"ffmpeg2pass_{uuid.uuid4().hex}")
    null_output = "NUL" if os.name == "nt" else "/dev/null"

    vf_filter = (
        "scale='if(gt(iw,ih),512,trunc(oh*a/2)*2)':"
        "'if(gt(iw,ih),trunc(ow/a/2)*2,512)',"
        "fps=fps=30"
    )

    common_flags = [
        "-t", "3",
        "-vf", vf_filter,
        "-c:v", "libvpx-vp9",
        "-b:v", "0",
        "-crf", "18",
        "-deadline", "best",
        "-cpu-used", "0",
        "-row-mt", "1",
        "-lag-in-frames", "25",
        "-auto-alt-ref", "1",
        "-an",
    ]

    pass1 = subprocess.run(
        ["ffmpeg", "-y", "-i", input_path]
        + common_flags
        + ["-pass", "1", "-passlogfile", passlog, "-f", "webm", null_output],
        capture_output=True, text=True, timeout=120
    )
    if pass1.returncode != 0:
        return False, pass1.stderr[-600:]

    pass2 = subprocess.run(
        ["ffmpeg", "-y", "-i", input_path]
        + common_flags
        + ["-pass", "2", "-passlogfile", passlog, output_path],
        capture_output=True, text=True, timeout=120
    )

    for ext in [".log", ".log.mbtree"]:
        lf = passlog + ext
        if os.path.exists(lf):
            os.remove(lf)

    if pass2.returncode != 0:
        return False, pass2.stderr[-600:]

    size_kb = os.path.getsize(output_path) / 1024
    if size_kb > 256:
        return False, f"size_exceeded:{size_kb:.1f}"

    return True, ""


def convert_with_target_size(input_path: str, output_path: str) -> tuple[bool, str]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_path],
        capture_output=True, text=True
    )
    try:
        duration = min(float(probe.stdout.strip()), 3.0)
    except ValueError:
        duration = 3.0

    target_kbps = int((256 * 8) / duration * 0.92)

    passlog = os.path.join(TEMP_DIR, f"ffmpeg2pass_{uuid.uuid4().hex}")
    null_output = "NUL" if os.name == "nt" else "/dev/null"

    vf_filter = (
        "scale='if(gt(iw,ih),512,trunc(oh*a/2)*2)':"
        "'if(gt(iw,ih),trunc(ow/a/2)*2,512)',"
        "fps=fps=30"
    )

    common_flags = [
        "-t", "3",
        "-vf", vf_filter,
        "-c:v", "libvpx-vp9",
        "-b:v", f"{target_kbps}k",
        "-deadline", "best",
        "-cpu-used", "0",
        "-row-mt", "1",
        "-lag-in-frames", "25",
        "-auto-alt-ref", "1",
        "-an",
    ]

    pass1 = subprocess.run(
        ["ffmpeg", "-y", "-i", input_path]
        + common_flags
        + ["-pass", "1", "-passlogfile", passlog, "-f", "webm", null_output],
        capture_output=True, text=True, timeout=120
    )
    if pass1.returncode != 0:
        return False, pass1.stderr[-600:]

    pass2 = subprocess.run(
        ["ffmpeg", "-y", "-i", input_path]
        + common_flags
        + ["-pass", "2", "-passlogfile", passlog, output_path],
        capture_output=True, text=True, timeout=120
    )

    for ext in [".log", ".log.mbtree"]:
        lf = passlog + ext
        if os.path.exists(lf):
            os.remove(lf)

    if pass2.returncode != 0:
        return False, pass2.stderr[-600:]

    size_kb = os.path.getsize(output_path) / 1024
    if size_kb > 256:
        return False, f"Файл всё равно {size_kb:.1f} КБ > 256 КБ. Видео слишком сложное."

    return True, ""


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🎨 <b>Конвертер в Telegram видео-стикеры</b>\n\n"
        "Отправь мне короткое видео <b>MP4</b> (до 3 сек, до 20 МБ) — "
        "я конвертирую его в <b>WebM VP9</b> готовый для загрузки в @Stickers.\n\n"
        "<b>Требования Telegram:</b>\n"
        "• Одна сторона = 512px\n"
        "• Длительность ≤ 3 сек\n"
        "• Размер ≤ 256 КБ\n"
        "• Без звука\n"
        "• FPS ≤ 30",
        parse_mode="HTML"
    )


@dp.message(F.video | F.document)
async def handle_video(message: Message):
    if message.video:
        file_obj = message.video
    elif message.document:
        file_obj = message.document
        mime = file_obj.mime_type or ""
        fname = file_obj.file_name or ""
        if "mp4" not in mime and not fname.endswith(".mp4"):
            await message.answer("❌ Пожалуйста, отправь файл в формате <b>MP4</b>.", parse_mode="HTML")
            return
    else:
        return

    if file_obj.file_size and file_obj.file_size > 20 * 1024 * 1024:
        await message.answer("⚠️ Файл слишком большой. Лимит — <b>20 МБ</b>.", parse_mode="HTML")
        return

    uid = uuid.uuid4().hex
    input_path = os.path.join(TEMP_DIR, f"{uid}_input.mp4")
    output_path = os.path.join(TEMP_DIR, f"{uid}_output.webm")

    status_msg = await message.answer("⏳ Скачиваю видео...")

    try:
        file = await bot.get_file(file_obj.file_id)
        await bot.download_file(file.file_path, destination=input_path)

        await status_msg.edit_text("🔄 Конвертирую в стикер (VP9, 2-pass)...")

        success, error = await asyncio.to_thread(convert_to_sticker, input_path, output_path)

        if not success and error.startswith("size_exceeded"):
            size_val = error.split(":")[1]
            await status_msg.edit_text(
                f"⚙️ Файл {size_val} КБ > 256 КБ, пересжимаю с целевым битрейтом..."
            )
            success, error = await asyncio.to_thread(
                convert_with_target_size, input_path, output_path
            )

        if not success:
            await status_msg.edit_text(
                f"❌ Ошибка конвертации:\n<code>{error}</code>",
                parse_mode="HTML"
            )
            return

        size_kb = os.path.getsize(output_path) / 1024
        await status_msg.edit_text("📤 Отправляю стикер...")

        output_file = FSInputFile(output_path, filename="sticker.webm")
        await message.answer_document(
            document=output_file,
            caption=(
                f"✅ <b>Готово!</b> Размер: <b>{size_kb:.1f} КБ</b> / 256 КБ\n\n"
                "📌 Загрузи файл в <b>@Stickers</b> → <i>Добавить видео-стикер</i>"
            ),
            parse_mode="HTML"
        )
        await status_msg.delete()

    except subprocess.TimeoutExpired:
        await status_msg.edit_text("❌ Превышено время конвертации (2 минуты).")
    except Exception as e:
        logging.exception(e)
        await status_msg.edit_text(f"❌ Произошла ошибка: <code>{e}</code>", parse_mode="HTML")
    finally:
        for path in [input_path, output_path]:
            if os.path.exists(path):
                os.remove(path)


@dp.message()
async def fallback(message: Message):
    await message.answer(
        "📎 Отправь мне короткое видео <b>MP4</b> для конвертации в стикер.",
        parse_mode="HTML"
    )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())