import uuid
from datetime import datetime
from typing import Dict, List, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Smartwatch Realtime Chat Engine")

# Static dosyaları bağla
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="static")

# ----------------------------------------------------
# IN-MEMORY DATABASE (Sadece RAM'de Tutulur)
# ----------------------------------------------------
class InMemoryStore:
    def __init__(self):
        # Mesajlar listesi: [{id, sender_deviceId, nickname, text, timestamp}]
        self.messages: List[Dict] = []
        # Cihazlar: { device_id: { nickname: str, joined_at: str } }
        self.devices: Dict[str, Dict] = {}
        # Banlanan cihaz ID'leri
        self.banned_devices: Set[str] = set()
        # Sistem ve mesaj logları (Admin için)
        self.system_logs: List[str] = []

    def log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.system_logs.append(entry)

db = InMemoryStore()

# ----------------------------------------------------
# WEBSOCKET MANAGER (Canlı Bağlantı Yönetimi)
# ----------------------------------------------------
class ConnectionManager:
    def __init__(self):
        # Active connections: device_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, device_id: str):
        await websocket.accept()
        self.active_connections[device_id] = websocket

    def disconnect(self, device_id: str):
        if device_id in self.active_connections:
            del self.active_connections[device_id]

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)

    async def kick_device(self, device_id: str):
        if device_id in self.active_connections:
            ws = self.active_connections[device_id]
            await ws.send_json({"type": "BANNED", "reason": "Cihazınız yönetici tarafından engellendi."})
            await ws.close()
            self.disconnect(device_id)

manager = ConnectionManager()

# ----------------------------------------------------
# ENDPOINTS
# ----------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/init")
async def init_device(request: Request):
    """Cihaz tarayıcıya girdiğinde durum kontrolü ve geçmiş mesajları döner."""
    client_ip = request.client.host
    device_id = request.headers.get("X-Device-Fingerprint")
    
    if not device_id:
        raise HTTPException(status_code=400, detail="Device Fingerprint eksik")

    if device_id in db.banned_devices:
        return JSONResponse({"banned": True, "reason": "Cihazınız sistemden yasaklanmıştır."}, status_code=403)

    if device_id not in db.devices:
        nickname = f"User_{device_id[:5]}"
        db.devices[device_id] = {
            "nickname": nickname,
            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ip": client_ip
        }
        db.log(f"Yeni cihaz kaydoldu: {device_id} ({nickname}) - IP: {client_ip}")

    # Sadece yasaklanmamış cihaz geçmiş mesajları alabilir
    return {
        "banned": False,
        "deviceId": device_id,
        "nickname": db.devices[device_id]["nickname"],
        "history": db.messages
    }

@app.post("/api/admin/auth")
async def admin_auth(payload: dict):
    password = payload.get("password")
    if password == "456456456":
        db.log("Başarılı Admin girişi yapıldı.")
        return {"success": True, "token": "admin-session-active"}
    db.log("Hatalı Admin giriş denemesi!")
    return JSONResponse({"success": False, "error": "Geçersiz Parola"}, status_code=401)

@app.get("/api/admin/devices")
async def get_admin_devices(auth: str = ""):
    if auth != "456456456":
        raise HTTPException(status_code=403, detail="Yetkisiz erişim")
    
    device_list = []
    for dev_id, info in db.devices.items():
        device_list.append({
            "deviceId": dev_id,
            "nickname": info["nickname"],
            "joinedAt": info["joined_at"],
            "ip": info["ip"],
            "isBanned": dev_id in db.banned_devices,
            "isOnline": dev_id in manager.active_connections
        })
    return {"devices": device_list}

@app.post("/api/admin/ban")
async def ban_device(payload: dict):
    if payload.get("password") != "456456456":
        raise HTTPException(status_code=403, detail="Yetkisiz işlem")
    
    target_id = payload.get("targetDeviceId")
    if target_id:
        db.banned_devices.add(target_id)
        db.log(f"ADMIN BAN: {target_id} cihazı yasaklandı.")
        await manager.kick_device(target_id)
        return {"success": True, "message": f"{target_id} başarıyla banlandı."}
    return {"success": False, "error": "Hedef ID bulunamadı."}

@app.get("/api/admin/logs/txt", response_class=PlainTextResponse)
async def download_logs_txt(password: str):
    if password != "456456456":
        raise HTTPException(status_code=403, detail="Yetkisiz işlem")
    return "\n".join(db.system_logs)

@app.get("/api/admin/logs/json")
async def download_logs_json(password: str):
    if password != "456456456":
        raise HTTPException(status_code=403, detail="Yetkisiz işlem")
    return {
        "logs": db.system_logs,
        "total_messages": len(db.messages),
        "messages": db.messages,
        "devices": db.devices,
        "banned_devices": list(db.banned_devices)
    }

# ----------------------------------------------------
# WEBSOCKET CHAT ENDPOINT
# ----------------------------------------------------
@app.websocket("/ws/chat/{device_id}")
async def websocket_chat(websocket: WebSocket, device_id: str):
    if device_id in db.banned_devices:
        await websocket.close(code=4003)
        return

    await manager.connect(websocket, device_id)
    db.log(f"WebSocket bağlantısı sağlandı: {device_id}")

    try:
        while True:
            data = await websocket.receive_json()
            
            # Canlı ban kontrolü
            if device_id in db.banned_devices:
                await manager.kick_device(device_id)
                break

            msg_text = data.get("text", "").strip()
            if msg_text:
                msg_payload = {
                    "id": str(uuid.uuid4()),
                    "deviceId": device_id,
                    "nickname": db.devices.get(device_id, {}).get("nickname", "Bilinmeyen"),
                    "text": msg_text,
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                }
                
                # RAM veritabanına kaydet (asla silinmez)
                db.messages.append(msg_payload)
                db.log(f"CHAT [{msg_payload['nickname']}]: {msg_text}")
                
                # Tüm bağlı istemcilere yayınla
                await manager.broadcast({"type": "NEW_MESSAGE", "data": msg_payload})

    except WebSocketDisconnect:
        manager.disconnect(device_id)
        db.log(f"WebSocket ayrıldı: {device_id}")
