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
import requests

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
class Config:
    """Configuration settings for the bot"""
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
    PORT = int(os.environ.get("PORT", 5000))  # FIXED: Proper port handling
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
    ALLOWED_ZOOM_FACTORS = [2.0, 3.0, 4.0]
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        if not cls.TOKEN:
            logger.error("❌ TELEGRAM_BOT_TOKEN environment variable is required!")
            sys.exit(1)
        if not cls.WEBHOOK_URL:
            logger.warning("⚠️ WEBHOOK_URL not set. Bot will use polling mode.")

# Validate config on startup
Config.validate()

# ============================================
# FLASK APP INITIALIZATION
# ============================================
app = Flask(__name__)

# ============================================
# TELEGRAM BOT INITIALIZATION
# ============================================
application = Application.builder().token(Config.TOKEN).build()

# ============================================
# IMAGE PROCESSING FUNCTIONS
# ============================================
class ImageProcessor:
    """Handles all image processing operations"""
    
    @staticmethod
    def zoom_image(image_data: bytes, zoom_factor: float) -> Optional[io.BytesIO]:
        """
        Zoom/enlarge an image by a given factor
        
        Args:
            image_data: Raw image bytes
            zoom_factor: Multiplication factor (e.g., 2.0 for 2x)
        
        Returns:
            BytesIO object containing the zoomed image, or None on error
        """
        try:
            # Open image from bytes
            img = Image.open(io.BytesIO(image_data))
            
            # Get original dimensions
            original_width, original_height = img.size
            
            # Calculate new dimensions
            new_width = int(original_width * zoom_factor)
            new_height = int(original_height * zoom_factor)
            
            # Validate size (prevent memory issues)
            if new_width > 8000 or new_height > 8000:
                logger.warning(f"Zoomed image too large: {new_width}x{new_height}")
                return None
            
            # Resize using high-quality LANCZOS resampling
            zoomed = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Save to bytes (use PNG for quality)
            output = io.BytesIO()
            zoomed.save(output, format="PNG", optimize=True)
            output.seek(0)
            
            logger.info(f"✅ Zoomed image: {original_width}x{original_height} → {new_width}x{new_height}")
            return output
            
        except Exception as e:
            logger.error(f"❌ Image zoom error: {e}")
            return None
    
    @staticmethod
    def get_image_info(image_data: bytes) -> Dict[str, Any]:
        """Get metadata about an image"""
        try:
            img = Image.open(io.BytesIO(image_data))
            return {
                "width": img.size[0],
                "height": img.size[1],
                "format": img.format,
                "mode": img.mode,
                "size_bytes": len(image_data),
                "size_kb": round(len(image_data) / 1024, 1),
            }
        except:
            return {"error": "Could not read image metadata"}

# ============================================
# BOT COMMAND HANDLERS
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
        "• Larger images take longer to process\n"
        "• You can send multiple images\n\n"
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
        # Get the highest quality photo
        photo = update.message.photo[-1]
        file = await photo.get_file()
        
        # Check file size
        if file.file_size > Config.MAX_FILE_SIZE:
            await update.message.reply_text(
                f"❌ File too large! Maximum size is {Config.MAX_FILE_SIZE // (1024*1024)}MB."
            )
            return
        
        # Download image data
        image_data = await file.download_as_bytearray()
        
        # Store in user context
        context.user_data['image_data'] = image_data
        
        # Get image info for user feedback
        info = ImageProcessor.get_image_info(image_data)
        
        # Show zoom options
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
            "❌ Error processing your image. Please try again with a different image."
        )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    # Handle cancel
    if data == "cancel":
        context.user_data.pop('image_data', None)
        await query.edit_message_text("❌ Zoom cancelled. Send me another image to try again!")
        return
    
    # Handle help
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
    
    # Handle about
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
    
    # Handle zoom levels
    if data.startswith("zoom_"):
        zoom_factor = float(data.split("_")[1])
        
        # Validate zoom factor
        if zoom_factor not in Config.ALLOWED_ZOOM_FACTORS:
            await query.edit_message_text("❌ Invalid zoom level selected.")
            return
        
        # Get stored image
        image_data = context.user_data.get('image_data')
        if not image_data:
            await query.edit_message_text(
                "❌ No image found. Please send a new photo using /start"
            )
            return
        
        # Show processing status
        await query.edit_message_text(
            f"⏳ *Processing image...* ({zoom_factor}x zoom)\n\n"
            f"🔄 Resizing... This may take a few seconds.",
            parse_mode="Markdown"
        )
        
        try:
            # Process the image
            zoomed_image = ImageProcessor.zoom_image(image_data, zoom_factor)
            
            if zoomed_image:
                # Get original and new sizes
                original_info = ImageProcessor.get_image_info(image_data)
                new_info = ImageProcessor.get_image_info(zoomed_image.getvalue())
                
                # Send zoomed image
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
                
                # Clean up stored image
                context.user_data.pop('image_data', None)
                logger.info(f"✅ User {user_id} zoomed image {zoom_factor}x")
                
            else:
                await query.message.reply_text(
                    "❌ Failed to zoom image. Please try with a smaller image or different format."
                )
                
        except Exception as e:
            logger.error(f"❌ Error in zoom callback: {e}")
            await query.message.reply_text(
                "❌ An error occurred while processing your image. Please try again."
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
    logger.error(f"❌ Update {update} caused error: {context.error}")
    
    # Notify user if possible
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Something went wrong. Please try again or use /start to restart."
        )

# ============================================
# FLASK ROUTES
# ============================================
@app.route("/", methods=["GET"])
def index():
    """Health check endpoint"""
    return jsonify({
        "status": "online",
        "bot": "ZoomInBot",
        "version": "2.0",
        "timestamp": datetime.now().isoformat(),
        "environment": "Railway"
    })


@app.route("/webhook", methods=["POST"])
async def webhook():
    """Handle incoming Telegram updates via webhook"""
    try:
        # Parse update data
        update_data = request.get_json(force=True)
        update = Update.de_json(update_data, application.bot)
        
        # Process update
        await application.process_update(update)
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    """Detailed health check"""
    return jsonify({
        "status": "healthy",
        "bot_token": "✓" if Config.TOKEN else "✗",
        "webhook_url": Config.WEBHOOK_URL or "Not set (polling mode)",
        "port": Config.PORT
    })

# ============================================
# WEBHOOK SETUP
# ============================================
async def setup_webhook():
    """Configure the bot's webhook"""
    if not Config.WEBHOOK_URL:
        logger.info("🌐 Running in polling mode...")
        return
    
    webhook_url = f"{Config.WEBHOOK_URL}/webhook"
    try:
        # Remove any existing webhook
        await application.bot.delete_webhook(drop_pending_updates=True)
        
        # Set new webhook
        await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"]
        )
        logger.info(f"✅ Webhook set to: {webhook_url}")
        
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")

# ============================================
# MAIN ENTRY POINT
# ============================================
def main():
    """Main application entry point"""
    try:
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_error_handler(error_handler)
        
        # Setup webhook
        asyncio.run(setup_webhook())
        
        # Start Flask server - FIXED: Proper port handling
        port = int(os.environ.get("PORT", 5000))
        logger.info(f"🚀 Starting Flask server on port {port}")
        app.run(host="0.0.0.0", port=port, debug=False)
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
