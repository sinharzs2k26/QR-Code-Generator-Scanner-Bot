import os
import io
import logging
from dotenv import load_dotenv
import qrcode
from PIL import Image
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
import base64
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Ensure QR codes directory exists
if not os.path.exists('qr_codes'):
    os.makedirs('qr_codes')

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the command /start is issued."""
    user = update.effective_user

    welcome_message = (
        f"👋 Hello {user.first_name}!\n"
        "I'm QR Code Bot 🤖\n"
        "📌 What I can do:\n"
        "• Generate QR codes from text/links\n"
        "• Read QR codes from images\n"
        "Commands:\n"
        "/help - See how to use\n" 
        "/generate - Create QR code\n"
        "/scan - Read QR from image\n"
        "/batchqr - Generate multiple QR codes from a list"
    )
    await update.message.reply_text(welcome_message)

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send help message."""
    help_text = (
        "🤖 QR Code Bot Commands:\n\n" 
        "Basic Commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n\n"
        "QR Code Operations:\n"
        "/generate - Generate a QR code\n"
        "/scan - Scan QR code from image\n"
        "/batchqr - Generate multiple QR codes from a list\n\n"
        "How to use:\n"
        "1. Generate QR: Send /generate then enter text/URL\n"
        "2. Scan QR: Send /scan then upload an image containing QR code\n"
        "3. Batch QR: Send /batchqr then enter multiple texts/URLs\n\n"
        "Features:\n"
        "• Supports URLs, text, contact info, WiFi credentials\n"
        "• Customizable QR colors\n"
        "• Batch QR generation\n"
    )
    await update.message.reply_text(help_text)

