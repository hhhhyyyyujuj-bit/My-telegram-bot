import asyncio
import sqlite3
import smtplib
import ssl
import logging
import warnings
import time
from datetime import datetime
from email.message import EmailMessage

warnings.filterwarnings("ignore")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ======================== الإعدادات ========================
BOT_TOKEN = "9227756385:AAHv1SGUvKugNEkt53Zw71_FAJm7XwOSNJQ"
ADMIN_ID = 8150202704
FORCE_CHANNEL = "@atlaseeq"
FORCE_CHANNEL_LINK = "https://t.me/atlaseeq"
DEVELOPER_USERNAME = "@nhnhhnhn"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DB_PATH = "bot_data.db"
ACTIVE_REPORTS = {} # يتتبع المستخدمين النشطين حالياً

# 🚦 صمام أمان قصوى: يسمح بـ 50 عملية إرسال متزامنة بالبوت كله (لحماية الاستضافة)
GLOBAL_SEMAPHORE = asyncio.Semaphore(50)

# ======================== دوال مساعدة ========================
def safe_format(template, **kwargs):
    if not template: return ""
    result = str(template)
    for k, v in kwargs.items():
        result = result.replace(f"{{{k}}}", str(v))
    return result

def make_button(text, callback_data=None, url=None, style=None):
    kwargs = {"text": text}
    if callback_data is not None: kwargs["callback_data"] = callback_data
    if url is not None: kwargs["url"] = url
    if style is not None: kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)

# ======================== قواميس الترجمة ========================
BUTTON_NAMES = {
    "btn_support": "زر بريد الدعم", "btn_subject": "زر الموضوع",
    "btn_template": "زر الكليشه", "btn_delay": "زر الفاصل الزمني",
    "btn_count": "زر عدد الإبلاغات", "btn_start": "زر بدء الإبلاغ",
    "btn_stop": "زر إيقاف الإبلاغ", "btn_developer": "زر مطور البوت", 
    "btn_admin": "زر لوحة الأدمن", "btn_join_channel": "زر اشترك في القناة", 
    "btn_check_sub": "زر تحقق من الاشتراك",
}

TEXT_NAMES = {
    "welcome_text": "رسالة الترحيب الرئيسية", "force_sub_text": "رسالة الاشتراك الإجباري",
    "msg_sub_verified": "رسالة (تم التحقق من الاشتراك)", "msg_not_subscribed_alert": "رسالة منبثقة (لم تشترك بعد)",
    "msg_bot_stopped": "رسالة (البوت متوقف حالياً)", "msg_banned": "رسالة (أنت محظور)",
    "prompt_support": "نص طلب (بريد الدعم)", "prompt_subject": "نص طلب (الموضوع)",
    "prompt_template": "نص طلب (الكليشه)", "prompt_delay": "نص طلب (الفاصل الزمني)",
    "prompt_count": "نص طلب (عدد الإبلاغات)", "msg_support_saved": "رسالة (تم حفظ بريد الدعم)",
    "msg_subject_saved": "رسالة (تم حفظ الموضوع)", "msg_template_saved": "رسالة (تم حفظ الكليشه)",
    "msg_delay_saved": "رسالة (تم حفظ الفاصل)", "msg_count_saved": "رسالة (تم حفظ العدد)",
    "err_invalid_delay": "رسالة خطأ (رقم الفاصل غير صحيح)", "err_invalid_count": "رسالة خطأ (رقم العدد غير صحيح)",
    "msg_missing_settings": "رسالة (ناقصك إعدادات)", "msg_report_already_running": "رسالة (لديك إبلاغ قيد التنفيذ)",
    "msg_starting_report": "رسالة (جاري بدء الإبلاغ...)", "msg_no_accounts_available": "رسالة (لا توجد حسابات جاهزة)",
    "msg_stop_sent_alert": "رسالة (تم إرسال أمر الإيقاف)", "msg_report_stopped_manual": "رسالة (تم إيقاف الإبلاغ)",
    "msg_no_active_report_alert": "رسالة (لا يوجد إبلاغ نشط)", "msg_report_progress_init": "رسالة بدء العداد",
    "msg_report_progress_update": "رسالة تحديث العداد", "msg_report_final_result": "رسالة النتيجة النهائية",
    "msg_report_status_stopped": "نص (تم الإيقاف يدوياً)", "msg_report_status_completed": "نص (اكتمل الإرسال)",
    "msg_admin_sub_warning": "تنبيه (البوت ليس أدمن في القناة)", "adm_welcome": "رسالة ترحيب لوحة الأدمن",
    "adm_prompt_email": "نص طلب (بريد الحساب التلقائي)", "adm_prompt_pass": "نص طلب (كلمة مرور التطبيق)",
    "adm_msg_acc_added": "رسالة (تمت إضافة الحساب)", "adm_msg_invalid_email": "رسالة خطأ (بريد غير صالح)",
    "adm_prompt_select_del": "نص طلب (اختر الحساب للحذف)", "adm_msg_no_accounts": "رسالة (لا توجد حسابات)",
    "adm_msg_acc_deleted": "رسالة (تم حذف الحساب)", "adm_msg_checking": "رسالة (جاري فحص الحسابات...)",
    "adm_msg_check_results": "نتائج الفحص", "adm_prompt_ban_id": "نص طلب (آيدي المستخدم للحظر)",
    "adm_prompt_unban_id": "نص طلب (آيدي المستخدم لفك الحظر)", "adm_msg_banned": "رسالة (تم حظر المستخدم)",
    "adm_msg_unbanned": "رسالة (تم فك حظر المستخدم)", "adm_msg_invalid_id": "رسالة خطأ (آيدي غير صالح)",
    "adm_prompt_bc_all": "نص طلب (رسالة البث للجميع)", "adm_prompt_bc_one_id": "نص طلب (آيدي المستهدف للبث)",
    "adm_prompt_bc_msg": "نص طلب (نص الرسالة للبث)", "adm_msg_broadcast_done": "رسالة (تم البث بنجاح)",
    "adm_msg_sent": "رسالة (تم الإرسال)", "adm_msg_send_failed": "رسالة (فشل الإرسال)",
    "adm_prompt_edit_text": "نص طلب (اختر النص للتعديل)", "adm_prompt_new_text": "نص طلب تعديل النص",
    "adm_msg_text_updated": "رسالة (تم تحديث النص)", "adm_prompt_edit_btn": "نص طلب (اختر الزر للتعديل)",
    "adm_prompt_btn_options": "نص خيارات الزر", "adm_prompt_new_btn_name": "نص طلب (اسم الزر الجديد)",
    "adm_prompt_new_btn_color": "نص طلب (اختر اللون الجديد)", "adm_msg_btn_color_changed": "رسالة (تم تغيير لون الزر)",
    "adm_msg_btn_name_updated": "رسالة (تم تحديث اسم الزر)", "adm_msg_no_users": "رسالة (لا يوجد مستخدمين)",
    "adm_msg_users_list": "قائمة المستخدمين", "adm_msg_toggle_status": "رسالة (حالة البوت)",
}

