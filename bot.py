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

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")

if not os.path.exists('qr_codes'):
    os.makedirs('qr_codes')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_message = (
        f"👋 <b>Hello {user.first_name}!</b>\n\n"
        "I'm QR Code Bot 🤖\n\n"
        "📌 <b>What I can do:</b>\n"
        "• Generate QR codes from text/links\n"
        "• Read QR codes from images\n\n"
        "⚙️ <b>Commands:</b>\n"
        "/help - See how to use\n" 
        "/generate - Create QR code\n"
        "/scan - Read QR from image\n"
        "/batchqr - Generate multiple QR codes from a list"
    )
    await update.message.reply_text(welcome_message, parse_mode="HTML")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 <b>QR Code Bot Commands:</b>\n\n" 
        "<b>• Basic Commands:</b>\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n\n"
        "<b>• QR Code Operations:</b>\n"
        "/generate - Generate a QR code\n"
        "/scan - Scan QR code from image\n"
        "/batchqr - Generate multiple QR codes from a list\n\n"
        "📌 <b>How to use:</b>\n"
        "1. <b>Generate QR:</b> Send /generate then enter text/URL\n"
        "2. <b>Scan QR:</b> Send /scan then upload an image containing QR code\n"
        "3. <b>Batch QR:</b> Send /batchqr then enter multiple texts/URLs\n\n"
        "✨ <b>Features:</b>\n"
        "• Supports URLs, text, contact info, WiFi credentials\n"
        "• Customizable QR colors\n"
        "• Batch QR generation\n"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

async def generate_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "✨ <b>QR Code Generator</b>\n\n"
        "Please send me the text or URL you want to encode in the QR code.\n\n"
        "📝 <b>Examples:</b>\n"
        "• <code>https://example.com</code>\n"
        "• Your contact information\n"
        "• WiFi: WPA2;SSID;Password\n"
        "• Plain text message"
    )
    
    context.user_data['awaiting_qr_text'] = True

async def process_qr_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_qr_text'):
        text = update.message.text
        keyboard = [
            [
                InlineKeyboardButton("⚫ Black (Default)", callback_data=f'color_black_{text}')
            ],
            [
                InlineKeyboardButton("🔵 Blue", callback_data=f'color_blue_{text}'),
                InlineKeyboardButton("🔴 Red", callback_data=f'color_red_{text}'),
            ],
            [
                InlineKeyboardButton("🟢 Green", callback_data=f'color_green_{text}'),
                InlineKeyboardButton("🟣 Purple", callback_data=f'color_purple_{text}')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_html(
            f"📝 <b>Text to encode:</b>\n<code>{text[:50]}{'...' if len(text) > 50 else ''}</code>\n\n"
            "Choose QR code color:",
            reply_markup=reply_markup
        )
        context.user_data['awaiting_qr_text'] = False

async def generate_qr_with_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    color_name = data.split('_')[1]
    text = '_'.join(data.split('_')[2:])
    color_map = {
        'black': (0, 0, 0),
        'blue': (0, 0, 255),
        'red': (255, 0, 0),
        'green': (0, 128, 0),
        'purple': (128, 0, 128)
    }
    fill_color = color_map.get(color_name, (0, 0, 0))
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
        img = qr.make_image(fill_color=fill_color, back_color="white")
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=bio,
            caption=f"✅ <b>QR Code Generated!</b>\n\n"
                   f"<b>Content:</b> <code>{text[:100]}{'...' if len(text) > 100 else ''}</code>\n"
                   f"<b>Color:</b> {color_name.capitalize()}",
                   parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error generating QR: {e}")
        await query.edit_message_text("❌ Error generating QR code. Please try again.")

async def scan_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "📸 <b>QR Code Scanner</b>\n\n"
        "Please send me an image containing a QR code.\n\n"
        "📌 <b>Tips:</b>\n"
        "• Ensure good lighting\n"
        "• QR code should be clear and centered\n"
        "• Send as photo (not as file)"
    )
    context.user_data['awaiting_qr_image'] = True

async def process_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_qr_image'):
        try:
            await update.message.reply_text("🔍 Scanning QR code")
            photo_file = await update.message.photo[-1].get_file()
            photo_bytes = io.BytesIO()
            await photo_file.download_to_memory(photo_bytes)
            photo_bytes.seek(0)
            image = Image.open(photo_bytes)
            response = requests.post(
                'https://api.qrserver.com/v1/read-qr-code/',
                files={'file': ('qr.png', photo_bytes.getvalue(), 'image/png')}
            )
            if response.status_code == 200:
                data = response.json()
                if data[0]['symbol'][0]['data']:
                    qr_data = data[0]['symbol'][0]['data']
                    if qr_data.startswith('http'):
                        formatted_data = f"🔗 <b>Link:</b> <code>{qr_data}</code>"
                    elif 'WIFI:' in qr_data.upper():
                        formatted_data = f"📶 <b>WiFi Config:</b> <code>{qr_data}</code>"
                    else:
                        formatted_data = f"📝 <b>Text:</b> <code>{qr_data}</code>"

                    await update.message.reply_html(
                        f"✅ <b>QR Code Detected!</b>\n\n{formatted_data}",
                    )
                else:
                    await update.message.reply_text("❌ No QR code found in the image.")
            else:
                await update.message.reply_text("❌ Error scanning QR code. Please try again.")
        except Exception as e:
            logger.error(f"Error scanning QR: {e}")
            await update.message.reply_text("❌ Error processing image. Please try again.")
        context.user_data['awaiting_qr_image'] = False

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith('color_'):
        await generate_qr_with_color(update, context)
    context.user_data['awaiting_qr_text'] = True

async def batch_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    caption=f"QR #{i}: <code>{text[:50]}{'...' if len(text) > 50 else ''}</code>",
                    parse_mode="HTML"
                )
    else:
        await update.message.reply_html(
            "📦 <b>Batch QR Generator</b>\n\n"
            "Usage: /batchqr <code>text1, text2, text3</code>\n\n"
            "Example: /batchqr <code>https://google.com, Hello World, WIFI:S:MyNetwork;T:WPA;P:mypassword;</code>",
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An error occurred. Please try again later."
        )

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("generate", generate_qr))
    app.add_handler(CommandHandler("scan", scan_qr))
    app.add_handler(CommandHandler("batchqr", batch_qr))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_qr_text))
    app.add_handler(MessageHandler(filters.PHOTO, process_image))
    app.add_error_handler(error_handler)
    
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
        httpd = HTTPServer(('0.0.0.0', 10000), HealthHandler)
        logger.info(f"✅ Health server on port 10000")
        httpd.serve_forever()
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
       )

if __name__ == '__main__':
    main()