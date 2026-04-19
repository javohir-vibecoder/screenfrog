import threading
import time
import requests
import os
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- SETTINGS ---
BOT_TOKEN = "8484712318:AAGEWAzaPjgUJ4TSG9_Or8SYlqsQWoyZOPc"
CHAT_ID = "947732542" 
SECRET_KEY = "super-secret-key"

# --- ACTIVATION STATE ---
activation_state = {
    "active": False,
    "one_time": True,
    "connected_ip": None,
    "active_hostname": None,   # имя компа которому разрешён стрим
}

# --- CHECKIN REGISTRY ---
# hostname -> {ip, last_seen, streaming}
checkin_registry = {}

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
                        
                        # Only accept commands from the OWNER
                        if user_chat_id != CHAT_ID:
                            continue

                        send_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

                        if text == "/start" or text == "/help":
                            print(f"[*] /start from owner", flush=True)
                            status = "🟢 АКТИВЕН" if activation_state["active"] else "🔴 СПИТ"
                            requests.post(send_url, json={
                                "chat_id": CHAT_ID,
                                "text": (
                                    f"👋 SEB Ghost Control Panel\n"
                                    f"Статус агента: {status}\n"
                                    f"Подключён IP: {activation_state['connected_ip'] or 'нет'}\n\n"
                                    f"/activate — разрешить запуск (одноразово)\n"
                                    f"/deactivate — принудительно остановить\n"
                                    f"/status — текущее состояние"
                                )
                            })

                        elif text == "/activate":
                            activation_state["active"] = True
                            activation_state["connected_ip"] = None
                            print(f"[*] ACTIVATED by owner!", flush=True)
                            requests.post(send_url, json={
                                "chat_id": CHAT_ID,
                                "text": "✅ Агент АКТИВИРОВАН!\nСледующий комп, который зайдёт — запустит стрим.\nОтправь /deactivate чтобы остановить."
                            })

                        elif text == "/deactivate":
                            activation_state["active"] = False
                            activation_state["connected_ip"] = None
                            print(f"[*] DEACTIVATED by owner!", flush=True)
                            requests.post(send_url, json={
                                "chat_id": CHAT_ID,
                                "text": "🔴 Агент остановлен. Все компы уснут в течение 5 секунд."
                            })

                        elif text == "/status":
                            status = "🟢 АКТИВЕН" if activation_state["active"] else "🔴 СПИТ"
                            requests.post(send_url, json={
                                "chat_id": CHAT_ID,
                                "text": f"Статус: {status}\nIP: {activation_state['connected_ip'] or 'нет'}"
                            })
        except Exception as e:
            print(f"[!] Polling error: {e}", flush=True)
        time.sleep(1)

@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/check_status", methods=["GET"])
def check_status():
    """Agents poll this endpoint every 5 seconds to see if they should activate."""
    if request.headers.get("X-Secret") != SECRET_KEY:
        return "Unauthorized", 401

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)

    if not activation_state["active"]:
        return jsonify({"run": False}), 200

    # If one_time mode: only the FIRST machine that asks gets the slot
    if activation_state["one_time"]:
        if activation_state["connected_ip"] is None:
            # First machine claiming the slot
            activation_state["connected_ip"] = client_ip
            print(f"[*] Slot claimed by {client_ip}", flush=True)
            # Notify owner
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": f"🖥️ Агент запущен на компе с IP: {client_ip}\nОтправь /deactivate когда экзамен закончится."}
            )
        if client_ip == activation_state["connected_ip"]:
            return jsonify({"run": True}), 200
        else:
            # Another machine asking — slot already taken
            return jsonify({"run": False}), 200

    return jsonify({"run": True}), 200

@app.route("/identify", methods=["POST"])
def identify():
    """
    Agent calls this when the secret hotkey is pressed inside SEB.
    Server marks this machine as active and notifies owner via Telegram.
    """
    if request.headers.get("X-Secret") != SECRET_KEY:
        return "Unauthorized", 401

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    machine   = request.json.get("machine", "unknown") if request.is_json else "unknown"

    # Mark as active (allow streaming)
    activation_state["active"] = True
    activation_state["connected_ip"] = client_ip

    print(f"[*] HOTKEY IDENTIFY from {client_ip} / {machine}", flush=True)

    # Notify owner
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": (
                    f"🔑 СЕКРЕТНАЯ КНОПКА НАЖАТА!\n"
                    f"🖥️ Комп: {machine}\n"
                    f"🌐 IP: {client_ip}\n"
                    f"✅ Стриминг АКТИВИРОВАН автоматически.\n"
                    f"Отправь /deactivate когда экзамен закончится."
                )
            },
            timeout=10
        )
    except Exception as e:
        print(f"[!] Telegram notify error: {e}", flush=True)

    return jsonify({"status": "identified", "streaming": True}), 200

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
            # We still send to Telegram for debugging/monitoring
            response = requests.post(url, data=payload, files=files, timeout=30)
            
        print(f"[*] Telegram API Response: {response.status_code} - {response.text}", flush=True)
        
        # --- AI INTEGRATION ---
        ai_response = {"action": "none"}
        OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
        if OPENAI_API_KEY:
            try:
                print("[*] Sending image to OpenAI API...", flush=True)
                import base64
                import json
                with open(temp_path, "rb") as image_file:
                    base64_image = base64.b64encode(image_file.read()).decode('utf-8')
                
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
                ai_payload = {
                    "model": "gpt-4o",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "You are a UI automation testing robot. Analyze the provided screenshot of a survey/quiz application. Read the main text prompt on the screen and evaluate the available options. Determine the most factually accurate option. You MUST respond with a JSON object containing three fields: 'reasoning' (a short explanation of why this option is factually accurate), 'click_x' and 'click_y' (the exact pixel coordinates of the center of the radio button/checkbox belonging to that specific option). Example: {\"reasoning\": \"The capital is Paris.\", \"click_x\": 500, \"click_y\": 300}. Output ONLY raw JSON, do not use formatting blocks or introductory text."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }],
                    "max_tokens": 200
                }
                ai_req = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=ai_payload, timeout=40)
                ai_res_json = ai_req.json()
                text_reply = ai_res_json['choices'][0]['message']['content'].strip()
                print(f"[*] OpenAI raw response: {text_reply}", flush=True)
                
                # Cleanup markdown formatting
                if text_reply.startswith("```json"): text_reply = text_reply[7:]
                if text_reply.startswith("```"): text_reply = text_reply[3:]
                if text_reply.endswith("```"): text_reply = text_reply[:-3]
                
                parsed = json.loads(text_reply.strip())
                reasoning = parsed.get("reasoning", "No reasoning provided")
                
                if "click_x" in parsed and "click_y" in parsed:
                    ai_response = {"action": "click", "x": parsed["click_x"], "y": parsed["click_y"]}
                    
                # SEND LOG TO TELEGRAM
                try:
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                        "chat_id": CHAT_ID,
                        "text": f"🤖 **Логи ИИ:**\n💭 Мысли: {reasoning}\n📍 Координаты клика: X={parsed.get('click_x')}, Y={parsed.get('click_y')}"
                    }, timeout=10)
                except Exception as tg_e:
                    print(f"[*] Failed to send AI log to telegram: {tg_e}", flush=True)

            except Exception as ai_e:
                print(f"[!] OpenAI processing error: {ai_e}", flush=True)
                try:
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                        "chat_id": CHAT_ID,
                        "text": f"❌ Ошибка вызова ИИ: {str(ai_e)}"
                    }, timeout=10)
                except:
                    pass

        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        # Return AI commands to the C++ agent
        return jsonify(ai_response), 200
            
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