# ======================== قاعدة البيانات ========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, is_banned INTEGER DEFAULT 0, joined_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS report_settings (user_id INTEGER PRIMARY KEY, support_email TEXT, subject TEXT, template TEXT, delay_seconds INTEGER, report_count INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admin_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, password TEXT, provider TEXT, is_active INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_texts (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_buttons (key TEXT PRIMARY KEY, text TEXT, style TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)''')

    try: c.execute("PRAGMA table_info(report_settings)"); columns = c.fetchall(); needs_migration = False
    except: needs_migration = False

    for col in columns:
        if col[1] == 'delay_seconds' and col[4] is not None:
            needs_migration = True
            break
    
    if needs_migration:
        c.execute("ALTER TABLE report_settings RENAME TO report_settings_bak")
        c.execute('''CREATE TABLE report_settings (user_id INTEGER PRIMARY KEY, support_email TEXT, subject TEXT, template TEXT, delay_seconds INTEGER, report_count INTEGER)''')
        c.execute('''INSERT INTO report_settings (user_id, support_email, subject, template, delay_seconds, report_count) SELECT user_id, support_email, subject, template, NULL, NULL FROM report_settings_bak''')
        c.execute("DROP TABLE report_settings_bak")
        logger.info("✅ تم ترحيل قاعدة البيانات بنجاح.")

    default_texts = {
        "welcome_text": "👋 أهلاً بك في بوت الإبلاغ!\n\nقم بإكمال الإعدادات ثم اضغط بدء الإبلاغ:",
        "force_sub_text": "🔒 عذراً، يجب عليك الاشتراك في قناتنا أولاً لاستخدام البوت.",
        "msg_sub_verified": "✅ تم التحقق!", "msg_not_subscribed_alert": "❌ لم تشترك بعد!",
        "msg_bot_stopped": "⛔ البوت متوقف حالياً.", "msg_banned": "🚫 أنت محظور.",
        "prompt_support": "📧 أرسل <b>بريد الدعم</b>:", "prompt_subject": "📝 أرسل <b>الموضوع</b>:",
        "prompt_template": "📄 أرسل <b>نص الكليشه</b>:", "prompt_delay": "⏱️ أرسل <b>الفاصل الزمني</b> (1 - 180):",
        "prompt_count": "🔢 أرسل <b>عدد الإبلاغات</b>:", "msg_support_saved": "✅ بريد الدعم: <code>{text}</code>",
        "msg_subject_saved": "✅ تم حفظ الموضوع.", "msg_template_saved": "✅ تم حفظ الكليشه.",
        "msg_delay_saved": "✅ الفاصل: {val} ثانية.", "msg_count_saved": "✅ العدد: {val}.",
        "err_invalid_delay": "❌ أرسل رقماً بين 1 و 180:", "err_invalid_count": "❌ أرسل رقماً أكبر من 0:",
        "msg_missing_settings": "⚠️ ناقصك الإعدادات التالية:\n{missing}\n\nيرجى إكمالها أولاً.",
        "msg_report_already_running": "⚠️ لديك إبلاغ قيد التنفيذ حالياً.",
        "msg_starting_report": "⏳ جاري بدء الإبلاغ وتوزيع الحسابات...",
        "msg_no_accounts_available": "⚠️ لا توجد حسابات جاهزة حالياً.",
        "msg_stop_sent_alert": "⏹️ تم إرسال أمر الإيقاف بنجاح!", "msg_report_stopped_manual": "⏹️ تم إيقاف الإبلاغ.",
        "msg_no_active_report_alert": "لا يوجد إبلاغ نشط حالياً.",
        "msg_report_progress_init": "📊 جاري الإبلاغ...\n✅ ناجح: 0\n❌ فاشل: 0\n👥 تم تخصيص {acc_count} حساب لك.",
        "msg_report_progress_update": "📊 جاري الإبلاغ...\n✅ ناجح: {success}\n❌ فاشل: {fail}\n📨 المتبقي: {remaining}\n👥 حساب: {acc_count}",
        "msg_report_final_result": "📊 <b>النتيجة النهائية:</b>\n✅ ناجح: {success}\n❌ فاشل: {fail}\n{status}",
        "msg_report_status_stopped": "⏹️ تم الإيقاف يدوياً.", "msg_report_status_completed": "✅ اكتمل الإرسال.",
        "msg_admin_sub_warning": "⚠️ تنبيه: البوت لا يستطيع فحص الاشتراك لأنه ليس أدمن في القناة.\nالخطأ: {error}",
        "adm_welcome": "⚙️ <b>لوحة الأدمن:</b>", "adm_prompt_email": "📧 أرسل <b>البريد</b>:",
        "adm_prompt_pass": "🔑 أرسل <b>كلمة مرور التطبيق</b>:", "adm_msg_acc_added": "✅ تمت إضافة الحساب.",
        "adm_msg_invalid_email": "❌ بريد غير صالح:", "adm_prompt_select_del": "اختر الحساب للحذف:",
        "adm_msg_no_accounts": "لا توجد حسابات.", "adm_msg_acc_deleted": "✅ تم حذف الحساب.",
        "adm_msg_checking": "🔍 جاري الفحص...", "adm_msg_check_results": "🔍 <b>نتائج الفحص:</b>\n{results}",
        "adm_prompt_ban_id": "🚫 أرسل <b>آيدي</b> المستخدم للحظر:", "adm_prompt_unban_id": "✅ أرسل <b>آيدي</b> المستخدم لفك الحظر:",
        "adm_msg_banned": "🚫 تم حظر <code>{target}</code>.", "adm_msg_unbanned": "✅ تم فك حظر <code>{target}</code>.",
        "adm_msg_invalid_id": "❌ آيدي غير صالح:", "adm_prompt_bc_all": "📢 أرسل <b>الرسالة</b> للجميع:",
        "adm_prompt_bc_one_id": "✉️ أرسل <b>آيدي</b> المستخدم المستهدف:", "adm_prompt_bc_msg": "✉️ أرسل <b>نص الرسالة</b>:",
        "adm_msg_broadcast_done": "✅ تم البث إلى {sent} مستخدم.", "adm_msg_sent": "✅ تم الإرسال.",
        "adm_msg_send_failed": "❌ فشل: {error}", "adm_prompt_edit_text": "اختر النص الذي تريد تعديله:",
        "adm_prompt_new_text": "✏️ النص الحالي لـ (<b>{name}</b>):\n\n<blockquote>{current}</blockquote>\n\nأرسل النص الجديد الآن:",
        "adm_msg_text_updated": "✅ تم تحديث النص بنجاح!", "adm_prompt_edit_btn": "اختر الزر الذي تريد تعديله:",
        "adm_prompt_btn_options": "أنت تعدل: <b>{name}</b>\nالاسم الحالي: <code>{current}</code>\nاللون الحالي: <code>{style}</code>\n\nماذا تريد أن تفعل؟",
        "adm_prompt_new_btn_name": "✏️ أرسل <b>الاسم الجديد</b> للزر:", "adm_prompt_new_btn_color": "🎨 اختر اللون الجديد للزر:",
        "adm_msg_btn_color_changed": "✅ تم تغيير لون الزر إلى <code>{color}</code> بنجاح!", "adm_msg_btn_name_updated": "✅ تم تحديث اسم الزر بنجاح!",
        "adm_msg_no_users": "❌ لم يقم أي مستخدم بتشغيل البوت حتى الآن.", "adm_msg_users_list": "👥 <b>المستخدمون ({count}):</b>\n\n{users}",
        "adm_msg_toggle_status": "✅ الحالة: {status}",
    }
    for k, v in default_texts.items(): c.execute("INSERT OR IGNORE INTO bot_texts (key, value) VALUES (?, ?)", (k, v))
    default_buttons = {
        "btn_support": ("📧 بريد الدعم", "primary"), "btn_subject": ("📝 الموضوع", "primary"),
        "btn_template": ("📄 الكليشه", "primary"), "btn_delay": ("⏱️ الفاصل الزمني", "primary"),
        "btn_count": ("🔢 عدد الإبلاغات", "primary"), "btn_start": ("🚀 بدء الإبلاغ", "success"),
        "btn_stop": ("⏹️ إيقاف الإبلاغ", "danger"), "btn_developer": ("👨‍💻 مطور البوت", "primary"), 
        "btn_admin": ("⚙️ لوحة الأدمن", "danger"), "btn_join_channel": ("📢 اشترك في القناة", "primary"), 
        "btn_check_sub": ("✅ تحقق من الاشتراك", "success"),
    }
    for k, (t, s) in default_buttons.items(): c.execute("INSERT OR IGNORE INTO bot_buttons (key, text, style) VALUES (?, ?, ?)", (k, t, s))
    conn.commit(); conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def get_text(key, default=""):
    conn = get_db(); row = conn.execute("SELECT value FROM bot_texts WHERE key=?", (key,)).fetchone(); conn.close()
    return row["value"] if row else default

