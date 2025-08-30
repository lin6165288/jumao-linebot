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
    parsed = parse_command(event.message.text)
    if not parsed:
        return
    rmb, level, use_coupon = parsed
    twd = quote_twd(rmb, level, use_coupon)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=build_reply(rmb, twd)))
