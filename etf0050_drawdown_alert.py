"""0050 距離高點跌幅通知（10% / 20% / 30%），以 LINE 推播
- 在 GitHub Actions 上每個交易日執行一次
- 「已通知過哪些門檻」存在 alert_state.json，由 workflow 提交回儲存庫，避免重複通知
環境變數：
  LINE_CHANNEL_TOKEN  必填
  LINE_USER_ID        選填；留空則用 broadcast（發給官方帳號所有好友）
測試：python etf0050_drawdown_alert.py --test
"""
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests
import yfinance as yf

SYMBOL = "0050.TW"
LEVELS = [10, 20, 30]  # 要通知的跌幅 (%)
STATE_FILE = Path(__file__).with_name("alert_state.json")
LINE_TOKEN = os.environ.get("LINE_CHANNEL_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")


def get_prices(retries=3):
    # auto_adjust=False：Close 已含拆股調整（2025/6 的 1 拆 4），但不扣除配息，
    # 與看盤軟體上的實際股價一致。
    last_err = None
    for i in range(retries):
        try:
            df = yf.Ticker(SYMBOL).history(period="max", interval="1d", auto_adjust=False)
            close = df["Close"].dropna()
            if close.empty:
                raise ValueError("Yahoo 回傳空資料")
            return (float(close.max()), close.idxmax().date(),
                    float(close.iloc[-1]), close.index[-1].date())
        except Exception as e:  # 網路或 Yahoo 暫時問題，稍後重試
            last_err = e
            print(f"抓價失敗（第 {i + 1} 次）：{e}")
            time.sleep(10 * (i + 1))
    raise RuntimeError(f"多次抓價失敗：{last_err}")


def notify(msg):
    """成功回傳 True，失敗回傳 False。"""
    if not LINE_TOKEN:
        print("[未設定 LINE_CHANNEL_TOKEN]", msg)
        return False
    if LINE_USER_ID:
        url = "https://api.line.me/v2/bot/message/push"
        body = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg}]}
    else:
        url = "https://api.line.me/v2/bot/message/broadcast"
        body = {"messages": [{"type": "text", "text": msg}]}
    try:
        r = requests.post(url,
                          headers={"Authorization": f"Bearer {LINE_TOKEN}",
                                   "Content-Type": "application/json"},
                          json=body, timeout=15)
    except requests.RequestException as e:
        print("LINE 連線失敗：", e)
        return False
    if r.status_code != 200:
        print("LINE 發送失敗：", r.status_code, r.text)
        return False
    return True


def main():
    if "--test" in sys.argv:
        ok = notify("0050 通知測試成功")
        sys.exit(0 if ok else 1)

    high, high_date, last, last_date = get_prices()
    drop = (high - last) / high * 100

    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    # 創新高（高點日期改變）就重置，下一輪下跌可重新通知
    if state.get("high_date") != str(high_date):
        state = {"high_date": str(high_date), "notified": []}

    failed = False
    for lv in LEVELS:
        if drop >= lv and lv not in state["notified"]:
            ok = notify(f"0050 已從高點 {high:.2f}（{high_date}）下跌 {drop:.1f}%，"
                        f"目前 {last:.2f}（{last_date}），觸發 -{lv}% 門檻")
            if ok:
                state["notified"].append(lv)
            else:
                failed = True  # 不記錄，下次執行會再試

    state["last_checked"] = dt.datetime.utcnow().strftime("%Y-%m-%d")
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"高點 {high:.2f} ({high_date})｜現價 {last:.2f}｜回檔 {drop:.1f}%")
    if failed:
        sys.exit(1)  # 讓 GitHub 把這次執行標為失敗並寄信提醒


if __name__ == "__main__":
    main()
