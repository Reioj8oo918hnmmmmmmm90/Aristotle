# Arzplus Price Bot — Railway

ربات ارسال خودکار نرخ ارز، طلا، سکه و رمزارز به کانال، با پنل مدیریت (`/panel`).

## فایل‌ها (همه در ریشه‌ی ریپو)
bot.py · requirements.txt · Procfile · railway.json · .python-version · .gitignore

## راه‌اندازی روی Railway
1. فایل‌ها را در یک ریپوی خصوصی GitHub بگذارید و با Deploy from GitHub وصل کنید.
2. Variables: فقط `BOT_TOKEN` (توکن BotFather). آیدی ادمین و کانال داخل کد تنظیم است؛ در صورت نیاز با `ADMIN_IDS` و `CHANNEL_ID` عوض می‌شود.
3. Volume: Mount path = `/data` (برای ماندن تنظیمات پنل).
4. ربات را در کانال ادمین کنید و در تلگرام `/panel` بزنید.

## متغیرهای اختیاری
COINGECKO_KEY · API_URL · API_KEY · DB_PATH · TZ_NAME · CHANNEL_TAG

## نکته
ربات را همزمان در دو جا (مثلاً گوشی و Railway) اجرا نکنید.
