import os
import re
from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境變數（.env）
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ——— 報價參數 ———
BASE_SELL_RATE = 4.5
VIP_RATE_OFF = {"一般": 0.00, "VIP1": 0.02, "VIP2": 0.03, "VIP3": 0.05}
VIP_FEE_OFF  = {"一般": 0,    "VIP1": 10,   "VIP2": 10,   "VIP3": 10}
MIN_FEE = 20

def calc_base_fee(rmb: int) -> int:
    # 1~499=30；500~999=50；1000~1499=100；… 以此類推（500一階，從30起算）
    return 30 + (rmb // 500) * 50

def parse_command(text: str):
    """
    允許：報價1680、報價 1680、報價：1680、報價 2200 VIP3、報價 2200 VIP3 用券
    """
    m = re.findall(r'報價[\s:：]*?(\d+)(?:\s+(一般|VIP1|VIP2|VIP3))?(?:\s+(用券))?', text.strip())
    if not m:
        return None
    rmb_str, level, coupon = m[0]
    rmb = int(rmb_str)
    level = level if level else "一般"
    use_coupon = (coupon == "用券")
    return rmb, level, use_coupon

def quote_twd(rmb: int, level: str, use_coupon: bool) -> int:
    sell_rate = BASE_SELL_RATE - VIP_RATE_OFF.get(level, 0.0)
    fee = calc_base_fee(rmb)
    # VIP 手續費 -10，下限 20
    if level != "一般":
        fee = max(fee - VIP_FEE_OFF.get(level, 0), MIN_FEE)
    # VIP3 + 用券 + 滿2000 才折 50
    coupon_cut = 50 if (level == "VIP3" and use_coupon and rmb >= 2000) else 0
    twd = rmb * sell_rate + fee - coupon_cut
    return int(round(twd))

def build_reply(rmb: int, twd: int) -> str:
    return (
        "【報價單】\n"
        f"商品價格：{rmb} RMB\n"
        f"換算台幣價格：NT$ {twd}\n"
        "沒問題的話跟我說一聲～\n"
        "傳給您付款資訊"
    )

# 健康檢查
@app.route("/bot/health")
def health():
    return "ok", 200

# LINE webhook
@app.route("/bot/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return "invalid signature", 400
    return "OK", 200

# 僅保留「報價」功能
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event: MessageEvent):
    parsed = parse_command(event.message.text)
    if not parsed:
        # 非報價指令→給一行簡易用法提示（不加任何其他功能）
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="輸入：報價 1680（可加 VIP1/VIP2/VIP3、用券）")
        )
        return
    rmb, level, use_coupon = parsed
    twd = quote_twd(rmb, level, use_coupon)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=build_reply(rmb, twd))
    )
