import os
import asyncio
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# تفعيل سجل الأخطاء
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# 1. كود فتح منفذ الويب (مهم جداً لسيرفر Render)
class WebServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is Running 24/7!")

def run_web_server():
    # جلب المنفذ الذي يحدده سيرفر Render تلقائياً
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), WebServerHandler)
    print(f"Web server started on port {port}")
    server.serve_forever()

# 2. دالة الترحيب بالبون
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(f"أهلاً بك يا {user_name} في نظام البيانات الذكي على سيرفر Render! 🤖✨")

def main():
    TOKEN = "8628368615:AAGoTAvfL-yZgkSnjYxqXAlJgXZZn9eeEL0"
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    
    # تشغيل سيرفر الويب في خلفية منفصلة
    Thread(target=run_web_server, daemon=True).start()
    
    print("البوت بدأ العمل والاستماع للرسائل...")
    app.run_polling(close_loop=False)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except RuntimeError:
        import nest_asyncio
        nest_asyncio.apply()
        main()
