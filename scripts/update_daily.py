#!/usr/bin/env python3
"""交易日盤後，以 FinMind 與證交所資料更新首頁 MARKET 區塊。"""

from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
FINMIND = "https://api.finmindtrade.com/api/v4/data"
TWSE_BFI = "https://www.twse.com.tw/rwd/zh/fund/BFI82U"
TWSE_MI = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TAIPEI = ZoneInfo("Asia/Taipei")
MACOS_CA = Path("/etc/ssl/cert.pem")
SSL_CONTEXT = ssl.create_default_context(cafile=str(MACOS_CA) if MACOS_CA.exists() else None)
# Python 3.13+ 的 X509 strict 會拒絕部分仍有效但缺少 SKI 的政府網站憑證；
# 保留完整憑證鏈與主機名驗證，只關閉額外的 strict 檢查。
if hasattr(ssl, "VERIFY_X509_STRICT"):
    SSL_CONTEXT.verify_flags &= ~ssl.VERIFY_X509_STRICT


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "tw-ai-stocks-daily/1.0"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25, context=SSL_CONTEXT) as response:
                return json.load(response)
        except Exception as exc:  # 網路暫時異常時短暫重試
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"無法取得 {url}: {last_error}")


def finmind_price(stock_id: str, date: str) -> dict | None:
    query = urllib.parse.urlencode(
        {"dataset": "TaiwanStockPrice", "data_id": stock_id, "start_date": date}
    )
    payload = fetch_json(f"{FINMIND}?{query}")
    rows = [row for row in payload.get("data", []) if row.get("date") == date]
    return rows[-1] if rows else None


