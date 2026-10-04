# -*- coding: utf-8 -*-
"""
ربات نرخ لحظه‌ای ارز، طلا، سکه و رمزارز — مخصوص Railway
منابع داده: TGJU (ارز/طلا/سکه، تومان) + CoinGecko (رمزارز، دلار)
"""
import os, re, json, time, copy, html, asyncio, ipaddress, socket, sqlite3, logging
from datetime import datetime
from urllib.parse import urlparse, urljoin
from zoneinfo import ZoneInfo

import httpx, jdatetime
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as KB
from telegram.error import BadRequest
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# امنیت: لاگ httpx آدرس کامل شامل توکن ربات را چاپ می‌کند؛ خاموشش می‌کنیم
for n in ("httpx", "httpcore", "telegram", "apscheduler"):
    logging.getLogger(n).setLevel(logging.WARNING)
log = logging.getLogger("ratebot")

# ───────────────────────── پیکربندی (فقط از Environment) ─────────────────────────
TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("متغیر BOT_TOKEN در Railway (بخش Variables) تنظیم نشده است.")
OWNERS = {int(x) for x in os.getenv("ADMIN_IDS", "8792486297").replace(" ", "").split(",") if x}
_vol = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
DB_PATH = os.getenv("DB_PATH") or (os.path.join(_vol, "ratebot.db") if _vol else os.path.expanduser("~/ratebot.db"))
TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Tehran"))
CG_KEY = os.getenv("COINGECKO_KEY", "")
MITHQAL_G = 4.3318
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/124 Mobile Safari/537.36",
      "Accept": "application/json"}

# ───────────────────────── کاتالوگ ─────────────────────────
# key, group, emoji, title, unit, is_usd, aliases(کلیدهای پاسخ TGJU), default_on
def fx(code, flag, title, extra=()):
    return (code, "cur", flag, title, "تومان", 0, [code, f"price_{code}", *extra], 0)

BASE = [
    ("usd", "cur", "💵", "دلار", "تومان", 0, ["usd", "dollar", "دلار", "price_dollar_rl"], 1),
    ("usdt", "cur", "₮", "تتر", "تومان", 0, ["usdt", "tether", "cryptotetherirr", "تتر"], 0),
    ("eur", "cur", "💶", "یورو", "تومان", 0, ["eur", "euro", "یورو", "price_eur"], 1),
    ("gbp", "cur", "💷", "پوند", "تومان", 0, ["gbp", "pound", "پوند", "price_gbp"], 1),
    ("aed", "cur", "💠", "درهم", "تومان", 0, ["aed", "dirham", "درهم", "price_aed"], 1),
    fx("try", "🇹🇷", "لیر ترکیه"), fx("cny", "🇨🇳", "یوان چین"), fx("jpy", "🇯🇵", "ین ژاپن (۱۰۰)"),
    fx("cad", "🇨🇦", "دلار کانادا"), fx("aud", "🇦🇺", "دلار استرالیا"), fx("chf", "🇨🇭", "فرانک سوئیس"),
    fx("sar", "🇸🇦", "ریال عربستان"), fx("kwd", "🇰🇼", "دینار کویت"), fx("qar", "🇶🇦", "ریال قطر"),
    fx("omr", "🇴🇲", "ریال عمان"), fx("bhd", "🇧🇭", "دینار بحرین"), fx("iqd", "🇮🇶", "دینار عراق"),
    fx("rub", "🇷🇺", "روبل روسیه"), fx("inr", "🇮🇳", "روپیه هند"), fx("afn", "🇦🇫", "افغانی"),
    fx("azn", "🇦🇿", "منات آذربایجان"), fx("amd", "🇦🇲", "درام ارمنستان"), fx("thb", "🇹🇭", "بات تایلند"),
    fx("myr", "🇲🇾", "رینگیت مالزی"), fx("sgd", "🇸🇬", "دلار سنگاپور"), fx("hkd", "🇭🇰", "دلار هنگ‌کنگ"),
    fx("nzd", "🇳🇿", "دلار نیوزیلند"), fx("sek", "🇸🇪", "کرون سوئد"), fx("nok", "🇳🇴", "کرون نروژ"),
    fx("dkk", "🇩🇰", "کرون دانمارک"),
    ("ons", "gold", "🌍", "انس جهانی", "دلار", 1, ["ons", "xauusd", "goldounce", "انس", "انسطلا"], 1),
    ("gold18", "gold", "✨", "طلای ۱۸ عیار", "تومان", 0, ["gold18", "geram18", "18k", "طلای18عیار"], 1),
    ("mithqal", "gold", "⚖️", "مثقال طلا", "تومان", 0, ["mithqal", "mesghal", "مثقال", "مثقالطلا"], 1),
    ("gold24", "gold", "🏅", "طلای ۲۴ عیار", "تومان", 0, ["gold24", "geram24", "24k"], 0),
    ("emami", "coin", "🔸", "امامی", "تومان", 0, ["emami", "sekee", "سکهامامی", "امامی"], 1),
    ("nim", "coin", "🔸", "نیم سکه", "تومان", 0, ["nim", "نیمسکه", "nimsekee"], 1),
    ("rob", "coin", "🔸", "ربع سکه", "تومان", 0, ["rob", "ربعسکه", "robsekee"], 1),
    ("gerami", "coin", "🔸", "گرمی", "تومان", 0, ["gerami", "سکهگرمی", "گرمی"], 1),
    ("bahar", "coin", "🔸", "بهار آزادی", "تومان", 0, ["bahar", "sekeb", "بهارآزادی"], 1),
]
# رمزارزها با شناسه‌ی CoinGecko: key = "cg:<id>"
for cid, emo, name, on in [("bitcoin", "₿", "بیت‌کوین", 1), ("ethereum", "Ξ", "اتریوم", 1),
                           ("tron", "◈", "ترون", 1), ("the-open-network", "💎", "تون‌کوین", 1),
                           ("binancecoin", "🟡", "بایننس‌کوین", 0), ("solana", "🟣", "سولانا", 0),
                           ("ripple", "✕", "ریپل", 0), ("dogecoin", "🐶", "دوج‌کوین", 0),
                           ("litecoin", "Ł", "لایت‌کوین", 0), ("cardano", "🔵", "کاردانو", 0),
                           ("notcoin", "🪙", "نات‌کوین", 0)]:
    BASE.append((f"cg:{cid}", "crypto", emo, name, "دلار", 1, [], on))

GROUPS = ["cur", "gold", "coin", "crypto"]
GTITLE = {"cur": "ارز", "gold": "طلا", "coin": "سکه", "crypto": "رمزارز"}

LINE = "━" * 22
PRESETS = {
    "plus": dict(
        header="╭" + LINE + "╮\n       💎 ارز پلاس\n    📊 نرخ لحظه‌ای بازار\n╰" + LINE + "╯",
        divider=LINE, updated="🕒 آخرین بروزرسانی\n📅 {date} │ ⏰ {time}",
        titles={"cur": "💱 ارزها", "gold": "🥇 طلا", "coin": "🪙 سکه", "crypto": "₿ رمزارزها"},
        line="{emoji} {title}  ›  {price} {unit}"),
    "classic": dict(
        header="💰 نرخ لحظه‌ای ارز، طلا و سکه", divider="", updated="🕒 آخرین بروزرسانی\n{date} | {time}",
        titles={"cur": "💱 ارز", "gold": "🥇 طلا", "coin": "🪙 سکه", "crypto": "₿ رمزارز"},
        line="{emoji} {title}: {price} {unit}"),
    "minimal": dict(
        header="📊 نرخ بازار", divider="──────────────", updated="🕒 {date} | {time}",
        titles={"cur": "▪️ ارز", "gold": "▪️ طلا", "coin": "▪️ سکه", "crypto": "▪️ رمزارز"},
        line="{emoji} {title}: {price} {unit}"),
}

PRESETS["pro"] = dict(
    header="▰" * 16 + "\n<b>💎 ارز پلاس</b>\n<i>رصد لحظه‌ای بازار ایران</i>\n" + "▰" * 16,
    divider="▱" * 16, updated="⏱ <b>{time_s}</b> │ {date}",
    titles={"cur": "<b>◤ 💱 ارزها</b>", "gold": "<b>◤ 🥇 طلا</b>", "coin": "<b>◤ 🪙 سکه</b>", "crypto": "<b>◤ ₿ رمزارزها</b>"},
    line="{emoji} {title}  ▸  <b>{price}</b> {unit} {chg}", chg_mode="pct")

