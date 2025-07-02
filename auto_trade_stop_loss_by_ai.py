import tkinter as tk
from tkinter import ttk, messagebox, TclError, simpledialog
from tkinter.constants import ANCHOR, END
import pyupbit
import pandas as pd
import numpy as np
import mplfinance as mpf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import threading
import time
import platform
import os
import requests
from queue import Queue, Empty
import json
from datetime import datetime, timedelta
from scipy.signal import find_peaks
from tkinter import filedialog
import traceback

# -----------------------------------------------------------------------------
# 한글 폰트 설정
# -----------------------------------------------------------------------------
if platform.system() == 'Windows':
    plt.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':  # Mac OS
    plt.rc('font', family='AppleGothic')
else:  # Linux
    plt.rc('font', family='NanumGothic')
plt.rcParams['axes.unicode_minus'] = False

# -----------------------------------------------------------------------------
# 1. API Key와 기본 설정
# -----------------------------------------------------------------------------
def select_login_file():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="login.txt 파일을 선택하세요",
        filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")]
    )
    root.destroy()
    return file_path

login_file = select_login_file()
if not login_file:
    messagebox.showerror("로그인 파일 오류", "login.txt 파일을 선택하지 않았습니다. 프로그램을 종료합니다.")
    exit()

try:
    with open(login_file, "r") as f:
        lines = f.readlines()
        if len(lines) < 3:
            raise ValueError("파일에 access key, secret key, 자동매매 비밀번호가 모두 필요합니다.")
        access = lines[0].strip()
        secret = lines[1].strip()
        trade_password = lines[2].strip()
except FileNotFoundError:
    messagebox.showerror("로그인 파일 오류", "login.txt 파일을 찾을 수 없습니다.\n선택한 파일을 확인해주세요.")
    exit()
except Exception as e:
    messagebox.showerror("로그인 파일 오류", f"login.txt 파일 처리 중 오류가 발생했습니다.\n\n{e}")
    exit()

try:
    upbit = pyupbit.Upbit(access, secret)
    balances = upbit.get_balances()
    print("✅ 업비트 로그인 성공")
except Exception as e:
    messagebox.showerror("로그인 실패", f"API 키가 유효하지 않거나 네트워크에 문제가 있습니다.\nlogin.txt 파일을 확인해주세요.\n\n{e}")
    exit()

