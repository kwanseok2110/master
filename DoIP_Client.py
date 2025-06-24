import tkinter as tk
from tkinter import ttk, scrolledtext
import socket
import struct
import threading
import queue
import binascii
import time

# --- DoIP 프로토콜 로직 처리 클래스 (수정됨) ---
class DoIPClient:
    PROTOCOL_VERSION = 0x02
    PAYLOAD_TYPE_ROUTING_ACTIVATION_REQUEST = 0x0005
    PAYLOAD_TYPE_ROUTING_ACTIVATION_RESPONSE = 0x0006
    PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE = 0x8001
    PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE_ACK = 0x8002
    PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE_NACK = 0x8003
    FUNCTIONAL_TARGET_ADDRESS = 0xFFFF # [추가] Functional 주소 정의

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
        # ... (이전 코드와 동일, 변경 없음)
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
        # ... (이전 코드와 동일, 변경 없음)
        if not self.is_connected: return None
        try:
            payload = struct.pack('>HBxxxx', source_addr, 0x00)
            header = self._create_doip_header(self.PAYLOAD_TYPE_ROUTING_ACTIVATION_REQUEST, len(payload))
            message = header + payload
            self._log(f"Sending Routing Activation Request...")
            self.tcp_socket.sendall(message)
            return self._receive_tcp()
        except socket.error as e:
            self._log(f"Error during routing activation: {e}")
            self.disconnect()
            return None

    # [변경] Functional/Physical 타입을 처리하도록 메서드 수정
    def send_tester_present(self, source_addr, physical_target_addr, message_type):
        """Tester Present 메시지를 보내고 응답은 기다리지 않습니다."""
        if not self.is_connected:
            return

        try:
            if message_type == "Functional":
                target_addr = self.FUNCTIONAL_TARGET_ADDRESS
                uds_data = b'\x3E\x80'  # 3E 80 (suppressPosRsp)
                log_msg = f"Sending Functional Tester Present: {binascii.hexlify(uds_data).decode('ascii').upper()}"
            else:  # "Physical"
                target_addr = physical_target_addr
                uds_data = b'\x3E\x00'  # 3E 00
                log_msg = f"Sending Physical Tester Present: {binascii.hexlify(uds_data).decode('ascii').upper()}"

            payload = struct.pack('>HH', source_addr, target_addr) + uds_data
            header = self._create_doip_header(self.PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE, len(payload))
            message = header + payload

            self._log(log_msg)
            self.tcp_socket.sendall(message)
        except socket.error as e:
            self._log(f"Error sending Tester Present: {e}")
            self.disconnect()

    def send_diagnostic_message(self, source_addr, target_addr, uds_data):
        # ... (이전 코드와 동일, 변경 없음)
        if not self.is_connected: return None
        try:
            payload = struct.pack('>HH', source_addr, target_addr) + uds_data
            header = self._create_doip_header(self.PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE, len(payload))
            message = header + payload
            self._log(f"Sending Diagnostic Message...")
            self._log(f"  - UDS Data: {binascii.hexlify(uds_data).decode('ascii').upper()}")
            self.tcp_socket.sendall(message)
            ack_response = self._receive_tcp()
            if ack_response and ack_response['type'] == self.PAYLOAD_TYPE_DIAGNOSTIC_MESSAGE_ACK:
                return self._receive_tcp()
            else:
                self._log("Did not receive positive ACK for diagnostic message.")
                return None
        except socket.error as e:
            self._log(f"Error sending diagnostic message: {e}")
            self.disconnect()
            return None


    def _receive_tcp(self):
        # ... (이전 코드와 동일, 변경 없음)
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
        # ... (이전 코드와 동일, 변경 없음)
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
        self.root.title("Python DoIP Client (Tester Present Select)")
        self.root.geometry("650x580") # 높이 살짝 조정

        self.log_queue = queue.Queue()
        self.doip_client = DoIPClient(self.queue_log)

        self.tester_present_thread = None
        self.tester_present_active = False
        self.auto_tester_present_var = tk.BooleanVar(value=True)
        # [추가] 라디오 버튼 상태 관리를 위한 변수, 기본값 "Functional"
        self.tester_present_type_var = tk.StringVar(value="Functional") 

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
        
        # [변경] Tester Present 관련 옵션을 한 줄에 배치
        tp_options_frame = ttk.Frame(action_frame)
        tp_options_frame.grid(row=1, column=0, columnspan=4, sticky="w", pady=5)
        
        self.tester_present_check = ttk.Checkbutton(tp_options_frame, text="Auto Tester Present (2s)", variable=self.auto_tester_present_var)
        self.tester_present_check.pack(side=tk.LEFT, padx=(0, 20))

        # [추가] Functional/Physical 선택 라디오 버튼
        functional_radio = ttk.Radiobutton(tp_options_frame, text="Functional", variable=self.tester_present_type_var, value="Functional")
        functional_radio.pack(side=tk.LEFT, padx=5)
        
        physical_radio = ttk.Radiobutton(tp_options_frame, text="Physical", variable=self.tester_present_type_var, value="Physical")
        physical_radio.pack(side=tk.LEFT, padx=5)

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
        # ... (이전 코드와 동일, 변경 없음)
        self.log_area.configure(state='normal')
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.configure(state='disabled')
        self.log_area.see(tk.END)

    def queue_log(self, message):
        # ... (이전 코드와 동일, 변경 없음)
        self.log_queue.put(message)

    def process_queue(self):
        # ... (이전 코드와 동일, 변경 없음)
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log(message)
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)

    def _run_in_thread(self, target_func, *args):
        # ... (이전 코드와 동일, 변경 없음)
        thread = threading.Thread(target=target_func, args=args, daemon=True)
        thread.start()

    def connect_and_activate(self):
        # ... (이전 코드와 동일, 변경 없음)
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
        # ... (이전 코드와 동일, 변경 없음)
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
            if self.auto_tester_present_var.get():
                self.start_tester_present()
        else:
            self.queue_log("Routing activation failed. Disconnecting.")
            self.doip_client.disconnect()
            self.connect_button.config(state="normal")

    def start_tester_present(self):
        # ... (이전 코드와 동일, 변경 없음)
        if not self.tester_present_active:
            self.tester_present_active = True
            self.tester_present_thread = threading.Thread(target=self._tester_present_worker, daemon=True)
            self.tester_present_thread.start()
            self.queue_log("[+] Auto Tester Present started.")
            
    def stop_tester_present(self):
        # ... (이전 코드와 동일, 변경 없음)
        if self.tester_present_active:
            self.tester_present_active = False
            if self.tester_present_thread and self.tester_present_thread.is_alive():
                self.tester_present_thread.join(timeout=0.5)
            self.queue_log("[-] Auto Tester Present stopped.")

    # [변경] 라디오 버튼 값을 읽어와서 DoIPClient 메서드로 전달
    def _tester_present_worker(self):
        try:
            source_addr = int(self.source_addr_entry.get(), 16)
            physical_target_addr = int(self.target_addr_entry.get(), 16)
            message_type = self.tester_present_type_var.get() # 라디오 버튼 값 읽기
        except ValueError:
            self.queue_log("Error: Invalid address format for Tester Present.")
            self.tester_present_active = False
            return

        while self.tester_present_active:
            # message_type을 인자로 전달
            self.doip_client.send_tester_present(source_addr, physical_target_addr, message_type)
            time.sleep(2)
            
    def disconnect(self):
        # ... (이전 코드와 동일, 변경 없음)
        self.stop_tester_present()
        self.doip_client.disconnect()
        self.connect_button.config(state="normal")
        self.disconnect_button.config(state="disabled")
        self.send_diag_button.config(state="disabled")

    def send_diag(self):
        # ... (이전 코드와 동일, 변경 없음)
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

    def on_closing(self):
        # ... (이전 코드와 동일, 변경 없음)
        self.stop_tester_present()
        if self.doip_client.is_connected:
            self.doip_client.disconnect()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = DoIPClientApp(root)
    root.mainloop()