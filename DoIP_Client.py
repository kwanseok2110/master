import tkinter as tk
from tkinter import ttk, scrolledtext
import socket
import struct
import threading
import queue
import binascii
import time # [추가] time.sleep을 위해 추가

# --- DoIP 프로토콜 로직 처리 클래스 (일부 수정) ---
class DoIPClient:
    """DoIP 통신의 핵심 로직을 담당하는 클래스"""

    # DoIP 프로토콜 상수
    PROTOCOL_VERSION = 0x02
    PAYLOAD_TYPE_ROUTING_ACTIVATION_REQUEST = 0x0005
    PAYLOAD_TYPE_ROUTING_ACTIVATION_RESPONSE = 0x0006
    PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE = 0x8001
    PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE_ACK = 0x8002
    PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE_NACK = 0x8003

    def __init__(self, log_callback):
        self.server_ip = None
        self.tcp_port = 13400
        self.tcp_socket = None
        self.is_connected = False
        self.log_callback = log_callback

    def _log(self, message):
        if self.log_callback:
            self.log_callback(message)

    def _create_doip_header(self, payload_type, payload_length):
        protocol_version_inv = self.PROTOCOL_VERSION ^ 0xFF
        header = struct.pack('>BBHL', self.PROTOCOL_VERSION, protocol_version_inv, payload_type, payload_length)
        return header

    def connect(self, server_ip):
        self.server_ip = server_ip
        try:
            self._log(f"Connecting to {self.server_ip}:{self.tcp_port}...")
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.settimeout(5)
            self.tcp_socket.connect((self.server_ip, self.tcp_port))
            self.is_connected = True
            return True
        except socket.error as e:
            self._log(f"Connection failed: {e}")
            self.is_connected = False
            return False

    def send_routing_activation(self, source_addr):
        if not self.is_connected:
            self._log("Error: Not connected.")
            return None
            
        try:
            payload = struct.pack('>HBxxxx', source_addr, 0x00)
            header = self._create_doip_header(self.PAYLOAD_TYPE_ROUTING_ACTIVATION_REQUEST, len(payload))
            message = header + payload

            self._log(f"Sending Routing Activation Request...")
            self._log(f"  - Payload: {binascii.hexlify(payload).decode('ascii').upper()}")
            self.tcp_socket.sendall(message)

            response = self._receive_tcp()
            return response
        except socket.error as e:
            self._log(f"Error during routing activation: {e}")
            self.disconnect()
            return None

    # [추가] Tester Present 전용 전송 메서드
    def send_tester_present(self, source_addr, target_addr):
        """Tester Present 메시지를 보내고 응답은 기다리지 않습니다."""
        if not self.is_connected:
            return # 연결이 끊기면 조용히 종료

        try:
            uds_data = b'\x3E\x00' # UDS Payload: Tester Present, zeroSubFunction
            payload = struct.pack('>HH', source_addr, target_addr) + uds_data
            header = self._create_doip_header(self.PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE, len(payload))
            message = header + payload

            self._log(f"Sending Tester Present: {binascii.hexlify(uds_data).decode('ascii').upper()}")
            self.tcp_socket.sendall(message)
            # 이 함수는 응답을 기다리지 않음
        except socket.error as e:
            self._log(f"Error sending Tester Present: {e}")
            self.disconnect()

    def send_diagnostic_message(self, source_addr, target_addr, uds_data):
        if not self.is_connected:
            self._log("Error: Not connected.")
            return None

        try:
            payload = struct.pack('>HH', source_addr, target_addr) + uds_data
            header = self._create_doip_header(self.PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE, len(payload))
            message = header + payload

            self._log(f"Sending Diagnostic Message...")
            self._log(f"  - UDS Data: {binascii.hexlify(uds_data).decode('ascii').upper()}")
            self.tcp_socket.sendall(message)

            ack_response = self._receive_tcp()
            if ack_response and ack_response['type'] == self.PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE_ACK:
                diag_response = self._receive_tcp()
                return diag_response
            else:
                self._log("Did not receive positive ACK for diagnostic message.")
                return None
        except socket.error as e:
            self._log(f"Error sending diagnostic message: {e}")
            self.disconnect()
            return None

    def _receive_tcp(self):
        try:
            header_data = self.tcp_socket.recv(8)
            if not header_data:
                self._log("Connection closed by server.")
                self.disconnect()
                return None

            _, _, payload_type, payload_length = struct.unpack('>BBHL', header_data)
            self._log(f"Received Message: Type={hex(payload_type)}, Length={payload_length}")
            
            payload_data = b''
            if payload_length > 0:
                received_len = 0
                while received_len < payload_length:
                    chunk = self.tcp_socket.recv(payload_length - received_len)
                    if not chunk: raise socket.error("Socket connection broken")
                    payload_data += chunk
                    received_len += len(chunk)
                self._log(f"  - Payload: {binascii.hexlify(payload_data).decode('ascii').upper()}")
            
            return {'type': payload_type, 'length': payload_length, 'payload': payload_data}
        except socket.timeout:
            self._log("Receive timed out.")
            return None
        except socket.error as e:
            self._log(f"Receive error: {e}")
            self.disconnect()
            return None

    def disconnect(self):
        if self.tcp_socket:
            self.tcp_socket.close()
            self.tcp_socket = None
        if self.is_connected:
            self.is_connected = False
            self._log("Disconnected.")