# -----------------------------------------------------------------------------
# 2. GUI 클래스 및 기능
# -----------------------------------------------------------------------------
class UpbitChartApp(tk.Tk):
    MAX_CANDLES = 5000 

    def __init__(self):
        super().__init__()
        self.trade_password = trade_password
        self.settings_window = None
        self.title("업비트 포트폴리오 & HTS")
        self.geometry("1600x980")

        self.is_running = True
        self.selected_ticker_display = tk.StringVar()
        self.selected_interval = tk.StringVar(value='day')
        self.current_price = 0.0
        self.avg_buy_price = 0.0
        self.balances_data = {}
        self.krw_balance = 0.0
        self.coin_balance = 0.0
        self.master_df = None
        self.is_loading_older = False
        self._keep_view = False
        self.current_chart_ticker = None
        self._ignore_market_select_event = False
        self.data_bounds = {'x': None, 'y': None}
        self.data_queue = Queue()

        self.ma_vars = {'5': tk.BooleanVar(value=True), '20': tk.BooleanVar(value=True), '60': tk.BooleanVar(), '120': tk.BooleanVar()}
        self.bb_var = tk.BooleanVar(value=True)
        self.is_panning = False
        self.pan_start_pos = None

        self.ticker_to_display_name = {}
        self.display_name_to_ticker = {}
        self.market_data = []
        self.sort_column = 'volume'
        self.sort_ascending = False

        self.krw_balance_summary_var = tk.StringVar(value="보유 KRW: 0 원")
        self.total_investment_var = tk.StringVar(value="총 투자금액: 0 원")
        self.total_valuation_var = tk.StringVar(value="총 평가금액: 0 원")
        self.total_pl_var = tk.StringVar(value="총 평가손익: 0 원 (0.00%)")
        self.buy_order_type = tk.StringVar(value="limit")
        self.buy_price_var, self.buy_amount_var, self.buy_total_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.sell_order_type = tk.StringVar(value="limit")
        self.sell_price_var, self.sell_amount_var, self.sell_total_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.sell_percentage_var = tk.StringVar()
        self.buy_krw_balance_var, self.sell_coin_balance_var = tk.StringVar(value="주문가능: 0 KRW"), tk.StringVar(value="주문가능: 0 COIN")
        self._is_calculating = False

        self.is_auto_trading = False
        self.auto_trade_settings = {}
        self.auto_trade_thread = None
        self.last_chart_redraw_time = 0

        self.load_ticker_names()
        self.load_auto_trade_settings()
        self.create_widgets()
        self.add_variable_traces()
        self.load_my_tickers()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def load_auto_trade_settings(self):
        try:
            with open("auto_trade_settings.json", "r", encoding="utf-8") as f:
                self.auto_trade_settings = json.load(f)
                print("✅ 자동매매 설정 로드 완료.")
        except (FileNotFoundError, json.JSONDecodeError):
            print("ℹ️ 자동매매 설정 파일 없음. 기본값으로 시작합니다.")
            # [수정 2] 자동매매 설정 기본값 변경
            self.auto_trade_settings = {
                'enabled_tickers': [], 
                'total_investment_limit': 100000, # 총 투자 한도
            }
            self.save_auto_trade_settings()

    def save_auto_trade_settings(self):
        with open("auto_trade_settings.json", "w", encoding="utf-8") as f:
            json.dump(self.auto_trade_settings, f, ensure_ascii=False, indent=4)
        print("💾 자동매매 설정 저장 완료.")

    def start_worker_threads(self):
        data_worker = threading.Thread(target=self.data_update_worker, daemon=True)
        data_worker.start()
        self.process_queue()

    def data_update_worker(self):
        counter = 0
        while self.is_running:
            self.fetch_current_price()
            if counter % 5 == 0: self._fetch_portfolio_data_worker()
            if counter % 10 == 0: self._fetch_market_data_worker()
            time.sleep(1)
            counter += 1

    def load_ticker_names(self):
        print("🔍 종목 이름 정보를 로드합니다...")
        try:
            url = "https://api.upbit.com/v1/market/all?isDetails=true"
            response = requests.get(url); response.raise_for_status()
            for market_info in response.json():
                if market_info['market'].startswith('KRW-'):
                    market, korean_name, symbol = market_info['market'], market_info['korean_name'], market_info['market'].split('-')[1]
                    display_name = f"{korean_name}({symbol})"
                    self.ticker_to_display_name[market], self.display_name_to_ticker[display_name] = display_name, market
            print("✅ 종목 이름 정보 로드 완료.")
        except Exception as e: print(f"❗️ 종목 이름 정보 로드 실패: {e}\n종목 코드를 그대로 사용합니다.")

    def add_variable_traces(self):
        self.buy_price_var.trace_add("write", self._on_buy_input_change)
        self.buy_amount_var.trace_add("write", self._on_buy_input_change)
        self.buy_total_var.trace_add("write", self._on_buy_total_change)
        self.sell_price_var.trace_add("write", self._on_sell_input_change)
        self.sell_amount_var.trace_add("write", self._on_sell_input_change)

    def create_widgets(self):
        main_frame = ttk.Frame(self); main_frame.pack(fill=tk.BOTH, expand=True)
        left_frame = ttk.Frame(main_frame, width=500, padding=10); left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        top_left_frame = ttk.Frame(left_frame); top_left_frame.pack(fill=tk.X, pady=5)
        summary_frame = ttk.LabelFrame(top_left_frame, text="종합 현황", padding=10)
        summary_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        ttk.Label(summary_frame, textvariable=self.krw_balance_summary_var, font=("Helvetica", 12)).pack(anchor="w")
        ttk.Label(summary_frame, textvariable=self.total_investment_var, font=("Helvetica", 12)).pack(anchor="w")
        ttk.Label(summary_frame, textvariable=self.total_valuation_var, font=("Helvetica", 12)).pack(anchor="w")
        self.total_pl_label = ttk.Label(summary_frame, textvariable=self.total_pl_var, font=("Helvetica", 12, "bold"))
        self.total_pl_label.pack(anchor="w")
        pie_frame = ttk.LabelFrame(top_left_frame, text="코인 비중", padding=10)
        pie_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        self.pie_fig, self.pie_ax = plt.subplots(figsize=(3, 2.5)); self.pie_fig.patch.set_facecolor('#F0F0F0')
        self.pie_canvas = FigureCanvasTkAgg(self.pie_fig, master=pie_frame); self.pie_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        tree_frame = ttk.LabelFrame(left_frame, text="보유 코인 (더블클릭하여 차트 보기)", padding=10)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        cols = ('display_name', 'balance', 'avg_price', 'cur_price', 'valuation', 'pl', 'pl_rate')
        self.portfolio_tree = ttk.Treeview(tree_frame, columns=cols, show='headings')
        col_map = {"종목명": 120, "보유수량": 80, "매수평균가": 90, "현재가": 90, "평가금액": 90, "평가손익": 90, "손익(%)": 70}
        for i, (text, width) in enumerate(col_map.items()):
            self.portfolio_tree.heading(cols[i], text=text); self.portfolio_tree.column(cols[i], width=width, anchor='e')
        self.portfolio_tree.column('display_name', anchor='w')
        self.portfolio_tree.tag_configure('plus', foreground='red'); self.portfolio_tree.tag_configure('minus', foreground='blue')
        self.portfolio_tree.pack(fill=tk.BOTH, expand=True); self.portfolio_tree.bind("<Double-1>", self.on_tree_double_click)
        bottom_frame = ttk.Frame(left_frame); bottom_frame.pack(fill=tk.BOTH, expand=True, pady=(5,0))
        order_frame = ttk.Frame(bottom_frame); order_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.order_notebook = ttk.Notebook(order_frame); self.order_notebook.pack(fill=tk.BOTH, expand=True)
        buy_tab, sell_tab = ttk.Frame(self.order_notebook, padding=10), ttk.Frame(self.order_notebook, padding=10)
        self.order_notebook.add(buy_tab, text="매수"); self.order_notebook.add(sell_tab, text="매도")
        self.create_buy_sell_tab(buy_tab, "buy"); self.create_buy_sell_tab(sell_tab, "sell")
        auto_trade_frame = ttk.LabelFrame(bottom_frame, text="자동매매", padding=10)
        auto_trade_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0), expand=False)
        settings_button = ttk.Button(auto_trade_frame, text="자동매매 설정", command=self.open_settings_window)
        settings_button.pack(pady=5, padx=5, fill='x', ipady=5)
        ttk.Style().configure("On.TButton", foreground="black", background="#4CAF50", font=('Helvetica', 10, 'bold'))
        ttk.Style().configure("Off.TButton", foreground="black", background="#F44336", font=('Helvetica', 10, 'bold'))
        self.auto_trade_toggle_button = ttk.Button(auto_trade_frame, text="자동매매 켜기", style="Off.TButton", command=self.toggle_auto_trading)
        self.auto_trade_toggle_button.pack(pady=5, padx=5, fill='x', ipady=8)
        log_frame = ttk.LabelFrame(left_frame, text="자동매매 로그", padding=10)
        log_frame.pack(side=tk.BOTTOM, fill=tk.X, expand=False, pady=(5,0))
        log_text_frame = ttk.Frame(log_frame); log_text_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_text_frame, height=5, state='disabled', font=('Courier New', 9), wrap='none')
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar_y = ttk.Scrollbar(log_text_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar_y.set); log_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        log_scrollbar_x = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(xscrollcommand=log_scrollbar_x.set); log_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        right_frame = ttk.Frame(main_frame, padding=10); right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        market_list_frame = ttk.LabelFrame(right_frame, text="KRW 마켓 (컬럼 헤더 클릭하여 정렬)", padding=10)
        market_list_frame.pack(side="top", fill="x", pady=5)
        market_cols = ('display_name', 'price', 'change_rate', 'volume')
        self.market_tree = ttk.Treeview(market_list_frame, columns=market_cols, show='headings', height=5)
        market_col_map = {"종목명": 150, "현재가": 100, "등락률": 80, "거래대금(24h)": 120}
        for i, (text, width) in enumerate(market_col_map.items()):
            col_id = market_cols[i]
            self.market_tree.heading(col_id, text=text, command=lambda c=col_id: self.sort_market_list(c))
            self.market_tree.column(col_id, width=width, anchor='e')
        self.market_tree.column('display_name', anchor='w')
        scrollbar = ttk.Scrollbar(market_list_frame, orient="vertical", command=self.market_tree.yview)
        self.market_tree.configure(yscrollcommand=scrollbar.set); scrollbar.pack(side="right", fill="y")
        self.market_tree.pack(side="left", fill="both", expand=True)
        self.market_tree.tag_configure('red', foreground='red'); self.market_tree.tag_configure('blue', foreground='blue'); self.market_tree.tag_configure('black', foreground='black')
        self.market_tree.bind("<<TreeviewSelect>>", self.on_market_list_select)
        control_frame_1 = ttk.Frame(right_frame); control_frame_1.pack(side="top", fill="x", pady=(10, 0))
        control_frame_2 = ttk.Frame(right_frame); control_frame_2.pack(side="top", fill="x", pady=5)
        ttk.Label(control_frame_1, text="종목 선택:").pack(side="left")
        self.ticker_combobox = ttk.Combobox(control_frame_1, textvariable=self.selected_ticker_display, width=20)
        self.ticker_combobox.pack(side="left", padx=(5, 15)); self.ticker_combobox.bind("<<ComboboxSelected>>", self.on_ticker_select)
        ttk.Label(control_frame_1, text="차트 주기:").pack(side="left")
        intervals = {"1분봉": "minute1", "5분봉": "minute5", "30분봉": "minute30", "1시간봉": "minute60", "4시간봉": "minute240", "일봉": "day", "주봉": "week"}
        for text, value in intervals.items():
            rb = ttk.Radiobutton(control_frame_1, text=text, variable=self.selected_interval, value=value, command=self.on_ticker_select)
            rb.pack(side="left")
        ttk.Label(control_frame_2, text="보조지표: ").pack(side="left")
        for period, var in self.ma_vars.items():
            cb = ttk.Checkbutton(control_frame_2, text=f"MA{period}", variable=var, command=lambda: self.draw_base_chart(keep_current_view=True))
            cb.pack(side="left")
        cb_bb = ttk.Checkbutton(control_frame_2, text="BBands", variable=self.bb_var, command=lambda: self.draw_base_chart(keep_current_view=True))
        cb_bb.pack(side="left", padx=5)
        chart_frame = ttk.Frame(right_frame); chart_frame.pack(side="bottom", fill="both", expand=True, pady=5)
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect('scroll_event', self.on_scroll); self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion); self.canvas.mpl_connect('button_release_event', self.on_release)

    def log_auto_trade(self, message):
        now = datetime.now().strftime('%H:%M:%S')
        log_message = f"[{now}] {message}"
        def update_ui():
            self.log_text.config(state='normal')
            self.log_text.insert(END, log_message + "\n")
            self.log_text.see(END)
            self.log_text.config(state='disabled')
            print(log_message)
        self.after(0, update_ui)

    def toggle_auto_trading(self):
        if not self.is_auto_trading:
            entered_password = simpledialog.askstring("비밀번호 확인", "자동매매를 시작하려면 비밀번호 4자리를 입력하세요.", show='*')
            if entered_password is None: return
            if entered_password == self.trade_password:
                self.is_auto_trading = True
                self.auto_trade_toggle_button.config(text="자동매매 끄기", style="On.TButton")
                enabled_count = len(self.auto_trade_settings.get('enabled_tickers', []))
                # [수정 2] 로그 메시지 변경
                total_limit = self.auto_trade_settings.get('total_investment_limit', 5000)
                self.log_auto_trade(f"▶️ 자동매매 시작 (대상: {enabled_count}개, 총 투자한도: {total_limit:,.0f}원)")
                self.auto_trade_thread = threading.Thread(target=self.auto_trade_worker, daemon=True)
                self.auto_trade_thread.start()
            else: messagebox.showerror("인증 실패", "비밀번호가 일치하지 않습니다.")
        else:
            self.is_auto_trading = False
            self.auto_trade_toggle_button.config(text="자동매매 켜기", style="Off.TButton")
            self.log_auto_trade("⏹️ 자동매매 중지")

    def open_settings_window(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
        else:
            self.settings_window = AutoTradeSettingsWindow(self)
            self.settings_window.grab_set()

    def select_ticker_from_settings(self, selected_ticker):
        if not selected_ticker: return
        display_name = self.ticker_to_display_name.get(selected_ticker, selected_ticker)
        self.selected_ticker_display.set(display_name)
        self._ignore_market_select_event = True
        found = False
        for iid in self.market_tree.get_children():
            vals = self.market_tree.item(iid, "values")
            if vals and self.display_name_to_ticker.get(vals[0]) == selected_ticker:
                self.market_tree.selection_set(iid); self.market_tree.focus(iid)
                self.market_tree.see(iid); found = True; break
        if not found: self.market_tree.selection_remove(self.market_tree.selection())
        self._ignore_market_select_event = False
        self.on_ticker_select()
        print(f"⚙️ 자동매매 설정 저장: {display_name} 차트를 표시합니다.")

    def get_market_state(self, df, window=20):
        if df is None or len(df) < 60: return '횡보장'
        ma5 = df['ma5'].iloc[-1]
        ma20 = df['ma20'].iloc[-1]
        ma60 = df['ma60'].iloc[-1]
        ma20_slope = (ma20 - df['ma20'].iloc[-window]) / window
        if ma5 > ma20 > ma60 and ma20_slope > 0: return '상승장'
        if ma5 < ma20 < ma60 and ma20_slope < 0: return '하락장'
        return '횡보장'

    def check_rsi_divergence(self, df):
        if len(df) < 20: return False
        try:
            low_peaks, _ = find_peaks(-df['low'].iloc[-20:].values)
            rsi_low_peaks, _ = find_peaks(-df['rsi'].iloc[-20:].values)
            if len(low_peaks) >= 2 and len(rsi_low_peaks) >= 2:
                price_low1_idx, price_low2_idx = -20 + low_peaks[-2], -20 + low_peaks[-1]
                rsi_low1_idx, rsi_low2_idx = -20 + rsi_low_peaks[-2], -20 + rsi_low_peaks[-1]
                if (df['low'].iloc[price_low2_idx] < df['low'].iloc[price_low1_idx]) and \
                   (df['rsi'].iloc[rsi_low2_idx] > df['rsi'].iloc[rsi_low1_idx]):
                    self.log_auto_trade(f"DEBUG: RSI 상승 다이버전스 감지! Price Low: {df['low'].iloc[price_low1_idx]:.2f}->{df['low'].iloc[price_low2_idx]:.2f}, RSI Low: {df['rsi'].iloc[rsi_low1_idx]:.2f}->{df['rsi'].iloc[rsi_low2_idx]:.2f}")
                    return True
        except Exception: return False
        return False

    def auto_trade_worker(self):
        self.log_auto_trade("🤖 다중 종목 자동매매 로직 시작...")
        trade_states = {}
        # [수정 2] 분할 매수 횟수 정의
        NUM_TRADE_DIVISIONS = 5 

        while self.is_running and self.is_auto_trading:
            try:
                enabled_tickers = self.auto_trade_settings.get('enabled_tickers', [])
                if not enabled_tickers:
                    self.log_auto_trade("⚠️ 자동매매 대상 종목이 없습니다. 설정 확인 후 재시작 필요.")
                    time.sleep(30)
                    continue
                
                # [수정 2] 설정값 가져오기
                total_investment_limit = self.auto_trade_settings.get('total_investment_limit', 5000)
                buy_amount_per_trade = total_investment_limit / NUM_TRADE_DIVISIONS

                for ticker in enabled_tickers:
                    if not self.is_running or not self.is_auto_trading: break

                    if ticker not in trade_states:
                        trade_states[ticker] = {
                            'has_coin': False, 'buy_price': 0, 'buy_amount': 0, 
                            'total_invested': 0.0, # 총 투자된 금액 추적
                            'buy_count': 0, # 매수 횟수 추적
                            'last_logged_profit_rate': 0, 'last_logged_market_state': ''
                        }
                    
                    df = self.get_technical_indicators(ticker, interval='minute1', count=200)
                    if df is None:
                        self.log_auto_trade(f"[{ticker}] 데이터 수집 실패. 다음 종목으로 넘어갑니다.")
                        time.sleep(1)
                        continue

                    current_price = pyupbit.get_current_price(ticker)
                    if current_price is None:
                        time.sleep(1)
                        continue

                    balance = upbit.get_balance(ticker)
                    state = trade_states[ticker]
                    state['has_coin'] = balance > 0
                    if state['has_coin']:
                        state['buy_price'] = float(upbit.get_avg_buy_price(ticker))
                        state['buy_amount'] = balance
                        # 총 투자금액이 0이면, 현재 보유자산 기준으로 재계산
                        if state['total_invested'] == 0:
                            state['total_invested'] = state['buy_price'] * state['buy_amount']
                    else: # 코인이 없으면 투자 상태 초기화
                        state['total_invested'] = 0.0
                        state['buy_count'] = 0


                    market_state = self.get_market_state(df)
                    last_rsi = df['rsi'].iloc[-1]
                    last_ma5 = df['ma5'].iloc[-1]
                    last_ma20 = df['ma20'].iloc[-1]

                    if state['has_coin']:
                        profit_rate = (current_price - state['buy_price']) / state['buy_price'] * 100
                        
                        if abs(profit_rate - state['last_logged_profit_rate']) >= 0.1 or market_state != state['last_logged_market_state']:
                            self.log_auto_trade(f"🔎 [{ticker}] 상태 변경 | 평단가: {state['buy_price']:,.2f} | 수익률: {profit_rate:+.2f}% | 시장: {market_state}")
                            state['last_logged_profit_rate'] = profit_rate
                            state['last_logged_market_state'] = market_state
                        
                        if profit_rate <= -5.0:
                            self.log_auto_trade(f"🚨 SELL [{ticker}][손절] | 수익률 {profit_rate:.2f}% < -5.0%")
                            upbit.sell_market_order(ticker, state['buy_amount'])
                            time.sleep(5); continue

                        sell_signal, reason = False, ""
                        if market_state == '상승장' and last_ma5 < last_ma20 and df['ma5'].iloc[-2] >= df['ma20'].iloc[-2]:
                            sell_signal, reason = True, "상승장 데드크로스"
                        elif market_state == '횡보장':
                            bb_upper = df['ma20'].iloc[-1] + 2 * df['close'].rolling(20).std().iloc[-1]
                            if current_price >= bb_upper: sell_signal, reason = True, "횡보장 BB상단 터치"
                        elif market_state == '하락장' and profit_rate >= 3.0:
                            sell_signal, reason = True, "하락장 단기수익(+3%)"
                        
                        if sell_signal:
                            self.log_auto_trade(f"💰 SELL [{ticker}][익절] | 사유: {reason}")
                            upbit.sell_market_order(ticker, state['buy_amount'])
                            time.sleep(5); continue

                        # [수정 2] 추가 매수 로직 변경
                        # 총 투자 한도 내에서 분할 매수 횟수가 남았는지 확인
                        can_additional_buy = state['buy_count'] < NUM_TRADE_DIVISIONS
                        if can_additional_buy and profit_rate <= -8.0 and last_rsi < 30 and market_state in ['횡보장', '상승장']:
                            try:
                                self.log_auto_trade(f"💧 BUY [{ticker}][추가매수 시도 {state['buy_count'] + 1}/{NUM_TRADE_DIVISIONS}] | 수익률: {profit_rate:.2f}%, RSI: {last_rsi:.2f}")
                                result = upbit.buy_market_order(ticker, buy_amount_per_trade)
                                if result and 'uuid' in result:
                                    state['buy_count'] += 1
                                    state['total_invested'] += buy_amount_per_trade # 이론상 투자금액 추가
                                    self.log_auto_trade(f"✅ 추가매수 성공 (총 {state['buy_count']}회)")
                                    time.sleep(5); continue
                                else:
                                    self.log_auto_trade(f"⚠️ [{ticker}] 추가매수 주문은 성공했으나, 결과를 확인하지 못했습니다: {result}")
                            except Exception as buy_error:
                                error_msg = str(buy_error).lower()
                                if 'money is not enough' in error_msg or 'insufficient' in error_msg:
                                    self.log_auto_trade(f"‼️ [{ticker}] 추가매수 실패: 잔고 부족. 계획된 전략 실패로 간주하여 손절을 실행합니다.")
                                    try:
                                        upbit.sell_market_order(ticker, state['buy_amount'])
                                        self.log_auto_trade(f"🚨 SELL [{ticker}][계획실패 손절] 완료.")
                                    except Exception as sell_error:
                                        self.log_auto_trade(f"🆘 [{ticker}] 잔고 부족 후 손절 시도 중 심각한 오류 발생: {sell_error}")
                                    time.sleep(5); continue
                                else:
                                    raise buy_error
                    else: # 보유 코인 없음
                        if market_state != state['last_logged_market_state']:
                            self.log_auto_trade(f"⏳ [{ticker}] 신규매수 기회탐색 | 시장: {market_state} | RSI: {last_rsi:.2f}")
                            state['last_logged_market_state'] = market_state

                        buy_signal, reason = False, ""
                        # [수정 2] 신규 매수 로직 변경
                        if state['buy_count'] < NUM_TRADE_DIVISIONS: # 아직 투자 시작 전
                            if market_state == '상승장':
                                is_golden_cross = last_ma5 > last_ma20 and df['ma5'].iloc[-2] <= df['ma20'].iloc[-2]
                                is_dip_buy = abs(current_price - last_ma20) / last_ma20 < 0.015
                                if (is_golden_cross or is_dip_buy) and last_rsi < 70:
                                    buy_signal, reason = True, "상승장 조정 매수 또는 골든크로스"
                            elif market_state == '횡보장':
                                bb_lower = df['ma20'].iloc[-1] - 2 * df['close'].rolling(20).std().iloc[-1]
                                if current_price <= bb_lower and last_rsi < 35:
                                    buy_signal, reason = True, "횡보장 BB하단 및 RSI 과매도"
                            elif market_state == '하락장':
                                if self.check_rsi_divergence(df):
                                    buy_signal, reason = True, "하락장 RSI 상승 다이버전스"
                        
                        if buy_signal:
                            self.log_auto_trade(f"📈 BUY [{ticker}][신규매수 1/{NUM_TRADE_DIVISIONS}] | 사유: {reason}")
                            upbit.buy_market_order(ticker, buy_amount_per_trade)
                            state['buy_count'] = 1
                            state['total_invested'] = buy_amount_per_trade
                            state['last_logged_profit_rate'] = 0 
                            state['last_logged_market_state'] = ''
                            time.sleep(5); continue
                    
                    time.sleep(2)
                
                # 모든 종목 순회 후 대기
                if enabled_tickers and enabled_tickers[-1] == ticker: # 마지막 종목까지 순회했다면
                    #self.log_auto_trade(f"--- 모든 {len(enabled_tickers)}개 종목 스캔 완료. 15초 후 다시 시작 ---")
                    time.sleep(15)

            except Exception as e:
                self.log_auto_trade(f"‼️ 자동매매 루프 오류: {e}")
                self.log_auto_trade(traceback.format_exc())
                time.sleep(60)

        self.log_auto_trade("🤖 다중 종목 자동매매 로직 종료.")

    def get_technical_indicators(self, ticker, interval='day', count=200):
        try:
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
            return self.get_technical_indicators_from_raw(df)
        except Exception as e:
            print(f"❗️ {ticker} 지표 계산 오류: {e}")
            return None

    def get_technical_indicators_from_raw(self, df, min_length=2):
        if df is None or len(df) < min_length: return None
        for p in [5, 20, 60, 120]: df[f'ma{p}'] = df['close'].rolling(window=p, min_periods=1).mean()
        delta = df['close'].diff(1); gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
        rs = gain / loss.replace(0, np.nan); df['rsi'] = 100 - (100 / (1 + rs))
        df['ema12'] = df['close'].ewm(span=12, adjust=False, min_periods=1).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False, min_periods=1).mean()
        df['macd'] = df['ema12'] - df['ema26']; df['signal'] = df['macd'].ewm(span=9, adjust=False, min_periods=1).mean()
        try:
            rsi_peaks, _ = find_peaks(df['rsi'].fillna(0), distance=5, width=1)
            rsi_troughs, _ = find_peaks(-df['rsi'].fillna(0), distance=5, width=1)
        except Exception: rsi_peaks, rsi_troughs = [], []
        df['bearish_div'] = self._check_divergence_static(df, rsi_peaks, 'bearish')
        df['bullish_div'] = self._check_divergence_static(df, rsi_troughs, 'bullish')
        return df

    @staticmethod
    def _check_divergence_static(df, peaks, div_type):
        if len(peaks) < 2: return [False] * len(df)
        result = [False] * len(df)
        for i in range(1, len(peaks)):
            idx1, idx2 = peaks[i-1], peaks[i]
            if div_type == 'bearish':
                if df['rsi'].iloc[idx2] < df['rsi'].iloc[idx1] and df['high'].iloc[idx2] > df['high'].iloc[idx1]: result[idx2] = True
            elif div_type == 'bullish':
                if df['rsi'].iloc[idx2] > df['rsi'].iloc[idx1] and df['low'].iloc[idx2] < df['low'].iloc[idx1]: result[idx2] = True
        return result

    def create_buy_sell_tab(self, parent_frame, side):
        is_buy = (side == "buy")
        order_type_var = self.buy_order_type if is_buy else self.sell_order_type
        price_var, amount_var, total_var = (self.buy_price_var, self.buy_amount_var, self.buy_total_var) if is_buy else (self.sell_price_var, self.sell_amount_var, self.sell_total_var)
        balance_var = self.buy_krw_balance_var if is_buy else self.sell_coin_balance_var
        top_frame = ttk.Frame(parent_frame); top_frame.pack(fill='x', expand=True, pady=(0, 5))
        order_type_frame = ttk.Frame(top_frame); order_type_frame.pack(side='left')
        ttk.Radiobutton(order_type_frame, text="지정가", variable=order_type_var, value="limit", command=self._update_order_ui_state).pack(side="left")
        ttk.Radiobutton(order_type_frame, text="시장가", variable=order_type_var, value="market", command=self._update_order_ui_state).pack(side="left")
        ttk.Label(top_frame, textvariable=balance_var, foreground='gray').pack(side='right')
        grid_frame = ttk.Frame(parent_frame); grid_frame.pack(fill='x', expand=True); grid_frame.columnconfigure(1, weight=1)
        labels = ["주문가격(KRW)", "주문수량(COIN)", "주문총액(KRW)"]
        vars_entries = [(price_var, ttk.Entry(grid_frame, textvariable=price_var)), (amount_var, ttk.Entry(grid_frame, textvariable=amount_var)), (total_var, ttk.Entry(grid_frame, textvariable=total_var))]
        for i, (label_text, (var, entry)) in enumerate(zip(labels, vars_entries)):
            ttk.Label(grid_frame, text=f"{label_text: <10}").grid(row=i, column=0, sticky='w', padx=5, pady=2)
            entry.grid(row=i, column=1, sticky='ew', padx=5, pady=2)
            if i==1:
                entry_symbol = ttk.Label(grid_frame, text="")
                entry_symbol.grid(row=i, column=2, sticky='w')
                if is_buy: self.buy_amount_symbol_label = entry_symbol
                else: self.sell_amount_symbol_label = entry_symbol
        entries = [e for _, e in vars_entries]
        if is_buy: self.buy_price_entry, self.buy_amount_entry, self.buy_total_entry = entries
        else: self.sell_price_entry, self.sell_amount_entry, self.sell_total_entry = entries
        percentage_frame = ttk.Frame(parent_frame)
        percentage_frame.pack(fill='x', expand=True, pady=5)
        if is_buy:
            for p in [0.1, 0.25, 0.5, 1.0]:
                btn = ttk.Button(percentage_frame, text=f"{p:.0%}", command=lambda pct=p: self._apply_buy_percentage(pct))
                btn.pack(side='left', fill='x', expand=True, padx=2)
        else:
            ttk.Label(percentage_frame, text="매도비율: ").pack(side="left")
            percentages = [f'{i}%' for i in range(5, 101, 5)]
            sell_combo = ttk.Combobox(percentage_frame, textvariable=self.sell_percentage_var, values=percentages, width=10)
            sell_combo.pack(side="left", padx=5)
            sell_combo.bind("<<ComboboxSelected>>", self._on_sell_percentage_select)
        action_text = "매수" if is_buy else "매도"
        style = "Buy.TButton" if is_buy else "Sell.TButton"
        ttk.Style().configure(style, foreground="black", background="#d24f45" if is_buy else "#1e6bde", font=('Helvetica', 10, 'bold'))
        action_button = ttk.Button(parent_frame, text=action_text, style=style, command=lambda s=side: self.place_order(s))
        action_button.pack(fill='x', expand=True, ipady=5, pady=(5,0))

    def process_queue(self):
        try:
            task_name, data = self.data_queue.get_nowait()
            if task_name == "update_portfolio": self.update_portfolio_gui(*data)
            elif task_name == "update_market":
                self.market_data = data; self._refresh_market_tree_gui()
            elif task_name == "update_live_candle": self._update_live_data(data)
            elif task_name == "draw_chart": self._finalize_chart_drawing(*data)
            elif task_name == "draw_older_chart": self._update_chart_after_loading(*data)
        except Empty:
            pass
        finally:
            if self.is_running:
                self.after(100, self.process_queue)

    def fetch_current_price(self):
        display_name = self.selected_ticker_display.get()
        ticker = self.display_name_to_ticker.get(display_name)
        if ticker and ticker != "종목 없음":
            try:
                price = pyupbit.get_current_price(ticker)
                if price is not None: self.data_queue.put(("update_live_candle", price))
            except Exception as e: print(f"❗️ 현재가 조회 오류: {e}")

    def _fetch_portfolio_data_worker(self):
        try:
            balances = upbit.get_balances()
            self.balances_data = {f"KRW-{b['currency']}": b for b in balances if b['currency'] != 'KRW'}
            krw_balance = next((float(b['balance']) for b in balances if b['currency'] == 'KRW'), 0.0)
            krw_balances_data = {f"KRW-{b['currency']}": b for b in balances if b['currency'] != 'KRW' and float(b.get('balance', 0)) > 0}
            display_name = self.selected_ticker_display.get()
            ticker = self.display_name_to_ticker.get(display_name)
            tickers_to_fetch = set(krw_balances_data.keys())
            if ticker: tickers_to_fetch.add(ticker)
            current_prices_dict = {}
            if tickers_to_fetch:
                price_data = pyupbit.get_current_price(list(tickers_to_fetch))
                if price_data: current_prices_dict = price_data if isinstance(price_data, dict) else {list(tickers_to_fetch)[0]: price_data}
            total_investment, total_valuation = 0.0, 0.0
            portfolio_data_list = []
            for t, balance_info in krw_balances_data.items():
                balance, avg_price, cur_price = float(balance_info['balance']), float(balance_info['avg_buy_price']), current_prices_dict.get(t, 0)
                investment, valuation = balance * avg_price, balance * cur_price
                total_investment, total_valuation = total_investment + investment, total_valuation + valuation
                portfolio_data_list.append({'ticker': t, 'balance': balance, 'avg_price': avg_price, 'cur_price': cur_price, 'valuation': valuation, 'pl': valuation - investment})
            coin_balance = float(krw_balances_data.get(ticker, {}).get('balance', 0.0))
            coin_symbol = ticker.split('-')[1] if ticker and '-' in ticker else "COIN"
            total_pl = total_valuation - total_investment
            total_pl_rate = (total_pl / total_investment) * 100 if total_investment > 0 else 0
            result_data = (total_investment, total_valuation, total_pl, total_pl_rate, portfolio_data_list, krw_balance, coin_balance, coin_symbol)
            self.data_queue.put(("update_portfolio", result_data))
        except Exception as e: print(f"❗️ 포트폴리오 업데이트 오류: {e}")

    def _fetch_market_data_worker(self):
        try:
            all_tickers_krw = pyupbit.get_tickers(fiat="KRW")
            url = f"https://api.upbit.com/v1/ticker?markets={','.join(all_tickers_krw)}"
            response = requests.get(url); response.raise_for_status()
            market_data = response.json()
            if market_data: self.data_queue.put(("update_market", market_data))
        except Exception as e: print(f"❗️ KRW 마켓 목록 업데이트 중 오류: {e}")

    def on_ticker_select(self, event=None):
        self.draw_base_chart()
        self._update_order_ui_state()
        display_name = self.selected_ticker_display.get()
        ticker = self.display_name_to_ticker.get(display_name)
        if ticker:
            symbol = ticker.split('-')[1]
            self.buy_amount_symbol_label.config(text=symbol); self.sell_amount_symbol_label.config(text=symbol)

    def draw_base_chart(self, *args, keep_current_view=False):
        display_name = self.selected_ticker_display.get()
        ticker, interval = self.display_name_to_ticker.get(display_name, display_name), self.selected_interval.get()
        if not ticker or ticker == "종목 없음": return
        if ticker != getattr(self, 'current_chart_ticker', None):
            self._keep_view = False
            self.current_chart_ticker = ticker
        else:
            self._keep_view = keep_current_view
        self.master_df = None
        threading.Thread(target=self._fetch_and_draw_chart, args=(ticker, interval, display_name), daemon=True).start()

    def _fetch_and_draw_chart(self, ticker, interval, display_name):
        try:
            df = self.get_technical_indicators(ticker, interval=interval, count=200)
            self.data_queue.put(("draw_chart", (df, interval, display_name)))
        except Exception as e: print(f"❗️ 차트 데이터 로딩 오류: {e}")

    def _update_live_data(self, price):
        if self.master_df is None or self.master_df.empty: return
        self.current_price = price
        last_idx = self.master_df.index[-1]
        self.master_df.loc[last_idx, 'close'] = price
        if price > self.master_df.loc[last_idx, 'high']: self.master_df.loc[last_idx, 'high'] = price
        if price < self.master_df.loc[last_idx, 'low']: self.master_df.loc[last_idx, 'low'] = price
        
        current_time = time.time()
        if current_time - self.last_chart_redraw_time > 3.0:
            cur_xlim, cur_ylim = self.ax.get_xlim(), self.ax.get_ylim()
            self._redraw_chart()
            try:
                if cur_xlim[0] < cur_xlim[1] and cur_ylim[0] < cur_ylim[1]:
                    self.ax.set_xlim(cur_xlim); self.ax.set_ylim(cur_ylim)
            except Exception: pass
            self.canvas.draw()
            self.last_chart_redraw_time = current_time

    def _finalize_chart_drawing(self, df, interval, display_name):
        self.master_df = df
        if self.master_df is None or len(self.master_df) < 2:
            self.ax.clear(); self.ax.text(0.5, 0.5, "차트 데이터가 없습니다.", ha='center', va='center', transform=self.ax.transAxes)
            self.canvas.draw(); self.master_df = None; return
        if self._keep_view:
            cur_xlim, cur_ylim = self.ax.get_xlim(), self.ax.get_ylim()
            self._redraw_chart()
            try:
                if cur_xlim[0] < cur_xlim[1] and cur_ylim[0] < cur_ylim[1]:
                    self.ax.set_xlim(cur_xlim); self.ax.set_ylim(cur_ylim)
            except Exception: self.reset_chart_view()
        else:
            self._redraw_chart()
            self.reset_chart_view()
        self.canvas.draw()
    
    def get_chart_title(self):
        display_name = self.selected_ticker_display.get()
        ticker = self.display_name_to_ticker.get(display_name)
        if not ticker: return "차트"
        self.avg_buy_price = float(self.balances_data.get(ticker, {}).get('avg_buy_price', 0.0))
        profit_rate = ((self.current_price - self.avg_buy_price) / self.avg_buy_price) * 100 if self.avg_buy_price > 0 and self.current_price > 0 else 0
        return f'{display_name} ({self.selected_interval.get()}) Chart (수익률: {profit_rate:+.2f}%)'

    def _redraw_chart(self):
        self.ax.clear()
        if self.master_df is None or self.master_df.empty:
            self.ax.text(0.5, 0.5, "차트 데이터가 없습니다.", ha='center', va='center', transform=self.ax.transAxes)
            self.canvas.draw(); return
        
        self.ax.yaxis.set_label_position("right"); self.ax.yaxis.tick_right()
        ma_data_to_plot, bb_data_to_plot = {}, {}
        for period, var in self.ma_vars.items():
            if var.get() and f'ma{period}' in self.master_df.columns: ma_data_to_plot[period] = self.master_df[f'ma{period}']
        if self.bb_var.get():
            bb_period = 20; middle = self.master_df['close'].rolling(window=bb_period).mean()
            std = self.master_df['close'].rolling(window=bb_period).std()
            bb_data_to_plot = {'upper': middle + (std * 2), 'middle': middle, 'lower': middle - (std * 2)}
        current_interval = self.selected_interval.get()
        dt_format = '%m-%d %H:%M' if current_interval not in ['day', 'week'] else '%Y-%m-%d'
        
        mpf.plot(self.master_df, type='candle', ax=self.ax, style='yahoo', ylabel='Price (KRW)', datetime_format=dt_format, xrotation=20)
        
        all_lows, all_highs = self.master_df['low'], self.master_df['high']
        data_min, data_max = all_lows.min(), all_highs.max()
        padding = (data_max - data_min) * 0.1
        y_bound_min, y_bound_max = max(0, data_min - padding), data_max + padding
        self.data_bounds = {'x': (0, len(self.master_df) - 1), 'y': (y_bound_min, y_bound_max)}
        
        self.plot_moving_averages(ma_data_to_plot)
        self.plot_bollinger_bands(bb_data_to_plot)
        self.plot_price_overlays()
        
        self.ax.grid(True, linestyle='--', alpha=0.6)
        if ma_data_to_plot or bb_data_to_plot: self.ax.legend()
        self.ax.set_title(self.get_chart_title())

    def plot_price_overlays(self):
        blended_transform = plt.matplotlib.transforms.blended_transform_factory(self.ax.transAxes, self.ax.transData)
        if self.current_price > 0:
            self.ax.axhline(y=self.current_price, color='red', linestyle='--', linewidth=0.9)
            self.ax.text(1.01, self.current_price, f' {self.current_price:,.2f} ', transform=blended_transform, color='white', backgroundcolor='red', va='center', ha='left', bbox=dict(facecolor='red', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.2'))
        display_name = self.selected_ticker_display.get()
        ticker = self.display_name_to_ticker.get(display_name)
        if ticker:
            avg_buy_price = float(self.balances_data.get(ticker, {}).get('avg_buy_price', 0.0))
            if avg_buy_price > 0:
                self.ax.axhline(y=avg_buy_price, color='blue', linestyle=':', linewidth=0.9)
                self.ax.text(1.01, avg_buy_price, f' {avg_buy_price:,.2f} ', transform=blended_transform, color='white', backgroundcolor='blue', va='center', ha='left', bbox=dict(facecolor='blue', alpha=0.8, edgecolor='none', boxstyle='round,pad=0.2'))
                
    def _update_chart_after_loading(self, new_df, new_xlim):
        num_added = len(new_df) - (len(self.master_df) if self.master_df is not None else 0)
        self.master_df = new_df
        print(f"✅ 과거 캔들({num_added})을 추가했습니다. 총 {len(new_df)}개")
        self._redraw_chart(); self.ax.set_xlim(new_xlim)
        self.canvas.draw(); self.is_loading_older = False

    def _on_buy_input_change(self, *args):
        if self._is_calculating or self.buy_order_type.get() != 'limit': return
        self._is_calculating = True
        try:
            price, amount = float(self.buy_price_var.get() or 0), float(self.buy_amount_var.get() or 0)
            self.buy_total_var.set(f"{price * amount:.0f}")
        except (ValueError, TclError): pass
        finally: self._is_calculating = False

    def _on_buy_total_change(self, *args):
        if self._is_calculating or self.buy_order_type.get() != 'limit': return
        self._is_calculating = True
        try:
            price, total = float(self.buy_price_var.get() or 0), float(self.buy_total_var.get() or 0)
            if price > 0: self.buy_amount_var.set(f"{total / price:g}")
        except (ValueError, TclError): pass
        finally: self._is_calculating = False

    def _on_sell_input_change(self, *args):
        if self._is_calculating or self.sell_order_type.get() != 'limit': return
        self._is_calculating = True
        try:
            price, amount = float(self.sell_price_var.get() or 0), float(self.sell_amount_var.get() or 0)
            self.sell_total_var.set(f"{price * amount:.0f}")
        except (ValueError, TclError): pass
        finally: self._is_calculating = False

    def _update_order_ui_state(self):
        buy_type = self.buy_order_type.get()
        self.buy_price_entry.config(state='normal' if buy_type == 'limit' else 'disabled')
        self.buy_amount_entry.config(state='normal' if buy_type == 'limit' else 'disabled')
        self.buy_total_entry.config(state='normal' if buy_type == 'market' else 'disabled')
        if buy_type == 'market': self.buy_price_var.set(""), self.buy_amount_var.set("")
        else: self.buy_total_entry.config(state='normal')
        sell_type = self.sell_order_type.get()
        self.sell_price_entry.config(state='normal' if sell_type == 'limit' else 'disabled')
        self.sell_amount_entry.config(state='normal')
        self.sell_total_entry.config(state='disabled')
        if sell_type == 'market': self.sell_price_var.set(""), self.sell_total_var.set("")

    def _apply_buy_percentage(self, percentage):
        buy_type, total_krw = self.buy_order_type.get(), self.krw_balance * percentage
        if buy_type == 'limit':
            try:
                price = float(self.buy_price_var.get())
                if price > 0: self.buy_amount_var.set(f"{total_krw / price * 0.9995:g}")
                else: messagebox.showwarning("가격 입력 필요", "주문 가격을 먼저 입력해주세요.")
            except (ValueError, TclError): messagebox.showwarning("가격 입력 필요", "유효한 주문 가격을 먼저 입력해주세요.")
        else: self.buy_total_var.set(f"{total_krw:.0f}")

    def _on_sell_percentage_select(self, event=None):
        try:
            percentage_str = self.sell_percentage_var.get()
            if not percentage_str: return
            percentage = float(percentage_str.replace('%', '')) / 100
            self.sell_amount_var.set(str(self.coin_balance * percentage))
            self.sell_percentage_var.set('')
        except (ValueError, TclError) as e: print(f"매도 비율 계산 중 오류: {e}")

    def place_order(self, side):
        display_name = self.selected_ticker_display.get()
        ticker = self.display_name_to_ticker.get(display_name, display_name)
        if not ticker: messagebox.showerror("오류", "주문할 종목이 선택되지 않았습니다."); return
        is_buy, order_type = (side == "buy"), self.buy_order_type.get() if side == "buy" else self.sell_order_type.get()
        price, amount, total_krw, order_params, amount_label, amount_unit, amount_display = None, 0.0, 0.0, (), "", "", ""
        try:
            if order_type == 'limit':
                price_str, amount_str = (self.buy_price_var.get(), self.buy_amount_var.get()) if is_buy else (self.sell_price_var.get(), self.sell_amount_var.get())
                if not price_str or not amount_str: raise ValueError("지정가 주문 시 가격과 수량을 모두 입력해야 합니다.")
                price, amount = float(price_str), float(amount_str)
                if price <= 0 or amount <= 0: raise ValueError("가격과 수량은 0보다 커야 합니다.")
                order_params, amount_label, amount_unit, amount_display = (ticker, price, amount), "주문 수량", ticker.split('-')[1], f"{amount:g}"
            else:
                if is_buy:
                    total_krw_str = self.buy_total_var.get()
                    if not total_krw_str: raise ValueError("시장가 매수 시 주문 총액(KRW)을 입력해야 합니다.")
                    total_krw = float(total_krw_str)
                    if total_krw < 5000: raise ValueError("시장가 매수 주문은 5,000원 이상이어야 합니다.")
                    order_params, amount_label, amount_unit, amount_display = (ticker, total_krw), "주문 총액", "KRW", f"{total_krw:,.0f}"
                else:
                    user_amount_str = self.sell_amount_var.get()
                    if not user_amount_str: raise ValueError("시장가 매도 시 주문 수량(COIN)을 입력해야 합니다.")
                    user_amount = float(user_amount_str)
                    if user_amount <= 0: raise ValueError("주문 수량은 0보다 커야 합니다.")
                    sellable_balance, current_price = upbit.get_balance(ticker), pyupbit.get_current_price(ticker)
                    amount_to_sell = min(user_amount, sellable_balance)
                    if current_price and (amount_to_sell * current_price < 5000): raise ValueError(f"주문 금액이 최소 기준(5,000원) 미만입니다.\n(예상 주문액: {amount_to_sell * current_price:,.0f}원)")
                    if amount_to_sell <= 0: raise ValueError("매도 가능한 코인 수량이 없습니다.")
                    order_params, amount_label, amount_unit, amount_display = (ticker, amount_to_sell), "주문 수량", ticker.split('-')[1], f"{amount_to_sell:g}"
        except ValueError as ve: messagebox.showerror("입력 오류", f"{ve}"); return
        except TclError: messagebox.showerror("입력 오류", "유효한 숫자를 입력하세요."); return
        order_side_text = ("매도", "매수")[is_buy]
        order_type_text = ("지정가", "시장가")[order_type == 'market']
        price_text = f"주문 가격: {price:,.0f} KRW\n" if price is not None else ""
        confirm_msg = f"[[ 주문 확인 ]]\n\n종목: {display_name}\n종류: {order_side_text} / {order_type_text}\n{price_text}{amount_label}: {amount_display} {amount_unit}\n\n위 내용으로 주문하시겠습니까?"
        if not messagebox.askyesno("주문 확인", confirm_msg): return
        try:
            result = None
            print(f"▶️ 주문 실행: {side}, {order_type}, params: {order_params}")
            if is_buy: result = upbit.buy_limit_order(*order_params) if order_type == 'limit' else upbit.buy_market_order(*order_params)
            else: result = upbit.sell_limit_order(*order_params) if order_type == 'limit' else upbit.sell_market_order(*order_params)
            messagebox.showinfo("주문 성공", f"주문이 성공적으로 접수되었습니다.\n\n{result}")
            self.buy_price_var.set(""), self.buy_amount_var.set(""), self.buy_total_var.set("")
            self.sell_price_var.set(""), self.sell_amount_var.set(""), self.sell_total_var.set("")
            print("ℹ️ 주문 체결 대기... 2초 후 잔고를 갱신합니다.")
            self.after(2000, self._fetch_portfolio_data_worker)
        except Exception as e:
            messagebox.showerror("주문 실패", f"주문 중 오류가 발생했습니다.\n\n오류 유형: {type(e).__name__}\n메시지: {e}")
            print(f"❗️ 주문 실패: {e}")

    def on_tree_double_click(self, event):
        item_id = self.portfolio_tree.focus()
        if not item_id: return
        display_name = self.portfolio_tree.item(item_id, "values")[0]
        if not display_name: return
        if self.selected_ticker_display.get() == display_name: return
        self._ignore_market_select_event = True
        self.selected_ticker_display.set(display_name)
        found = False
        for iid in self.market_tree.get_children():
            vals = self.market_tree.item(iid, "values")
            if vals and vals[0] == display_name:
                self.market_tree.selection_set(iid); self.market_tree.focus(iid); found = True; break
        if not found: self.market_tree.selection_remove(self.market_tree.selection())
        self._ignore_market_select_event = False
        self.on_ticker_select()
        print(f"📋 포트폴리오 더블클릭: {display_name} 차트를 표시합니다.")

    def on_market_list_select(self, event):
        if getattr(self, '_ignore_market_select_event', False): return
        selection = self.market_tree.selection()
        if not selection: return
        display_name = self.market_tree.item(selection[0])['values'][0]
        if self.selected_ticker_display.get() == display_name: return
        self.portfolio_tree.selection_remove(self.portfolio_tree.selection())
        self.portfolio_tree.focus('')
        self.selected_ticker_display.set(display_name)
        self.on_ticker_select()
        print(f"💹 거래대금 목록 선택: {display_name} 차트를 표시합니다.")

    def reset_chart_view(self):
        if self.master_df is None or len(self.master_df) < 1: return
        view_start, view_end = max(0, len(self.master_df) - 200), len(self.master_df) + 2
        self.ax.set_xlim(view_start, view_end - 1)
        try:
            visible_df = self.master_df.iloc[int(view_start):int(view_end-2)]
            min_low, max_high = visible_df['low'].min(), visible_df['high'].max()
            padding = (max_high - min_low) * 0.05
            self.ax.set_ylim(min_low - padding, max_high + padding)
        except Exception as e:
            print(f"❗️ 뷰 리셋 중 Y축 범위 설정 오류: {e}")
            self.ax.autoscale(enable=True, axis='y', tight=False)
        self.canvas.draw_idle()
        print("🔄️ 차트 뷰를 초기 상태로 리셋했습니다.")

    def on_scroll(self, event):
        if event.inaxes != self.ax: return
        zoom_factor = 1/1.1 if event.step > 0 else 1.1
        cur_xlim, cur_ylim = self.ax.get_xlim(), self.ax.get_ylim()
        x_data, y_data = event.xdata, event.ydata
        if x_data is None or y_data is None: return
        new_xlim = [(cur_xlim[0] - x_data) * zoom_factor + x_data, (cur_xlim[1] - x_data) * zoom_factor + x_data]
        new_ylim = [(cur_ylim[0] - y_data) * zoom_factor + y_data, (cur_ylim[1] - y_data) * zoom_factor + y_data]
        x_bounds, y_bounds = self.data_bounds.get('x'), self.data_bounds.get('y')
        if x_bounds:
            if new_xlim[0] < x_bounds[0]: new_xlim[0] = x_bounds[0]
            if new_xlim[1] > x_bounds[1] + 2: new_xlim[1] = x_bounds[1] + 2
        if y_bounds:
            if new_ylim[0] < y_bounds[0]: new_ylim[0] = y_bounds[0]
            if new_ylim[1] > y_bounds[1]: new_ylim[1] = y_bounds[1]
        self.ax.set_xlim(new_xlim); self.ax.set_ylim(new_ylim); self.canvas.draw_idle()

    def on_press(self, event):
        if event.inaxes != self.ax: return
        if event.dblclick: self.reset_chart_view(); return
        self.is_panning = True; self.pan_start_pos = (event.xdata, event.ydata)

    def on_motion(self, event):
        if not self.is_panning or event.inaxes != self.ax or self.pan_start_pos is None: return
        try:
            dx, dy = event.xdata - self.pan_start_pos[0], event.ydata - self.pan_start_pos[1]
            cur_xlim, cur_ylim = self.ax.get_xlim(), self.ax.get_ylim()
            new_xlim = [cur_xlim[0] - dx, cur_xlim[1] - dx]
            if x_bounds := self.data_bounds.get('x'):
                width = new_xlim[1] - new_xlim[0]
                if new_xlim[0] < x_bounds[0]: new_xlim = [x_bounds[0], x_bounds[0] + width]
                if new_xlim[1] > x_bounds[1] + 2: new_xlim = [x_bounds[1] + 2 - width, x_bounds[1] + 2]
            self.ax.set_xlim(new_xlim); self.ax.set_ylim([cur_ylim[0] - dy, cur_ylim[1] - dy]); self.canvas.draw_idle()
        except TypeError: pass

    def on_release(self, event):
        if not self.is_panning: return
        self.is_panning = False; self.pan_start_pos = None
        if self.ax.get_xlim()[0] < 1 and not self.is_loading_older:
            print("⏳ 차트 왼쪽 끝에 도달, 과거 데이터를 로딩합니다..."); self.load_older_data()

    def load_older_data(self):
        if self.master_df is None or self.master_df.empty: return
        self.is_loading_older = True
        display_name = self.selected_ticker_display.get()
        ticker, interval, to_date, current_xlim = self.display_name_to_ticker.get(display_name), self.selected_interval.get(), self.master_df.index[0], self.ax.get_xlim()
        threading.Thread(target=self._fetch_older_data_worker, args=(ticker, interval, to_date, current_xlim), daemon=True).start()

    def _fetch_older_data_worker(self, ticker, interval, to_date, current_xlim):
        try:
            to_date_str = (pd.to_datetime(to_date) - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
            older_df_raw = pyupbit.get_ohlcv(ticker, interval=interval, count=200, to=to_date_str)
            if older_df_raw is None or len(older_df_raw) < 2:
                print("ℹ️ 더 이상 로드할 과거 데이터가 없습니다."); self.is_loading_older = False; return
            current_ohlcv = self.master_df[['open', 'high', 'low', 'close', 'volume']]
            combined_df_raw = pd.concat([older_df_raw, current_ohlcv])
            combined_df_raw = combined_df_raw[~combined_df_raw.index.duplicated(keep='last')].sort_index()
            df_with_indicators = self.get_technical_indicators_from_raw(combined_df_raw, min_length=2)
            
            if df_with_indicators is not None and not df_with_indicators.empty:
                if len(df_with_indicators) > self.MAX_CANDLES:
                    df_with_indicators = df_with_indicators.iloc[-self.MAX_CANDLES:]
                    print(f"ℹ️ 메모리 관리를 위해 캔들 데이터를 {self.MAX_CANDLES}개로 제한합니다.")
                
                num_candles_added = len(df_with_indicators) - len(self.master_df)
                if num_candles_added > 0:
                    new_xlim = (current_xlim[0] + num_candles_added, current_xlim[1] + num_candles_added)
                    self.data_queue.put(("draw_older_chart", (df_with_indicators, new_xlim))); return
            print("ℹ️ 더 이상 로드할 과거 데이터가 없습니다.")
        except Exception as e: print(f"❗️ 과거 데이터 로딩 중 오류 발생: {e}")
        self.is_loading_older = False

    def plot_moving_averages(self, ma_data):
        if ma_data:
            for period, ma_series in ma_data.items():
                self.ax.plot(range(len(ma_series)), ma_series.values, label=f"MA{period}")

    def plot_bollinger_bands(self, bb_data):
        if bb_data:
            x_axis = range(len(self.master_df))
            self.ax.plot(x_axis, bb_data['middle'].values, color='orange', linestyle='--', linewidth=1, label='BB Center')
            self.ax.plot(x_axis, bb_data['upper'].values, color='gray', linestyle='--', linewidth=0.7)
            self.ax.plot(x_axis, bb_data['lower'].values, color='gray', linestyle='--', linewidth=0.7)
            self.ax.fill_between(x_axis, bb_data['lower'].values, bb_data['upper'].values, color='gray', alpha=0.1)

    def update_portfolio_gui(self, total_investment, total_valuation, total_pl, total_pl_rate, portfolio_data, krw_balance, coin_balance, coin_symbol):
        self.krw_balance, self.coin_balance = krw_balance, coin_balance
        self.krw_balance_summary_var.set(f"보유 KRW: {krw_balance:,.0f} 원")
        self.total_investment_var.set(f"총 투자금액: {total_investment:,.0f} 원")
        self.total_valuation_var.set(f"총 평가금액: {total_valuation:,.0f} 원")
        self.total_pl_var.set(f"총 평가손익: {total_pl:,.0f} 원 ({total_pl_rate:+.2f}%)")
        
        # [수정 1] 하이라이트 유지를 위해 현재 선택된 항목 저장
        selected_id = self.portfolio_tree.focus()
        selected_display_name = None
        if selected_id:
            try:
                selected_display_name = self.portfolio_tree.item(selected_id, "values")[0]
            except IndexError:
                selected_display_name = None

        self.portfolio_tree.delete(*self.portfolio_tree.get_children())
        new_selection_id = None
        for item in portfolio_data:
            display_name = self.ticker_to_display_name.get(item['ticker'], item['ticker'])
            balance, avg_price, cur_price, valuation, pl = item['balance'], item['avg_price'], item['cur_price'], item['valuation'], item['pl']
            pl_rate = (pl / (avg_price * balance) * 100) if avg_price > 0 and balance > 0 else 0
            tag = 'plus' if pl > 0 else 'minus' if pl < 0 else ''
            
            # [수정 1] Treeview에 항목을 추가하고, 이전에 선택된 항목이라면 새 ID를 저장
            item_id = self.portfolio_tree.insert('', 'end', values=(display_name, f"{balance:.8f}".rstrip('0').rstrip('.'), f"{avg_price:,.2f}", f"{cur_price:,.2f}", f"{valuation:,.0f}", f"{pl:,.0f}", f"{pl_rate:+.2f}%"), tags=(tag,))
            if display_name == selected_display_name:
                new_selection_id = item_id

        # [수정 1] 갱신 후, 이전에 선택된 항목이 여전히 존재하면 다시 선택(하이라이트)
        if new_selection_id:
            self.portfolio_tree.focus(new_selection_id)
            self.portfolio_tree.selection_set(new_selection_id)

        self.pie_ax.clear()
        if portfolio_data and total_valuation > 0:
            chart_data = [{'label': self.ticker_to_display_name.get(item['ticker'], item['ticker']), 'value': item['valuation']} for item in portfolio_data]
            main_items, other_items_value = [], 0.0
            sorted_chart_data = sorted(chart_data, key=lambda x: x['value'], reverse=True)
            for item in sorted_chart_data:
                percentage = (item['value'] / total_valuation) * 100
                if len(main_items) < 7 and percentage >= 2.0: main_items.append(item)
                else: other_items_value += item['value']
            if other_items_value > 0: main_items.append({'label': '기타', 'value': other_items_value})
            labels, percentages = [item['label'].split('(')[0] for item in main_items][::-1], [(item['value'] / total_valuation) * 100 for item in main_items][::-1]
            num_items = len(labels)
            try: colors = plt.colormaps.get_cmap('viridis_r')(np.linspace(0, 1, num_items))
            except AttributeError: colors = plt.cm.get_cmap('viridis_r', num_items)(range(num_items))
            bars = self.pie_ax.barh(labels, percentages, color=colors, height=0.6)
            self.pie_ax.set_xlabel('비중 (%)', fontsize=9); self.pie_ax.tick_params(axis='y', labelsize=9)
            self.pie_ax.set_title('포트폴리오 구성', fontsize=11, fontweight='bold')
            self.pie_ax.spines['top'].set_visible(False); self.pie_ax.spines['right'].set_visible(False); self.pie_ax.spines['left'].set_visible(False)
            for bar in bars:
                width = bar.get_width()
                self.pie_ax.text(width + 0.5, bar.get_y() + bar.get_height()/2., f'{width:.1f}%', ha='left', va='center', fontsize=8.5)
            self.pie_ax.set_xlim(0, max(percentages) * 1.15 if percentages else 100)
        else:
            self.pie_ax.text(0.5, 0.5, "보유 코인이 없습니다", ha='center', va='center')
            self.pie_ax.set_xticks([]); self.pie_ax.set_yticks([])
        self.pie_fig.tight_layout(); self.pie_canvas.draw()
        self.buy_krw_balance_var.set(f"주문가능: {krw_balance:,.0f} KRW"); self.sell_coin_balance_var.set(f"주문가능: {coin_balance:g} {coin_symbol}")

    def _refresh_market_tree_gui(self):
        if not self.market_data: return
        sort_key_map = {'display_name': 'market', 'price': 'trade_price', 'change_rate': 'signed_change_rate', 'volume': 'acc_trade_price_24h'}
        key_to_sort = sort_key_map.get(self.sort_column, 'acc_trade_price_24h')
        sorted_data = sorted(self.market_data, key=lambda x: x.get(key_to_sort, 0), reverse=not self.sort_ascending)
        try:
            selected_id = self.market_tree.focus()
            selected_display_name = self.market_tree.item(selected_id, 'values')[0] if selected_id else None
            self.market_tree.delete(*self.market_tree.get_children()); new_selection_id = None
            for item in sorted_data:
                ticker_name, display_name = item['market'], self.ticker_to_display_name.get(item['market'], item['market'])
                price, change_rate, volume = item['trade_price'], item['signed_change_rate'] * 100, item['acc_trade_price_24h']
                tag = 'red' if change_rate > 0 else 'blue' if change_rate < 0 else 'black'
                price_str, change_rate_str, volume_str = f"{price:,.0f}" if price >= 100 else f"{price:g}", f"{change_rate:+.2f}%", self.format_trade_volume(volume)
                item_id = self.market_tree.insert('', 'end', values=(display_name, price_str, change_rate_str, volume_str), tags=(tag,))
                if display_name == selected_display_name: new_selection_id = item_id
            if new_selection_id: self.market_tree.focus(new_selection_id); self.market_tree.selection_set(new_selection_id)
        except Exception: pass

    def sort_market_list(self, col):
        if self.sort_column == col: self.sort_ascending = not self.sort_ascending
        else: self.sort_column, self.sort_ascending = col, False
        self._refresh_market_tree_gui()

    def format_trade_volume(self, volume):
        if volume > 1_000_000_000_000: return f"{volume/1_000_000_000_000:.1f}조"
        if volume > 1_000_000_000: return f"{volume/1_000_000_000:.0f}십억"
        if volume > 1_000_000: return f"{volume/1_000_000:.0f}백만"
        return f"{volume:,.0f}"

    def load_my_tickers(self):
        threading.Thread(target=self._load_my_tickers_worker, daemon=True).start()

    def _load_my_tickers_worker(self):
        balances = upbit.get_balances()
        my_tickers = [f"KRW-{b['currency']}" for b in balances if b['currency'] != 'KRW' and float(b.get('balance', 0)) > 0]
        all_display_names = sorted(list(self.display_name_to_ticker.keys()))
        self.after(0, lambda: self.ticker_combobox.config(values=all_display_names))
        if my_tickers:
            display_name = self.ticker_to_display_name.get(my_tickers[0], my_tickers[0])
            self.selected_ticker_display.set(display_name)
        elif all_display_names: self.selected_ticker_display.set(all_display_names[0])
        else: self.selected_ticker_display.set("종목 없음")
        self.after(0, self.on_ticker_select)

    def on_closing(self):
        self.is_running = False
        time.sleep(1.1)
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.destroy()

# [수정 2] 자동매매 설정창 클래스 전체 수정
class AutoTradeSettingsWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.master_app = master
        self.title("자동매매 설정")
        self.geometry("400x380")
        self.resizable(False, False)
        self.vars = {
            'total_investment_limit': tk.StringVar()
        }
        self.setup_widgets()
        self.load_settings()

    def setup_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 저장/닫기 버튼 프레임
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(button_frame, text="저장", command=self.save_and_close).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="닫기", command=self.destroy).pack(side=tk.RIGHT)
        
        # 총 투자 한도 설정 프레임
        options_frame = ttk.LabelFrame(main_frame, text="[2] 투자 설정", padding=10)
        options_frame.pack(side="bottom", fill=tk.X, pady=5)
        ttk.Label(options_frame, text="총 투자 한도 (원):").pack(side=tk.LEFT, padx=5)
        self.amount_entry = ttk.Entry(options_frame, textvariable=self.vars['total_investment_limit'], width=15)
        self.amount_entry.pack(side=tk.LEFT)
        # [수정] foreground 옵션을 pack()이 아닌 Label 생성 시에 전달
        ttk.Label(options_frame, text="(설정 금액을 5회 분할 매수)", foreground="gray").pack(side=tk.LEFT, padx=5)
        
        # 종목 선택 프레임
        tickers_frame = ttk.LabelFrame(main_frame, text="[1] 자동매매 대상 종목 (거래대금 상위 10개, 단일 선택)", padding=10)
        tickers_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        list_frame = ttk.Frame(tickers_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.ticker_listbox = tk.Listbox(list_frame, selectmode='browse', exportselection=False)
        self.ticker_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.ticker_listbox.yview)
        self.ticker_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        refresh_button = ttk.Button(tickers_frame, text="목록 새로고침", command=self.populate_top_tickers)
        refresh_button.pack(pady=(5,0), fill='x')

    def populate_top_tickers(self):
        # 목록 새로고침을 스레드로 실행하여 GUI 멈춤 방지
        threading.Thread(target=self._populate_worker, daemon=True).start()

    # [수정] 빠져있던 _populate_worker 메소드 추가
    def _populate_worker(self):
        """백그라운드에서 마켓 데이터를 직접 조회하고 리스트박스를 채우는 작업자"""
        try:
            # 메인 앱 데이터에 의존하지 않고 직접 API 호출
            all_tickers_krw = pyupbit.get_tickers(fiat="KRW")
            url = f"https://api.upbit.com/v1/ticker?markets={','.join(all_tickers_krw)}"
            response = requests.get(url, timeout=5) # 타임아웃 추가
            response.raise_for_status()
            market_data = response.json()
            
            if not market_data:
                # 메인 스레드에서 UI 업데이트
                self.after(0, lambda: messagebox.showwarning("데이터 없음", "업비트에서 마켓 데이터를 가져오지 못했습니다.", parent=self))
                return

            top_10 = sorted(market_data, key=lambda x: x.get('acc_trade_price_24h', 0), reverse=True)[:10]
            
            # 리스트박스 업데이트는 메인 스레드에서 안전하게 처리
            def update_listbox():
                self.ticker_listbox.delete(0, END)
                for item in top_10:
                    display_name = self.master_app.ticker_to_display_name.get(item['market'], item['market'])
                    self.ticker_listbox.insert(END, display_name)
                self.restore_selection()
                print("✅ 거래대금 상위 10개 종목을 리스트에 업데이트했습니다.")
            
            self.after(0, update_listbox)

        except requests.exceptions.RequestException as e:
            # 네트워크 관련 에러 처리
            self.after(0, lambda: messagebox.showerror("네트워크 오류", f"종목 목록을 불러오는 중 네트워크 오류가 발생했습니다:\n{e}", parent=self))
        except Exception as e:
            # 그 외 모든 에러 처리
            self.after(0, lambda: messagebox.showerror("오류", f"종목 목록을 불러오는 중 오류가 발생했습니다:\n{e}", parent=self))

    def load_settings(self):
        s = self.master_app.auto_trade_settings
        self.vars['total_investment_limit'].set(str(s.get('total_investment_limit', 100000)))
        # 창이 열릴 때 바로 목록을 채우도록 호출
        self.populate_top_tickers()

    def restore_selection(self):
        s = self.master_app.auto_trade_settings
        enabled_tickers = s.get('enabled_tickers', [])
        if not enabled_tickers: return
        selected_ticker = enabled_tickers[0] 
        for i in range(self.ticker_listbox.size()):
            display_name = self.ticker_listbox.get(i)
            if self.master_app.display_name_to_ticker.get(display_name) == selected_ticker:
                self.ticker_listbox.selection_set(i)
                self.ticker_listbox.activate(i)
                break

    def save_and_close(self):
        try:
            new_settings = {}
            selected_ticker_for_chart = None
            
            selected_indices = self.ticker_listbox.curselection()
            enabled_tickers = []
            if selected_indices:
                display_name = self.ticker_listbox.get(selected_indices[0])
                ticker = self.master_app.display_name_to_ticker.get(display_name)
                if ticker:
                    enabled_tickers.append(ticker)
                    selected_ticker_for_chart = ticker
            new_settings['enabled_tickers'] = enabled_tickers
            
            amount = int(self.vars['total_investment_limit'].get())
            if amount < 25000: # 5000원 * 5회
                messagebox.showwarning("금액 확인", "최소 투자 한도는 25,000원입니다 (최소주문 5,000원 * 5회 분할).", parent=self)
                return
            new_settings['total_investment_limit'] = amount
            
            self.master_app.auto_trade_settings = new_settings
            self.master_app.save_auto_trade_settings()
            
            if selected_ticker_for_chart:
                self.master_app.select_ticker_from_settings(selected_ticker_for_chart)
                
            messagebox.showinfo("저장 완료", "자동매매 설정이 저장되었습니다.", parent=self)
            self.destroy()
        except ValueError:
            messagebox.showerror("입력 오류", "총 투자 한도는 숫자로 입력해야 합니다.", parent=self)
        except Exception as e:
            messagebox.showerror("오류", f"설정 저장 중 오류가 발생했습니다: {e}", parent=self)


if __name__ == "__main__":
    app = UpbitChartApp()
    app.start_worker_threads()
    app.mainloop()