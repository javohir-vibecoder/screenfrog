import threading
import time
import requests
import os
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- SETTINGS ---
# Using the information provided by the user earlier
BOT_TOKEN = "8484712318:AAGEWAzaPjgUJ4TSG9_Or8SYlqsQWoyZOPc"
CHAT_ID = "947732542" 
SECRET_KEY = "super-secret-key"

def telegram_polling():
    """Background thread to listen for /start command"""
    offset = 0
    print("[*] Telegram polling thread started...", flush=True)
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset + 1}&timeout=30"
            resp = requests.get(url, timeout=35).json()
            if resp.get("ok"):
                for update in resp.get("result", []):
                    offset = update["update_id"]
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        user_chat_id = str(update["message"]["chat"]["id"])
                        
                        if text == "/start":
                            print(f"[*] Received /start from {user_chat_id}. Sending welcome...", flush=True)
                            welcome_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                            requests.post(welcome_url, json={
                                "chat_id": user_chat_id,
                                "text": "Привет! Я твой SEB Мост. Пришли скриншот через Ctrl+Shift+X!"
                            })
        except Exception as e:
            print(f"[!] Polling error: {e}", flush=True)
        time.sleep(1)

@app.route("/", methods=["GET"])
def health():
    print("[*] Health check request received", flush=True)
    return f"SEB Bridge is running! (Bot Token & Polling Active)", 200

@app.route("/upload", methods=["POST"])
def upload():
    print(f"[*] Received upload request from {request.remote_addr}", flush=True)
    if SECRET_KEY and request.headers.get("X-Secret") != SECRET_KEY:
        print("[!] Unauthorized: Wrong Secret Key", flush=True)
        return "Unauthorized", 401

    if "file" not in request.files:
        print("[!] No file part in request", flush=True)
        return "No file part", 400
    
    file = request.files["file"]
    if file.filename == "":
        print("[!] No selected file", flush=True)
        return "No selected file", 400

    temp_path = "temp_capture.jpg"
    try:
        file.save(temp_path)
        print(f"[*] File saved temporarily. Forwarding to Telegram (ChatID: {CHAT_ID})...", flush=True)

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": CHAT_ID,
            "caption": "Captured from SEB Stealth Agent"
        }
        
        with open(temp_path, "rb") as photo:
            files = {"photo": photo}
            response = requests.post(url, data=payload, files=files, timeout=30)
            
        print(f"[*] Telegram API Response: {response.status_code} - {response.text}", flush=True)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        if response.status_code == 200:
            return jsonify({"status": "success", "info": "Photo sent to Telegram"}), 200
        else:
            return jsonify({"status": "error", "info": response.text}), 500
            
    except Exception as e:
        print(f"[!] Server Error during processing: {e}", flush=True)
        traceback.print_exc()
        return jsonify({"status": "error", "info": str(e)}), 500

if __name__ == "__main__":
    # Start polling in background
    thread = threading.Thread(target=telegram_polling, daemon=True)
    thread.start()
    
    # Render.com provides the PORT as an environment variable
    port = int(os.environ.get("PORT", 5000))
    print(f"[*] Starting server on port {port}...", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False)