# --- GUI 애플리케이션 클래스 (수정됨) ---
class DoIPClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Python DoIP Client (Auto Tester Present)")
        self.root.geometry("650x550")

        self.log_queue = queue.Queue()
        self.doip_client = DoIPClient(self.queue_log)

        # [추가] Tester Present 스레드 관리를 위한 변수
        self.tester_present_thread = None
        self.tester_present_active = False
        self.auto_tester_present_var = tk.BooleanVar(value=True) # 체크박스 상태 변수

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.process_queue()

    def create_widgets(self):
        conn_frame = ttk.LabelFrame(self.root, text="Connection", padding="10")
        conn_frame.pack(padx=10, pady=5, fill="x")

        ttk.Label(conn_frame, text="DoIP Server IP:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.ip_entry = ttk.Entry(conn_frame, width=20)
        self.ip_entry.grid(row=0, column=1, padx=5, pady=5)
        self.ip_entry.insert(0, "127.0.0.1")

        self.connect_button = ttk.Button(conn_frame, text="Connect & Activate", command=self.connect_and_activate)
        self.connect_button.grid(row=0, column=2, padx=5, pady=5)

        self.disconnect_button = ttk.Button(conn_frame, text="Disconnect", command=self.disconnect, state="disabled")
        self.disconnect_button.grid(row=0, column=3, padx=5, pady=5)

        action_frame = ttk.LabelFrame(self.root, text="DoIP Actions", padding="10")
        action_frame.pack(padx=10, pady=5, fill="x")
        
        ttk.Label(action_frame, text="Source Addr (Hex):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.source_addr_entry = ttk.Entry(action_frame, width=10)
        self.source_addr_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.source_addr_entry.insert(0, "0E00")

        ttk.Label(action_frame, text="Target Addr (Hex):").grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.target_addr_entry = ttk.Entry(action_frame, width=10)
        self.target_addr_entry.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        self.target_addr_entry.insert(0, "1000")
        
        # [추가] Tester Present 자동 전송 체크박스
        self.tester_present_check = ttk.Checkbutton(action_frame, text="Auto Tester Present (2s)", variable=self.auto_tester_present_var)
        self.tester_present_check.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w")
        
        ttk.Label(action_frame, text="UDS Payload (Hex):").grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="w")
        self.uds_entry = ttk.Entry(action_frame, width=40)
        self.uds_entry.grid(row=3, column=0, columnspan=4, padx=5, pady=5, sticky="ew")
        self.uds_entry.insert(0, "22F190")

        self.send_diag_button = ttk.Button(action_frame, text="Send Diag Message", command=self.send_diag, state="disabled")
        self.send_diag_button.grid(row=4, column=0, columnspan=2, padx=5, pady=5, sticky="ew")

        log_frame = ttk.LabelFrame(self.root, text="Log", padding="10")
        log_frame.pack(padx=10, pady=5, fill="both", expand=True)

        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, width=80, height=20)
        self.log_area.pack(fill="both", expand=True)
        self.log_area.configure(state='disabled')
        
    def log(self, message):
        self.log_area.configure(state='normal')
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.configure(state='disabled')
        self.log_area.see(tk.END)

    def queue_log(self, message):
        self.log_queue.put(message)

    def process_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log(message)
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)

    def _run_in_thread(self, target_func, *args):
        thread = threading.Thread(target=target_func, args=args, daemon=True)
        thread.start()

    def connect_and_activate(self):
        ip = self.ip_entry.get()
        if not ip:
            self.log("Please enter a server IP.")
            return
        
        try:
            source_addr = int(self.source_addr_entry.get(), 16)
        except ValueError:
            self.log("Invalid hex value for Source Address.")
            return

        self._run_in_thread(self._connect_and_activate_worker, ip, source_addr)
        self.connect_button.config(state="disabled")

    def _connect_and_activate_worker(self, ip, source_addr):
        if not self.doip_client.connect(ip):
            self.queue_log("-> Process failed.")
            self.connect_button.config(state="normal")
            return

        self.queue_log("Connection successful.")
        response = self.doip_client.send_routing_activation(source_addr)

        if (response and response['type'] == self.doip_client.PAYLOAD_TYPE_ROUTING_ACTIVATION_RESPONSE and
                len(response['payload']) >= 5 and response['payload'][4] == 0x10):
            
            self.queue_log("Routing activation successful.")
            self.disconnect_button.config(state="normal")
            self.send_diag_button.config(state="normal")
            
            # [추가] 연결 성공 시 Tester Present 스레드 시작
            if self.auto_tester_present_var.get():
                self.start_tester_present()
        else:
            self.queue_log("Routing activation failed. Disconnecting.")
            self.doip_client.disconnect()
            self.connect_button.config(state="normal")

    # [추가] Tester Present 스레드 시작 함수
    def start_tester_present(self):
        if not self.tester_present_active:
            self.tester_present_active = True
            self.tester_present_thread = threading.Thread(target=self._tester_present_worker, daemon=True)
            self.tester_present_thread.start()
            self.queue_log("[+] Auto Tester Present started.")

    # [추가] Tester Present 스레드 중지 함수
    def stop_tester_present(self):
        if self.tester_present_active:
            self.tester_present_active = False
            # 스레드가 완전히 종료될 때까지 잠시 기다릴 수 있음
            if self.tester_present_thread and self.tester_present_thread.is_alive():
                self.tester_present_thread.join(timeout=0.5)
            self.queue_log("[-] Auto Tester Present stopped.")
            
    # [추가] Tester Present를 주기적으로 보내는 워커 함수 (스레드에서 실행됨)
    def _tester_present_worker(self):
        try:
            source_addr = int(self.source_addr_entry.get(), 16)
            target_addr = int(self.target_addr_entry.get(), 16)
        except ValueError:
            self.queue_log("Error: Invalid address format for Tester Present.")
            self.tester_present_active = False # 오류 발생 시 루프 중단
            return

        while self.tester_present_active:
            self.doip_client.send_tester_present(source_addr, target_addr)
            time.sleep(2) # 2초 대기
            
    # [변경] disconnect 함수에 스레드 중지 로직 추가
    def disconnect(self):
        self.stop_tester_present() # 연결 끊기 전에 스레드부터 중지
        self.doip_client.disconnect()
        self.connect_button.config(state="normal")
        self.disconnect_button.config(state="disabled")
        self.send_diag_button.config(state="disabled")

    def send_diag(self):
        try:
            source_addr = int(self.source_addr_entry.get(), 16)
            target_addr = int(self.target_addr_entry.get(), 16)
            uds_payload_hex = self.uds_entry.get().replace(" ", "")
            uds_data = binascii.unhexlify(uds_payload_hex)
            self._run_in_thread(self.doip_client.send_diagnostic_message, source_addr, target_addr, uds_data)
        except ValueError:
            self.log("Invalid hex value for addresses.")
        except binascii.Error:
            self.log("Invalid hex string for UDS payload.")

    # [변경] on_closing 함수에 스레드 중지 로직 추가
    def on_closing(self):
        self.stop_tester_present() # 프로그램 종료 전 스레드 중지
        if self.doip_client.is_connected:
            self.doip_client.disconnect()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = DoIPClientApp(root)
    root.mainloop()