def get_button(key, default_text="", default_style="primary"):
    conn = get_db(); row = conn.execute("SELECT text, style FROM bot_buttons WHERE key=?", (key,)).fetchone(); conn.close()
    if row: return row["text"], (row["style"] or default_style)
    return default_text, default_style

def set_text(key, value):
    conn = get_db(); conn.execute("INSERT OR REPLACE INTO bot_texts (key, value) VALUES (?, ?)", (key, value)); conn.commit(); conn.close()

def set_button(key, text, style):
    conn = get_db(); conn.execute("INSERT OR REPLACE INTO bot_buttons (key, text, style) VALUES (?, ?, ?)", (key, text, style)); conn.commit(); conn.close()

def update_report_setting(user_id, column, value):
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM report_settings WHERE user_id=?", (user_id,))
    if cursor.fetchone(): cursor.execute(f"UPDATE report_settings SET {column}=? WHERE user_id=?", (value, user_id))
    else: cursor.execute(f"INSERT INTO report_settings (user_id, {column}) VALUES (?, ?)", (user_id, value))
    conn.commit(); conn.close()

def is_bot_active():
    conn = get_db(); row = conn.execute("SELECT value FROM bot_state WHERE key='active'").fetchone(); conn.close()
    return (row["value"] == "1") if row else True

