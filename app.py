import os
import sys
import logging
import io
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)
from PIL import Image

# ============================================
# LOGGING CONFIGURATION
# ============================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION
# ============================================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
PORT = int(os.environ.get("PORT", 8080))
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_ZOOM_FACTORS = [2.0, 3.0, 4.0]

if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN environment variable is required!")
    sys.exit(1)

# ============================================
# FLASK APP & TELEGRAM BOT
# ============================================
app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# ============================================
# IMAGE PROCESSING
# ============================================
def zoom_image(image_data: bytes, zoom_factor: float) -> Optional[io.BytesIO]:
    """Zoom/enlarge an image by a given factor"""
    try:
        img = Image.open(io.BytesIO(image_data))
        original_width, original_height = img.size
        new_width = int(original_width * zoom_factor)
        new_height = int(original_height * zoom_factor)
        
        if new_width > 8000 or new_height > 8000:
            logger.warning(f"Zoomed image too large: {new_width}x{new_height}")
            return None
        
        zoomed = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        zoomed.save(output, format="PNG", optimize=True)
        output.seek(0)
        
        logger.info(f"✅ Zoomed: {original_width}x{original_height} → {new_width}x{new_height}")
        return output
        
    except Exception as e:
        logger.error(f"❌ Image zoom error: {e}")
        return None

def get_image_info(image_data: bytes) -> Dict[str, Any]:
    """Get metadata about an image"""
    try:
        img = Image.open(io.BytesIO(image_data))
        return {
            "width": img.size[0],
            "height": img.size[1],
            "format": img.format,
            "mode": img.mode,
            "size_kb": round(len(image_data) / 1024, 1),
        }
    except:
        return {"error": "Could not read image metadata"}

