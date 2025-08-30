import os, re
from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

# --- 讀取 .env（若沒有環境變數就從檔案補） ---
def _load_dotenv(path="/home/jumao/bot/.env"):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line=line.strip()
                    if not line or line.startswith("#") or "=" not in line: 
                        continue
                    k,v=line.split("=",1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass
_load_dotenv()
# ---------------------------------------------

app = Flask(__name__)


# ====== 管理（商家）與名單功能 ======
import json, threading, os, re
from linebot.models import TextSendMessage

USERS_JSON = "/home/jumao/linebot/data/users.json"
_users_lock = threading.Lock()

def _load_users():
    try:
        with open(USERS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_users(d):
    tmp = USERS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USERS_JSON)

def set_alias(alias: str, user_id: str):
    alias = alias.strip()
    if not alias or not user_id.startswith("U"):
        return False
    with _users_lock:
        d = _load_users()
        d[alias] = user_id
        _save_users(d)
    return True

def find_user_id(alias: str):
    return _load_users().get(alias.strip())

def list_aliases(n=30):
    d = _load_users()
    items = sorted(d.items())[:n]
    return "\n".join([f"{k} → {v[:8]}…{v[-4:]}" for k,v in items]) or "（目前沒有名單）"

# 從 .env 讀取商家 userId（可多個，以逗號分隔）
ADMIN_USER_IDS = {x.strip() for x in (os.getenv("ADMIN_USER_IDS") or "").split(",") if x.strip()}

def is_admin(user_id: str) -> bool:
    return user_id in ADMIN_USER_IDS

# 客戶第一次私聊時，自動記錄 顯示名稱 → userId
def remember_user_profile(user_id: str):
    try:
        prof = line_bot_api.get_profile(user_id)
        if prof and prof.display_name:
            set_alias(prof.display_name, user_id)
    except Exception:
        pass

# 商家指令：報價 2200 VIP3 用券 @小美
_CMD_PUSH = re.compile(r'^報價[\s:：]*?(\d+)(?:\s+(一般|VIP1|VIP2|VIP3))?(?:\s+(用券))?\s+@(\S+)$')
# 綁定 小美 Uxxxxxxxx...
_CMD_BIND = re.compile(r'^綁定\s+(\S+)\s+(U[0-9a-f]{32})$', re.IGNORECASE)

def push_quote_to_alias(rmb: int, level: str, use_coupon: bool, alias: str) -> str:
    uid = find_user_id(alias)
    if not uid:
        return f"找不到別名「{alias}」，請先讓對方私聊一次，或用「綁定 {alias} Uxxxx」新增。"
    twd = quote_twd(rmb, level, use_coupon)
    text = build_reply(rmb, twd)
    try:
        line_bot_api.push_message(uid, TextSendMessage(text=text))
        return f"已推播給「{alias}」（{uid[:8]}…{uid[-4:]}）"
    except Exception as e:
        return f"推播失敗：{e}"




CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
# 建議：若沒讀到就丟更清楚的錯
if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    raise RuntimeError("LINE credentials missing: set LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

BASE_SELL_RATE = 4.5
VIP_RATE_OFF = {"一般":0.00, "VIP1":0.02, "VIP2":0.03, "VIP3":0.05}
VIP_FEE_OFF  = {"一般":0, "VIP1":10, "VIP2":10, "VIP3":10}
MIN_FEE = 20

def calc_base_fee(rmb: int) -> int:
    return 30 + (rmb // 500) * 50

def parse_command(text: str):
    text = text.strip()
    if not text.startswith("報價"):
        return None
    m = re.findall(r'(報價)\s+(\d+)(?:\s+(一般|VIP1|VIP2|VIP3))?(?:\s+(用券))?', text)
    if not m:
        return None
    _, rmb_str, level, coupon = m[0]
    rmb = int(rmb_str)
    level = level if level else "一般"
    use_coupon = (coupon == "用券")
    return rmb, level, use_coupon

def quote_twd(rmb: int, level: str, use_coupon: bool) -> int:
    sell_rate = BASE_SELL_RATE - VIP_RATE_OFF.get(level, 0.0)
    fee = calc_base_fee(rmb)
    fee = fee if level=="一般" else max(fee - VIP_FEE_OFF.get(level,0), MIN_FEE)
    coupon_cut = 50 if (level=="VIP3" and use_coupon and rmb>=2000) else 0
    return int(round(rmb * sell_rate + fee - coupon_cut))

def build_reply(rmb: int, twd: int) -> str:
    return (f"【[報價單]\n"
            f"商品價格：{rmb} RMB\n"
            f"換算台幣價格：NT$ {twd}\n"
            f"沒問題的話跟我說一聲～\n"
            f"傳給您付款資訊】")

# 同時支援 /health 及 /bot/health（避免 Trim path 影響）
@app.route("/health")
@app.route("/bot/health")
def health():
    return "ok", 200

# 同時支援 /callback 及 /bot/callback
@app.route("/callback", methods=["POST"])
@app.route("/bot/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "invalid signature", 400
    return "OK", 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event: MessageEvent):
    text = event.message.text.strip()
    src_type = event.source.type

    # ====== 商家（admin）私聊：可發推播指令 ======
    if src_type == "user" and is_admin(event.source.user_id):
        # 1) 工具指令：我的ID / 名單 / 綁定 別名 Uxxxx
        if text in ("我的ID", "my id", "uid"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"你的 userId：{event.source.user_id}"))
            return
        if text in ("名單", "list"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已存名單（最多30筆）：\n"+list_aliases()))
            return
        m = _CMD_BIND.match(text)
        if m:
            alias, uid = m.group(1), m.group(2)
            ok = set_alias(alias, uid)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="綁定成功" if ok else "綁定失敗"))
            return

        # 2) 推播報價：報價 金額 [VIP*] [用券] @別名
        m = _CMD_PUSH.match(text)
        if m:
            rmb = int(m.group(1))
            level = m.group(2) or "一般"
            use_coupon = bool(m.group(3))
            alias = m.group(4)
            result = push_quote_to_alias(rmb, level, use_coupon, alias)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))
            return

        # 3) 其他情況 → 當一般客人自助報價（方便你自己先看結果）
        parsed = parse_command(text)
        if parsed:
            rmb, level, use_coupon = parsed
            twd = quote_twd(rmb, level, use_coupon)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=build_reply(rmb, twd)))
        else:
            tip = ("管理指令：\n"
                   "．報價 2200 VIP3 用券 @小美\n"
                   "．綁定 小美 Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
                   "．名單／我的ID\n"
                   "（客戶自助可用：報價 1680、報價 2200 VIP3 用券）")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=tip))
        return

    # ====== 一般使用者私聊：自助報價 & 自動記名單 ======
    if src_type == "user":
        remember_user_profile(event.source.user_id)
        parsed = parse_command(text)  # 你原有的：報價 1680 / 報價 2200 VIP3 用券
        if parsed:
            rmb, level, use_coupon = parsed
            twd = quote_twd(rmb, level, use_coupon)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=build_reply(rmb, twd)))
        else:
            help_text = ("輸入格式：\n"
                         "．報價 1680\n．報價 2200 VIP3 用券\n"
                         "VIP：一般/VIP1/VIP2/VIP3；VIP3 才能用「用券」")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=help_text))
        return

    # ====== 其他來源（群/聊天室等）— 不處理或給提示 ======
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請以私訊使用"))