def set_bot_active(active):
    conn = get_db(); conn.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES ('active', ?)", ("1" if active else "0",)); conn.commit(); conn.close()

def register_user(user_id, username):
    try:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO users (user_id, username, joined_at) VALUES (?, ?, ?)", (user_id, username, datetime.now().isoformat()))
        conn.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
        conn.commit(); conn.close()
    except Exception as e: logger.error(f"Error registering user: {e}")

def is_banned(user_id):
    conn = get_db(); row = conn.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone(); conn.close()
    return (row["is_banned"] == 1) if row else False

def ban_user(user_id, banned=True):
    conn = get_db(); conn.execute("UPDATE users SET is_banned=? WHERE user_id=?", (1 if banned else 0, user_id)); conn.commit(); conn.close()

# ======================== إرسال البريد ========================
def send_email_sync(sender_email, sender_pass, support_email, subject, body):
    try:
        msg = EmailMessage(); msg.set_content(body); msg['Subject'] = subject; msg['From'] = sender_email; msg['To'] = support_email
        domain = sender_email.split('@')[-1].lower()
        if "gmail" in domain: server_addr, port = "smtp.gmail.com", 587
        elif "hotmail" in domain or "outlook" in domain or "live" in domain: server_addr, port = "smtp-mail.outlook.com", 587
        elif "yahoo" in domain: server_addr, port = "smtp.mail.yahoo.com", 587
        elif "icloud" in domain or "me.com" in domain: server_addr, port = "smtp.mail.me.com", 587
        else: server_addr, port = f"smtp.{domain}", 587
        ctx = ssl.create_default_context()
        with smtplib.SMTP(server_addr, port, timeout=15) as server:
            server.starttls(context=ctx); server.login(sender_email, sender_pass); server.send_message(msg)
        return True, "OK"
    except Exception as e:
        err_str = str(e)
        if "550" in err_str and "5.4.5" in err_str: return False, "LIMIT_EXCEEDED"
        return False, err_str

# ======================== التحقق من الاشتراك ========================
async def check_subscription(update, context):
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=FORCE_CHANNEL, user_id=user_id)
        return member.status in ["member", "administrator", "creator", "owner"]
    except Exception as e: 
        if user_id == ADMIN_ID and update.effective_message:
            try: await update.effective_message.reply_text(safe_format(get_text("msg_admin_sub_warning"), error=e), parse_mode=ParseMode.HTML)
            except: pass
        return True 

async def enforce_subscription(update, context):
    text = get_text("force_sub_text", "🔒 يجب الاشتراك أولاً.")
    t1, s1 = get_button("btn_join_channel", "📢 اشترك في القناة", "primary")
    t2, s2 = get_button("btn_check_sub", "✅ تحقق", "success")
    keyboard = [[make_button(t1, url=FORCE_CHANNEL_LINK, style=s1)], [make_button(t2, callback_data="check_sub", style=s2)]]
    await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

# ======================== القوائم ========================
def main_menu_keyboard(user_id):
    conn = get_db(); settings = conn.execute("SELECT * FROM report_settings WHERE user_id=?", (user_id,)).fetchone(); conn.close()
    has_sup = " ✅" if settings and settings["support_email"] else ""
    has_sub = " ✅" if settings and settings["subject"] else ""
    has_tpl = " ✅" if settings and settings["template"] else ""
    has_dly = " ✅" if settings and settings["delay_seconds"] else ""
    has_cnt = " ✅" if settings and settings["report_count"] else ""
    def bt(key, default, style="primary"): return get_button(key, default, style)
    t_sup, s_sup = bt("btn_support", "📧 بريد الدعم", "primary"); t_sub, s_sub = bt("btn_subject", "📝 الموضوع", "primary")
    t_tpl, s_tpl = bt("btn_template", "📄 الكليشه", "primary"); t_dly, s_dly = bt("btn_delay", "⏱️ الفاصل الزمني", "primary")
    t_cnt, s_cnt = bt("btn_count", "🔢 عدد الإبلاغات", "primary"); t_start, s_start = bt("btn_start", "🚀 بدء الإبلاغ", "success")
    t_stop, s_stop = bt("btn_stop", "⏹️ إيقاف الإبلاغ", "danger"); t_dev, s_dev = bt("btn_developer", "👨‍💻 مطور البوت", "primary")
    t_adm, s_adm = bt("btn_admin", "⚙️ لوحة الأدمن", "danger")
    kb = [
        [make_button(t_sup + has_sup, callback_data="set_support", style=s_sup), make_button(t_sub + has_sub, callback_data="set_subject", style=s_sub)],
        [make_button(t_tpl + has_tpl, callback_data="set_template", style=s_tpl), make_button(t_dly + has_dly, callback_data="set_delay", style=s_dly)],
        [make_button(t_cnt + has_cnt, callback_data="set_count", style=s_cnt)], [make_button(t_start, callback_data="start_report", style=s_start)],
        [make_button(t_stop, callback_data="stop_report", style=s_stop)], [make_button(t_dev, url=f"https://t.me/{DEVELOPER_USERNAME.replace('@', '')}", style=s_dev)],
    ]
    if user_id == ADMIN_ID: kb.append([make_button(t_adm, callback_data="admin_panel", style=s_adm)])
    return InlineKeyboardMarkup(kb)

