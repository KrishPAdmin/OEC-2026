from flask import Flask, render_template
from flask_socketio import SocketIO
import threading
import queue
import time
import os
import serial

BAUD_RATE = 115200
SERIAL_PORT = os.environ.get("ARDUINO_PORT", "/dev/cu.usbmodem101").strip()

# Web App and Socket.IO Setup
app = Flask(__name__)
socketio = SocketIO(app, async_mode="threading")

# Client Session Tracking
client_lock = threading.Lock()
client_count = 0
safe_stop_timer = None


# Serial Bridge
class SerialBridge:
    def __init__(self, port: str, baud: int):
        self.port = port
        self.baud = baud

        self.ser = None
        self.ser_lock = threading.Lock()

        self.cmd_q = queue.Queue()

        self.state_lock = threading.Lock()
        self.desired_magnet = False
        self.desired_solenoid = False
        self.sent_magnet = None
        self.sent_solenoid = None

        self.stop_flag = False
        self.tx_thread = threading.Thread(target=self._tx_worker, daemon=True)
        self.rx_thread = threading.Thread(target=self._rx_worker, daemon=True)

    # Lifecycle
    def start(self):
        self._connect()
        self.tx_thread.start()
        self.rx_thread.start()

    def _connect(self):
        with self.ser_lock:
            if self.ser and self.ser.is_open:
                return
            try:
                self.ser = serial.Serial(self.port, self.baud, timeout=0.1, write_timeout=0.2)
                time.sleep(2.0)
                try:
                    self.ser.reset_input_buffer()
                    self.ser.reset_output_buffer()
                except Exception:
                    pass
                print(f"SERIAL: connected on {self.port} @ {self.baud}")
            except Exception as e:
                self.ser = None
                print(f"SERIAL: connect failed ({self.port}): {e}")

    def is_connected(self) -> bool:
        with self.ser_lock:
            return bool(self.ser and self.ser.is_open)

    # Command Queue and Desired Output State
    def queue_cmd(self, cmd: str):
        cmd = (cmd or "").strip()
        if not cmd:
            return
        self.cmd_q.put(cmd)

    def set_magnet(self, on: bool):
        with self.state_lock:
            self.desired_magnet = bool(on)

    def set_solenoid(self, on: bool):
        with self.state_lock:
            self.desired_solenoid = bool(on)

    def safe_stop(self):
        with self.state_lock:
            self.desired_magnet = False
            self.desired_solenoid = False
        self.queue_cmd("MOVE_STOP")

    # Serial Write Helper
    def _send_line(self, line: str):
        payload = (line + "\n").encode("utf-8", errors="ignore")
        with self.ser_lock:
            if not (self.ser and self.ser.is_open):
                return False
            try:
                self.ser.write(payload)
                self.ser.flush()
                return True
            except Exception as e:
                print(f"SERIAL: write failed: {e}")
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
                return False

    # TX Worker
    def _tx_worker(self):
        while not self.stop_flag:
            if not self.is_connected():
                self._connect()

            magnet_cmd = None
            sol_cmd = None

            with self.state_lock:
                if self.sent_magnet is None or self.desired_magnet != self.sent_magnet:
                    magnet_cmd = "MAGNET_ON" if self.desired_magnet else "MAGNET_OFF"
                if self.sent_solenoid is None or self.desired_solenoid != self.sent_solenoid:
                    sol_cmd = "SOLENOID_ON" if self.desired_solenoid else "SOLENOID_OFF"

            if magnet_cmd:
                if self._send_line(magnet_cmd):
                    with self.state_lock:
                        self.sent_magnet = self.desired_magnet
                time.sleep(0.01)

            if sol_cmd:
                if self._send_line(sol_cmd):
                    with self.state_lock:
                        self.sent_solenoid = self.desired_solenoid
                time.sleep(0.01)

            try:
                cmd = self.cmd_q.get(timeout=0.05)
            except queue.Empty:
                time.sleep(0.01)
                continue

            if not self.is_connected():
                self._connect()

            self._send_line(cmd)
            time.sleep(0.01)

    # RX Worker
    def _rx_worker(self):
        while not self.stop_flag:
            if not self.is_connected():
                self._connect()
                time.sleep(0.2)
                continue

            line = b""
            with self.ser_lock:
                try:
                    line = self.ser.readline()
                except Exception:
                    line = b""

            if line:
                txt = line.decode("utf-8", errors="ignore").strip()
                if txt:
                    print(f"ARDUINO: {txt}")
                    socketio.emit("arduino", {"line": txt})

            time.sleep(0.01)


bridge = SerialBridge(SERIAL_PORT, BAUD_RATE)


# Safe Stop Timer Helpers
def cancel_safe_stop_timer():
    global safe_stop_timer
    if safe_stop_timer is not None:
        try:
            safe_stop_timer.cancel()
        except Exception:
            pass
        safe_stop_timer = None


def schedule_safe_stop(delay_s: float = 2.0):
    global safe_stop_timer

    def _do():
        with client_lock:
            count = client_count
        if count == 0:
            bridge.safe_stop()

    cancel_safe_stop_timer()
    safe_stop_timer = threading.Timer(delay_s, _do)
    safe_stop_timer.daemon = True
    safe_stop_timer.start()


# HTTP Routes
@app.route("/")
def index():
    return render_template("index.html")


# Socket.IO Events
@socketio.on("cmd")
def handle_cmd(cmd):
    cmd = (cmd or "").strip()
    if not cmd:
        return

    print("CMD:", cmd)

    if cmd == "MAGNET_ON":
        bridge.set_magnet(True)
        return
    if cmd == "MAGNET_OFF":
        bridge.set_magnet(False)
        return
    if cmd == "SOLENOID_ON":
        bridge.set_solenoid(True)
        return
    if cmd == "SOLENOID_OFF":
        bridge.set_solenoid(False)
        return

    bridge.queue_cmd(cmd)


@socketio.on("connect")
def handle_connect():
    global client_count
    with client_lock:
        client_count += 1
    cancel_safe_stop_timer()
    print("CLIENT: connected")
    socketio.emit("state", {"magnet": bridge.desired_magnet, "solenoid": bridge.desired_solenoid})


@socketio.on("disconnect")
def handle_disconnect():
    global client_count
    with client_lock:
        client_count = max(0, client_count - 1)
        count = client_count
    print("CLIENT: disconnected")
    if count == 0:
        schedule_safe_stop(2.0)


# Main Entry
if __name__ == "__main__":
    print(f"Using Arduino port: {SERIAL_PORT}")
    bridge.start()
    bridge.safe_stop()
    print("Server started on http://localhost:5050")
    socketio.run(app, host="0.0.0.0", port=5050, use_reloader=False)
