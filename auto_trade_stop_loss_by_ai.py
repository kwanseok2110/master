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
            self.auto_trade_settings = {
                'enabled_tickers': [], 
                'total_investment_limit': 100000,
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
        self.fig = plt.figure(figsize=(10, 6))
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
        original_display_name = self.ticker_to_display_name.get(selected_ticker, selected_ticker)
        self.selected_ticker_display.set(original_display_name)
        self._ignore_market_select_event = True
        found = False
        for iid in self.market_tree.get_children():
            tree_value = self.market_tree.item(iid, "values")[0]
            if tree_value.endswith(original_display_name): 
                self.market_tree.selection_set(iid); self.market_tree.focus(iid)
                self.market_tree.see(iid); found = True; break
        if not found: self.market_tree.selection_remove(self.market_tree.selection())
        self._ignore_market_select_event = False
        self.on_ticker_select()
        print(f"⚙️ 자동매매 설정 저장: {original_display_name} 차트를 표시합니다.")

    def get_market_state(self, df, window=20):
        if df is None or len(df) < 60: return '횡보장'
        ma5 = df['ma5'].iloc[-1]
        ma20 = df['ma20'].iloc[-1]
        ma60 = df['ma60'].iloc[-1]
        ma20_slope = (ma20 - df['ma20'].iloc[-window]) / window
        if ma5 > ma20 > ma60 and ma20_slope > 0: return '상승장'
        if ma5 < ma20 < ma60 and ma20_slope < 0: return '하락장'
        return '횡보장'

    def _check_obv_divergence(self, df, period=60): # [수정] period를 30에서 60으로 변경
        if df is None or len(df) < period:
            return None, None
        
        price_high = df['high'].iloc[-period:]
        obv_high = df['obv'].iloc[-period:]
        if price_high.iloc[-1] >= price_high.max() * 0.98 and obv_high.iloc[-1] < obv_high.max() * 0.9:
             return "Bearish", "OBV 약세 다이버전스(매도) 의심"

        price_low = df['low'].iloc[-period:]
        obv_low = df['obv'].iloc[-period:]
        if price_low.iloc[-1] <= price_low.min() * 1.02 and obv_low.iloc[-1] > obv_low.min() * 1.1:
            return "Bullish", "OBV 강세 다이버전스(매집) 의심"
            
        return None, None

    def auto_trade_worker(self):
        self.log_auto_trade("🤖 다중 종목 자동매매 로직 시작...")
        trade_states = {}
        SIDEWAYS_MAX_BUY_COUNT = 3
        TREND_MAX_BUY_COUNT = 5
        MIN_HOLD_CANDLES = 3 # 최소 3개 캔들(3분)은 보유하는 규칙

        while self.is_running and self.is_auto_trading:
            try:
                enabled_tickers = self.auto_trade_settings.get('enabled_tickers', [])
                if not enabled_tickers:
                    time.sleep(30)
                    continue

                total_investment_limit = self.auto_trade_settings.get('total_investment_limit', 5000)
                trend_buy_amount_per_trade = total_investment_limit / TREND_MAX_BUY_COUNT
                sideways_buy_amount_per_trade = total_investment_limit / TREND_MAX_BUY_COUNT

                for ticker in enabled_tickers:
                    if not self.is_running or not self.is_auto_trading: break

                    if ticker not in trade_states:
                        trade_states[ticker] = {'has_coin': False, 'buy_price': 0, 'buy_amount': 0, 'buy_count': 0, 
                                                'last_logged_profit_rate': 0, 'last_logged_market_state': '', 'strategy': None,
                                                'buy_time': None, 'buy_candle_count': 0}

                    df = self.get_technical_indicators(ticker, interval='minute1', count=200)
                    if df is None: time.sleep(1); continue

                    current_price = pyupbit.get_current_price(ticker)
                    if current_price is None: time.sleep(1); continue
                    
                    market_state = self.get_market_state(df)

                    balance = upbit.get_balance(ticker)
                    state = trade_states[ticker]
                    state['has_coin'] = balance > 0
                    
                    if state['has_coin']:
                        state['buy_price'] = float(upbit.get_avg_buy_price(ticker))
                        state['buy_amount'] = balance
                        
                        if state.get('strategy') is None:
                            self.log_auto_trade(f"ℹ️ [{ticker}] 기존 보유 포지션 발견. 현재 시장 상태 분석...")
                            
                            state['buy_time'] = datetime.now() 
                            state['buy_candle_count'] = 0

                            if market_state == '횡보장':
                                state['strategy'] = 'sideways_1p'
                                if state['buy_count'] == 0: state['buy_count'] = 1
                                self.log_auto_trade(f"➡️ 현재 '횡보장'이므로 [횡보장 단타] 전략으로 관리를 시작합니다.")
                            else: 
                                state['strategy'] = 'trend_follow'
                                if state['buy_count'] == 0: state['buy_count'] = 1
                                self.log_auto_trade(f"➡️ 현재 '{market_state}'이므로 [추세추종] 전략으로 관리를 시작합니다.")
                        else:
                             if state['buy_time']:
                                state['buy_candle_count'] = (datetime.now() - state['buy_time']).total_seconds() / 60

                    else:
                        state['buy_count'] = 0
                        state['strategy'] = None
                        state['buy_time'] = None
                        state['buy_candle_count'] = 0

                    last_rsi = df['rsi'].iloc[-1]
                    last_ma5 = df['ma5'].iloc[-1]
                    last_ma20 = df['ma20'].iloc[-1]

                    # --- 보유 코인 처리 로직 (매도 및 물타기) ---
                    if state['has_coin']:
                        profit_rate = (current_price - state['buy_price']) / state['buy_price'] * 100

                        def log_and_sell(reason):
                            sell_type = "익절" if profit_rate >= 0 else "손절"
                            self.log_auto_trade(f"💰 SELL [{ticker}][{sell_type}] | 사유: {reason}, 수익률: {profit_rate:+.2f}%")
                            upbit.sell_market_order(ticker, state['buy_amount'])
                            time.sleep(5)
                        
                        if state['buy_candle_count'] < MIN_HOLD_CANDLES:
                            time.sleep(1) 
                            continue

                        # 횡보장 전략의 매도 및 물타기 로직
                        if state.get('strategy') == 'sideways_1p':
                            sell_reason = None
                            if profit_rate >= 1.0:
                                sell_reason = "횡보장 1% 익절"
                            elif state['buy_count'] >= SIDEWAYS_MAX_BUY_COUNT and profit_rate <= -5.0:
                                sell_reason = f"횡보장 최종 손절 (-5%)"
                            elif market_state != '횡보장':
                                sell_reason = f"시장상황 변경({market_state})으로 포지션 정리"

                            if sell_reason:
                                log_and_sell(sell_reason)
                                continue

                            can_buy_more = state['buy_count'] < SIDEWAYS_MAX_BUY_COUNT
                            is_loss_for_add_buy = profit_rate <= -3.0
                            is_still_sideways = market_state == '횡보장'
                            is_oversold = last_rsi < 30

                            if can_buy_more and is_loss_for_add_buy and is_still_sideways and is_oversold:
                                log_icon = "💧"
                                self.log_auto_trade(f"{log_icon} BUY [{ticker}][횡보장 물타기 {state['buy_count'] + 1}/{SIDEWAYS_MAX_BUY_COUNT}] | 수익률: {profit_rate:+.2f}%, RSI: {last_rsi:.2f}")
                                try:
                                    result = upbit.buy_market_order(ticker, sideways_buy_amount_per_trade)
                                    if result and 'uuid' in result:
                                        state['buy_count'] += 1
                                        self.log_auto_trade(f"✅ [물타기] 성공 (총 {state['buy_count']}회)")
                                        time.sleep(5)
                                        continue
                                except Exception as buy_error:
                                    self.log_auto_trade(f"⚠️ [물타기] 주문 실패: {buy_error}")

                        # 추세추종 전략의 매도 및 추가매수 로직
                        elif state.get('strategy') == 'trend_follow':
                            if abs(profit_rate - state['last_logged_profit_rate']) >= 0.1 or market_state != state['last_logged_market_state']:
                                self.log_auto_trade(f"🔎 [{ticker}] 상태 변경 | 평단가: {state['buy_price']:,.2f} | 수익률: {profit_rate:+.2f}% | 시장: {market_state}")
                                state['last_logged_profit_rate'] = profit_rate
                                state['last_logged_market_state'] = market_state
                            
                            sell_signal, reason = False, ""
                            
                            # 상승장에서는 OBV 다이버전스 매도 신호를 사용하지 않음 (주석 처리)
                            # obv_div_type, obv_div_reason = self._check_obv_divergence(df)
                            # if obv_div_type == "Bearish" and last_rsi > 68: 
                            #     sell_signal, reason = True, obv_div_reason
                            
                            if profit_rate <= -5.0:
                                self.log_auto_trade(f"🚨 SELL [{ticker}][손절] | 사유: 강제 손절 라인(-5%) 도달, 수익률: {profit_rate:.2f}%")
                                upbit.sell_market_order(ticker, state['buy_amount'])
                                time.sleep(5); continue
                            
                            elif market_state == '상승장' and last_ma5 < last_ma20 and df['ma5'].iloc[-2] >= df['ma20'].iloc[-2]:
                                sell_signal, reason = True, "상승장 데드크로스 (추세 종료)"
                            
                            elif market_state == '하락장' and profit_rate >= 3.0:
                                sell_signal, reason = True, "하락장 단기수익(+3%)"
                            
                            if sell_signal:
                                log_and_sell(reason)
                                continue
                            
                            can_buy_more = state['buy_count'] < TREND_MAX_BUY_COUNT
                            if can_buy_more:
                                is_loss_for_add_buy = profit_rate <= -8.0 and last_rsi < 30 and market_state in ['횡보장', '상승장']
                                is_profit_for_add_buy = profit_rate > 5.0 and market_state == '상승장'
                                
                                buy_reason = None
                                if is_loss_for_add_buy: buy_reason = "물타기"
                                elif is_profit_for_add_buy:
                                    is_dip = abs(current_price - last_ma20) / last_ma20 < 0.015
                                    is_not_overbought = last_rsi < 70
                                    if is_dip and is_not_overbought: buy_reason = "불타기"
                                if buy_reason:
                                    log_icon = "💧" if buy_reason == "물타기" else "🔥"
                                    self.log_auto_trade(f"{log_icon} BUY [{ticker}][{buy_reason} 시도 {state['buy_count'] + 1}/{TREND_MAX_BUY_COUNT}] | 수익률: {profit_rate:+.2f}%, RSI: {last_rsi:.2f}")
                                    try:
                                        result = upbit.buy_market_order(ticker, trend_buy_amount_per_trade)
                                        if result and 'uuid' in result:
                                            state['buy_count'] += 1; self.log_auto_trade(f"✅ [{buy_reason}] 성공 (총 {state['buy_count']}회)"); time.sleep(5); continue
                                    except Exception as buy_error: pass

                    # --- 신규 매수 로직 ---
                    else: # 코인 미보유
                        if market_state != state['last_logged_market_state']:
                            self.log_auto_trade(f"⏳ [{ticker}] 신규매수 기회탐색 | 시장: {market_state} | RSI: {last_rsi:.2f}")
                            state['last_logged_market_state'] = market_state
                        
                        def buy_coin(strategy, amount, reason):
                            self.log_auto_trade(f"📈 BUY [{ticker}][{reason}]")
                            try:
                                result = upbit.buy_market_order(ticker, amount)
                                if result and 'uuid' in result:
                                    state['strategy'] = strategy
                                    state['buy_count'] = 1
                                    state['buy_time'] = datetime.now()
                                    state['buy_candle_count'] = 0
                                    time.sleep(5)
                                    return True
                            except Exception as e:
                                self.log_auto_trade(f"⚠️ [{reason}] 주문 실패: {e}")
                            return False

                        if market_state == '횡보장' and 'bb_lower' in df.columns and current_price <= df['bb_lower'].iloc[-1] and last_rsi < 40 and state['buy_count'] == 0:
                            if buy_coin('sideways_1p', sideways_buy_amount_per_trade, "횡보장 1차 매수 | 사유: BB하단 터치 및 RSI 과매도"):
                                continue
                        
                        else:
                            buy_signal, reason = False, ""
                            obv_div_type, obv_div_reason = self._check_obv_divergence(df)
                            if obv_div_type == "Bullish" and last_rsi < 40: 
                                buy_signal, reason = True, obv_div_reason
                            elif state['buy_count'] < TREND_MAX_BUY_COUNT:
                                if market_state == '상승장':
                                    is_golden_cross = last_ma5 > last_ma20 and df['ma5'].iloc[-2] <= df['ma20'].iloc[-2]
                                    is_dip_buy = abs(current_price - last_ma20) / last_ma20 < 0.015
                                    if (is_golden_cross or is_dip_buy) and last_rsi < 70:
                                        buy_signal, reason = True, "상승장 조정 매수 또는 골든크로스"
                                elif 'bb_lower' in df.columns and market_state == '횡보장' and current_price <= df['bb_lower'].iloc[-1] and last_rsi < 35:
                                    buy_signal, reason = True, "횡보장 BB하단 및 RSI 과매도"
                            
                            if buy_signal:
                                if buy_coin('trend_follow', trend_buy_amount_per_trade, f"신규매수 1/{TREND_MAX_BUY_COUNT} | 사유: {reason}"):
                                    continue
                    time.sleep(2)
                time.sleep(15)

            except Exception as e:
                self.log_auto_trade(f"‼️ 자동매매 루프 오류: {e}")
                self.log_auto_trade(traceback.format_exc())
                time.sleep(60)
        self.log_auto_trade("🤖 다중 종목 자동매매 로직 종료.")


    def get_technical_indicators(self, ticker, interval='day', count=200):
        try:
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
            if df is None: return None
            return self.get_technical_indicators_from_raw(df)
        except Exception as e:
            print(f"❗️ {ticker} 지표 계산 오류: {e}")
            return None

    def get_technical_indicators_from_raw(self, df, min_length=20):
        if df is None or len(df) < min_length: return None
        df = df.copy() 

        for p in [5, 20, 60, 120]: df[f'ma{p}'] = df['close'].rolling(window=p, min_periods=1).mean()
        
        delta = df['close'].diff(1); gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']; df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
        df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
        
        obv = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        df['obv'] = obv
        df['obv_ema'] = df['obv'].ewm(com=20).mean()
        
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        money_flow = typical_price * df['volume']
        
        positive_flow_values = [money_flow.iloc[i] if typical_price.iloc[i] > typical_price.iloc[i-1] else 0 for i in range(1, len(typical_price))]
        negative_flow_values = [money_flow.iloc[i] if typical_price.iloc[i] < typical_price.iloc[i-1] else 0 for i in range(1, len(typical_price))]

        positive_flow = pd.Series(positive_flow_values, index=typical_price.index[1:])
        negative_flow = pd.Series(negative_flow_values, index=typical_price.index[1:])
        
        positive_mf_14 = positive_flow.rolling(14).sum()
        negative_mf_14 = negative_flow.rolling(14).sum()

        money_ratio = positive_mf_14 / negative_mf_14
        money_ratio = money_ratio.replace([np.inf, -np.inf], 0)

        df['mfi'] = 100 - (100 / (1 + money_ratio))
        df['mfi'] = df['mfi'].fillna(50)

        df['volume_ma20'] = df['volume'].rolling(window=20, min_periods=1).mean()
        return df
        
    def _fetch_market_data_worker(self):
        try:
            url_market_info = "https://api.upbit.com/v1/market/all?isDetails=true"
            res_market_info = requests.get(url_market_info)
            res_market_info.raise_for_status()
            
            live_market_data = {item['market']: item for item in res_market_info.json() if item['market'].startswith('KRW-')}

            initial_krw_tickers = set(self.ticker_to_display_name.keys())
            live_krw_tickers = set(live_market_data.keys())
            
            suspended_tickers = initial_krw_tickers - live_krw_tickers
            
            if suspended_tickers:
                print(f"ℹ️ API 목록에서 제외된 종목 발견 (거래지원 종료 간주): {suspended_tickers}")

            for ticker in suspended_tickers:
                korean_name = self.ticker_to_display_name.get(ticker, ticker).split('(')[0]
                live_market_data[ticker] = {'market': ticker, 'korean_name': korean_name, 'market_warning': 'TRADING_SUSPENSION'}
            
            all_market_data = live_market_data
            
            krw_tickers = list(all_market_data.keys())
            tickers_for_price_check = [t for t in krw_tickers if t not in suspended_tickers]
            
            if tickers_for_price_check:
                url_ticker_price = f"https://api.upbit.com/v1/ticker?markets={','.join(tickers_for_price_check)}"
                res_ticker_price = requests.get(url_ticker_price)
                res_ticker_price.raise_for_status()
                price_data = {item['market']: item for item in res_ticker_price.json()}
                for ticker, price_info in price_data.items():
                    if ticker in all_market_data:
                        all_market_data[ticker].update(price_info)
            
            combined_data = list(all_market_data.values())
            
            if combined_data:
                self.data_queue.put(("update_market", combined_data))

        except Exception as e:
            print(f"❗️ KRW 마켓 목록 업데이트 중 오류: {e}")
            traceback.print_exc()

    def _redraw_chart(self):
        self.fig.clear() 
        if self.master_df is None or self.master_df.empty:
            ax = self.fig.add_subplot(111)
            ax.text(0.5, 0.5, "차트 데이터가 없습니다.", ha='center', va='center')
            self.canvas.draw()
            return

        df = self.master_df.copy()
        x_indices = np.arange(len(df))

        gs = self.fig.add_gridspec(4, 1, height_ratios=[4, 1, 1, 1], hspace=0.05)
        ax1 = self.fig.add_subplot(gs[0, 0])
        ax2 = self.fig.add_subplot(gs[1, 0], sharex=ax1)
        ax3 = self.fig.add_subplot(gs[2, 0], sharex=ax1)
        ax4 = self.fig.add_subplot(gs[3, 0], sharex=ax1)

        plt.setp(ax1.get_xticklabels(), visible=False)
        plt.setp(ax2.get_xticklabels(), visible=False)
        plt.setp(ax3.get_xticklabels(), visible=False)
        
        mpf.plot(df, type='candle', ax=ax1, style='yahoo')

        for period, var in self.ma_vars.items():
            if var.get() and f'ma{period}' in df.columns:
                ax1.plot(x_indices, df[f'ma{period}'], label=f'MA{period}', lw=0.8)

        if self.bb_var.get() and 'bb_upper' in df.columns:
            ax1.plot(x_indices, df['bb_middle'], color='orange', linestyle=':', lw=1, label='BB Center')
            ax1.fill_between(x_indices, df['bb_lower'], df['bb_upper'], color='gray', alpha=0.1)

        ax1.set_ylabel('Price (KRW)')
        ax1.set_title(self.get_chart_title())
        ax1.legend(loc='upper left', fontsize='small')
        ax1.grid(True, linestyle=':', alpha=0.6)
        ax1.yaxis.set_label_position("right")
        ax1.yaxis.tick_right()

        colors = ['red' if c >= o else 'blue' for c, o in zip(df['close'], df['open'])]
        ax2.bar(x_indices, df['volume'], color=colors, alpha=0.7, width=0.8)
        ax2.plot(x_indices, df['volume_ma20'], 'm--', lw=1, label='Vol MA20')
        ax2.set_ylabel('Volume')
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: format(int(x), ',')))
        ax2.yaxis.set_label_position("right")
        ax2.yaxis.tick_right()

        ax3.plot(x_indices, df['obv'], 'g-', lw=1, label='OBV')
        ax3.plot(x_indices, df['obv_ema'], 'r--', lw=1, label='OBV Signal')
        ax3.set_ylabel('OBV')
        ax3.legend(loc='upper left', fontsize='small')
        ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: format(int(x), ',')))
        ax3.yaxis.set_label_position("right")
        ax3.yaxis.tick_right()

        ax4.plot(x_indices, df['mfi'], 'b-', lw=1, label='MFI')
        ax4.axhline(80, color='r', linestyle=':', lw=1)
        ax4.axhline(20, color='g', linestyle=':', lw=1)
        ax4.fill_between(x_indices, 80, 100, color='r', alpha=0.1)
        ax4.fill_between(x_indices, 0, 20, color='g', alpha=0.1)
        ax4.set_ylabel('MFI')
        ax4.set_ylim(0, 100)
        ax4.yaxis.set_label_position("right")
        ax4.yaxis.tick_right()
        
        tick_indices = np.linspace(0, len(df) - 1, 5, dtype=int)
        tick_labels = [df.index[i].strftime('%m-%d %H:%M' if self.selected_interval.get() not in ['day', 'week'] else '%Y-%m-%d') for i in tick_indices]
        ax4.set_xticks(tick_indices)
        ax4.set_xticklabels(tick_labels, rotation=10, ha='right')

        blended_transform = plt.matplotlib.transforms.blended_transform_factory(ax1.transAxes, ax1.transData)
        if self.current_price > 0:
            ax1.axhline(y=self.current_price, color='red', linestyle='--', linewidth=0.9)
            ax1.text(1.01, self.current_price, f' {self.current_price:,.2f} ', transform=blended_transform, color='white', backgroundcolor='red', va='center', ha='left')

        display_name = self.selected_ticker_display.get()
        ticker = None
        for original_name, ticker_code in self.display_name_to_ticker.items():
            if display_name.endswith(original_name):
                ticker = ticker_code; break

        if ticker:
            avg_buy_price = float(self.balances_data.get(ticker, {}).get('avg_buy_price', 0.0))
            if avg_buy_price > 0:
                ax1.axhline(y=avg_buy_price, color='blue', linestyle=':', linewidth=0.9)
                ax1.text(1.01, avg_buy_price, f' {avg_buy_price:,.2f} ', transform=blended_transform, color='white', backgroundcolor='blue', va='center', ha='left')
        
        self.fig.subplots_adjust(left=0.08, right=0.88, bottom=0.1, top=0.92)
        
        self.canvas.draw()

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
        ticker = None
        for original_name, ticker_code in self.display_name_to_ticker.items():
            if display_name.endswith(original_name):
                ticker = ticker_code; break
        
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
            ticker = None
            for original_name, ticker_code in self.display_name_to_ticker.items():
                if display_name.endswith(original_name):
                    ticker = ticker_code; break
            
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
            
            coin_balance = float(krw_balances_data.get(ticker, {}).get('balance', 0.0)) if ticker else 0.0
            coin_symbol = ticker.split('-')[1] if ticker and '-' in ticker else "COIN"
            total_pl = total_valuation - total_investment
            total_pl_rate = (total_pl / total_investment) * 100 if total_investment > 0 else 0
            result_data = (total_investment, total_valuation, total_pl, total_pl_rate, portfolio_data_list, krw_balance, coin_balance, coin_symbol)
            self.data_queue.put(("update_portfolio", result_data))
        except Exception as e: print(f"❗️ 포트폴리오 업데이트 오류: {e}")
    
    def on_ticker_select(self, event=None):
        self.draw_base_chart()
        self._update_order_ui_state()
        display_name = self.selected_ticker_display.get()
        ticker = None
        for original_name, ticker_code in self.display_name_to_ticker.items():
            if display_name.endswith(original_name):
                ticker = ticker_code; break

        if ticker:
            symbol = ticker.split('-')[1]
            self.buy_amount_symbol_label.config(text=symbol); self.sell_amount_symbol_label.config(text=symbol)

    def draw_base_chart(self, *args, keep_current_view=False):
        display_name = self.selected_ticker_display.get()
        ticker = None
        for original_name, ticker_code in self.display_name_to_ticker.items():
            if display_name.endswith(original_name):
                ticker = ticker_code; break
        else:
            ticker = self.display_name_to_ticker.get(display_name, display_name)
        
        interval = self.selected_interval.get()
        if not ticker or ticker == "종목 없음": return
        
        if self.current_chart_ticker == ticker and self.selected_interval.get() == interval:
             self._keep_view = keep_current_view
        else:
             self._keep_view = False
        
        self.current_chart_ticker = ticker
        
        self.master_df = None
        threading.Thread(target=self._fetch_and_draw_chart, args=(ticker, interval, display_name), daemon=True).start()

    def _fetch_and_draw_chart(self, ticker, interval, display_name):
        try:
            df = self.get_technical_indicators(ticker, interval=interval, count=200)
            self.data_queue.put(("draw_chart", (df, interval, display_name)))
        except Exception as e: print(f"❗️ 차트 데이터 로딩 오류: {e}")

    def _update_live_data(self, price):
        if self.master_df is None or self.master_df.empty or not hasattr(self, 'fig') or not self.fig.axes:
            return

        self.current_price = price
        last_idx = self.master_df.index[-1]
        self.master_df.loc[last_idx, 'close'] = price
        if price > self.master_df.loc[last_idx, 'high']: self.master_df.loc[last_idx, 'high'] = price
        if price < self.master_df.loc[last_idx, 'low']: self.master_df.loc[last_idx, 'low'] = price

        current_time = time.time()
        if current_time - self.last_chart_redraw_time < 1.0:
            return
        self.last_chart_redraw_time = current_time

        main_ax = self.fig.axes[0]
        
        artists_to_remove = []
        for artist in main_ax.lines:
            if artist.get_label() in ['_price_line', '_avg_buy_line']:
                artists_to_remove.append(artist)
        for artist in main_ax.texts:
            if artist.get_label() in ['_price_text', '_avg_buy_text']:
                artists_to_remove.append(artist)
        
        for artist in artists_to_remove:
            artist.remove()

        blended_transform = plt.matplotlib.transforms.blended_transform_factory(main_ax.transAxes, main_ax.transData)
        if self.current_price > 0:
            main_ax.axhline(y=self.current_price, color='red', linestyle='--', linewidth=0.9, label='_price_line')
            main_ax.text(1.01, self.current_price, f' {self.current_price:,.2f} ', transform=blended_transform, color='white', backgroundcolor='red', va='center', ha='left', label='_price_text')

        main_ax.set_title(self.get_chart_title())
        
        self.canvas.draw_idle()

    def _finalize_chart_drawing(self, df, interval, display_name):
        if self._keep_view and hasattr(self, 'fig') and self.fig.axes:
            cur_xlim = self.fig.axes[0].get_xlim()
            cur_ylim = self.fig.axes[0].get_ylim()
        else:
            cur_xlim, cur_ylim = None, None

        self.master_df = df
        
        self._redraw_chart()

        if self._keep_view and cur_xlim and cur_ylim:
             try:
                self.fig.axes[0].set_xlim(cur_xlim)
                self.fig.axes[0].set_ylim(cur_ylim)
                self.canvas.draw()
             except Exception:
                self.reset_chart_view()
        else:
            self.reset_chart_view()
    
    def get_chart_title(self):
        display_name = self.selected_ticker_display.get()
        ticker = None
        for original_name, ticker_code in self.display_name_to_ticker.items():
            if display_name.endswith(original_name):
                ticker = ticker_code; break
        if not ticker: return "차트"
        
        avg_buy_price = float(self.balances_data.get(ticker, {}).get('avg_buy_price', 0.0))
        profit_rate = ((self.current_price - avg_buy_price) / avg_buy_price) * 100 if avg_buy_price > 0 and self.current_price > 0 else 0
        return f'{display_name} ({self.selected_interval.get()}) Chart (수익률: {profit_rate:+.2f}%)'

    def _update_chart_after_loading(self, new_df, current_xlim, num_candles_added):
        print(f"✅ 과거 캔들({num_candles_added})을 추가했습니다. 총 {len(new_df)}개")
        self.master_df = new_df
        self._keep_view = True 
        
        self._redraw_chart()

        try:
            main_ax = self.fig.axes[0]
            new_x_start = current_xlim[0] + num_candles_added
            new_x_end = current_xlim[1] + num_candles_added
            main_ax.set_xlim(new_x_start, new_x_end)

            start_idx = max(0, int(new_x_start))
            end_idx = min(len(new_df), int(new_x_end))
            visible_df = new_df.iloc[start_idx:end_idx]

            if not visible_df.empty:
                min_low = visible_df['low'].min()
                max_high = visible_df['high'].max()
                padding = (max_high - min_low) * 0.05
                main_ax.set_ylim(min_low - padding, max_high + padding)

            self.canvas.draw()
        except Exception as e:
            print(f"❗️ 차트 뷰 업데이트 중 오류: {e}")
            traceback.print_exc()

        self.is_loading_older = False
        self._keep_view = False

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
        ticker = None
        for original_name, ticker_code in self.display_name_to_ticker.items():
            if display_name.endswith(original_name):
                ticker = ticker_code; break
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
            vals = self.market_tree.item(iid, "values")[0]
            if vals == display_name:
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
        if self.master_df is None or len(self.master_df) < 1 or not hasattr(self, 'fig') or not self.fig.axes: return
        main_ax = self.fig.axes[0]
        
        num_candles_to_show = 100
        view_start = max(0, len(self.master_df) - num_candles_to_show)
        view_end = len(self.master_df)
        
        main_ax.set_xlim(view_start, view_end)
        
        try:
            visible_df = self.master_df.iloc[int(view_start):int(view_end)]
            if not visible_df.empty:
                min_low, max_high = visible_df['low'].min(), visible_df['high'].max()
                padding = (max_high - min_low) * 0.05
                main_ax.set_ylim(min_low - padding, max_high + padding)
        except Exception as e:
            print(f"❗️ 뷰 리셋 중 Y축 범위 설정 오류: {e}")
            main_ax.autoscale(enable=True, axis='y', tight=False)
            
        self.canvas.draw_idle()
        print("🔄️ 차트 뷰를 초기 상태로 리셋했습니다.")

    def on_scroll(self, event):
        if not hasattr(self, 'fig') or not self.fig.axes or event.inaxes not in self.fig.axes: return
        main_ax = self.fig.axes[0]
        zoom_factor = 1/1.1 if event.step > 0 else 1.1
        cur_xlim = main_ax.get_xlim()
        x_data = event.xdata
        if x_data is None: return
        new_xlim = [(cur_xlim[0] - x_data) * zoom_factor + x_data, (cur_xlim[1] - x_data) * zoom_factor + x_data]
        main_ax.set_xlim(new_xlim)
        self.canvas.draw_idle()

    def on_press(self, event):
        if not hasattr(self, 'fig') or not self.fig.axes or event.inaxes not in self.fig.axes: return
        if event.dblclick: self.reset_chart_view(); return
        self.is_panning = True
        self.pan_start_pos = (event.xdata, event.ydata)

    def on_motion(self, event):
        if not self.is_panning or not hasattr(self, 'fig') or not self.fig.axes or \
           event.inaxes not in self.fig.axes or self.pan_start_pos is None or \
           event.xdata is None or event.ydata is None:
            return
            
        main_ax = self.fig.axes[0]
        dx = event.xdata - self.pan_start_pos[0]
        dy = event.ydata - self.pan_start_pos[1]

        cur_xlim = main_ax.get_xlim()
        main_ax.set_xlim([cur_xlim[0] - dx, cur_xlim[1] - dx])
        
        cur_ylim = main_ax.get_ylim()
        main_ax.set_ylim([cur_ylim[0] - dy, cur_ylim[1] - dy])
        
        self.canvas.draw_idle()

    def on_release(self, event):
        if not self.is_panning: return
        self.is_panning = False
        self.pan_start_pos = None
        if not hasattr(self, 'fig') or not self.fig.axes: return
        main_ax = self.fig.axes[0]
        if main_ax.get_xlim()[0] < 1 and not self.is_loading_older:
            self.is_loading_older = True
            print("⏳ 차트 왼쪽 끝에 도달, 과거 데이터를 로딩합니다...")
            self.load_older_data()

    def load_older_data(self):
        if self.master_df is None or self.master_df.empty:
            self.is_loading_older = False
            return
            
        display_name = self.selected_ticker_display.get()
        ticker = None
        for original_name, ticker_code in self.display_name_to_ticker.items():
            if display_name.endswith(original_name):
                ticker = ticker_code; break
        if not ticker: 
            self.is_loading_older = False
            return
        
        interval, to_date, current_xlim = self.selected_interval.get(), self.master_df.index[0], self.fig.axes[0].get_xlim()
        threading.Thread(target=self._fetch_older_data_worker, args=(ticker, interval, to_date, current_xlim), daemon=True).start()

    def _fetch_older_data_worker(self, ticker, interval, to_date, current_xlim):
        try:
            if isinstance(to_date, pd.Timestamp):
                to_date_str = (to_date - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
            else:
                to_date_str = (pd.to_datetime(to_date) - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
            
            older_df_raw = pyupbit.get_ohlcv(ticker, interval=interval, count=200, to=to_date_str)
            
            if older_df_raw is None or older_df_raw.empty:
                print("ℹ️ 더 이상 로드할 과거 데이터가 없습니다.")
                self.is_loading_older = False
                return
            
            current_ohlcv = self.master_df[['open', 'high', 'low', 'close', 'volume']]
            combined_df_raw = pd.concat([older_df_raw, current_ohlcv])
            combined_df_raw = combined_df_raw[~combined_df_raw.index.duplicated(keep='last')].sort_index()

            df_with_indicators = self.get_technical_indicators_from_raw(combined_df_raw)
            
            if df_with_indicators is not None and not df_with_indicators.empty:
                if len(df_with_indicators) > self.MAX_CANDLES:
                    df_with_indicators = df_with_indicators.iloc[-self.MAX_CANDLES:]
                    print(f"ℹ️ 메모리 관리를 위해 캔들 데이터를 {self.MAX_CANDLES}개로 제한합니다.")
                
                num_candles_added = len(df_with_indicators) - len(self.master_df)

                if num_candles_added > 0:
                    self.data_queue.put(("draw_older_chart", (df_with_indicators, current_xlim, num_candles_added)))
                    return
                else:
                    print("ℹ️ 추가된 신규 캔들이 없습니다 (중복 데이터).")

        except Exception as e:
            print(f"❗️ 과거 데이터 로딩 중 오류 발생: {e}")
            traceback.print_exc()
        
        self.is_loading_older = False

    def update_portfolio_gui(self, total_investment, total_valuation, total_pl, total_pl_rate, portfolio_data, krw_balance, coin_balance, coin_symbol):
        self.krw_balance, self.coin_balance = krw_balance, coin_balance
        self.krw_balance_summary_var.set(f"보유 KRW: {krw_balance:,.0f} 원")
        self.total_investment_var.set(f"총 투자금액: {total_investment:,.0f} 원")
        self.total_valuation_var.set(f"총 평가금액: {total_valuation:,.0f} 원")
        self.total_pl_var.set(f"총 평가손익: {total_pl:,.0f} 원 ({total_pl_rate:+.2f}%)")
        
        selected_id = self.portfolio_tree.focus()
        selected_display_name = None
        if selected_id:
            try: selected_display_name = self.portfolio_tree.item(selected_id, "values")[0]
            except IndexError: selected_display_name = None

        self.portfolio_tree.delete(*self.portfolio_tree.get_children())
        new_selection_id = None
        for item in portfolio_data:
            display_name = self.ticker_to_display_name.get(item['ticker'], item['ticker'])
            balance, avg_price, cur_price, valuation, pl = item['balance'], item['avg_price'], item['cur_price'], item['valuation'], item['pl']
            pl_rate = (pl / (avg_price * balance) * 100) if avg_price > 0 and balance > 0 else 0
            tag = 'plus' if pl > 0 else 'minus' if pl < 0 else ''
            
            item_id = self.portfolio_tree.insert('', 'end', values=(display_name, f"{balance:.8f}".rstrip('0').rstrip('.'), f"{avg_price:,.2f}", f"{cur_price:,.2f}", f"{valuation:,.0f}", f"{pl:,.0f}", f"{pl_rate:+.2f}%"), tags=(tag,))
            if display_name == selected_display_name:
                new_selection_id = item_id

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
        
        normal_data = [d for d in self.market_data if d.get('market_warning') != 'TRADING_SUSPENSION']
        suspended_data = [d for d in self.market_data if d.get('market_warning') == 'TRADING_SUSPENSION']
        
        sorted_normal_data = sorted(normal_data, key=lambda x: x.get(key_to_sort, 0), reverse=not self.sort_ascending)
        sorted_data = sorted_normal_data + suspended_data

        try:
            selected_id = self.market_tree.focus()
            selected_display_name_raw = self.market_tree.item(selected_id, 'values')[0] if selected_id else None
            
            self.market_tree.delete(*self.market_tree.get_children())
            new_selection_id = None
            
            self.market_tree.tag_configure('caution', foreground='orange')
            self.market_tree.tag_configure('suspended', foreground='gray', font=('Helvetica', 9, 'italic'))

            for item in sorted_data:
                ticker_name = item['market']
                display_name = self.ticker_to_display_name.get(ticker_name, ticker_name)
                
                warning_status = item.get('market_warning', 'NONE')
                tags_to_apply = []
                
                final_display_name = display_name
                if warning_status == 'CAUTION':
                    final_display_name = f"[유의] {display_name}"
                    tags_to_apply.append('caution')
                elif warning_status == 'TRADING_SUSPENSION':
                    final_display_name = f"[정지] {display_name}"
                    tags_to_apply.append('suspended')

                price = item.get('trade_price', 0)
                change_rate = item.get('signed_change_rate', 0) * 100
                volume = item.get('acc_trade_price_24h', 0)
                
                if change_rate > 0: tags_to_apply.append('red')
                elif change_rate < 0: tags_to_apply.append('blue')
                else: tags_to_apply.append('black')
                
                price_str = f"{price:,.0f}" if price >= 100 else f"{price:g}"
                change_rate_str = f"{change_rate:+.2f}%"
                volume_str = self.format_trade_volume(volume)
                
                item_id = self.market_tree.insert('', 'end', values=(final_display_name, price_str, change_rate_str, volume_str), tags=tuple(tags_to_apply))
                
                if selected_display_name_raw and selected_display_name_raw == final_display_name:
                    new_selection_id = item_id
            
            if new_selection_id:
                self.market_tree.focus(new_selection_id)
                self.market_tree.selection_set(new_selection_id)
        except Exception as e:
            print(f"Error refreshing market tree: {e}")
            traceback.print_exc()

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
        all_display_names = sorted(list(self.ticker_to_display_name.keys()))
        all_combobox_values = [self.ticker_to_display_name[t] for t in all_display_names]
        self.after(0, lambda: self.ticker_combobox.config(values=all_combobox_values))
        
        try:
            balances = upbit.get_balances()
            my_tickers = [f"KRW-{b['currency']}" for b in balances if b['currency'] != 'KRW' and float(b.get('balance', 0)) > 0]
            if my_tickers:
                display_name = self.ticker_to_display_name.get(my_tickers[0], my_tickers[0])
                self.selected_ticker_display.set(display_name)
            elif all_combobox_values: self.selected_ticker_display.set(all_combobox_values[0])
            else: self.selected_ticker_display.set("종목 없음")
        except Exception as e:
            print(f"초기 보유 종목 로딩 실패: {e}")
            if all_combobox_values: self.selected_ticker_display.set(all_combobox_values[0])
        
        self.after(0, self.on_ticker_select)

    def on_closing(self):
        self.is_running = False
        time.sleep(1.1)
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.destroy()

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

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(button_frame, text="저장", command=self.save_and_close).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="닫기", command=self.destroy).pack(side=tk.RIGHT)
        
        options_frame = ttk.LabelFrame(main_frame, text="[2] 투자 설정", padding=10)
        options_frame.pack(side="bottom", fill=tk.X, pady=5)
        ttk.Label(options_frame, text="총 투자 한도 (원):").pack(side=tk.LEFT, padx=5)
        self.amount_entry = ttk.Entry(options_frame, textvariable=self.vars['total_investment_limit'], width=15)
        self.amount_entry.pack(side=tk.LEFT)
        ttk.Label(options_frame, text="(설정 금액을 분할 매수)", foreground="gray").pack(side=tk.LEFT, padx=5)
        
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
        threading.Thread(target=self._populate_worker, daemon=True).start()

    def _populate_worker(self):
        try:
            all_tickers_krw = pyupbit.get_tickers(fiat="KRW")
            url = f"https://api.upbit.com/v1/ticker?markets={','.join(all_tickers_krw)}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            market_data = response.json()
            
            if not market_data:
                self.after(0, lambda: messagebox.showwarning("데이터 없음", "업비트에서 마켓 데이터를 가져오지 못했습니다.", parent=self))
                return

            top_10 = sorted(market_data, key=lambda x: x.get('acc_trade_price_24h', 0), reverse=True)[:10]
            
            def update_listbox():
                self.ticker_listbox.delete(0, END)
                for item in top_10:
                    display_name = self.master_app.ticker_to_display_name.get(item['market'], item['market'])
                    self.ticker_listbox.insert(END, display_name)
                self.restore_selection()
                print("✅ 거래대금 상위 10개 종목을 리스트에 업데이트했습니다.")
            
            self.after(0, update_listbox)

        except requests.exceptions.RequestException as e:
            self.after(0, lambda: messagebox.showerror("네트워크 오류", f"종목 목록을 불러오는 중 네트워크 오류가 발생했습니다:\n{e}", parent=self))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("오류", f"종목 목록을 불러오는 중 오류가 발생했습니다:\n{e}", parent=self))

    def load_settings(self):
        s = self.master_app.auto_trade_settings
        self.vars['total_investment_limit'].set(str(s.get('total_investment_limit', 100000)))
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
            if amount < 25000:
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