# ============================================
# BOT HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_text = (
        "🔍 *Welcome to ZoomInBot!*\n\n"
        "I can zoom/enlarge any image you send me!\n\n"
        "📤 *How to use:*\n"
        "1. Send me a photo\n"
        "2. Choose a zoom level\n"
        "3. Receive your zoomed image!\n\n"
        "🛠 *Available zoom levels:*\n"
        "• 2x Zoom\n"
        "• 3x Zoom\n"
        "• 4x Zoom\n\n"
        "📸 Send me an image to get started!"
    )
    
    keyboard = [
        [InlineKeyboardButton("📸 How to Use", callback_data="help")],
        [InlineKeyboardButton("ℹ️ About", callback_data="about")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = (
        "🔍 *ZoomInBot Help*\n\n"
        "1️⃣ Send me any photo\n"
        "2️⃣ Choose a zoom level from the buttons\n"
        "3️⃣ Wait while I process it\n"
        "4️⃣ Receive your zoomed image!\n\n"
        "⚠️ *Tips:*\n"
        "• For best results, send images under 10MB\n"
        "• Larger images take longer to process\n\n"
        "🔄 *Commands:*\n"
        "/start - Show main menu\n"
        "/help - Show this help\n"
        "/cancel - Cancel current operation"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command"""
    context.user_data.pop('image_data', None)
    await update.message.reply_text(
        "✅ Operation cancelled. Send me a new image to zoom!"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos"""
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(
                f"❌ File too large! Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB."
            )
            return
        
        image_data = await file.download_as_bytearray()
        context.user_data['image_data'] = image_data
        info = get_image_info(image_data)
        
        keyboard = [
            [
                InlineKeyboardButton("🔍 2x Zoom", callback_data="zoom_2"),
                InlineKeyboardButton("🔍 3x Zoom", callback_data="zoom_3"),
            ],
            [
                InlineKeyboardButton("🔍 4x Zoom", callback_data="zoom_4"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📷 *Image received!*\n\n"
            f"📐 Size: {info.get('width', '?')}×{info.get('height', '?')}\n"
            f"📦 {info.get('size_kb', 0)} KB\n\n"
            f"Choose your zoom level:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"❌ Error handling photo: {e}")
        await update.message.reply_text(
            "❌ Error processing your image. Please try again."
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    if data == "cancel":
        context.user_data.pop('image_data', None)
        await query.edit_message_text("❌ Zoom cancelled. Send me another image to try again!")
        return
    
    if data == "help":
        help_text = (
            "📸 *How to use ZoomInBot*\n\n"
            "1. Send a photo to the bot\n"
            "2. Choose a zoom level (2x, 3x, or 4x)\n"
            "3. Wait for processing\n"
            "4. Get your zoomed image!\n\n"
            "It's that simple! 🎉"
        )
        await query.edit_message_text(help_text, parse_mode="Markdown")
        return
    
    if data == "about":
        about_text = (
            "🤖 *About ZoomInBot*\n\n"
            "I'm a Telegram bot that zooms/enlarges images!\n\n"
            "🛠 *Tech Stack:*\n"
            "• Python 3.11\n"
            "• python-telegram-bot v20\n"
            "• Pillow for image processing\n"
            "• Deployed on Railway\n\n"
            "📅 Created: 2026"
        )
        await query.edit_message_text(about_text, parse_mode="Markdown")
        return
    
    if data.startswith("zoom_"):
        zoom_factor = float(data.split("_")[1])
        
        if zoom_factor not in ALLOWED_ZOOM_FACTORS:
            await query.edit_message_text("❌ Invalid zoom level selected.")
            return
        
        image_data = context.user_data.get('image_data')
        if not image_data:
            await query.edit_message_text(
                "❌ No image found. Please send a new photo using /start"
            )
            return
        
        await query.edit_message_text(
            f"⏳ *Processing image...* ({zoom_factor}x zoom)\n\n"
            f"🔄 Resizing... This may take a few seconds.",
            parse_mode="Markdown"
        )
        
        try:
            zoomed_image = zoom_image(image_data, zoom_factor)
            
            if zoomed_image:
                original_info = get_image_info(image_data)
                new_info = get_image_info(zoomed_image.getvalue())
                
                caption = (
                    f"✅ *Zoomed {zoom_factor}x!*\n\n"
                    f"📐 Original: {original_info.get('width', '?')}×{original_info.get('height', '?')}\n"
                    f"📐 Zoomed: {new_info.get('width', '?')}×{new_info.get('height', '?')}\n"
                    f"📦 {new_info.get('size_kb', 0)} KB\n\n"
                    f"Send another image to zoom again!"
                )
                
                await query.message.reply_photo(
                    photo=zoomed_image,
                    caption=caption,
                    parse_mode="Markdown"
                )
                
                context.user_data.pop('image_data', None)
                logger.info(f"✅ User {user_id} zoomed image {zoom_factor}x")
                
            else:
                await query.message.reply_text(
                    "❌ Failed to zoom image. Please try with a smaller image."
                )
                
        except Exception as e:
            logger.error(f"❌ Error in zoom callback: {e}")
            await query.message.reply_text(
                "❌ An error occurred. Please try again."
            )

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown commands"""
    await update.message.reply_text(
        "🤔 I don't understand that command.\n\n"
        "Send me a photo and I'll zoom it for you!\n\n"
        "Type /start to see the menu."
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors globally"""
    logger.error(f"❌ Update caused error: {context.error}")

# ============================================
# FLASK ROUTES
# ============================================
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "online",
        "bot": "ZoomInBot",
        "version": "2.0",
        "timestamp": datetime.now().isoformat()
    })

@app.route("/webhook", methods=["POST"])
async def webhook():
    try:
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, application.bot)
        await application.process_update(update)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200

# ============================================
# WEBHOOK SETUP
# ============================================
async def setup_webhook():
    if not WEBHOOK_URL:
        logger.info("🌐 WEBHOOK_URL not set. Using polling mode...")
        return
    
    webhook_url = f"{WEBHOOK_URL}/webhook"
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"]
        )
        logger.info(f"✅ Webhook set to: {webhook_url}")
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")

# ============================================
# MAIN
# ============================================
def main():
    try:
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_error_handler(error_handler)
        
        # Setup webhook synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(setup_webhook())
        
        # Start Flask
        logger.info(f"🚀 Starting Flask server on port {PORT}")
        app.run(host="0.0.0.0", port=PORT, debug=False)
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