def admin_menu_keyboard():
    kb = [
        [make_button("➕ إضافة حساب تلقائي", callback_data="adm_add_acc", style="success"), make_button("🗑️ حذف حساب تلقائي", callback_data="adm_del_acc", style="danger")],
        [make_button("🔍 فحص الحسابات", callback_data="adm_check_acc", style="primary")],
        [make_button("🚫 حظر مستخدم", callback_data="adm_ban", style="danger"), make_button("✅ فك حظر", callback_data="adm_unban", style="success")],
        [make_button("📢 بث للجميع", callback_data="adm_bc_all", style="primary"), make_button("✉️ بث لشخص", callback_data="adm_bc_one", style="primary")],
        [make_button("📝 تعديل نصوص البوت", callback_data="adm_edit_text", style="primary"), make_button("🎨 تعديل أزرار البوت", callback_data="adm_edit_btn", style="primary")],
        [make_button("👥 عرض المستخدمين", callback_data="adm_list_users", style="primary")],
        [make_button("⏸️ إيقاف البوت" if is_bot_active() else "▶️ تشغيل البوت", callback_data="adm_toggle", style="danger" if is_bot_active() else "success")],
        [make_button("🔙 رجوع", callback_data="back_main", style="primary")],
    ]
    return InlineKeyboardMarkup(kb)

# ======================== أوامر البوت ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; username = user.username or user.first_name; register_user(user.id, username); context.user_data.clear()
    if not is_bot_active() and user.id != ADMIN_ID: await update.message.reply_text(get_text("msg_bot_stopped")); return
    if is_banned(user.id): await update.message.reply_text(get_text("msg_banned")); return
    if not await check_subscription(update, context): await enforce_subscription(update, context); return
    await update.message.reply_text(get_text("welcome_text"), reply_markup=main_menu_keyboard(user.id), parse_mode=ParseMode.HTML)