# Generate QR code
async def generate_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start QR generation process."""
    await update.message.reply_text(
        "✨ QR Code Generator\n\n"
        "Please send me the text or URL you want to encode in the QR code.\n\n"
        "📝 Examples:\n"
        "• https://example.com\n"
        "• Your contact information\n"
        "• WiFi: WPA2;SSID;Password\n"
        "• Plain text message"
    )

    # Set state to waiting for QR text
    context.user_data['awaiting_qr_text'] = True

# Process QR text input
async def process_qr_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the text and generate QR code."""
    if context.user_data.get('awaiting_qr_text'):
        text = update.message.text

        # Ask for QR code color
        keyboard = [
            [
                InlineKeyboardButton("⚫ Black (Default)", callback_data=f'color_black_{text}'),
                InlineKeyboardButton("🔵 Blue", callback_data=f'color_blue_{text}')
            ],
            [
                InlineKeyboardButton("🔴 Red", callback_data=f'color_red_{text}'),
                InlineKeyboardButton("🟢 Green", callback_data=f'color_green_{text}')
            ],
            [
                InlineKeyboardButton("🟣 Purple", callback_data=f'color_purple_{text}')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"📝 Text to encode:\n{text[:50]}{'...' if len(text) > 50 else ''}\n\n"
            "Choose QR code color:",
            reply_markup=reply_markup,
        )

        # Reset state
        context.user_data['awaiting_qr_text'] = False

# Generate QR with specific color
async def generate_qr_with_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate QR code with chosen color."""
    query = update.callback_query
    await query.answer()

    # Parse callback data
    data = query.data
    color_name = data.split('_')[1]
    text = '_'.join(data.split('_')[2:])  # Reconstruct text

    # Map color names to RGB
    color_map = {
        'black': (0, 0, 0),
        'blue': (0, 0, 255),
        'red': (255, 0, 0),
        'green': (0, 128, 0),
        'purple': (128, 0, 128)
    }

    fill_color = color_map.get(color_name, (0, 0, 0))

    # Generate QR code
    try:
        await query.edit_message_text(f"🎨 Generating {color_name} QR code...")

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)

        # Create QR image
        img = qr.make_image(fill_color=fill_color, back_color="white")

        # Convert to bytes
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)

        # Send QR code
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=bio,
            caption=f"✅ QR Code Generated!\n\n"
                   f"Content: {text[:100]}{'...' if len(text) > 100 else ''}\n"
                   f"Color: {color_name.capitalize()}"
        )

    except Exception as e:
        logger.error(f"Error generating QR: {e}")
        await query.edit_message_text("❌ Error generating QR code. Please try again.")

# Scan QR code from image
async def scan_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start QR scanning process."""
    await update.message.reply_text(
        "📸 QR Code Scanner\n\n"
        "Please send me an image containing a QR code.\n\n"
        "📌 Tips:\n"
        "• Ensure good lighting\n"
        "• QR code should be clear and centered\n"
        "• Send as photo (not as file)"
    )

    # Set state to waiting for image
    context.user_data['awaiting_qr_image'] = True

# New scanning function using pure Python
async def process_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process uploaded image and scan for QR codes."""
    if context.user_data.get('awaiting_qr_image'):
        try:
            # Get the photo
            photo_file = await update.message.photo[-1].get_file()

            # Download photo to bytes
            photo_bytes = io.BytesIO()
            await photo_file.download_to_memory(photo_bytes)
            photo_bytes.seek(0)

            # Convert to PIL Image
            image = Image.open(photo_bytes)

            # Upload to a free QR decoding API
            response = requests.post(
                'https://api.qrserver.com/v1/read-qr-code/',
                files={'file': ('qr.png', photo_bytes.getvalue(), 'image/png')}
            )

            if response.status_code == 200:
                data = response.json()
                if data[0]['symbol'][0]['data']:
                    qr_data = data[0]['symbol'][0]['data']
                    # Format the response
                    if qr_data.startswith('http'):
                        formatted_data = f"🔗 Link: [{qr_data}]({qr_data})"
                    elif 'WIFI:' in qr_data.upper():
                        formatted_data = f"📶 WiFi Config: {qr_data}"
                    else:
                        formatted_data = f"📝 Text: {qr_data}"

                    await update.message.reply_text(
                        f"✅ QR Code Detected!\n\n{formatted_data}",
                    )
                else:
                    await update.message.reply_text("❌ No QR code found in the image.")
            else:
                await update.message.reply_text("❌ Error scanning QR code. Please try again.")

        except Exception as e:
            logger.error(f"Error scanning QR: {e}")
            await update.message.reply_text("❌ Error processing image. Please try again.")

        # Reset state
        context.user_data['awaiting_qr_image'] = False

# Handle button callbacks
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()

    if query.data.startswith('color_'):
        await generate_qr_with_color(update, context)

    # Set state
    context.user_data['awaiting_qr_text'] = True

# Batch QR generation
async def batch_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate multiple QR codes from a list."""
    if context.args:
        texts = ' '.join(context.args).split(',')

        if len(texts) > 5:
            await update.message.reply_text("⚠️ Please limit to 5 QR codes at a time.")
            return

        await update.message.reply_text(f"Generating {len(texts)} QR codes...")

        for i, text in enumerate(texts, 1):
            text = text.strip()
            if text:
                qr = qrcode.make(text)
                bio = io.BytesIO()
                qr.save(bio, 'PNG')
                bio.seek(0)

                await update.message.reply_photo(
                    photo=bio,
                    caption=f"QR #{i}: {text[:50]}{'...' if len(text) > 50 else ''}",
                )
    else:
        await update.message.reply_text(
            "📦 Batch QR Generator\n\n"
            "Usage: /batchqr text1, text2, text3\n\n"
            "Example: /batchqr https://google.com, Hello World, WIFI:S:MyNetwork;T:WPA;P:mypassword;",
        )

# Error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors."""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An error occurred. Please try again later."
        )

# Main function
def main():
    """Start the bot."""
    # Create application
    application = Application.builder().token(TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("generate", generate_qr))
    application.add_handler(CommandHandler("scan", scan_qr))
    application.add_handler(CommandHandler("batchqr", batch_qr))

    # Add callback handler for buttons
    application.add_handler(CallbackQueryHandler(button_handler))

    # Add message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_qr_text))
    application.add_handler(MessageHandler(filters.PHOTO, process_image))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the bot
    print("🤖 QR Code Bot is starting...")
    print("Press Ctrl+C to stop")

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is alive!')

        def log_message(self, format, *args):
            pass  # Silence logs

    def run_health_server():
        port = int(os.environ.get("PORT", 10000))
        httpd = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"✅ Health server on port {port}")
        httpd.serve_forever()

    # Start health server
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
       )

if __name__ == '__main__':
    main()