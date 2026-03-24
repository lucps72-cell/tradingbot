'''
Docstring for sideways.make_trade_summary

사용법:
python sideways/make_trade_summary.py [YYYY-MM-DD]
날짜를 입력하지 않으면 오늘 날짜 기준으로 자동 생성됩니다.

기능:
    로그와 config.json을 기반으로 진입(🟢/🔴)만 추출
    최대 3회 연속 그룹핑, 평균진입가 계산
    청산가/실현손익/수익률/비고 자동 처리(마지막은 미청산)
    손절가/목표가/수수료 등 config 값 반영
    원하는 날짜의 거래 요약 CSV 자동 생성
'''
import pandas as pd
import json
import re
import sys
from datetime import datetime
import os

# 파일 경로 설정
LOG_DIR = "sideways/logs/"
CONFIG_FILE = "sideways/config.json"
OUTPUT_DIR = "sideways/logs/"
SYMBOL = "XRPUSDT"

# 날짜 입력 처리
def get_target_date():
    if len(sys.argv) > 1:
        return sys.argv[1]
    else:
        return datetime.now().strftime("%Y-%m-%d")

target_date = get_target_date()

# 설정값 로드
def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    trading = config["trading"]
    risk = config["risk_management"]
    backtest = config["backtest"]
    return {
        "order_amount": trading["order_amount_usdt"],
        "split_count": trading["entry_split_count"],
        "sl_ratio": risk["sl_ratio"],
        "tp_ratio": risk["tp_ratio"],
        "commission_rate": backtest["commission_rate"]
    }
config = load_config()

# 로그 파일명 결정 (YYYY-MM-DD 형식)
def get_log_file(date_str):
    file_path = os.path.join(LOG_DIR, f"tradingbot.trade.{date_str}")
    if os.path.exists(file_path):
        return file_path
    # fallback: 통합 로그 파일
    file_path = os.path.join(LOG_DIR, "tradingbot.trade")
    return file_path

log_file = get_log_file(target_date)

# 진입 로그 파싱 함수
def parse_trade_log(log_file, date_str):
    entries = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            if date_str in line and ("🟢 진입" in line or "🔴 진입" in line):
                # 날짜, 시각
                m = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}),\d+.*trade: (🟢|🔴) 진입 : (매수|매도) \| price: ([0-9.]+)", line)
                if m:
                    date, time, signal, position, price = m.groups()
                    entries.append({
                        "date": date,
                        "time": time,
                        "signal": signal,
                        "position": position,
                        "price": float(price),
                        "raw": line.strip()
                    })
    return entries

trade_entries = parse_trade_log(log_file, target_date)

# 포지션 그룹핑 (최대 3회 연속)
def group_positions(entries):
    grouped = []
    i = 0
    n = len(entries)
    split_count = config["split_count"]
    while i < n:
        pos = entries[i]["position"]
        group = [entries[i]]
        for j in range(i+1, min(i+split_count, n)):
            if entries[j]["position"] == pos:
                group.append(entries[j])
            else:
                break
        time_range = f"{group[0]['time']}~{group[-1]['time']}"
        avg_entry = sum(e["price"] for e in group) / len(group)
        grouped.append({
            "date": group[0]["date"],
            "time_range": time_range,
            "position": pos,
            "avg_entry": avg_entry,
            "count": len(group),
            "raws": [e["raw"] for e in group]
        })
        i += len(group)
        while i < n and entries[i]["position"] == pos:
            i += 1
    return grouped

grouped_entries = group_positions(trade_entries)

# 청산가/실현손익/수익률 계산 (다음 반대포지션 진입가, 마지막은 미청산)
def make_summary(grouped):
    rows = []
    for idx, g in enumerate(grouped):
        # 청산가: 다음 반대포지션 avg_entry, 없으면 ''
        exit_price = ''
        realized_pnl = ''
        profit_rate = ''
        # 진입 메시지: 첫 진입 로그의 메시지(예: '매수 진입(5m): 상승 후 하락 시작 신호' 등)
        # raw 예시: '2026-01-31 00:21:35,123 [INFO] trade: 🟢 진입 : 매수 | price: 1.7574 | 매수 진입(5m): 상승 후 하락 시작 신호 | ...'
        entry_msg = ''
        if g['raws']:
            raw = g['raws'][0]
            # 'price: ... | ' 이후 메시지 추출
            m = re.search(r'\| price: [0-9.]+ \| (.+)', raw)
            if m:
                entry_msg = m.group(1).strip()
        note = f"{'매수' if g['position']=='매수' else '매도'} {g['count']}분할"
        if entry_msg:
            note += f" | {entry_msg}"
        if idx < len(grouped)-1:
            next_g = grouped[idx+1]
            if next_g['position'] != g['position']:
                exit_price = next_g['avg_entry']
                # 실현손익 계산
                if g['position'] == '매수':
                    pnl = (exit_price - g['avg_entry']) * config['order_amount']
                else:
                    pnl = (g['avg_entry'] - exit_price) * config['order_amount']
                realized_pnl = round(pnl, 2)
                profit_rate = f"{round((pnl/config['order_amount'])*100,2)}%"
            else:
                exit_price = ''
                realized_pnl = ''
                profit_rate = ''
                note = '미청산'
        else:
            note = '미청산'
        # 손절가/목표가
        if g['position'] == '매수':
            sl = round(g['avg_entry'] * (1-config['sl_ratio']), 4)
            tp = round(g['avg_entry'] * (1+config['tp_ratio']), 4)
        else:
            sl = round(g['avg_entry'] * (1+config['sl_ratio']), 4)
            tp = round(g['avg_entry'] * (1-config['tp_ratio']), 4)
        rows.append({
            "날짜": g['date'],
            "진입시각(구간)": g['time_range'],
            "종목": SYMBOL,
            "포지션": g['position'],
            "주문방식": "limit",
            "진입수량(USDT)": config['order_amount'] * g['count'],
            "평균진입가": round(g['avg_entry'], 4),
            "손절가": sl,
            "청산가": exit_price,
            "목표가": tp,
            "실현손익": realized_pnl,
            "수수료": f"-{round(config['commission_rate']*100,2)}%",
            "수익률": profit_rate,
            "비고": note
        })
    return rows

summary_rows = make_summary(grouped_entries)
df = pd.DataFrame(summary_rows)
output_file = os.path.join(OUTPUT_DIR, f"{target_date}_trade_summary_final_with_sl_sorted.csv")
df.to_csv(output_file, index=False, encoding="utf-8-sig")
print(f"거래 요약 CSV 생성 완료: {output_file}")