DEFAULTS = dict(
    channel=os.getenv("CHANNEL_ID", "@teleArzplus"),
    items=[c[0] for c in BASE if c[7]], custom={},
    interval=30, align=True, start="00:00", end="23:59",
    paused=False, mode="new", silent=False, delprev=False, digits="fa", arrows=False, crypto_toman=False,
    api_url=os.getenv("API_URL") or os.getenv("BITBIN_API_URL") or "https://call4.tgju.org/ajax.json",
    api_key=os.getenv("API_KEY") or os.getenv("BITBIN_API_KEY") or "",
    api_header="Authorization", api_scheme="Bearer", api_unit="rial",
    **copy.deepcopy(PRESETS["plus"]), footer=os.getenv("CHANNEL_TAG", "💎 @teleArzplus"),
    labels={}, allow_derived=False, ons_tol=3.0, frozen=0, schema=0,
    premium=True, order=[], gorder=list(GROUPS), ghide=[], chg_mode="off", btns=[], base={"day": "", "p": {}},
    max_dev=20.0, next_run=0.0, last_msg_id=0, last_ok=0.0,
    aliases={}, admins=[], last_prices={}, last_missing=[],
)


def catalog():
    out = list(BASE)
    for cid, info in S("custom").items():
        out.append((f"cg:{cid}", "crypto", "🪙", info["name"], "دلار", 1, [], 0))
    lab, res = S("labels"), []
    for c in out:
        l = lab.get(c[0])
        if l: c = (c[0], c[1], l.get("emoji", c[2]), l.get("title", c[3]), *c[4:])
        res.append(c)
    return res


def cat(): return {c[0]: c for c in catalog()}
def title_of(k): return cat().get(k, (0, 0, 0, k))[3]


# ───────────────────────── دیتابیس ─────────────────────────
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.execute("create table if not exists settings(k text primary key, v text)")
_db.execute("create table if not exists logs(ts real, level text, msg text)")
_db.commit()
try: os.chmod(DB_PATH, 0o600)
except OSError: pass
_cache = {}


def S(k):
    if k not in _cache:
        r = _db.execute("select v from settings where k=?", (k,)).fetchone()
        _cache[k] = json.loads(r[0]) if r else copy.deepcopy(DEFAULTS[k])
    return _cache[k]


def W(k, v):
    _cache[k] = v
    _db.execute("insert or replace into settings values(?,?)", (k, json.dumps(v, ensure_ascii=False)))
    _db.commit()


def dblog(level, msg):
    msg = re.sub(r"\d{6,}:[A-Za-z0-9_-]{30,}", "***", str(msg))[:500]  # هرگز توکن در لاگ نماند
    log.info("%s %s", level, msg)
    _db.execute("insert into logs values(?,?,?)", (time.time(), level, msg))
    _db.execute("delete from logs where ts < ?", (time.time() - 7 * 86400,))
    _db.commit()


if S("schema") < 2:  # قالب جدید «ارز پلاس»: تنظیمات قدیمی قالب/آیتم‌ها یک‌بار بازنشانی می‌شود
    for _k in ("header", "titles", "line", "updated", "divider", "footer", "items", "digits", "crypto_toman"):
        _db.execute("delete from settings where k=?", (_k,)); _cache.pop(_k, None)
    W("schema", 2)
if S("schema") < 3:  # قالب‌ها از این نسخه HTML هستند؛ متن‌های ذخیره‌شده‌ی قبلی escape می‌شوند
    for _k in ("header", "divider", "updated", "footer", "line"):
        if _db.execute("select 1 from settings where k=?", (_k,)).fetchone():
            W(_k, html.escape(S(_k), quote=False))
    if _db.execute("select 1 from settings where k='titles'").fetchone():
        W("titles", {g: html.escape(x, quote=False) for g, x in S("titles").items()})
    W("schema", 3)


def is_admin(uid): return uid in OWNERS or uid in S("admins")


# ───────────────────────── ابزارها ─────────────────────────
DIG_FA = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")
DIG_EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
FA_DAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
FA_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
             "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def fa(s): return str(s).translate(DIG_FA)
def esc(s): return html.escape(str(s))
def norm(s): return re.sub(r"[\s_\-/.]", "", str(s).translate(DIG_EN).lower().replace("ي", "ی").replace("ك", "ک"))
def hhmm(ts): return datetime.fromtimestamp(ts, TZ).strftime("%H:%M")


def now_parts():
    n = datetime.now(TZ)
    j = jdatetime.datetime.fromgregorian(datetime=n)
    wd = FA_DAYS[n.weekday()]
    date = f"{wd} {fa(j.day)} {FA_MONTHS[j.month - 1]} {fa(j.year)}"
    tm, tms = fa(n.strftime("%H:%M")), fa(n.strftime("%H:%M:%S"))
    if S("digits") == "en": date, tm, tms = date.translate(DIG_EN), tm.translate(DIG_EN), tms.translate(DIG_EN)
    return date, tm, wd, tms


def fmt_price(v):
    if v >= 100: s = f"{round(v):,}"
    elif v >= 1: s = f"{v:,.2f}"
    else: s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s.translate(DIG_FA) if S("digits") == "fa" else s


# ───────────────────────── قالب غنی (HTML + ایموجی پرمیوم) ─────────────────────────
_TAGS = {"bold": "b", "italic": "i", "underline": "u", "strikethrough": "s", "code": "code",
         "spoiler": "tg-spoiler", "blockquote": "blockquote", "pre": "pre"}
_TGE = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.S)


def strip_emoji(h): return _TGE.sub(r"\1", h)
def strip_tags(h): return html.unescape(re.sub(r"<[^>]+>", "", h))
def finalize(h): return h if S("premium") else strip_emoji(h)