# ======================== معالج الأزرار ========================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data; user_id = query.from_user.id; await query.answer()
    register_user(user_id, query.from_user.username or query.from_user.first_name)
    if not is_bot_active() and user_id != ADMIN_ID: await query.edit_message_text(get_text("msg_bot_stopped")); return
    if is_banned(user_id): await query.edit_message_text(get_text("msg_banned")); return
    if data == "check_sub":
        if await check_subscription(update, context): await query.edit_message_text(get_text("msg_sub_verified"), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML)
        else: await query.answer(get_text("msg_not_subscribed_alert"), show_alert=True)
        return
    if not await check_subscription(update, context): await enforce_subscription(update, context); return

    if data == "back_main": context.user_data.clear(); await query.edit_message_text(get_text("welcome_text"), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML); return
    elif data == "set_support": context.user_data['pending'] = 'support_email'; await query.edit_message_text(get_text("prompt_support"), parse_mode=ParseMode.HTML)
    elif data == "set_subject": context.user_data['pending'] = 'subject'; await query.edit_message_text(get_text("prompt_subject"), parse_mode=ParseMode.HTML)
    elif data == "set_template": context.user_data['pending'] = 'template'; await query.edit_message_text(get_text("prompt_template"), parse_mode=ParseMode.HTML)
    elif data == "set_delay": context.user_data['pending'] = 'delay'; await query.edit_message_text(get_text("prompt_delay"), parse_mode=ParseMode.HTML)
    elif data == "set_count": context.user_data['pending'] = 'count'; await query.edit_message_text(get_text("prompt_count"), parse_mode=ParseMode.HTML)
    elif data == "start_report": await handle_start_report(update, context)
    elif data == "stop_report":
        ev = ACTIVE_REPORTS.get(user_id)
        if ev: 
            ev.set(); await query.answer(get_text("msg_stop_sent_alert"), show_alert=True)
            try: await query.edit_message_text(get_text("msg_report_stopped_manual"), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML)
            except: pass
        else: await query.answer(get_text("msg_no_active_report_alert"), show_alert=True)
    elif data == "admin_panel": await query.edit_message_text(get_text("adm_welcome"), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif data == "adm_add_acc": context.user_data['pending'] = 'adm_email'; await query.edit_message_text(get_text("adm_prompt_email"), parse_mode=ParseMode.HTML)
    elif data == "adm_del_acc":
        conn = get_db(); accs = conn.execute("SELECT id, email FROM admin_accounts").fetchall(); conn.close()
        if not accs: await query.edit_message_text(get_text("adm_msg_no_accounts"), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML); return
        kb = [[make_button(f"🗑️ {a['email']}", callback_data=f"adm_del_{a['id']}", style="danger")] for a in accs]; kb.append([make_button("🔙 رجوع", callback_data="admin_panel", style="primary")])
        await query.edit_message_text(get_text("adm_prompt_select_del"), reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    elif data.startswith("adm_del_"):
        acc_id = int(data.split("_")[-1]); conn = get_db(); conn.execute("DELETE FROM admin_accounts WHERE id=?", (acc_id,)); conn.commit(); conn.close()
        await query.edit_message_text(get_text("adm_msg_acc_deleted"), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif data == "adm_check_acc":
        await query.edit_message_text(get_text("adm_msg_checking"), parse_mode=ParseMode.HTML)
        conn = get_db(); accs = conn.execute("SELECT * FROM admin_accounts").fetchall(); conn.close()
        if not accs: await query.edit_message_text(get_text("adm_msg_no_accounts"), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML); return
        lines = []
        for a in accs:
            try:
                domain = a["email"].split('@')[-1].lower(); srv = "smtp.gmail.com" if "gmail" in domain else ("smtp-mail.outlook.com" if "hotmail" in domain or "outlook" in domain else f"smtp.{domain}")
                ctx2 = ssl.create_default_context()
                with smtplib.SMTP(srv, 587, timeout=8) as s: s.starttls(context=ctx2); s.login(a["email"], a["password"])
                lines.append(f"✅ {a['email']}")
            except Exception as e: lines.append(f"❌ {a['email']}: {str(e)[:40]}")
        await query.edit_message_text(safe_format(get_text("adm_msg_check_results"), results="\n".join(lines)), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif data == "adm_ban": context.user_data['pending'] = 'adm_ban_id'; await query.edit_message_text(get_text("adm_prompt_ban_id"), parse_mode=ParseMode.HTML)
    elif data == "adm_unban": context.user_data['pending'] = 'adm_unban_id'; await query.edit_message_text(get_text("adm_prompt_unban_id"), parse_mode=ParseMode.HTML)
    elif data == "adm_bc_all": context.user_data['pending'] = 'adm_bc_all_msg'; await query.edit_message_text(get_text("adm_prompt_bc_all"), parse_mode=ParseMode.HTML)
    elif data == "adm_bc_one": context.user_data['pending'] = 'adm_bc_one_id'; await query.edit_message_text(get_text("adm_prompt_bc_one_id"), parse_mode=ParseMode.HTML)
    elif data == "adm_edit_text":
        kb = []
        for key, name in TEXT_NAMES.items(): kb.append([make_button(f"📝 {name}", callback_data=f"adm_et_{key}", style="primary")])
        kb.append([make_button("🔙 رجوع", callback_data="admin_panel", style="primary")])
        await query.edit_message_text(get_text("adm_prompt_edit_text"), reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    elif data.startswith("adm_et_"):
        key = data[7:]; context.user_data['edit_key'] = key; context.user_data['pending'] = 'adm_edit_text_value'
        current_val = get_text(key, "غير محدد")
        await query.edit_message_text(safe_format(get_text("adm_prompt_new_text"), name=TEXT_NAMES.get(key, key), current=current_val), parse_mode=ParseMode.HTML)
    elif data == "adm_edit_btn":
        kb = []
        for key, name in BUTTON_NAMES.items(): kb.append([make_button(f"🎨 {name}", callback_data=f"adm_eb_{key}", style="primary")])
        kb.append([make_button("🔙 رجوع", callback_data="admin_panel", style="primary")])
        await query.edit_message_text(get_text("adm_prompt_edit_btn"), reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    elif data.startswith("adm_eb_"):
        key = data[7:]; current_text, current_style = get_button(key); context.user_data['edit_key'] = key
        kb = [[make_button("✏️ تعديل اسم الزر", callback_data=f"adm_ebn_{key}", style="primary")], [make_button("🎨 تعديل لون الزر", callback_data=f"adm_ebc_{key}", style="primary")], [make_button("🔙 رجوع", callback_data="adm_edit_btn", style="danger")]]
        await query.edit_message_text(safe_format(get_text("adm_prompt_btn_options"), name=BUTTON_NAMES.get(key, key), current=current_text, style=current_style), reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    elif data.startswith("adm_ebn_"):
        key = data[8:]; context.user_data['edit_key'] = key; context.user_data['pending'] = 'adm_edit_btn_name'
        await query.edit_message_text(get_text("adm_prompt_new_btn_name"), parse_mode=ParseMode.HTML)
    elif data.startswith("adm_ebc_"):
        key = data[8:]; context.user_data['edit_key'] = key
        kb = [[make_button("🔵 أزرق (أساسي)", callback_data=f"adm_ebcol_{key}_primary", style="primary")], [make_button("🟢 أخضر (نجاح)", callback_data=f"adm_ebcol_{key}_success", style="success")], [make_button("🔴 أحمر (خطر)", callback_data=f"adm_ebcol_{key}_danger", style="danger")], [make_button("🔙 رجوع", callback_data=f"adm_eb_{key}", style="primary")]]
        await query.edit_message_text(get_text("adm_prompt_new_btn_color"), reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    elif data.startswith("adm_ebcol_"):
        rest = data[len("adm_ebcol_"):]; key, new_style = rest.rsplit("_", 1); current_text, _ = get_button(key); set_button(key, current_text, new_style)
        await query.edit_message_text(safe_format(get_text("adm_msg_btn_color_changed"), color=new_style), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif data == "adm_list_users":
        conn = get_db(); users = conn.execute("SELECT user_id, username, is_banned FROM users ORDER BY user_id").fetchall(); conn.close()
        if not users: await query.edit_message_text(get_text("adm_msg_no_users"), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML); return
        lines = [f"{'🚫' if u['is_banned'] else '✅'} <code>{u['user_id']}</code> - {u['username'] or 'بدون اسم'}" for u in users[:80]]
        await query.edit_message_text(safe_format(get_text("adm_msg_users_list"), count=len(users), users="\n".join(lines)), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif data == "adm_toggle":
        set_bot_active(not is_bot_active()); status_text = "يعمل" if is_bot_active() else "متوقف"
        await query.edit_message_text(safe_format(get_text("adm_msg_toggle_status"), status=status_text), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)

# ======================== معالج النصوص ========================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    if update.message.text == "/start": await start(update, context); return
    pending = context.user_data.get('pending')
    if not pending: return
    text_html = update.message.text_html if update.message.text_html else update.message.text
    text_plain = update.message.text.strip(); user_id = update.effective_user.id
    def clear_pending(): context.user_data.pop('pending', None); context.user_data.pop('temp_email', None); context.user_data.pop('edit_key', None); context.user_data.pop('bc_one_id', None)
    
    if pending == 'support_email': update_report_setting(user_id, "support_email", text_plain); clear_pending(); await update.message.reply_text(safe_format(get_text("msg_support_saved"), text=text_plain), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML)
    elif pending == 'subject': update_report_setting(user_id, "subject", text_plain); clear_pending(); await update.message.reply_text(get_text("msg_subject_saved"), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML)
    elif pending == 'template': update_report_setting(user_id, "template", text_plain); clear_pending(); await update.message.reply_text(get_text("msg_template_saved"), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML)
    elif pending == 'delay':
        try: val = int(text_plain); assert 1 <= val <= 180
        except: await update.message.reply_text(get_text("err_invalid_delay"), parse_mode=ParseMode.HTML); return
        update_report_setting(user_id, "delay_seconds", val); clear_pending(); await update.message.reply_text(safe_format(get_text("msg_delay_saved"), val=val), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML)
    elif pending == 'count':
        try: val = int(text_plain); assert val > 0
        except: await update.message.reply_text(get_text("err_invalid_count"), parse_mode=ParseMode.HTML); return
        update_report_setting(user_id, "report_count", val); clear_pending(); await update.message.reply_text(safe_format(get_text("msg_count_saved"), val=val), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML)
    elif pending == 'adm_email':
        if "@" not in text_plain: await update.message.reply_text(get_text("adm_msg_invalid_email"), parse_mode=ParseMode.HTML); return
        context.user_data['temp_email'] = text_plain; context.user_data['pending'] = 'adm_pass'
        await update.message.reply_text(get_text("adm_prompt_pass"), parse_mode=ParseMode.HTML)
    elif pending == 'adm_pass':
        email = context.user_data.get('temp_email'); conn = get_db(); conn.execute("INSERT INTO admin_accounts (email, password, provider) VALUES (?, ?, ?)", (email, text_plain, email.split('@')[-1])); conn.commit(); conn.close()
        clear_pending(); await update.message.reply_text(get_text("adm_msg_acc_added"), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif pending == 'adm_ban_id':
        try: target = int(text_plain)
        except: await update.message.reply_text(get_text("adm_msg_invalid_id"), parse_mode=ParseMode.HTML); return
        ban_user(target, True); clear_pending(); await update.message.reply_text(safe_format(get_text("adm_msg_banned"), target=target), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif pending == 'adm_unban_id':
        try: target = int(text_plain)
        except: await update.message.reply_text(get_text("adm_msg_invalid_id"), parse_mode=ParseMode.HTML); return
        ban_user(target, False); clear_pending(); await update.message.reply_text(safe_format(get_text("adm_msg_unbanned"), target=target), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif pending == 'adm_bc_all_msg':
        conn = get_db(); users = conn.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall(); conn.close(); sent = 0
        for u in users:
            try: await context.bot.send_message(chat_id=u["user_id"], text=text_html, parse_mode=ParseMode.HTML); sent += 1; await asyncio.sleep(0.05)
            except: pass
        clear_pending(); await update.message.reply_text(safe_format(get_text("adm_msg_broadcast_done"), sent=sent), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif pending == 'adm_bc_one_id':
        try: target = int(text_plain)
        except: await update.message.reply_text(get_text("adm_msg_invalid_id"), parse_mode=ParseMode.HTML); return
        context.user_data['bc_one_id'] = target; context.user_data['pending'] = 'adm_bc_one_msg'
        await update.message.reply_text(get_text("adm_prompt_bc_msg"), parse_mode=ParseMode.HTML)
    elif pending == 'adm_bc_one_msg':
        target = context.user_data.get('bc_one_id')
        try: await context.bot.send_message(chat_id=target, text=text_html, parse_mode=ParseMode.HTML); await update.message.reply_text(get_text("adm_msg_sent"), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
        except Exception as e: await update.message.reply_text(safe_format(get_text("adm_msg_send_failed"), error=e), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
        clear_pending()
    elif pending == 'adm_edit_text_value':
        key = context.user_data.get('edit_key'); set_text(key, text_html); clear_pending(); await update.message.reply_text(get_text("adm_msg_text_updated"), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)
    elif pending == 'adm_edit_btn_name':
        key = context.user_data.get('edit_key'); current_text, current_style = get_button(key); set_button(key, text_plain, current_style); clear_pending(); await update.message.reply_text(get_text("adm_msg_btn_name_updated"), reply_markup=admin_menu_keyboard(), parse_mode=ParseMode.HTML)

# ======================== منطق بدء الإبلاغ (التقسيم الفوري الديناميكي) ========================
async def handle_start_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = query.from_user.id
    if user_id in ACTIVE_REPORTS:
        await query.edit_message_text(get_text("msg_report_already_running"), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML); return

    conn = get_db()
    settings = conn.execute("SELECT * FROM report_settings WHERE user_id=?", (user_id,)).fetchone()
    conn.close()

    missing = []
    if not settings: missing = ["بريد الدعم", "الموضوع", "الكليشه", "الفاصل الزمني", "عدد الإبلاغات"]
    else:
        if not settings["support_email"]: missing.append("بريد الدعم")
        if not settings["subject"]: missing.append("الموضوع")
        if not settings["template"]: missing.append("الكليشه")
        if not settings["delay_seconds"]: missing.append("الفاصل الزمني")
        if not settings["report_count"]: missing.append("عدد الإبلاغات")

    if missing:
        missing_str = "\n".join([f"• {m}" for m in missing])
        msg_template = get_text("msg_missing_settings", "⚠️ ناقصك الإعدادات التالية:\n{missing}\n\nيرجى إكمالها أولاً.")
        await query.edit_message_text(safe_format(msg_template, missing=missing_str), reply_markup=main_menu_keyboard(user_id), parse_mode=ParseMode.HTML)
        return

    await query.edit_message_text(get_text("msg_starting_report"), parse_mode=ParseMode.HTML)
    
    stop_event = asyncio.Event()
    ACTIVE_REPORTS[user_id] = stop_event
    asyncio.create_task(run_report(context, user_id, settings, stop_event))

async def run_report(context, user_id, settings, stop_event):
    total = settings["report_count"]
    delay = settings["delay_seconds"]
    
    success = 0
    fail = 0
    done = 0
    last_update_time = time.time()

    # إنشاء رسالة العداد
    counter_msg = await context.bot.send_message(
        chat_id=user_id,
        text=safe_format(get_text("msg_report_progress_init"), acc_count="..."),
        reply_markup=InlineKeyboardMarkup([[make_button("⏹️ إيقاف الإبلاغ", callback_data="stop_report", style="danger")]]),
        parse_mode=ParseMode.HTML
    )

    loop = asyncio.get_running_loop()
    
    try:
        while not stop_event.is_set() and done < total:
            # ⏱️ 1. حساب التوزيع الفوري بناءً على عدد المستخدمين النشطين حالياً
            current_active_users = list(ACTIVE_REPORTS.keys())
            if user_id not in current_active_users: break
            
            num_users = len(current_active_users)
            my_index = current_active_users.index(user_id)

            # جلب الحسابات النشطة
            conn = get_db()
            all_accs = conn.execute("SELECT * FROM admin_accounts WHERE is_active=1").fetchall()
            conn.close()

            if not all_accs:
                logger.warning("لا توجد حسابات نشطة متاحة للإرسال.")
                break

            num_accs = len(all_accs)
            
            # تقسيم الحسابات بالتساوي
            base = num_accs // num_users
            rem = num_accs % num_users
            start = my_index * base + min(my_index, rem)
            length = base + (1 if my_index < rem else 0)
            
            # إذا كان عدد الحسابات أقل من المستخدمين، الجميع يشارك كل الحسابات
            my_slice = all_accs[start:start+length] if length > 0 else all_accs

            # 🚀 2. تحديد عدد الرسائل المتزامنة في هذه الدورة (Burst Size)
            # نرسل 3 رسائل بنفس الوقت كحد أقصى، أو أقل إذا كان نصيبنا من الحسابات أقل
            burst_size = min(len(my_slice), 3, total - done)
            
            # اختيار الحسابات لهذه الدورة (بشكل متناوب)
            accs_to_use = [my_slice[(done + i) % len(my_slice)] for i in range(burst_size)]

            # 🚦 3. تنفيذ الإرسال المتزامن (الخيوط)
            async def send_task(acc):
                async with GLOBAL_SEMAPHORE: # صمام الأمان العام
                    return await loop.run_in_executor(None, send_email_sync, acc["email"], acc["password"], settings["support_email"], settings["subject"], settings["template"])

            tasks = [send_task(acc) for acc in accs_to_use]
            results = await asyncio.gather(*tasks)

            # 📊 4. معالجة النتائج
            for res, acc in zip(results, accs_to_use):
                ok, msg = res
                if ok: 
                    success += 1
                else: 
                    fail += 1
                    if msg == "LIMIT_EXCEEDED":
                        # تعطيل الحساب فوراً وتحديث القاعدة
                        conn = get_db(); conn.execute("UPDATE admin_accounts SET is_active=0 WHERE email=?", (acc["email"],)); conn.commit(); conn.close()
                        logger.warning(f"تم تعطيل الحساب {acc['email']} (تجاوز الحد).")
                    else:
                        logger.warning(f"فشل عبر {acc['email']}: {msg}")
                
                done += 1

            # 🔄 5. تحديث الواجهة (كل 3 ثواني لتجنب الضغط)
            if time.time() - last_update_time > 3 or done >= total:
                try:
                    # نقوم بجلب نصيبنا الحالي فقط لعرضه في الواجهة
                    current_slice_count = len(my_slice) if 'my_slice' in locals() else 0
                    await context.bot.edit_message_text(
                        chat_id=user_id, message_id=counter_msg.message_id,
                        text=safe_format(
                            get_text("msg_report_progress_update"), 
                            success=success, fail=fail, remaining=total-done, 
                            acc_count=current_slice_count
                        ),
                        reply_markup=InlineKeyboardMarkup([[make_button("⏹️ إيقاف الإبلاغ", callback_data="stop_report", style="danger")]]),
                        parse_mode=ParseMode.HTML
                    )
                    last_update_time = time.time()
                except: pass

            # ⏳ 6. الانتظار للفاصل الزمني (إذا لم ينتهي الهجوم)
            if not stop_event.is_set() and done < total:
                await asyncio.sleep(delay)

    finally:
        if user_id in ACTIVE_REPORTS: del ACTIVE_REPORTS[user_id]

    # 🏁 النتيجة النهائية
    status_str = get_text("msg_report_status_stopped") if stop_event.is_set() else get_text("msg_report_status_completed")
    final_text = safe_format(get_text("msg_report_final_result"), success=success, fail=fail, status=status_str)
    try: await context.bot.edit_message_text(chat_id=user_id, message_id=counter_msg.message_id, text=final_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard(user_id))
    except: pass

# ======================== معالج الأخطاء والبدء ========================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"خطأ: {context.error}", exc_info=context.error)

def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_error_handler(error_handler)
    print("✅ البوت يعمل الآن بكامل ميزاته...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()