def twse_stock_prices(date: str, wanted: tuple[str, ...]) -> dict[str, dict]:
    """以單一證交所請求取得所有代表股，避免 FinMind 免費額度限流。"""
    ymd = date.replace("-", "")
    payload = fetch_json(f"{TWSE_MI}?date={ymd}&type=ALLBUT0999&response=json")
    tables = payload.get("tables", [])
    stock_table = next(
        (table for table in tables if table.get("fields", [None])[0] == "證券代號"), None
    )
    if not stock_table:
        return {}
    fields = stock_table["fields"]
    index = {name: fields.index(name) for name in ("證券代號", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差")}
    result: dict[str, dict] = {}
    for row in stock_table["data"]:
        code = row[index["證券代號"]].strip()
        if code not in wanted:
            continue
        sign = -1 if "-" in row[index["漲跌(+/-)"]] else 1
        number = lambda field: float(row[index[field]].replace(",", ""))
        result[code] = {
            "stock_id": code,
            "Trading_Volume": int(row[index["成交股數"]].replace(",", "")),
            "Trading_money": int(row[index["成交金額"]].replace(",", "")),
            "open": number("開盤價"),
            "max": number("最高價"),
            "min": number("最低價"),
            "close": number("收盤價"),
            "spread": sign * number("漲跌價差"),
        }
    return result


def fmt_number(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def fmt_price(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def direction(change: float) -> str:
    return "上漲" if change > 0 else "下跌" if change < 0 else "持平"


def build_market(date: str, taiex: dict, stocks: dict[str, dict], bfi: dict) -> str:
    close = float(taiex["close"])
    spread = float(taiex["spread"])
    previous = close - spread
    pct = spread / previous * 100 if previous else 0
    turnover_billion = float(taiex["Trading_money"]) / 100_000_000

    flows = {row[0]: int(row[3].replace(",", "")) / 100_000_000 for row in bfi["data"]}
    dealer = flows.get("自營商(自行買賣)", 0) + flows.get("自營商(避險)", 0)
    trust = flows.get("投信", 0)
    foreign = flows.get("外資及陸資(不含外資自營商)", 0)
    total = flows.get("合計", 0)

    names = {
        "2330": "台積電", "2454": "聯發科", "2317": "鴻海", "2308": "台達電",
        "2408": "南亞科", "2344": "華邦電", "2337": "旺宏",
        "3037": "欣興", "3189": "景碩", "8046": "南電",
    }

    def stock_text(code: str) -> str:
        row = stocks[code]
        change = float(row["spread"])
        return f'{names[code]}{direction(change)} {fmt_price(abs(change))} 元收 {fmt_price(float(row["close"]))} 元'

    memory = [code for code in ("2408", "2344", "2337") if code in stocks]
    abf = [code for code in ("3037", "3189", "8046") if code in stocks]
    strong_memory = sorted(memory, key=lambda code: float(stocks[code]["spread"]), reverse=True)
    strong_abf = sorted(abf, key=lambda code: float(stocks[code]["spread"]), reverse=True)

    weight_parts = [stock_text(code) for code in ("2330", "2454", "2317", "2308") if code in stocks]
    rotation_parts = [stock_text(code) for code in (strong_memory[:2] + strong_abf[:2])]
    month_day = f'{int(date[5:7])}/{int(date[8:10])}'
    market_dir = direction(spread)
    summary = (
        f"{month_day} 台股加權指數終場收 {fmt_number(close)} 點，{market_dir} "
        f"{fmt_number(abs(spread))} 點（{pct:+.2f}%），成交值約 {fmt_number(turnover_billion)} 億元；"
        f"盤中最高 {fmt_number(float(taiex['max']))} 點、最低 {fmt_number(float(taiex['min']))} 點。"
        f"三大法人合計{'買超' if total >= 0 else '賣超'} {fmt_number(abs(total))} 億元，其中"
        f"外資及陸資{'買超' if foreign >= 0 else '賣超'} {fmt_number(abs(foreign))} 億元、"
        f"投信{'買超' if trust >= 0 else '賣超'} {fmt_number(abs(trust))} 億元、"
        f"自營商合計{'買超' if dealer >= 0 else '賣超'} {fmt_number(abs(dealer))} 億元。"
        f"權值股方面，{'、'.join(weight_parts)}。"
        f"族群輪動方面，{'、'.join(rotation_parts)}。"
    )

    positive_codes = sorted(stocks, key=lambda code: float(stocks[code]["spread"]), reverse=True)
    negative_codes = sorted(stocks, key=lambda code: float(stocks[code]["spread"]))
    pos = [
        f"三大法人合計{'買超' if total >= 0 else '賣超'} {fmt_number(abs(total))} 億元，投信與外資動向可作為後續籌碼觀察重點",
        "相對強勢個股包括「" + "、".join(stock_text(code) for code in positive_codes[:3]) + "」，顯示盤面仍有資金輪動",
        f"成交值約 {fmt_number(turnover_billion)} 億元，市場仍維持一定流動性",
    ]
    neg = [
        f"加權指數{market_dir} {fmt_number(abs(spread))} 點，盤中高低差 {fmt_number(float(taiex['max']) - float(taiex['min']))} 點，短線波動仍高",
        "相對弱勢個股包括「" + "、".join(stock_text(code) for code in negative_codes[:2]) + "」，大型權值股走勢可能壓抑指數",
        f"自營商合計{'買超' if dealer >= 0 else '賣超'} {fmt_number(abs(dealer))} 億元，後續仍須觀察法人資金是否延續",
    ]

    ymd = date.replace("-", "")
    taiex_url = f"{FINMIND}?dataset=TaiwanStockPrice&data_id=TAIEX&start_date={date}"
    bfi_url = f"{TWSE_BFI}?date={ymd}&response=html"
    tsmc_url = f"{TWSE_MI}?date={ymd}&type=ALLBUT0999&response=html"
    items = [
        {"t": f"{month_day} 加權指數日行情：收 {fmt_number(close)} 點、{market_dir} {fmt_number(abs(spread))} 點", "s": "FinMind", "u": taiex_url},
        {"t": f"{month_day} 三大法人買賣金額：合計{'買超' if total >= 0 else '賣超'} {fmt_number(abs(total))} 億元", "s": "臺灣證券交易所", "u": bfi_url},
        {"t": f"{month_day} 台積電日行情：{stock_text('2330')}", "s": "臺灣證券交易所", "u": tsmc_url},
    ]

    dumps = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    item_lines = ",\n".join(
        f'    {{t:{dumps(item["t"])},s:{dumps(item["s"])},u:{dumps(item["u"])}}}'
        for item in items
    )
    return (
        "const MARKET={\n"
        f"  asOf:{dumps(date)},\n"
        f"  summary:{dumps(summary)},\n"
        f"  pos:{dumps(pos)},\n"
        f"  neg:{dumps(neg)},\n"
        "  items:[\n"
        f"{item_lines}\n"
        "  ]\n"
        "};"
    )


def main() -> int:
    today = datetime.now(TAIPEI).date()
    if today.weekday() >= 5:
        print(f"{today}: 週末，略過")
        return 0
    date = today.isoformat()
    taiex = finmind_price("TAIEX", date)
    if not taiex:
        print(f"{date}: 查無收盤資料，可能休市或資料尚未完成，略過")
        return 0

    ymd = date.replace("-", "")
    bfi = fetch_json(f"{TWSE_BFI}?date={ymd}&response=json")
    if bfi.get("stat") != "OK" or not bfi.get("data"):
        print(f"{date}: 三大法人資料尚未完成，略過")
        return 0

    codes = ("2330", "2454", "2317", "2308", "2408", "2344", "2337", "3037", "3189", "8046")
    stocks = twse_stock_prices(date, codes)
    if "2330" not in stocks:
        print(f"{date}: 台積電資料尚未完成，略過")
        return 0

    html = INDEX.read_text(encoding="utf-8")
    html, date_count = re.subn(r'const AS_OF="\d{4}-\d{2}-\d{2}";', f'const AS_OF="{date}";', html, count=1)
    market = build_market(date, taiex, stocks, bfi)
    html, market_count = re.subn(r"const MARKET=\{.*?\n\};", market, html, count=1, flags=re.S)
    if date_count != 1 or market_count != 1:
        raise RuntimeError("找不到唯一的 AS_OF 或 MARKET 區塊，停止寫入")
    INDEX.write_text(html, encoding="utf-8")
    print(f"{date}: 已更新 AS_OF 與 MARKET（{len(stocks)} 檔代表股）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