def ent_html(text, ents):
    """متن + entityهای تلگرام (بولد، ایموجی پرمیوم، ...) → HTML امن."""
    u = text.encode("utf-16-le")
    def seg(a, b): return html.escape(u[a * 2:b * 2].decode("utf-16-le", "ignore"), quote=False)
    ok = [e for e in (ents or []) if e.type in _TAGS or e.type in ("custom_emoji", "text_link", "expandable_blockquote")]
    ok.sort(key=lambda e: (e.offset, -e.length))

    def wrap(e, inner, a, b):
        t = e.type
        if t == "custom_emoji":
            return f'<tg-emoji emoji-id="{e.custom_emoji_id}">{seg(a, b)}</tg-emoji>' if str(e.custom_emoji_id).isdigit() else inner
        if t == "text_link":
            return f'<a href="{html.escape(e.url, quote=True)}">{inner}</a>' if re.match(r"(https?|tg)://", e.url or "") else inner
        if t == "expandable_blockquote": return f"<blockquote expandable>{inner}</blockquote>"
        return f"<{_TAGS[t]}>{inner}</{_TAGS[t]}>"

    def render(a, b, es):
        out, pos, i = [], a, 0
        while i < len(es):
            e = es[i]; s0, t0 = e.offset, e.offset + e.length
            if s0 < pos or t0 > b: i += 1; continue
            out.append(seg(pos, s0))
            inner = [x for x in es[i + 1:] if x.offset >= s0 and x.offset + x.length <= t0]
            out.append(wrap(e, render(s0, t0, inner), s0, t0))
            pos, i = t0, i + 1
        out.append(seg(pos, b))
        return "".join(out)
    return render(0, len(u) // 2, ok)


def emoji_html(key, char):
    ce = S("labels").get(key, {}).get("ce")
    return f'<tg-emoji emoji-id="{ce}">{esc(char)}</tg-emoji>' if ce and str(ce).isdigit() else esc(char)


def ordered_keys():
    ks = [c[0] for c in catalog()]
    o = [k for k in S("order") if k in ks]
    return o + [k for k in ks if k not in o]


def group_order():
    return [g for g in S("gorder") if g in GROUPS] + [g for g in GROUPS if g not in S("gorder")]


def move_item(key, d):
    C, en, o = cat(), set(S("items")), ordered_keys()
    if key not in en or key not in C: return
    grp = [k for k in o if C[k][1] == C[key][1] and k in en]
    j = grp.index(key) + d
    if 0 <= j < len(grp):
        a, b = o.index(key), o.index(grp[j]); o[a], o[b] = o[b], o[a]; W("order", o)


def move_group(g, d):
    gs = group_order(); i = gs.index(g) if g in gs else -1; j = i + d
    if i >= 0 and 0 <= j < len(gs): gs[i], gs[j] = gs[j], gs[i]; W("gorder", gs)


def ensure_base(prices):
    today, b = datetime.now(TZ).strftime("%Y-%m-%d"), S("base")
    if b.get("day") != today: b = {"day": today, "p": {}}
    for k, v in prices.items(): b["p"].setdefault(k, v)
    W("base", b)


def chg_html(key, v):
    mode, b = S("chg_mode"), S("base")["p"].get(key)
    if mode == "off" or not b: return ""
    pct = (v - b) / b * 100
    ar = "🟢▲" if pct >= 0.005 else ("🔴▼" if pct <= -0.005 else "▪️")
    if mode == "arrow": return ar
    n = f"{abs(pct):.2f}"
    return f"{ar} {n.translate(DIG_FA) if S('digits') == 'fa' else n}٪"


def markup():
    b = S("btns")
    return KB([[B(x["text"], url=x["url"]) for x in b[i:i + 2]] for i in range(0, len(b), 2)]) if b else None


async def send_html(bot, chat, h, **kw):
    try: return await bot.send_message(chat, finalize(h), parse_mode="HTML", **kw)
    except BadRequest as e:
        if any(w in str(e).lower() for w in ("emoji", "entit", "parse")):
            dblog("WARN", f"emoji/format rejected, plain fallback: {e}")
            return await bot.send_message(chat, strip_emoji(h), parse_mode="HTML", **kw)
        raise


async def edit_html(bot, chat, mid, h, **kw):
    try: return await bot.edit_message_text(finalize(h), chat_id=chat, message_id=mid, parse_mode="HTML", **kw)
    except BadRequest as e:
        if any(w in str(e).lower() for w in ("emoji", "entit", "parse")):
            return await bot.edit_message_text(strip_emoji(h), chat_id=chat, message_id=mid, parse_mode="HTML", **kw)
        raise


async def safe_send(bot, chat, text, mk=None):
    try: return await bot.send_message(chat, finalize(text), reply_markup=mk, parse_mode="HTML")
    except BadRequest: return await bot.send_message(chat, strip_tags(text), reply_markup=mk)


async def safe_edit(q, text, mk):
    try: await q.edit_message_text(finalize(text), reply_markup=mk, parse_mode="HTML")
    except BadRequest as e:
        if "not modified" in str(e).lower(): return
        try: await q.edit_message_text(strip_tags(text), reply_markup=mk)
        except Exception: pass


# ───────────────────────── شبکه امن ─────────────────────────
async def check_url(url):
    """فقط https و فقط آی‌پی‌های عمومی (جلوگیری از SSRF به شبکه داخلی)."""
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname: raise ValueError("فقط آدرس https مجاز است")
    infos = await asyncio.to_thread(socket.getaddrinfo, u.hostname, u.port or 443, 0, socket.SOCK_STREAM)
    for i in infos:
        if not ipaddress.ip_address(i[4][0]).is_global: raise ValueError("آدرس داخلی/خصوصی مجاز نیست")


async def get_json(url, headers=None, params=None, trusted=False, limit=2_000_000):
    h0 = urlparse(url).hostname
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as c:
        for _ in range(4):
            if not trusted: await check_url(url)
            hdr = {**UA, **(headers or {})} if urlparse(url).hostname == h0 else dict(UA)
            async with c.stream("GET", url, headers=hdr, params=params) as r:
                if r.is_redirect:
                    url, params = urljoin(url, r.headers.get("location", "")), None
                    continue
                r.raise_for_status()
                buf = b""
                async for ch in r.aiter_bytes():
                    buf += ch
                    if len(buf) > limit: raise ValueError("پاسخ بیش‌ازحد بزرگ است")
                return json.loads(buf)
    raise ValueError("تعداد ریدایرکت زیاد")


IDF = ("symbol", "key", "slug", "name", "code", "title", "id", "ticker", "pair")
PRF = ("price", "p", "last", "value", "rate", "sell", "ask", "close", "current", "latest")


def num(v):
    if isinstance(v, bool): return None
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        try: return float(v.translate(DIG_EN).replace(",", "").replace("٬", "").strip())
        except ValueError: return None
    if isinstance(v, dict):
        for f in PRF:
            if f in v:
                n = num(v[f])
                if n is not None: return n
    return None


def flatten(data, out=None):
    out = {} if out is None else out
    if isinstance(data, dict):
        for k, v in data.items():
            n = num(v)
            if n is not None: out.setdefault(norm(k), n)
            if isinstance(v, (dict, list)): flatten(v, out)
        ident = next((data[f] for f in IDF if isinstance(data.get(f), str)), None)
        if ident:
            n = num(data)
            if n is not None: out.setdefault(norm(ident), n)
    elif isinstance(data, list):
        for x in data: flatten(x, out)
    return out


async def fetch_main():
    url, key = S("api_url"), S("api_key")
    if not url: raise RuntimeError("آدرس API تنظیم نشده است")
    headers = {}
    if key and "{key}" not in url: headers[S("api_header")] = f"{S('api_scheme')} {key}".strip()
    return flatten(await get_json(url.replace("{key}", key), headers=headers))


async def fetch_crypto(ids):
    h = {"x-cg-demo-api-key": CG_KEY} if CG_KEY else {}
    data = await get_json("https://api.coingecko.com/api/v3/simple/price", headers=h, trusted=True,
                          params={"ids": ",".join(ids), "vs_currencies": "usd"})
    return {f"cg:{i}": float(data[i]["usd"]) for i in ids if i in data and data[i].get("usd")}


def extract(flat, items):
    ov, div, raw, derived = S("aliases"), (10 if S("api_unit") == "rial" else 1), {}, set()
    for key, _g, _e, _t, _u, usd, aliases, _d in catalog():
        if key.startswith("cg:"): continue
        names = [ov[key]] if key in ov else aliases
        v = next((flat[n] for n in map(norm, names) if n in flat and flat[n] > 0), None)
        if v is not None: raw[key] = v if usd else v / div
    if "mithqal" not in raw and "gold18" in raw: raw["mithqal"] = raw["gold18"] * MITHQAL_G; derived.add("mithqal")
    if "gold24" not in raw and "gold18" in raw: raw["gold24"] = raw["gold18"] / 0.75; derived.add("gold24")
    return raw, derived


async def collect(only_enabled=True):
    items = S("items") if only_enabled else [c[0] for c in catalog()]
    errs, raw, derived, info = [], {}, set(), {}
    if any(not k.startswith("cg:") for k in items):
        try: raw, derived = extract(await fetch_main(), items)
        except Exception as e: errs.append(f"منبع ارز/طلا: {e}")
    cg = [k[3:] for k in items if k.startswith("cg:")]
    ids = cg + (["pax-gold"] if raw.get("ons") and "pax-gold" not in cg else [])  # مرجع تطبیق انس جهانی
    if ids:
        try:
            got = await fetch_crypto(ids)
            raw.update({k: v for k, v in got.items() if k[3:] in cg})
            info["pax"] = got.get("cg:pax-gold")
        except Exception as e:
            if cg: errs.append(f"منبع رمزارز: {e}")
    info.update(ons=raw.get("ons"), usd=raw.get("usd"), usdt=raw.get("usdt"), gold18=raw.get("gold18"))
    if only_enabled and not S("allow_derived"):
        for k in derived: raw.pop(k, None)  # قیمت محاسبه‌شده، قیمت واقعی بازار نیست
    prices = {k: raw[k] for k in items if k in raw}
    return prices, [k for k in items if k not in raw], derived, errs, raw.get("usd"), info


def build_text(prices, usd_rate=None):
    C, blocks, keys = cat(), [], ordered_keys()
    for g in group_order():
        if g in S("ghide"): continue
        rows = []
        for key in keys:
            if C[key][1] != g or key not in prices: continue
            _, _, emo, title, unit, *_ = C[key]
            v, row, chg = prices[key], S("line"), chg_html(key, prices[key])
            for ph, val in (("{emoji}", emoji_html(key, emo)), ("{title}", esc(title)),
                            ("{price}", fmt_price(v)), ("{unit}", esc(unit))):
                row = row.replace(ph, val)
            if g == "crypto" and S("crypto_toman") and usd_rate:
                row += f" | {fmt_price(v * usd_rate)} تومان"
            if "{chg}" in row: row = row.replace("{chg}", chg)
            elif chg: row += " " + chg
            rows.append(row.rstrip())
        if rows: blocks.append("\n".join([S("titles")[g], *rows]))
    out = ([S("header")] if S("header") else []) + blocks
    tail = "\n".join(t for t in (S("divider"), S("updated")) if t)
    if tail: out.append(tail)
    if S("footer"): out.append(S("footer"))
    date, tm, wd, tms = now_parts()
    text = "\n\n".join(out)
    for ph, val in (("{date}", date), ("{time_s}", tms), ("{time}", tm), ("{weekday}", wd)): text = text.replace(ph, val)
    return text


# ───────────────────────── ارسال ─────────────────────────
_post_lock = asyncio.Lock()


async def notify(app, text, markup=None):
    for uid in OWNERS | set(S("admins")):
        try: await app.bot.send_message(uid, text, reply_markup=markup)
        except Exception as e: log.warning("notify failed: %s", type(e).__name__)


async def post(app, force=False):
    async with _post_lock:
        return await _post(app, force)


async def _post(app, force):
    ch = S("channel")
    if not ch: return "❌ کانال تنظیم نشده"
    prices, missing, _, errs, usd, info = await collect()
    if errs and not force:
        dblog("ERR", "; ".join(errs))
        await notify(app, "❌ دریافت قیمت کامل نبود؛ برای حفظ دقت چیزی ارسال نشد:\n" + "\n".join(errs),
                     KB([[B("📤 با اطلاعات موجود ارسال کن", "force")]]))
        return "❌ " + "؛ ".join(errs)
    if not prices:
        dblog("ERR", "no prices"); await notify(app, "❌ هیچ قیمتی پیدا نشد. پنل ← API ← تست."); return "❌ قیمتی پیدا نشد"
    last, C = S("last_prices"), cat()
    bad = [f"{C[k][3]} ({last[k]:,.4g}→{v:,.4g})" for k, v in prices.items()
           if last.get(k) and abs(v - last[k]) / last[k] * 100 > S("max_dev")]
    o, px = info.get("ons"), info.get("pax")
    if o and px and abs(o - px) / px * 100 > S("ons_tol"):
        bad.append(f"انس جهانی {o:,.0f}$ با مرجع جهانی (PAXG) {px:,.0f}$ بیش از {S('ons_tol'):g}٪ اختلاف دارد")
    if bad and not force:
        dblog("WARN", f"accuracy hold: {bad}")
        await notify(app, "⚠️ مغایرت در قیمت‌ها؛ ارسال متوقف شد:\n" + "\n".join(bad),
                     KB([[B("✅ با این حال ارسال کن", "force")]]))
        return "⚠️ متوقف شد (مغایرت قیمت)"
    if missing and sorted(missing) != sorted(S("last_missing")):
        await notify(app, "ℹ️ این آیتم‌ها قیمت نداشتند و حذف شدند:\n" + "، ".join(title_of(k) for k in missing))
    W("last_missing", missing)
    ensure_base(prices)
    text, prev = build_text(prices, usd), S("last_msg_id")
    if len(strip_tags(text)) > 4000:
        await notify(app, "❌ پیام از ۴۰۰۰ کاراکتر بیشتر شد؛ آیتم‌های کمتری انتخاب کنید.")
        return "❌ پیام بیش‌ازحد طولانی"
    try:
        sent = None
        if S("mode") == "edit" and prev:
            try:
                await edit_html(app.bot, ch, prev, text, reply_markup=markup()); sent = prev
            except Exception as e:
                if "not modified" in str(e).lower(): sent = prev
        if sent is None:
            sent = (await send_html(app.bot, ch, text, disable_notification=S("silent"), reply_markup=markup())).message_id
            if S("delprev") and prev and S("mode") == "new":
                try: await app.bot.delete_message(ch, prev)
                except Exception: pass
        W("last_msg_id", sent)
    except Exception as e:
        dblog("ERR", f"send: {e}")
        await notify(app, f"❌ ارسال به کانال ناموفق بود:\n{e}")
        return f"❌ {e}"
    core = [k for k in prices if not k.startswith("cg:")]
    same = bool(core) and all(last.get(k) == prices[k] for k in core)
    W("frozen", S("frozen") + 1 if same else 0)
    if S("frozen") == 4:
        await notify(app, "⚠️ قیمت‌ها ۴ ارسال پشت‌سرهم دقیقاً ثابت بودند؛ ممکن است منبع بروز نباشد. پنل ← دقت و صحت قیمت‌ها.")
    W("last_prices", {**S("last_prices"), **prices}); W("last_ok", time.time())
    dblog("OK", f"sent {len(prices)} items")
    return "✅ ارسال شد"


def compute_next():
    m = S("interval") * 60
    if not S("align"): return time.time() + m
    mid = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return mid + (int((time.time() - mid) // m) + 1) * m


def in_window():
    n, s, e = datetime.now(TZ).strftime("%H:%M"), S("start"), S("end")
    return s <= n <= e if s <= e else (n >= s or n <= e)


async def tick(ctx: ContextTypes.DEFAULT_TYPE):
    if S("paused") or not S("channel") or time.time() < S("next_run"): return
    W("next_run", compute_next())
    if in_window():
        try: await post(ctx.application)
        except Exception as e: dblog("ERR", f"tick: {e}")


# ───────────────────────── پنل ─────────────────────────
def kb(rows): return KB([[B(t, callback_data=d) for t, d in r] for r in rows])
def onoff(v): return "✅" if v else "▫️"
BACK = [("🔙 بازگشت", "main")]


def scr_main():
    nxt = "—" if S("paused") else hhmm(S("next_run"))
    ok = hhmm(S("last_ok")) if S("last_ok") else "—"
    t = (f"🎛 <b>پنل مدیریت ربات نرخ</b>\n\nوضعیت: {'⏸ متوقف' if S('paused') else '▶️ فعال'}\n"
         f"کانال: <code>{esc(S('channel') or 'تنظیم نشده')}</code>\n"
         f"هر <b>{S('interval')}</b> دقیقه  |  بازه: {S('start')}–{S('end')}\n"
         f"ارسال بعدی: {nxt}  |  آخرین ارسال موفق: {ok}\nآیتم‌های فعال: {len(S('items'))}")
    return t, kb([
        [("📋 انتخاب ارز/طلا/رمزارز", "go:items"), ("⏱ زمان‌بندی", "go:sched")],
        [("🧩 قالب پیام", "go:tpl"), ("📡 منبع قیمت (API)", "go:api")],
        [("📢 کانال", "go:chan"), ("⚙️ نمایش و ارسال", "go:disp")],
        [("👁 پیش‌نمایش", "preview"), ("📤 ارسال همین الان", "sendnow")],
        [("▶️ ادامه" if S("paused") else "⏸ توقف ارسال", "tgl:paused"), ("📜 گزارش‌ها", "go:logs")],
        [("↕️ ترتیب و بخش‌ها", "go:order"), ("🎨 ایموجی پرمیوم", "go:emoji")],
        [("🔘 دکمه‌های زیر پیام", "go:btns"), ("🎯 دقت و صحت قیمت‌ها", "go:acc")],
        [("👥 ادمین‌ها", "go:admins"), ("💾 بکاپ", "backup")],
    ])


def scr_items(pick=None):
    en, rows, C = set(S("items")), [], catalog()
    pre = {None: None, "alias": "🔗 ", "label": "✏️ "}[pick]
    for g in GROUPS:
        rows.append([(f"— {GTITLE[g]} —", "noop")])
        its = [c for c in C if c[1] == g and not (pick == "alias" and c[0].startswith("cg:"))]
        for j in range(0, len(its), 2):
            rows.append([((pre or (onoff(c[0] in en) + " ")) + f"{c[2]} {c[3]}",
                          {None: "tg:", "alias": "al:", "label": "lb:"}[pick] + c[0]) for c in its[j:j + 2]])
    if pick == "alias":
        return "🔗 کدام آیتم به شناسه‌ی دلخواه در پاسخ API وصل شود؟", kb(rows + [[("🔙 API", "go:api")]])
    if pick == "label":
        return ("✏️ <b>نام و ایموجی آیتم‌ها</b>\nآیتم را بزنید و مثلاً بنویسید: <code>💵 دلار آمریکا</code>\n"
                "(ایموجی پرمیوم: فقط خود ایموجی یا همراه نام بفرستید. ایموجی معمولی: ایموجی و نام با هم. فقط نام: بدون ایموجی. بازگشت: «-»)"), kb(
            rows + [[("♻️ بازگشت همه‌ی نام‌ها", "lbreset")], [("🔙 قالب", "go:tpl")]])
    rows += [[("🔎 جستجو و افزودن رمزارز", "ask:coin_search")]]
    if S("custom"): rows += [[("🗑 حذف رمزارزهای افزوده‌شده", "go:delcoins")]]
    rows += [[("♻️ پیش‌فرض", "itdef"), ("🚫 خاموش‌کردن همه", "itnone")], BACK]
    return "📋 <b>آیتم‌های پیام</b>\nروی هر مورد بزنید تا روشن/خاموش شود.", kb(rows)


def scr_delcoins():
    rows = [[(f"🗑 {i['name']}", f"delcoin:{c}")] for c, i in S("custom").items()]
    return "کدام رمزارز حذف شود؟", kb(rows + [[("🔙 بازگشت", "go:items")]])


def scr_sched():
    iv = S("interval")
    lab = lambda p: ("✅ " if iv == p else "") + (f"{p}د" if p < 60 else f"{p // 60}س")
    rows = [[(lab(p), f"iv:{p}") for p in (1, 5, 10, 15)], [(lab(p), f"iv:{p}") for p in (30, 60, 120, 180)],
            [("✏️ عدد دلخواه (دقیقه)", "ask:interval")],
            [(f"🌅 شروع: {S('start')}", "ask:start"), (f"🌙 پایان: {S('end')}", "ask:end")],
            [(f"{onoff(S('align'))} هم‌تراز با ساعت (:00 و :30)", "tgl:align")], BACK]
    return (f"⏱ <b>زمان‌بندی</b>\nهر {iv} دقیقه | بازه‌ی فعال: {S('start')} تا {S('end')}\n"
            f"ارسال بعدی: {hhmm(S('next_run'))}"), kb(rows)


def scr_tpl():
    t = S("titles")
    rows = [[("🎨 قالب‌های آماده", "go:presets")],
            [("🧱 هدر", "ask:header"), ("➖ جداکننده", "ask:divider")],
            [("💱 ارز", "ask:t_cur"), ("🥇 طلا", "ask:t_gold"), ("🪙 سکه", "ask:t_coin"), ("₿ رمزارز", "ask:t_crypto")],
            [("📐 قالب هر خط", "ask:line"), ("🕒 بلوک بروزرسانی", "ask:updated")],
            [("🔖 امضا", "ask:footer"), ("✏️ نام/ایموجی آیتم‌ها", "go:labels")],
            [("↕️ ترتیب و نمایش بخش‌ها", "go:order"), ("🎨 ایموجی پرمیوم", "go:emoji")],
            [("👁 پیش‌نمایش با قیمت زنده", "preview")],
            [("♻️ بازگشت به قالب پیش‌فرض", "tplreset")], BACK]
    return ("🧩 <b>قالب پیام</b>\nهر بخش را می‌توانید با ایموجی پرمیوم و قالب‌بندی (بولد، ایتالیک، لینک) بفرستید.\n\n"
            f"<b>هدر:</b>\n{S('header') or '—'}\n\n"
            f"<b>بخش‌ها:</b> {t['cur']} | {t['gold']} | {t['coin']} | {t['crypto']}\n"
            f"<b>قالب خط:</b> {S('line')}\n"
            f"<b>جداکننده:</b> {S('divider') or '—'}\n"
            f"<b>بروزرسانی:</b> {S('updated') or '—'}\n"
            f"<b>امضا:</b> {S('footer') or '—'}\n\n"
            "خط: <code>{emoji} {title} {price} {unit} {chg}</code>\n"
            "تاریخ: <code>{date} {time} {time_s} {weekday}</code>"), kb(rows)


def scr_presets():
    return ("🎨 <b>قالب‌های آماده</b>\nهدر، خط، جداکننده و عنوان بخش‌ها عوض می‌شود. "
            "امضا و نام/ایموجی آیتم‌ها دست‌نخورده می‌ماند."), kb(
        [[("💎 ارز پلاس (کادر)", "preset:plus")], [("⚡ ارز پلاس پرو (ثانیه‌ای + درصد تغییر)", "preset:pro")],
         [("📰 کلاسیک", "preset:classic")], [("▫️ مینیمال", "preset:minimal")], [("🔙 قالب", "go:tpl")]])


def scr_order():
    C, en, o, rows = cat(), set(S("items")), ordered_keys(), []
    for g in group_order():
        rows.append([(("🚫 " if g in S("ghide") else "👁 ") + GTITLE[g], f"gtg:{g}"), ("⬆️", f"gmv:{g}:-1"), ("⬇️", f"gmv:{g}:1")])
        for k in o:
            if C[k][1] == g and k in en:
                rows.append([(f"   {C[k][2]} {C[k][3]}", "noop"), ("⬆️", f"imv:{k}:-1"), ("⬇️", f"imv:{k}:1")])
    return ("↕️ <b>ترتیب و نمایش</b>\nبخش‌ها و آیتم‌های روشن را با ⬆️⬇️ جابه‌جا کنید.\n"
            "👁/🚫 = نمایش یا پنهان‌کردن کل یک بخش."), kb(rows + [BACK])


def scr_btns():
    b = S("btns")
    rows = [[(f"🗑 {x['text']}", f"btnrm:{i}")] for i, x in enumerate(b)]
    if len(b) < 6: rows.append([("➕ افزودن دکمه", "ask:btn_add")])
    return ("🔘 <b>دکمه‌های لینک زیر پیام کانال</b>\n" +
            ("\n".join(f"• {esc(x['text'])} → {esc(x['url'])}" for x in b) or "هنوز دکمه‌ای ندارید.") +
            "\nحداکثر ۶ دکمه (دوتا در هر ردیف)."), kb(rows + [BACK])


def scr_emoji():
    rows = [[(f"{onoff(S('premium'))} استفاده از ایموجی پرمیوم", "tgl:premium")],
            [("🆔 گرفتن آیدی ایموجی پرمیوم", "ask:emoji_probe"), ("✏️ تنظیم ایموجی آیتم‌ها", "go:labels")],
            [("🧪 تست در همین چت", "emotest"), ("🧪 تست در کانال (۱۵ ثانیه)", "emotest_ch")], BACK]
    return ("🎨 <b>ایموجی پرمیوم</b>\n\n"
            "• اکانت <b>مالک ربات</b> باید پریمیوم باشد (طبق Bot API 9.4).\n"
            "• تلگرام رسماً فقط ارسال به چت خصوصی/گروه/سوپرگروه را ذکر کرده؛ <b>کانال ذکر نشده</b>. "
            "برای همین دکمه‌ی «تست در کانال» را بزنید و ببینید در کانال شما نمایش داده می‌شود یا نه.\n"
            "• اگر در کانال پذیرفته نشود، ربات خودکار ایموجی معمولی می‌فرستد و چیزی خراب نمی‌شود.\n"
            "• بینندگان بدون پریمیوم هم ایموجی را می‌بینند (ثابت)."), kb(rows)


def scr_acc():
    rows = [[("🎯 گزارش دقت و تطبیق با بازار", "audit")],
            [(f"{onoff(S('allow_derived'))} اجازه‌ی قیمت محاسبه‌شده (مثقال/۲۴ عیار)", "tgl:allow_derived")],
            [(f"🛡 حد تغییر غیرعادی: {S('max_dev'):g}٪", "ask:max_dev")],
            [(f"🔬 حد اختلاف انس با مرجع جهانی: {S('ons_tol'):g}٪", "ask:ons_tol")], BACK]
    return ("🎯 <b>دقت و صحت قیمت‌ها</b>\n\n"
            "• قیمت هر آیتم عیناً از منبع گرفته می‌شود و گرد یا تخمین زده نمی‌شود.\n"
            "• انس جهانی با مرجع مستقل (PAXG) تطبیق داده می‌شود؛ اختلاف زیاد = توقف ارسال.\n"
            "• تغییر ناگهانی نسبت به ارسال قبل = توقف ارسال و تأیید شما.\n"
            "• اگر قیمت‌ها ۴ ارسال پشت‌سرهم ثابت بمانند هشدار می‌گیرید.\n"
            "• قیمت محاسبه‌شده به‌طور پیش‌فرض در پیام نمی‌آید."), kb(rows)


def scr_api():
    k = S("api_key")
    rows = [[("🔗 آدرس API", "ask:api_url"), ("🔑 کلید API", "ask:api_key")],
            [("🏷 نام هدر", "ask:api_header"), ("🏷 پیشوند (Bearer)", "ask:api_scheme")],
            [(f"💱 واحد قیمت API: {'ریال' if S('api_unit') == 'rial' else 'تومان'}", "tgl:api_unit")],
            [("🧪 تست منابع و تطبیق آیتم‌ها", "apitest"), ("🔗 نگاشت دستی آیتم", "go:alias")],
            [(f"🛡 حد تغییر غیرعادی: {S('max_dev'):g}٪", "ask:max_dev")], BACK]
    return (f"📡 <b>منابع قیمت</b>\nارز/طلا/سکه: <code>{esc(S('api_url') or '—')}</code>\n"
            f"کلید: {'•••' + esc(k[-3:]) if k else 'ندارد'}\nرمزارز: CoinGecko\n"
            "فقط آدرس https عمومی پذیرفته می‌شود."), kb(rows)


def scr_chan():
    return (f"📢 <b>کانال</b>\nفعلی: <code>{esc(S('channel') or 'تنظیم نشده')}</code>\n\n"
            "ربات باید ادمین کانال با اجازه‌ی ارسال پیام باشد."), kb(
        [[("✏️ تغییر کانال", "ask:channel")], [("🔍 بررسی دسترسی ربات", "chantest")], BACK])


def scr_disp():
    rows = [[(f"{onoff(S('mode') == 'edit')} ویرایش پیام قبلی (به‌جای پیام جدید)", "tgl:mode")],
            [(f"{onoff(S('delprev'))} حذف پیام قبلی بعد از ارسال جدید", "tgl:delprev")],
            [(f"{onoff(S('silent'))} ارسال بی‌صدا", "tgl:silent")],
            [(f"{onoff(S('digits') == 'fa')} ارقام فارسی در قیمت‌ها", "tgl:digits")],
            [(f"📈 تغییر روزانه: {({'off': 'خاموش', 'arrow': 'فلش', 'pct': 'درصد'})[S('chg_mode')]}", "tgl:chg_mode")],
            [(f"{onoff(S('crypto_toman'))} نمایش قیمت تومانی رمزارزها", "tgl:crypto_toman")], BACK]
    return "⚙️ <b>نمایش و ارسال</b>", kb(rows)


def scr_admins():
    rows = [[(f"🗑 {a}", f"rmadmin:{a}")] for a in S("admins")]
    return (f"👥 <b>ادمین‌ها</b>\nمالک‌ها (ENV): <code>{', '.join(map(str, OWNERS)) or '—'}</code>\n"
            "ادمین‌های عادی به تنظیمات API، کانال، ادمین‌ها و بکاپ دسترسی ندارند."), kb(
        rows + [[("➕ افزودن ادمین (آیدی عددی)", "ask:addadmin")], BACK])


def scr_logs():
    rs = _db.execute("select ts,level,msg from logs order by ts desc limit 15").fetchall()
    body = "\n".join(f"{datetime.fromtimestamp(t, TZ).strftime('%m-%d %H:%M')} [{l}] {esc(m[:90])}" for t, l, m in rs) or "—"
    return f"📜 <b>آخرین گزارش‌ها</b>\n<pre>{body}</pre>", kb([BACK])


SCREENS = {"main": scr_main, "items": scr_items, "sched": scr_sched, "tpl": scr_tpl, "api": scr_api,
           "chan": scr_chan, "disp": scr_disp, "admins": scr_admins, "logs": scr_logs,
           "alias": lambda: scr_items("alias"), "labels": lambda: scr_items("label"), "delcoins": scr_delcoins,
           "presets": scr_presets, "acc": scr_acc, "order": scr_order, "btns": scr_btns, "emoji": scr_emoji}

PROMPTS = {
    "header": "عنوان جدید پیام:", "t_cur": "عنوان بخش «ارز»:", "t_gold": "عنوان بخش «طلا»:",
    "t_coin": "عنوان بخش «سکه»:", "t_crypto": "عنوان بخش «رمزارز»:",
    "line": "قالب هر خط (حتماً شامل {title} و {price}):\nمثال: {emoji} {title}: {price} {unit}",
    "updated": "برچسب بالای تاریخ (حذف: «-»):", "footer": "امضا/آیدی پایین پیام (حذف: «-»):",
    "interval": "فاصله ارسال به دقیقه (۱ تا ۱۴۴۰):", "start": "ساعت شروع، مثل 08:00", "end": "ساعت پایان، مثل 23:30",
    "api_url": "آدرس کامل https منبع قیمت:", "api_key": "کلید API (پیام شما بلافاصله پاک می‌شود):",
    "api_header": "نام هدر احراز هویت (مثل X-API-KEY):", "api_scheme": "پیشوند مقدار هدر، مثل Bearer (خالی: «-»):",
    "max_dev": "حداکثر تغییر مجاز نسبت به ارسال قبل (درصد):",
    "channel": "@username کانال یا آیدی عددی، یا یک پیام فوروارد‌شده از کانال:",
    "addadmin": "آیدی عددی ادمین جدید:", "coin_search": "نام یا نماد رمزارز را (ترجیحاً انگلیسی) بفرستید، مثل gram یا pepe:",
}
NEXT_SCREEN = {"header": "tpl", "t_cur": "tpl", "t_gold": "tpl", "t_coin": "tpl", "t_crypto": "tpl", "line": "tpl",
               "updated": "tpl", "footer": "tpl", "interval": "sched", "start": "sched", "end": "sched",
               "api_url": "api", "api_key": "api", "api_header": "api", "api_scheme": "api", "max_dev": "api",
               "channel": "chan", "addadmin": "admins"}
OWNER_KEYS = {"api_url", "api_key", "api_header", "api_scheme", "channel", "addadmin"}
OWNER_DATA = {"go:admins", "go:alias", "backup", "tgl:api_unit", "emotest_ch"}
CAPS = {"header": 300, "divider": 60, "line": 120, "updated": 150, "footer": 80, "api_url": 300, "api_key": 300}
PROMPTS.update({
    "header": "هدر پیام را بفرستید (می‌تواند چندخطی باشد؛ حذف: «-»):",
    "divider": "خط جداکننده‌ی بالای بلوک بروزرسانی، مثل ━━━━━━━━━━ (حذف: «-»):",
    "updated": "بلوک بروزرسانی (چندخطی). متغیرها: {date} {time} {weekday}\nمثال:\n🕒 آخرین بروزرسانی\n📅 {date} │ ⏰ {time}\n(حذف: «-»)",
    "ons_tol": "حداکثر اختلاف مجاز انس با مرجع جهانی (درصد، ۰.۵ تا ۲۰):",
})
NEXT_SCREEN.update({"divider": "tpl", "ons_tol": "acc", "max_dev": "acc", "btn_add": "btns", "emoji_probe": "emoji"})
CAPS["btn_add"] = 200
RICH_KEYS = {"header", "divider", "updated", "footer", "line", "t_cur", "t_gold", "t_coin", "t_crypto"}
PROMPTS.update({
    "header": "هدر پیام را بفرستید. چندخطی، بولد/ایتالیک و ایموجی پرمیوم مجاز است (حذف: «-»):",
    "t_cur": "عنوان بخش «ارز» (ایموجی پرمیوم و بولد مجاز):", "t_gold": "عنوان بخش «طلا»:",
    "t_coin": "عنوان بخش «سکه»:", "t_crypto": "عنوان بخش «رمزارز»:",
    "footer": "امضا/آیدی پایین پیام (ایموجی پرمیوم مجاز؛ حذف: «-»):",
    "emoji_probe": "یک پیام با ایموجی(های) پرمیوم بفرستید تا آیدی‌شان را نشان بدهم:",
    "btn_add": "دکمه جدید را این‌طور بفرستید:\nمتن دکمه | https://آدرس",
})


async def apply_input(key, t, msg, ctx):
    uid = msg.from_user.id
    if (key in OWNER_KEYS or key.startswith("alias:")) and uid not in OWNERS:
        raise ValueError("این بخش فقط برای مالک است")
    cap = CAPS.get(key, 60 if key.startswith("t_") else 100)
    if len(t) > cap: raise ValueError(f"حداکثر {cap} کاراکتر")
    th = ent_html(msg.text or "", msg.entities).strip() if key in RICH_KEYS else t
    if key.startswith("label:"):
        k, labs = key[6:], dict(S("labels"))
        if t == "-": labs.pop(k, None)
        else:
            lab, txt = dict(labs.get(k, {})), msg.text or ""
            ce = next((e for e in (msg.entities or []) if e.type == "custom_emoji" and e.offset == 0), None)
            if ce:
                u = txt.encode("utf-16-le")
                lab["emoji"], lab["ce"] = u[:ce.length * 2].decode("utf-16-le", "ignore"), ce.custom_emoji_id
                rest = u[ce.length * 2:].decode("utf-16-le", "ignore").strip()
                if rest: lab["title"] = rest
            else:
                parts = t.split(None, 1)
                if len(parts) == 2: lab["emoji"], lab["title"] = parts; lab.pop("ce", None)
                else: lab["title"] = parts[0]
            labs[k] = lab
        W("labels", labs); return "labels"
    if key.startswith("alias:"):
        W("aliases", {**S("aliases"), key[6:]: t}); return "api"
    if key.startswith("t_"): W("titles", {**S("titles"), key[2:]: th})
    elif key == "line":
        if "{title}" not in t or "{price}" not in t: raise ValueError("قالب باید شامل {title} و {price} باشد")
        W("line", th)
    elif key in ("updated", "footer", "header", "divider"): W(key, "" if t == "-" else th)
    elif key == "btn_add":
        txt, _, url = t.partition("|")
        txt, url = txt.strip(), url.strip()
        if not txt or len(txt) > 40 or not re.match(r"(https://|http://|tg://)", url) or " " in url:
            raise ValueError("فرمت درست: متن | https://آدرس")
        if len(S("btns")) >= 6: raise ValueError("حداکثر ۶ دکمه")
        W("btns", [*S("btns"), {"text": txt, "url": url}])
    elif key == "interval":
        n = int(t.translate(DIG_EN))
        if not 1 <= n <= 1440: raise ValueError("بین ۱ تا ۱۴۴۰")
        W("interval", n); W("next_run", compute_next())
    elif key in ("start", "end"):
        t = t.translate(DIG_EN)
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t): raise ValueError("فرمت درست: 08:00")
        W(key, t)
    elif key == "api_url":
        await check_url(t); W("api_url", t)
    elif key == "api_key":
        W("api_key", t)
        try: await msg.delete()
        except Exception: pass
    elif key == "api_header":
        if not re.fullmatch(r"[A-Za-z0-9-]{1,40}", t): raise ValueError("نام هدر نامعتبر")
        W("api_header", t)
    elif key == "api_scheme": W("api_scheme", "" if t == "-" else t)
    elif key == "max_dev":
        n = float(t.translate(DIG_EN))
        if not 1 <= n <= 100: raise ValueError("بین ۱ تا ۱۰۰")
        W("max_dev", n)
    elif key == "ons_tol":
        n = float(t.translate(DIG_EN))
        if not 0.5 <= n <= 20: raise ValueError("بین ۰.۵ تا ۲۰")
        W("ons_tol", n)
    elif key == "addadmin": W("admins", sorted(set(S("admins")) | {int(t.translate(DIG_EN))}))
    elif key == "channel":
        fo = getattr(msg, "forward_origin", None)
        target = getattr(getattr(fo, "chat", None), "id", None) or t
        if isinstance(target, str) and not re.fullmatch(r"@[A-Za-z0-9_]{5,32}|-?\d{5,20}", target):
            raise ValueError("فرمت کانال نامعتبر")
        W("channel", str((await ctx.bot.get_chat(target)).id))
    return NEXT_SCREEN[key]


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = update.message
    if not m or m.chat.type != "private" or not is_admin(m.from_user.id): return
    key = ctx.user_data.pop("await", None)
    if not key: return
    t = (m.text or "").strip()
    if key == "emoji_probe":
        ents = [e for e in (m.entities or []) if e.type == "custom_emoji"]
        if not ents: await m.reply_text("ایموجی پرمیومی در پیام نبود."); return
        u = (m.text or "").encode("utf-16-le")
        lines = [f"{u[e.offset * 2:(e.offset + e.length) * 2].decode('utf-16-le', 'ignore')}  <code>{e.custom_emoji_id}</code>" for e in ents]
        await m.reply_text("آیدی ایموجی‌ها:\n" + "\n".join(lines) + "\n\nبرای انتساب به آیتم: قالب ← نام/ایموجی آیتم‌ها.", parse_mode="HTML"); return
    if key == "coin_search":
        try:
            h = {"x-cg-demo-api-key": CG_KEY} if CG_KEY else {}
            data = await get_json("https://api.coingecko.com/api/v3/search", headers=h, trusted=True,
                                  params={"query": t[:40]})
            coins = [c for c in data.get("coins", []) if len(c.get("id", "")) <= 45][:8]
        except Exception as e:
            await m.reply_text(f"❌ جستجو ناموفق: {e}"); return
        if not coins: await m.reply_text("چیزی پیدا نشد. نام انگلیسی یا نماد را امتحان کنید."); return
        ctx.user_data["coinres"] = {c["id"]: (c["name"], c["symbol"]) for c in coins}
        rows = [[(f"{c['name']} ({c['symbol']})", f"addcoin:{c['id']}")] for c in coins] + [[("🔙 انصراف", "go:items")]]
        await m.reply_text("کدام را اضافه کنم؟", reply_markup=kb(rows)); return
    try:
        scr = await apply_input(key, t, m, ctx)
    except Exception as e:
        await m.reply_text(f"❌ مقدار نامعتبر: {e}\nدوباره از پنل تلاش کنید.")
        scr = NEXT_SCREEN.get(key, "main")
    txt, mk = SCREENS[scr]()
    await safe_send(ctx.bot, m.chat_id, txt, mk)


# ───────────────────────── دکمه‌ها ─────────────────────────
async def api_test_text():
    prices, missing, derived, errs, _, _i = await collect(only_enabled=False)
    ok = [f"✅ {title_of(k)}: {fmt_price(v)}" + (" (محاسبه‌شده)" if k in derived else "") for k, v in prices.items()]
    bad = [f"❌ {title_of(k)}" for k in missing]
    return ("🧪 نتیجه تست\n" + ("\n".join("⚠️ " + e for e in errs) + "\n" if errs else "") +
            "\n".join(ok + bad) + "\n\nبرای ❌ها: «نگاشت دستی آیتم» یا خاموش‌کردن آن‌ها.")


async def audit_text():
    prices, missing, derived, errs, usd, i = await collect(only_enabled=False)
    L = ["🎯 گزارش دقت", "منبع: TGJU (بازار آزاد ایران) برای ارز/طلا/سکه — CoinGecko برای رمزارز", ""]
    L += [f"⚠️ {e}" for e in errs]
    o, px = i.get("ons"), i.get("pax")
    if o and px:
        d = abs(o - px) / px * 100
        L.append(f"{'✅' if d <= S('ons_tol') else '❌'} انس {o:,.2f}$ ↔ PAXG {px:,.2f}$ (اختلاف {d:.2f}٪)")
    else: L.append("➖ تطبیق انس با مرجع جهانی انجام نشد")
    u, t = i.get("usd"), i.get("usdt")
    if u and t:
        d = abs(u - t) / u * 100
        L.append(f"{'✅' if d <= 6 else '⚠️'} دلار {fmt_price(u)} ↔ تتر {fmt_price(t)} (اختلاف {d:.1f}٪)")
    g = i.get("gold18")
    if g and o and u:
        fair = o * u / 31.1035 * 0.75
        L.append(f"ℹ️ ۱۸ عیار {fmt_price(g)} ↔ معادل جهانی {fmt_price(fair)} ({(g - fair) / fair * 100:+.1f}٪)")
    if derived: L.append("⚠️ محاسبه‌شده (نه قیمت واقعی منبع): " + "، ".join(title_of(k) for k in derived))
    L.append("")
    for k in S("items"):
        L.append(f"{'✅' if k in prices else '❌'} {title_of(k)}: {fmt_price(prices[k]) if k in prices else '—'}")
    return "\n".join(L)


async def del_job(ctx):
    ch, mid = ctx.job.data
    try: await ctx.bot.delete_message(ch, mid)
    except Exception: pass


_last_hit = {}


async def cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        dblog("SEC", f"unauthorized callback from {uid}")
        await q.answer(); return
    now = time.monotonic()
    if now - _last_hit.get(uid, 0) < 0.35: await q.answer(); return
    _last_hit[uid] = now
    d = q.data or ""
    act, _, arg = d.partition(":")
    if uid not in OWNERS and (d in OWNER_DATA or act in ("rmadmin", "al") or (act == "ask" and arg in OWNER_KEYS)):
        await q.answer("این بخش فقط برای مالک است", show_alert=True); return
    screen, toast = None, None

    async def edit(name):
        t, mk = SCREENS[name]()
        await safe_edit(q, t, mk)

    if d == "noop": await q.answer(); return
    if act == "go" and arg in SCREENS: screen = arg
    elif d == "main": screen = "main"
    elif act == "tg":
        s = set(S("items")) ^ {arg}
        W("items", [c[0] for c in catalog() if c[0] in s]); screen = "items"
    elif d == "itdef": W("items", DEFAULTS["items"]); screen = "items"
    elif d == "itnone": W("items", []); screen = "items"
    elif act == "iv":
        W("interval", max(1, min(1440, int(arg)))); W("next_run", compute_next()); screen = "sched"
    elif act == "tgl":
        if arg == "mode": W("mode", "new" if S("mode") == "edit" else "edit"); screen = "disp"
        elif arg == "digits": W("digits", "en" if S("digits") == "fa" else "fa"); screen = "disp"
        elif arg == "api_unit": W("api_unit", "toman" if S("api_unit") == "rial" else "rial"); screen = "api"
        elif arg == "chg_mode": W("chg_mode", {"off": "arrow", "arrow": "pct", "pct": "off"}[S("chg_mode")]); screen = "disp"
        elif arg == "premium": W("premium", not S("premium")); screen = "emoji"
        elif arg in ("paused", "align", "silent", "delprev", "arrows", "crypto_toman", "allow_derived"):
            W(arg, not S(arg)); screen = {"paused": "main", "align": "sched", "allow_derived": "acc"}.get(arg, "disp")
            if arg == "align" or (arg == "paused" and not S("paused")): W("next_run", compute_next())
    elif act == "ask" and arg in PROMPTS:
        ctx.user_data["await"] = arg
        await q.answer()
        await ctx.bot.send_message(q.message.chat_id, PROMPTS[arg] + "\n(لغو: /cancel)"); return
    elif act == "al" and arg in cat():
        ctx.user_data["await"] = f"alias:{arg}"
        await q.answer()
        await ctx.bot.send_message(q.message.chat_id, f"شناسه‌ی «{title_of(arg)}» را همان‌طور که در پاسخ API هست بفرستید:"); return
    elif act == "addcoin":
        name, sym = ctx.user_data.get("coinres", {}).get(arg, (arg, ""))
        W("custom", {**S("custom"), arg: {"name": f"{name} ({sym.upper()})" if sym else name}})
        W("items", [c[0] for c in catalog() if c[0] in set(S("items")) | {f"cg:{arg}"}])
        screen, toast = "items", "افزوده شد"
    elif act == "delcoin":
        c = dict(S("custom")); c.pop(arg, None); W("custom", c)
        W("items", [k for k in S("items") if k != f"cg:{arg}"]); screen = "items"
    elif act == "gtg" and arg in GROUPS:
        W("ghide", [g for g in S("ghide") if g != arg] if arg in S("ghide") else [*S("ghide"), arg]); screen = "order"
    elif act == "gmv": g, _, dd = arg.partition(":"); move_group(g, int(dd)); screen = "order"
    elif act == "imv": k, _, dd = arg.rpartition(":"); move_item(k, int(dd)); screen = "order"
    elif act == "btnrm":
        b = list(S("btns"))
        if arg.isdigit() and int(arg) < len(b): b.pop(int(arg)); W("btns", b)
        screen = "btns"
    elif d in ("emotest", "emotest_ch"):
        ce = next((l["ce"] for l in S("labels").values() if l.get("ce")), "5368324170671202286")
        body = f'<tg-emoji emoji-id="{ce}">⭐</tg-emoji> تست ایموجی پرمیوم'
        if d == "emotest":
            await q.answer(); await send_html(ctx.bot, q.message.chat_id, body); return
        try:
            m = await send_html(ctx.bot, S("channel"), body + "\n(این پیام ۱۵ ثانیه‌ی دیگر پاک می‌شود)")
            ctx.job_queue.run_once(del_job, 15, data=(S("channel"), m.message_id))
            await q.answer("ارسال شد؛ ۱۵ ثانیه در کانال بررسی کنید", show_alert=True)
        except Exception as e: await q.answer(f"❌ {e}"[:190], show_alert=True)
        return
    elif act == "lb" and arg in cat():
        ctx.user_data["await"] = f"label:{arg}"
        await q.answer()
        await ctx.bot.send_message(q.message.chat_id, f"ایموجی و نام جدید «{title_of(arg)}» را بفرستید. مثال: 💵 دلار آمریکا\n(بازگشت: «-»)"); return
    elif d == "lbreset": W("labels", {}); screen = "labels"
    elif act == "preset" and arg in PRESETS:
        for k, v in PRESETS[arg].items(): W(k, copy.deepcopy(v))
        screen, toast = "tpl", "قالب اعمال شد"
    elif d == "audit":
        await q.answer("در حال بررسی…")
        try: txt = await audit_text()
        except Exception as e: txt = f"❌ {e}"
        await ctx.bot.send_message(q.message.chat_id, txt[:4000]); return
    elif d == "tplreset":
        for k in ("header", "titles", "line", "updated", "divider", "footer"): W(k, copy.deepcopy(DEFAULTS[k]))
        screen, toast = "tpl", "قالب پیش‌فرض برگشت"
    elif act == "rmadmin":
        W("admins", [a for a in S("admins") if str(a) != arg]); screen = "admins"
    elif d == "preview":
        await q.answer("در حال دریافت…")
        prices, _, _, errs, usd, _i = await collect()
        txt = build_text(prices, usd) if prices else "هیچ قیمتی پیدا نشد"
        if errs: txt += "\n\n⚠️ " + "\n⚠️ ".join(esc(e) for e in errs)
        await send_html(ctx.bot, q.message.chat_id, "👁 <b>پیش‌نمایش</b> (به کانال ارسال نشد)\n\n" + txt); return
    elif d in ("sendnow", "force"):
        await q.answer("در حال ارسال…")
        await ctx.bot.send_message(q.message.chat_id, await post(ctx.application, force=(d == "force"))); return
    elif d == "apitest":
        await q.answer("در حال تست…")
        try: txt = await api_test_text()
        except Exception as e: txt = f"❌ {e}"
        await ctx.bot.send_message(q.message.chat_id, txt[:4000]); return
    elif d == "chantest":
        try:
            me = await ctx.bot.get_me()
            m = await ctx.bot.get_chat_member(S("channel"), me.id)
            ok = m.status == "creator" or (m.status == "administrator" and getattr(m, "can_post_messages", True))
            toast = "✅ دسترسی ارسال دارد" if ok else "❌ ربات باید ادمین با اجازه‌ی ارسال باشد"
        except Exception as e: toast = f"❌ {e}"[:190]
        await q.answer(toast, show_alert=True); return
    elif d == "backup":
        await q.answer()
        _db.commit()
        with open(DB_PATH, "rb") as f:
            await ctx.bot.send_document(q.message.chat_id, f, filename="ratebot-backup.db")
        return
    if screen: await edit(screen)
    await q.answer(toast)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = update.message
    if m.chat.type != "private": return
    if not is_admin(m.from_user.id):
        dblog("SEC", f"unauthorized /start from {m.from_user.id}"); return
    t, mk = scr_main()
    await m.reply_text(t, reply_markup=mk, parse_mode="HTML")


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private" and is_admin(update.effective_user.id):
        ctx.user_data.pop("await", None)
        await update.message.reply_text("لغو شد. /panel")


async def on_error(update, ctx): dblog("ERR", f"handler: {type(ctx.error).__name__}: {ctx.error}")


def main():
    app = Application.builder().token(TOKEN).build()
    if S("next_run") < time.time(): W("next_run", compute_next())
    app.add_handler(CommandHandler(["start", "panel"], start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    app.job_queue.run_repeating(tick, interval=20, first=5)
    log.info("bot started; db=%s", DB_PATH)
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
