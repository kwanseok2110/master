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
    def __init__(self):
        super().__init__()
        self.trade_password = trade_password
        self.settings_window = None # 설정 창 객체 초기화
        self.title("업비트 포트폴리오 & HTS")
        self.geometry("1600x980")

        # --- 상태 변수 ---
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
        self._ignore_market_select_event = False
        self.data_bounds = {'x': None, 'y': None}
        self.data_queue = Queue()
        self.update_loop_counter = 0

        # --- 차트 관련 변수 ---
        self.chart_elements = {'main': [], 'overlay': []}
        self.ma_vars = {'5': tk.BooleanVar(value=True), '20': tk.BooleanVar(value=True), '60': tk.BooleanVar(), '120': tk.BooleanVar()}
        self.bb_var = tk.BooleanVar(value=True)
        self.is_panning = False
        self.pan_start_pos = None

        # --- 데이터 관련 변수 ---
        self.ticker_to_display_name = {}
        self.display_name_to_ticker = {}
        self.market_data = []
        self.sort_column = 'volume'
        self.sort_ascending = False

        # --- UI 문자열 변수 ---
        self.krw_balance_summary_var = tk.StringVar(value="보유 KRW: 0 원")
        self.total_investment_var = tk.StringVar(value="총 투자금액: 0 원")
        self.total_valuation_var = tk.StringVar(value="총 평가금액: 0 원")
        self.total_pl_var = tk.StringVar(value="총 평가손익: 0 원 (0.00%)")
        self.buy_order_type = tk.StringVar(value="limit")
        self.buy_price_var = tk.StringVar()
        self.buy_amount_var = tk.StringVar()
        self.buy_total_var = tk.StringVar()
        self.sell_order_type = tk.StringVar(value="limit")
        self.sell_price_var = tk.StringVar()
        self.sell_amount_var = tk.StringVar()
        self.sell_total_var = tk.StringVar()
        self.sell_percentage_var = tk.StringVar()
        self.buy_krw_balance_var = tk.StringVar(value="주문가능: 0 KRW")
        self.sell_coin_balance_var = tk.StringVar(value="주문가능: 0 COIN")
        self._is_calculating = False

        # --- 자동매매 관련 변수 ---
        self.is_auto_trading = False
        self.auto_trade_settings = {}
        self.auto_trade_thread = None

        # --- 초기화 작업 ---
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
                'investment_amount': 5000,
                'max_additional_buys': 5,
            }
            self.save_auto_trade_settings()

    def save_auto_trade_settings(self):
        with open("auto_trade_settings.json", "w", encoding="utf-8") as f:
            json.dump(self.auto_trade_settings, f, ensure_ascii=False, indent=4)
        print("💾 자동매매 설정 저장 완료.")

    def start_updates(self):
        self.update_loop()
        self.process_queue()

    def load_ticker_names(self):
        print("🔍 종목 이름 정보를 로드합니다...")
        try:
            url = "https://api.upbit.com/v1/market/all?isDetails=true"
            response = requests.get(url)
            response.raise_for_status()
            all_market_info = response.json()
            for market_info in all_market_info:
                if market_info['market'].startswith('KRW-'):
                    market = market_info['market']
                    korean_name = market_info['korean_name']
                    symbol = market.split('-')[1]
                    display_name = f"{korean_name}({symbol})"
                    self.ticker_to_display_name[market] = display_name
                    self.display_name_to_ticker[display_name] = market
            print("✅ 종목 이름 정보 로드 완료.")
        except Exception as e:
            print(f"❗️ 종목 이름 정보 로드 실패: {e}\n종목 코드를 그대로 사용합니다.")

    def add_variable_traces(self):
        self.buy_price_var.trace_add("write", self._on_buy_input_change)
        self.buy_amount_var.trace_add("write", self._on_buy_input_change)
        self.buy_total_var.trace_add("write", self._on_buy_total_change)
        self.sell_price_var.trace_add("write", self._on_sell_input_change)
        self.sell_amount_var.trace_add("write", self._on_sell_input_change)

    def create_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_frame, width=500, padding=10)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)

        top_left_frame = ttk.Frame(left_frame)
        top_left_frame.pack(fill=tk.X, pady=5)

        summary_frame = ttk.LabelFrame(top_left_frame, text="종합 현황", padding=10)
        summary_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        ttk.Label(summary_frame, textvariable=self.krw_balance_summary_var, font=("Helvetica", 12)).pack(anchor="w")
        ttk.Label(summary_frame, textvariable=self.total_investment_var, font=("Helvetica", 12)).pack(anchor="w")
        ttk.Label(summary_frame, textvariable=self.total_valuation_var, font=("Helvetica", 12)).pack(anchor="w")
        self.total_pl_label = ttk.Label(summary_frame, textvariable=self.total_pl_var, font=("Helvetica", 12, "bold"))
        self.total_pl_label.pack(anchor="w")

        pie_frame = ttk.LabelFrame(top_left_frame, text="코인 비중", padding=10)
        pie_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        self.pie_fig, self.pie_ax = plt.subplots(figsize=(3, 2.5))
        self.pie_fig.patch.set_facecolor('#F0F0F0')
        self.pie_canvas = FigureCanvasTkAgg(self.pie_fig, master=pie_frame)
        self.pie_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        tree_frame = ttk.LabelFrame(left_frame, text="보유 코인 (더블클릭하여 차트 보기)", padding=10)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        cols = ('display_name', 'balance', 'avg_price', 'cur_price', 'valuation', 'pl', 'pl_rate')
        self.portfolio_tree = ttk.Treeview(tree_frame, columns=cols, show='headings')
        col_map = {"종목명": 120, "보유수량": 80, "매수평균가": 90, "현재가": 90, "평가금액": 90, "평가손익": 90, "손익(%)": 70}
        for i, (text, width) in enumerate(col_map.items()):
            self.portfolio_tree.heading(cols[i], text=text)
            self.portfolio_tree.column(cols[i], width=width, anchor='e')
        self.portfolio_tree.column('display_name', anchor='w')
        self.portfolio_tree.tag_configure('plus', foreground='red')
        self.portfolio_tree.tag_configure('minus', foreground='blue')
        self.portfolio_tree.pack(fill=tk.BOTH, expand=True)
        self.portfolio_tree.bind("<Double-1>", self.on_tree_double_click)

        bottom_frame = ttk.Frame(left_frame)
        bottom_frame.pack(fill=tk.BOTH, expand=True, pady=(5,0))

        order_frame = ttk.Frame(bottom_frame)
        order_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.order_notebook = ttk.Notebook(order_frame)
        self.order_notebook.pack(fill=tk.BOTH, expand=True)
        buy_tab = ttk.Frame(self.order_notebook, padding=10)
        sell_tab = ttk.Frame(self.order_notebook, padding=10)
        self.order_notebook.add(buy_tab, text="매수")
        self.order_notebook.add(sell_tab, text="매도")
        self.create_buy_sell_tab(buy_tab, "buy")
        self.create_buy_sell_tab(sell_tab, "sell")

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
        log_text_frame = ttk.Frame(log_frame)
        log_text_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_text_frame, height=5, state='disabled', font=('Courier New', 9), wrap='none')
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar_y = ttk.Scrollbar(log_text_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar_y.set)
        log_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        log_scrollbar_x = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(xscrollcommand=log_scrollbar_x.set)
        log_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)

        right_frame = ttk.Frame(main_frame, padding=10)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

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
        self.market_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.market_tree.pack(side="left", fill="both", expand=True)
        self.market_tree.tag_configure('red', foreground='red')
        self.market_tree.tag_configure('blue', foreground='blue')
        self.market_tree.tag_configure('black', foreground='black')
        self.market_tree.bind("<<TreeviewSelect>>", self.on_market_list_select)

        control_frame_1 = ttk.Frame(right_frame)
        control_frame_1.pack(side="top", fill="x", pady=(10, 0))
        control_frame_2 = ttk.Frame(right_frame)
        control_frame_2.pack(side="top", fill="x", pady=5)
        ttk.Label(control_frame_1, text="종목 선택:").pack(side="left")
        self.ticker_combobox = ttk.Combobox(control_frame_1, textvariable=self.selected_ticker_display, width=20)
        self.ticker_combobox.pack(side="left", padx=(5, 15))
        self.ticker_combobox.bind("<<ComboboxSelected>>", self.on_ticker_select)
        ttk.Label(control_frame_1, text="차트 주기:").pack(side="left")
        intervals = {"5분봉": "minute5", "30분봉": "minute30", "1시간봉": "minute60", "4시간봉": "minute240", "일봉": "day", "주봉": "week"}
        for text, value in intervals.items():
            rb = ttk.Radiobutton(control_frame_1, text=text, variable=self.selected_interval, value=value, command=self.on_ticker_select)
            rb.pack(side="left")
        ttk.Label(control_frame_2, text="보조지표: ").pack(side="left")
        for period, var in self.ma_vars.items():
            cb = ttk.Checkbutton(control_frame_2, text=f"MA{period}", variable=var, command=self.draw_base_chart)
            cb.pack(side="left")
        cb_bb = ttk.Checkbutton(control_frame_2, text="BBands", variable=self.bb_var, command=self.draw_base_chart)
        cb_bb.pack(side="left", padx=5)

        chart_frame = ttk.Frame(right_frame)
        chart_frame.pack(side="bottom", fill="both", expand=True, pady=5)
        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas.mpl_connect('button_release_event', self.on_release)

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
                amount = self.auto_trade_settings.get('investment_amount', 5000)
                add_buys = self.auto_trade_settings.get('max_additional_buys', 5)
                self.log_auto_trade(f"▶️ 자동매매 시작 (대상: {enabled_count}개, 주문액: {amount:,.0f}원, 추가매수: {add_buys}회)")
                self.auto_trade_thread = threading.Thread(target=self.auto_trade_worker, daemon=True)
                self.auto_trade_thread.start()
            else:
                messagebox.showerror("인증 실패", "비밀번호가 일치하지 않습니다.")
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
        if not selected_ticker:
            return
        display_name = self.ticker_to_display_name.get(selected_ticker, selected_ticker)
        self.selected_ticker_display.set(display_name)
        self._ignore_market_select_event = True
        found = False
        for iid in self.market_tree.get_children():
            vals = self.market_tree.item(iid, "values")
            if vals and self.display_name_to_ticker.get(vals[0]) == selected_ticker:
                self.market_tree.selection_set(iid)
                self.market_tree.focus(iid)
                self.market_tree.see(iid)
                found = True
                break
        if not found:
            self.market_tree.selection_remove(self.market_tree.selection())
        self._ignore_market_select_event = False
        self.on_ticker_select()
        print(f"⚙️ 자동매매 설정 저장: {display_name} 차트를 표시합니다.")

    def auto_trade_worker(self):
        self.log_auto_trade("자동매매 스레드가 시작되었습니다.")
        while self.is_auto_trading:
            try:
                self.log_auto_trade("자동매매 루프 실행 중...")
            except Exception as e:
                self.log_auto_trade(f"❗️ 자동매매 루프 오류: {e}")
            time.sleep(10)
        self.log_auto_trade("자동매매 스레드가 종료되었습니다.")

    def get_technical_indicators(self, ticker, interval='day', count=200):
        try:
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
            return self.get_technical_indicators_from_raw(df)
        except Exception as e:
            print(f"❗️ {ticker} 지표 계산 오류: {e}")
            return None

    def get_technical_indicators_from_raw(self, df, min_length=2):
        if df is None or len(df) < min_length: return None
        for p in [5, 20, 60, 120]:
            df[f'ma{p}'] = df['close'].rolling(window=p, min_periods=1).mean()
        delta = df['close'].diff(1)
        gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
        rs = gain / loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['ema12'] = df['close'].ewm(span=12, adjust=False, min_periods=1).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False, min_periods=1).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['signal'] = df['macd'].ewm(span=9, adjust=False, min_periods=1).mean()
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
        price_var = self.buy_price_var if is_buy else self.sell_price_var
        amount_var = self.buy_amount_var if is_buy else self.sell_amount_var
        total_var = self.buy_total_var if is_buy else self.sell_total_var
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
            while not self.data_queue.empty():
                task_name, data = self.data_queue.get_nowait()
                if task_name == "update_portfolio": self.update_portfolio_gui(*data)
                elif task_name == "update_market":
                    self.market_data = data
                    self._refresh_market_tree_gui()
                elif task_name == "update_live_candle": self._update_live_data(data)
                elif task_name == "draw_chart": self._finalize_chart_drawing(*data)
                elif task_name == "draw_older_chart": self._update_chart_after_loading(*data)
        except Empty: pass
        finally:
            if self.is_running: self.after(100, self.process_queue)

    def update_loop(self):
        if not self.is_running: return
        threading.Thread(target=self.fetch_current_price, daemon=True).start()
        if self.update_loop_counter % 5 == 0: threading.Thread(target=self._fetch_portfolio_data_worker, daemon=True).start()
        if self.update_loop_counter % 10 == 0: threading.Thread(target=self._fetch_market_data_worker, daemon=True).start()
        self.update_loop_counter += 1
        self.after(1000, self.update_loop)

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
                balance = float(balance_info['balance'])
                avg_price = float(balance_info['avg_buy_price'])
                cur_price = current_prices_dict.get(t, 0)
                investment = balance * avg_price
                valuation = balance * cur_price
                total_investment += investment
                total_valuation += valuation
                portfolio_data_list.append({'ticker': t, 'balance': balance, 'avg_price': avg_price, 'cur_price': cur_price, 'valuation': valuation, 'pl': valuation - investment})
            coin_balance = float(krw_balances_data.get(ticker, {}).get('balance', 0.0))
            coin_symbol = ticker.split('-')[1] if ticker and '-' in ticker else "COIN"
            total_pl = total_valuation - total_investment
            total_pl_rate = (total_pl / total_investment) * 100 if total_investment > 0 else 0
            result_data = (total_investment, total_valuation, total_pl, total_pl_rate, portfolio_data_list, krw_balance, coin_balance, coin_symbol)
            self.data_queue.put(("update_portfolio", result_data))
        except Exception as e:
            print(f"❗️ 포트폴리오 업데이트 오류: {e}")

    def _fetch_market_data_worker(self):
        try:
            all_tickers_krw = pyupbit.get_tickers(fiat="KRW")
            url = f"https://api.upbit.com/v1/ticker?markets={','.join(all_tickers_krw)}"
            response = requests.get(url)
            response.raise_for_status()
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
            self.buy_amount_symbol_label.config(text=symbol)
            self.sell_amount_symbol_label.config(text=symbol)

    def draw_base_chart(self, *args):
        display_name = self.selected_ticker_display.get()
        ticker = self.display_name_to_ticker.get(display_name, display_name)
        interval = self.selected_interval.get()
        if not ticker or ticker == "종목 없음": return
        if hasattr(self, "_keep_view") and self._keep_view: pass
        else: self._keep_view = False
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
        self.update_overlays()
        self.canvas.draw_idle()

    def _finalize_chart_drawing(self, df, interval, display_name):
        self.master_df = df
        if self.master_df is None or len(self.master_df) < 2:
            self.ax.clear()
            self.ax.text(0.5, 0.5, "차트 데이터가 없습니다.", horizontalalignment='center', verticalalignment='center')
            self.canvas.draw()
            self.master_df = None
            self._keep_view = False
            return
        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()
        self._redraw_chart()
        if hasattr(self, "_keep_view") and self._keep_view and all(cur_xlim) and all(cur_ylim):
            try:
                self.ax.set_xlim(cur_xlim)
                self.ax.set_ylim(cur_ylim)
            except Exception: self.reset_chart_view()
        else: self.reset_chart_view()
        self.canvas.draw()
        self._keep_view = False

    def _redraw_chart(self):
        self.ax.clear()
        for key in self.chart_elements: self.chart_elements[key].clear()
        if self.master_df is None or self.master_df.empty:
            self.canvas.draw()
            return
        display_name = self.selected_ticker_display.get()
        ma_data_to_plot, bb_data_to_plot = {}, {}
        for period, var in self.ma_vars.items():
            if var.get() and f'ma{period}' in self.master_df.columns:
                ma_data_to_plot[period] = self.master_df[f'ma{period}']
        if self.bb_var.get():
            bb_period = 20
            middle = self.master_df['close'].rolling(window=bb_period).mean()
            std = self.master_df['close'].rolling(window=bb_period).std()
            bb_data_to_plot = {'upper': middle + (std * 2), 'middle': middle, 'lower': middle - (std * 2)}
        current_interval = self.selected_interval.get()
        dt_format = '%m-%d %H:%M' if current_interval not in ['day', 'week'] else '%Y-%m-%d'
        mpf.plot(self.master_df, type='candle', ax=self.ax, style='yahoo', ylabel='Price (KRW)', datetime_format=dt_format, xrotation=20)
        all_lows, all_highs = self.master_df['low'], self.master_df['high']
        data_min, data_max = all_lows.min(), all_highs.max()
        padding = (data_max - data_min) * 0.1
        y_bound_min = max(0, data_min - padding)
        y_bound_max = data_max + padding
        self.data_bounds = {'x': (0, len(self.master_df) - 1), 'y': (y_bound_min, y_bound_max)}
        self.plot_moving_averages(ma_data_to_plot)
        self.plot_bollinger_bands(bb_data_to_plot)
        self.ax.grid(True, linestyle='--', alpha=0.6)
        if ma_data_to_plot or bb_data_to_plot: self.ax.legend()
        self.update_overlays()
        print(f"📈 {display_name} ({self.selected_interval.get()}) 차트를 새로 그렸습니다. (총 {len(self.master_df)}개 캔들)")

    def _update_chart_after_loading(self, new_df, new_xlim):
        num_added = len(new_df) - (len(self.master_df) if self.master_df is not None else 0)
        self.master_df = new_df
        print(f"✅ 과거 캔들({num_added})을 추가했습니다. 총 {len(new_df)}개")
        self._redraw_chart()
        self.ax.set_xlim(new_xlim)
        self.canvas.draw()
        self.is_loading_older = False

    def _on_buy_input_change(self, *args):
        if self._is_calculating or self.buy_order_type.get() != 'limit': return
        self._is_calculating = True
        try:
            price = float(self.buy_price_var.get() or 0)
            amount = float(self.buy_amount_var.get() or 0)
            self.buy_total_var.set(f"{price * amount:.0f}")
        except (ValueError, TclError): pass
        finally: self._is_calculating = False

    def _on_buy_total_change(self, *args):
        if self._is_calculating or self.buy_order_type.get() != 'limit': return
        self._is_calculating = True
        try:
            price = float(self.buy_price_var.get() or 0)
            total = float(self.buy_total_var.get() or 0)
            if price > 0: self.buy_amount_var.set(f"{total / price:g}")
        except (ValueError, TclError): pass
        finally: self._is_calculating = False

    def _on_sell_input_change(self, *args):
        if self._is_calculating or self.sell_order_type.get() != 'limit': return
        self._is_calculating = True
        try:
            price = float(self.sell_price_var.get() or 0)
            amount = float(self.sell_amount_var.get() or 0)
            self.sell_total_var.set(f"{price * amount:.0f}")
        except (ValueError, TclError): pass
        finally: self._is_calculating = False

    def _update_order_ui_state(self):
        buy_type = self.buy_order_type.get()
        self.buy_price_entry.config(state='normal' if buy_type == 'limit' else 'disabled')
        self.buy_amount_entry.config(state='normal' if buy_type == 'limit' else 'disabled')
        self.buy_total_entry.config(state='normal' if buy_type == 'market' else 'disabled')
        if buy_type == 'market':
            self.buy_price_var.set("")
            self.buy_amount_var.set("")
        else: self.buy_total_entry.config(state='normal')
        sell_type = self.sell_order_type.get()
        self.sell_price_entry.config(state='normal' if sell_type == 'limit' else 'disabled')
        self.sell_amount_entry.config(state='normal')
        self.sell_total_entry.config(state='disabled')
        if sell_type == 'market':
            self.sell_price_var.set("")
            self.sell_total_var.set("")

    def _apply_buy_percentage(self, percentage):
        buy_type = self.buy_order_type.get()
        total_krw = self.krw_balance * percentage
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
            amount_to_sell = self.coin_balance * percentage
            self.sell_amount_var.set(str(amount_to_sell))
            self.sell_percentage_var.set('')
        except (ValueError, TclError) as e:
            print(f"매도 비율 계산 중 오류: {e}")
            pass

    def place_order(self, side):
        display_name = self.selected_ticker_display.get()
        ticker = self.display_name_to_ticker.get(display_name, display_name)
        if not ticker:
            messagebox.showerror("오류", "주문할 종목이 선택되지 않았습니다.")
            return
        is_buy = (side == "buy")
        order_type = self.buy_order_type.get() if is_buy else self.sell_order_type.get()
        price, amount, total_krw = None, 0.0, 0.0
        order_params, amount_label, amount_unit, amount_display = (), "", "", ""
        try:
            if order_type == 'limit':
                price_str = self.buy_price_var.get() if is_buy else self.sell_price_var.get()
                amount_str = self.buy_amount_var.get() if is_buy else self.sell_amount_var.get()
                if not price_str or not amount_str: raise ValueError("지정가 주문 시 가격과 수량을 모두 입력해야 합니다.")
                price, amount = float(price_str), float(amount_str)
                if price <= 0 or amount <= 0: raise ValueError("가격과 수량은 0보다 커야 합니다.")
                order_params = (ticker, price, amount)
                amount_label, amount_unit, amount_display = "주문 수량", ticker.split('-')[1], f"{amount:g}"
            else:
                if is_buy:
                    total_krw_str = self.buy_total_var.get()
                    if not total_krw_str: raise ValueError("시장가 매수 시 주문 총액(KRW)을 입력해야 합니다.")
                    total_krw = float(total_krw_str)
                    if total_krw < 5000: raise ValueError("시장가 매수 주문은 5,000원 이상이어야 합니다.")
                    order_params = (ticker, total_krw)
                    amount_label, amount_unit, amount_display = "주문 총액", "KRW", f"{total_krw:,.0f}"
                else:
                    user_amount_str = self.sell_amount_var.get()
                    if not user_amount_str: raise ValueError("시장가 매도 시 주문 수량(COIN)을 입력해야 합니다.")
                    user_amount = float(user_amount_str)
                    if user_amount <= 0: raise ValueError("주문 수량은 0보다 커야 합니다.")
                    sellable_balance = upbit.get_balance(ticker)
                    amount_to_sell = min(user_amount, sellable_balance)
                    current_price = pyupbit.get_current_price(ticker)
                    if current_price and (amount_to_sell * current_price < 5000):
                        raise ValueError(f"주문 금액이 최소 기준(5,000원) 미만입니다.\n(예상 주문액: {amount_to_sell * current_price:,.0f}원)")
                    if amount_to_sell <= 0: raise ValueError("매도 가능한 코인 수량이 없습니다.")
                    order_params = (ticker, amount_to_sell)
                    amount_label, amount_unit, amount_display = "주문 수량", ticker.split('-')[1], f"{amount_to_sell:g}"
        except ValueError as ve:
            messagebox.showerror("입력 오류", f"{ve}")
            return
        except TclError:
            messagebox.showerror("입력 오류", "유효한 숫자를 입력하세요.")
            return
        order_side_text = "매수" if is_buy else "매도"
        order_type_text = "지정가" if order_type == 'limit' else "시장가"
        price_text = f"주문 가격: {price:,.0f} KRW\n" if price is not None else ""
        confirm_msg = (f"[[ 주문 확인 ]]\n\n종목: {display_name}\n종류: {order_side_text} / {order_type_text}\n{price_text}{amount_label}: {amount_display} {amount_unit}\n\n위 내용으로 주문하시겠습니까?")
        if not messagebox.askyesno("주문 확인", confirm_msg): return
        try:
            result = None
            print(f"▶️ 주문 실행: {side}, {order_type}, params: {order_params}")
            if is_buy:
                if order_type == 'limit': result = upbit.buy_limit_order(*order_params)
                else: result = upbit.buy_market_order(*order_params)
            else:
                if order_type == 'limit': result = upbit.sell_limit_order(*order_params)
                else: result = upbit.sell_market_order(*order_params)
            messagebox.showinfo("주문 성공", f"주문이 성공적으로 접수되었습니다.\n\n{result}")
            self.buy_price_var.set(""); self.buy_amount_var.set(""); self.buy_total_var.set("")
            self.sell_price_var.set(""); self.sell_amount_var.set(""); self.sell_total_var.set("")
            print("ℹ️ 주문 체결 대기... 2초 후 잔고를 갱신합니다.")
            self.after(2000, lambda: threading.Thread(target=self._fetch_portfolio_data_worker, daemon=True).start())
        except Exception as e:
            messagebox.showerror("주문 실패", f"주문 중 오류가 발생했습니다.\n\n오류 유형: {type(e).__name__}\n메시지: {e}")
            print(f"❗️ 주문 실패: {e}")

    def on_tree_double_click(self, event):
        item_id = self.portfolio_tree.focus()
        if not item_id: return
        item_values = self.portfolio_tree.item(item_id, "values")
        display_name = item_values[0]
        if not display_name: return
        self._ignore_market_select_event = True
        self.selected_ticker_display.set(display_name)
        found = False
        for iid in self.market_tree.get_children():
            vals = self.market_tree.item(iid, "values")
            if vals and vals[0] == display_name:
                self.market_tree.selection_set(iid)
                self.market_tree.focus(iid)
                found = True
                break
        if not found: self.market_tree.selection_remove(self.market_tree.selection())
        self._ignore_market_select_event = False
        self.on_ticker_select()
        print(f"📋 포트폴리오 더블클릭: {display_name} 차트를 표시합니다.")

    def on_market_list_select(self, event):
        if getattr(self, '_ignore_market_select_event', False): return
        selection = self.market_tree.selection()
        if not selection: return
        item = self.market_tree.item(selection[0])
        display_name = item['values'][0]
        if self.selected_ticker_display.get() == display_name:
            self._keep_view = True
            return
        else: self._keep_view = False
        self.portfolio_tree.selection_remove(self.portfolio_tree.selection())
        self.portfolio_tree.focus('')
        self.selected_ticker_display.set(display_name)
        self.on_ticker_select()
        print(f"💹 거래대금 목록 선택: {display_name} 차트를 표시합니다.")

    def reset_chart_view(self):
        if self.master_df is None or len(self.master_df) < 1: return
        view_start = max(0, len(self.master_df) - 200)
        view_end = len(self.master_df) + 2
        self.ax.set_xlim(view_start, view_end - 1)
        try:
            visible_df = self.master_df.iloc[int(view_start):int(view_end-2)]
            min_low = visible_df['low'].min()
            max_high = visible_df['high'].max()
            padding = (max_high - min_low) * 0.05
            self.ax.set_ylim(min_low - padding, max_high + padding)
        except Exception as e:
            print(f"❗️ 뷰 리셋 중 Y축 범위 설정 오류: {e}")
            self.ax.autoscale(enable=True, axis='y', tight=False)
        self.canvas.draw_idle()
        print("🔄️ 차트 뷰를 초기 상태로 리셋했습니다.")

    def on_scroll(self, event):
        if event.inaxes != self.ax: return
        zoom_factor = 1 / 1.1 if event.step > 0 else 1.1
        cur_xlim = self.ax.get_xlim(); cur_ylim = self.ax.get_ylim()
        x_data, y_data = event.xdata, event.ydata
        if x_data is None or y_data is None: return
        new_xlim = [(cur_xlim[0] - x_data) * zoom_factor + x_data, (cur_xlim[1] - x_data) * zoom_factor + x_data]
        new_ylim = [(cur_ylim[0] - y_data) * zoom_factor + y_data, (cur_ylim[1] - y_data) * zoom_factor + y_data]
        x_bounds = self.data_bounds.get('x'); y_bounds = self.data_bounds.get('y')
        if x_bounds:
            if new_xlim[0] < x_bounds[0]: new_xlim[0] = x_bounds[0]
            if new_xlim[1] > x_bounds[1] + 2: new_xlim[1] = x_bounds[1] + 2
        if y_bounds:
            if new_ylim[0] < y_bounds[0]: new_ylim[0] = y_bounds[0]
            if new_ylim[1] > y_bounds[1]: new_ylim[1] = y_bounds[1]
        self.ax.set_xlim(new_xlim); self.ax.set_ylim(new_ylim); self.canvas.draw_idle()

    def on_press(self, event):
        if event.inaxes != self.ax: return
        if event.dblclick:
            self.reset_chart_view()
            return
        self.is_panning = True
        self.pan_start_pos = (event.xdata, event.ydata)

    def on_motion(self, event):
        if not self.is_panning or event.inaxes != self.ax or self.pan_start_pos is None: return
        try:
            dx = event.xdata - self.pan_start_pos[0]
            dy = event.ydata - self.pan_start_pos[1]
            cur_xlim = self.ax.get_xlim(); cur_ylim = self.ax.get_ylim()
            new_xlim = [cur_xlim[0] - dx, cur_xlim[1] - dx]
            x_bounds = self.data_bounds.get('x')
            if x_bounds:
                width = new_xlim[1] - new_xlim[0]
                if new_xlim[0] < x_bounds[0]: new_xlim = [x_bounds[0], x_bounds[0] + width]
                if new_xlim[1] > x_bounds[1] + 2: new_xlim = [x_bounds[1] + 2 - width, x_bounds[1] + 2]
            self.ax.set_xlim(new_xlim); self.ax.set_ylim([cur_ylim[0] - dy, cur_ylim[1] - dy]); self.canvas.draw_idle()
        except TypeError: pass

    def on_release(self, event):
        if not self.is_panning: return
        self.is_panning = False; self.pan_start_pos = None
        current_xlim = self.ax.get_xlim()
        if current_xlim[0] < 1 and not self.is_loading_older:
            print("⏳ 차트 왼쪽 끝에 도달, 과거 데이터를 로딩합니다...");
            self.load_older_data()

    def load_older_data(self):
        if self.master_df is None or self.master_df.empty: return
        self.is_loading_older = True
        display_name = self.selected_ticker_display.get()
        ticker = self.display_name_to_ticker.get(display_name)
        interval = self.selected_interval.get()
        to_date = self.master_df.index[0]
        current_xlim = self.ax.get_xlim()
        threading.Thread(target=self._fetch_older_data_worker, args=(ticker, interval, to_date, current_xlim), daemon=True).start()

    def _fetch_older_data_worker(self, ticker, interval, to_date, current_xlim):
        try:
            if isinstance(to_date, pd.Timestamp):
                to_date_str = (to_date - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
            else:
                to_date_str = (pd.to_datetime(to_date) - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
            older_df_raw = pyupbit.get_ohlcv(ticker, interval=interval, count=200, to=to_date_str)
            if older_df_raw is None or len(older_df_raw) < 2:
                print("ℹ️ 더 이상 로드할 과거 데이터가 없습니다.")
                self.is_loading_older = False
                return
            current_ohlcv = self.master_df[['open', 'high', 'low', 'close', 'volume']]
            combined_df_raw = pd.concat([older_df_raw, current_ohlcv])
            combined_df_raw = combined_df_raw[~combined_df_raw.index.duplicated(keep='last')]
            combined_df_raw = combined_df_raw.sort_index()
            df_with_indicators = self.get_technical_indicators_from_raw(combined_df_raw, min_length=2)
            if df_with_indicators is not None and not df_with_indicators.empty:
                num_candles_added = len(df_with_indicators) - len(self.master_df)
                if num_candles_added > 0:
                    new_xlim = (current_xlim[0] + num_candles_added, current_xlim[1] + num_candles_added)
                    self.data_queue.put(("draw_older_chart", (df_with_indicators, new_xlim)))
                    return
            print("ℹ️ 더 이상 로드할 과거 데이터가 없습니다.")
        except Exception as e:
            print(f"❗️ 과거 데이터 로딩 중 오류 발생: {e}")
        self.is_loading_older = False

    def plot_moving_averages(self, ma_data):
        if ma_data:
            lines = []
            for period, ma_series in ma_data.items():
                line, = self.ax.plot(range(len(ma_series)), ma_series.values, label=f"MA{period}")
                lines.append(line)
            self.chart_elements['main'].extend(lines)

    def plot_bollinger_bands(self, bb_data):
        if bb_data:
            x_axis = range(len(self.master_df))
            middle, = self.ax.plot(x_axis, bb_data['middle'].values, color='orange', linestyle='--', linewidth=1, label='BB Center')
            upper, = self.ax.plot(x_axis, bb_data['upper'].values, color='gray', linestyle='--', linewidth=0.7)
            lower, = self.ax.plot(x_axis, bb_data['lower'].values, color='gray', linestyle='--', linewidth=0.7)
            fill = self.ax.fill_between(x_axis, bb_data['lower'].values, bb_data['upper'].values, color='gray', alpha=0.1)
            self.chart_elements['main'].extend([middle, upper, lower, fill])

    def update_portfolio_gui(self, total_investment, total_valuation, total_pl, total_pl_rate, portfolio_data, krw_balance, coin_balance, coin_symbol):
        self.krw_balance = krw_balance
        self.coin_balance = coin_balance
        self.krw_balance_summary_var.set(f"보유 KRW: {krw_balance:,.0f} 원")
        self.total_investment_var.set(f"총 투자금액: {total_investment:,.0f} 원")
        self.total_valuation_var.set(f"총 평가금액: {total_valuation:,.0f} 원")
        self.total_pl_var.set(f"총 평가손익: {total_pl:,.0f} 원 ({total_pl_rate:+.2f}%)")
        self.portfolio_tree.delete(*self.portfolio_tree.get_children())
        for item in portfolio_data:
            display_name = self.ticker_to_display_name.get(item['ticker'], item['ticker'])
            balance, avg_price, cur_price, valuation, pl = item['balance'], item['avg_price'], item['cur_price'], item['valuation'], item['pl']
            pl_rate = (pl / (avg_price * balance) * 100) if avg_price > 0 and balance > 0 else 0
            tag = 'plus' if pl > 0 else 'minus' if pl < 0 else ''
            self.portfolio_tree.insert('', 'end', values=(display_name, f"{balance:.8f}".rstrip('0').rstrip('.'), f"{avg_price:,.2f}", f"{cur_price:,.2f}", f"{valuation:,.0f}", f"{pl:,.0f}", f"{pl_rate:+.2f}%"), tags=(tag,))
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
            labels = [item['label'].split('(')[0] for item in main_items][::-1]
            percentages = [(item['value'] / total_valuation) * 100 for item in main_items][::-1]
            num_items = len(labels)
            try: colors = plt.colormaps.get_cmap('viridis_r')(np.linspace(0, 1, num_items))
            except AttributeError: colors = plt.cm.get_cmap('viridis_r', num_items)(range(num_items))
            bars = self.pie_ax.barh(labels, percentages, color=colors, height=0.6)
            self.pie_ax.set_xlabel('비중 (%)', fontsize=9)
            self.pie_ax.tick_params(axis='y', labelsize=9)
            self.pie_ax.set_title('포트폴리오 구성', fontsize=11, fontweight='bold')
            self.pie_ax.spines['top'].set_visible(False); self.pie_ax.spines['right'].set_visible(False); self.pie_ax.spines['left'].set_visible(False)
            for bar in bars:
                width = bar.get_width()
                self.pie_ax.text(width + 0.5, bar.get_y() + bar.get_height()/2., f'{width:.1f}%', ha='left', va='center', fontsize=8.5)
            self.pie_ax.set_xlim(0, max(percentages) * 1.15 if percentages else 100)
        else:
            self.pie_ax.text(0.5, 0.5, "보유 코인이 없습니다", horizontalalignment='center', verticalalignment='center')
            self.pie_ax.set_xticks([]); self.pie_ax.set_yticks([])
        self.pie_fig.tight_layout()
        self.pie_canvas.draw()
        self.buy_krw_balance_var.set(f"주문가능: {krw_balance:,.0f} KRW")
        self.sell_coin_balance_var.set(f"주문가능: {coin_balance:g} {coin_symbol}")

    def _refresh_market_tree_gui(self):
        if not self.market_data: return
        sort_key_map = { 'display_name': 'market', 'price': 'trade_price', 'change_rate': 'signed_change_rate', 'volume': 'acc_trade_price_24h' }
        key_to_sort = sort_key_map.get(self.sort_column, 'acc_trade_price_24h')
        sorted_data = sorted(self.market_data, key=lambda x: x.get(key_to_sort, 0), reverse=not self.sort_ascending)
        try:
            selected_id = self.market_tree.focus()
            selected_display_name = self.market_tree.item(selected_id, 'values')[0] if selected_id else None
            self.market_tree.delete(*self.market_tree.get_children()); new_selection_id = None
            for item in sorted_data:
                ticker_name = item['market']; display_name = self.ticker_to_display_name.get(ticker_name, ticker_name)
                price = item['trade_price']; change_rate = item['signed_change_rate'] * 100; volume = item['acc_trade_price_24h']
                tag = 'red' if change_rate > 0 else 'blue' if change_rate < 0 else 'black'
                price_str = f"{price:,.0f}" if price >= 100 else f"{price:g}"; change_rate_str = f"{change_rate:+.2f}%"; volume_str = self.format_trade_volume(volume)
                item_id = self.market_tree.insert('', 'end', values=(display_name, price_str, change_rate_str, volume_str), tags=(tag,))
                if display_name == selected_display_name: new_selection_id = item_id
            if new_selection_id:
                self.market_tree.focus(new_selection_id); self.market_tree.selection_set(new_selection_id)
        except Exception: pass

    def sort_market_list(self, col):
        if self.sort_column == col: self.sort_ascending = not self.sort_ascending
        else: self.sort_column = col; self.sort_ascending = False
        self._refresh_market_tree_gui()

    def format_trade_volume(self, volume):
        if volume > 1_000_000_000_000: return f"{volume / 1_000_000_000_000:.1f}조"
        if volume > 1_000_000_000: return f"{volume / 1_000_000_000:.0f}십억"
        if volume > 1_000_000: return f"{volume / 1_000_000:.0f}백만"
        return f"{volume:,.0f}"

    def load_my_tickers(self):
        threading.Thread(target=self._load_my_tickers_worker, daemon=True).start()

    def _load_my_tickers_worker(self):
        balances = upbit.get_balances()
        my_tickers = [f"KRW-{b['currency']}" for b in balances if b['currency'] != 'KRW' and float(b.get('balance', 0)) > 0]
        all_display_names = sorted(list(self.display_name_to_ticker.keys()))
        self.after(0, lambda: self.ticker_combobox.config(values=all_display_names))
        if my_tickers:
            first_ticker = my_tickers[0]
            display_name = self.ticker_to_display_name.get(first_ticker, first_ticker)
            self.selected_ticker_display.set(display_name)
        elif all_display_names:
            self.selected_ticker_display.set(all_display_names[0])
        else:
            self.selected_ticker_display.set("종목 없음")
        self.after(0, self.on_ticker_select)

    def update_overlays(self):
        for element in self.chart_elements['overlay']:
            try: element.remove()
            except: pass
        self.chart_elements['overlay'].clear()
        if self.master_df is None: return
        display_name = self.selected_ticker_display.get()
        ticker = self.display_name_to_ticker.get(display_name)
        if not ticker: return
        current_xlim = self.ax.get_xlim()
        current_ylim = self.ax.get_ylim()
        self.avg_buy_price = float(self.balances_data.get(ticker, {}).get('avg_buy_price', 0.0))
        profit_rate = ((self.current_price - self.avg_buy_price) / self.avg_buy_price) * 100 if self.avg_buy_price > 0 and self.current_price > 0 else 0
        self.ax.set_title(f'{display_name} ({self.selected_interval.get()}) Chart (수익률: {profit_rate:+.2f}%)', fontsize=14)
        right_limit = current_xlim[1]
        if self.current_price > 0 and current_ylim[0] < self.current_price < current_ylim[1]:
            line = self.ax.axhline(y=self.current_price, color='red', linestyle='--')
            text = self.ax.text(right_limit, self.current_price, f' {self.current_price:,.2f}', color='red', va='center', ha='left', bbox=dict(facecolor='white', alpha=0.5, edgecolor='none', boxstyle='round,pad=0.2'))
            self.chart_elements['overlay'].extend([line, text])
        if self.avg_buy_price > 0 and current_ylim[0] < self.avg_buy_price < current_ylim[1]:
            line = self.ax.axhline(y=self.avg_buy_price, color='blue', linestyle=':')
            text = self.ax.text(right_limit, self.avg_buy_price, f' {self.avg_buy_price:,.2f}', color='blue', va='center', ha='left', bbox=dict(facecolor='white', alpha=0.5, edgecolor='none', boxstyle='round,pad=0.2'))
            self.chart_elements['overlay'].extend([line, text])

    def on_closing(self):
        self.is_running = False
        if hasattr(self, 'settings_window') and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.destroy()

class AutoTradeSettingsWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.master_app = master
        self.title("자동매매 설정")
        self.geometry("400x450")
        self.resizable(False, False)

        self.vars = {
            'investment_amount': tk.StringVar(),
            'max_additional_buys': tk.StringVar(),
        }

        self.setup_widgets()
        self.load_settings()

    def setup_widgets(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

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

        options_frame = ttk.LabelFrame(main_frame, text="[2] 설정 금액", padding=10)
        options_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(options_frame, text="1회 매수 금액 (원):").pack(side=tk.LEFT, padx=5)
        self.amount_entry = ttk.Entry(options_frame, textvariable=self.vars['investment_amount'], width=15)
        self.amount_entry.pack(side=tk.LEFT)

        add_buy_frame = ttk.LabelFrame(main_frame, text="[3] 추가 매수 설정", padding=10)
        add_buy_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(add_buy_frame, text="추가 매수 횟수 (최대 10회):").pack(side=tk.LEFT, padx=5)
        buy_counts = [str(i) for i in range(0, 11)]
        self.add_buy_combo = ttk.Combobox(add_buy_frame, textvariable=self.vars['max_additional_buys'], values=buy_counts, width=5, state="readonly")
        self.add_buy_combo.pack(side=tk.LEFT)
        self.add_buy_combo.set('5')

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(button_frame, text="저장", command=self.save_and_close).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="닫기", command=self.destroy).pack(side=tk.RIGHT)

    def populate_top_tickers(self):
        self.ticker_listbox.delete(0, END)
        market_data = self.master_app.market_data
        if not market_data:
            messagebox.showwarning("데이터 없음", "아직 마켓 데이터가 로드되지 않았습니다.\n잠시 후 다시 시도해주세요.", parent=self)
            return
        try:
            top_10 = sorted(market_data, key=lambda x: x.get('acc_trade_price_24h', 0), reverse=True)[:10]
            for item in top_10:
                ticker = item['market']
                display_name = self.master_app.ticker_to_display_name.get(ticker, ticker)
                self.ticker_listbox.insert(END, display_name)
            self.restore_selection()
            print("✅ 거래대금 상위 10개 종목을 리스트에 업데이트했습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"종목 목록을 불러오는 중 오류가 발생했습니다:\n{e}", parent=self)

    def load_settings(self):
        s = self.master_app.auto_trade_settings
        self.vars['investment_amount'].set(str(s.get('investment_amount', 5000)))
        self.vars['max_additional_buys'].set(str(s.get('max_additional_buys', 5)))
        self.populate_top_tickers()

    def restore_selection(self):
        s = self.master_app.auto_trade_settings
        enabled_tickers = s.get('enabled_tickers', [])
        if not enabled_tickers:
            return
        selected_ticker = enabled_tickers[0] 
        for i in range(self.ticker_listbox.size()):
            display_name = self.ticker_listbox.get(i)
            ticker = self.master_app.display_name_to_ticker.get(display_name)
            if ticker == selected_ticker:
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
                selected_index = selected_indices[0]
                display_name = self.ticker_listbox.get(selected_index)
                ticker = self.master_app.display_name_to_ticker.get(display_name)
                if ticker:
                    enabled_tickers.append(ticker)
                    selected_ticker_for_chart = ticker

            new_settings['enabled_tickers'] = enabled_tickers

            amount = int(self.vars['investment_amount'].get())
            if amount < 5000:
                messagebox.showwarning("금액 확인", "최소 주문 금액은 5,000원입니다.", parent=self)
                return
            new_settings['investment_amount'] = amount

            new_settings['max_additional_buys'] = int(self.vars['max_additional_buys'].get())

            self.master_app.auto_trade_settings = new_settings
            self.master_app.save_auto_trade_settings()
            
            if selected_ticker_for_chart:
                self.master_app.select_ticker_from_settings(selected_ticker_for_chart)

            messagebox.showinfo("저장 완료", "자동매매 설정이 저장되었습니다.", parent=self)
            self.destroy()
        except ValueError:
            messagebox.showerror("입력 오류", "매수 금액은 숫자로 입력해야 합니다.", parent=self)
        except Exception as e:
            messagebox.showerror("오류", f"설정 저장 중 오류가 발생했습니다: {e}", parent=self)

if __name__ == "__main__":
    app = UpbitChartApp()
    app.start_updates()
    app.mainloop()