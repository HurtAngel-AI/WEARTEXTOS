import uuid
from datetime import datetime
from typing import Dict, List, Set
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, JSONResponse

app = FastAPI(title="Watch DM Engine")

# ----------------------------------------------------
# IN-MEMORY DATABASE (RAM)
# ----------------------------------------------------
class InMemoryStore:
    def __init__(self):
        # Mesajlar: [{id, sender, receiver, text, timestamp}]
        self.messages: List[Dict] = []
        # Cihazlar: { device_id: { nickname: str, last_seen: str, ip: str } }
        self.devices: Dict[str, Dict] = {}
        self.banned_devices: Set[str] = set()
        self.system_logs: List[str] = []

    def log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.system_logs.append(f"[{timestamp}] {message}")

db = InMemoryStore()

# ----------------------------------------------------
# GÖMÜLÜ TEK PARÇA ARAYÜZ (HTML + CSS + JS)
# ----------------------------------------------------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Watch DM Engine</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, sans-serif; }
    body { background: #090a0f; color: #e2e8f0; height: 100dvh; display: flex; justify-content: center; align-items: center; }
    
    .app { width: 100%; max-width: 420px; height: 100dvh; background: #12121a; display: flex; flex-direction: column; position: relative; }
    
    .header { padding: 12px; background: #000; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #222; }
    .header h3 { font-size: 0.9rem; color: #a29bfe; }
    
    .user-bar { display: flex; gap: 8px; padding: 10px; background: #1a1a24; overflow-x: auto; border-bottom: 1px solid #222; }
    .user-chip { padding: 6px 12px; background: #252538; border-radius: 12px; font-size: 0.75rem; cursor: pointer; white-space: nowrap; border: 1px solid transparent; }
    .user-chip.active { background: #6c5ce7; color: white; border-color: #a29bfe; }
    
    .chat-area { flex: 1; padding: 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
    
    .msg { max-width: 80%; padding: 8px 12px; border-radius: 12px; font-size: 0.85rem; line-height: 1.3; }
    .msg.in { background: #252538; align-self: flex-start; }
    .msg.out { background: #6c5ce7; align-self: flex-end; }
    .msg .time { font-size: 0.6rem; opacity: 0.5; text-align: right; margin-top: 3px; }
    
    .input-box { padding: 10px; background: #000; display: flex; gap: 8px; }
    .input-box input { flex: 1; padding: 10px; border-radius: 8px; border: 1px solid #333; background: #111; color: white; outline: none; }
    .input-box button { padding: 10px 16px; border-radius: 8px; border: none; background: #6c5ce7; color: white; font-weight: bold; cursor: pointer; }
    
    .ban-overlay { position: absolute; inset: 0; background: #000; color: #ff7675; display: none; flex-direction: column; justify-content: center; align-items: center; text-align: center; p: 20px; z-index: 99; }
    
    .admin-modal { position: absolute; inset: 0; background: rgba(0,0,0,0.95); display: none; flex-direction: column; padding: 15px; z-index: 50; }
    .admin-modal h4 { margin-bottom: 10px; }
    .dev-item { display: flex; justify-content: space-between; padding: 8px; background: #222; margin-bottom: 5px; border-radius: 6px; font-size: 0.75rem; }
  </style>
</head>
<body>

<div class="app">
  <div class="header">
    <h3 id="myTitle">Giriş yapılıyor...</h3>
    <button style="background:#333; color:white; border:none; padding:4px 8px; border-radius:6px; cursor:pointer;" onclick="openAdmin()">Admin</button>
  </div>

  <!-- DM Kişi Seçme Alanı -->
  <div class="user-bar" id="userBar">
    <div class="user-chip active" onclick="selectUser('GLOBAL')">🌐 Genel</div>
  </div>

  <!-- Mesaj Alanı -->
  <div class="chat-area" id="chatArea"></div>

  <!-- Yazma Kutusu -->
  <div class="input-box">
    <input type="text" id="msgInput" placeholder="Mesaj yaz..." onkeypress="if(event.key==='Enter') sendMsg()">
    <button onclick="sendMsg()">Gönder</button>
  </div>

  <!-- Ban Ekranı -->
  <div class="ban-overlay" id="banOverlay">
    <h2>🚫 BANLANDINIZ</h2>
    <p style="margin-top:10px; color:#aaa;">Cihazınız yönetici tarafından engellendi.</p>
  </div>

  <!-- Admin Modalı -->
  <div class="admin-modal" id="adminModal">
    <div style="display:flex; justify-size:space-between; justify-content:space-between; align-items:center; margin-bottom:10px;">
      <h4>Admin Paneli</h4>
      <button onclick="document.getElementById('adminModal').style.display='none'" style="background:none; color:white; border:none; cursor:pointer;">✕</button>
    </div>
    <div id="adminDevList" style="flex:1; overflow-y:auto;"></div>
    <div style="display:flex; gap:5px; margin-top:10px;">
      <button style="flex:1; padding:8px; background:#00b894; color:white; border:none; border-radius:6px;" onclick="downloadLog('txt')">TXT Log</button>
      <button style="flex:1; padding:8px; background:#0984e3; color:white; border:none; border-radius:6px;" onclick="downloadLog('json')">JSON Log</button>
    </div>
  </div>
</div>

<script>
  let myDevId = localStorage.getItem("dev_id") || "DEV-" + Math.random().toString(36).substring(2, 9);
  localStorage.setItem("dev_id", myDevId);

  let activeTarget = "GLOBAL"; // Standart Genel Sohbet
  let adminPass = "";

  async function apiCall(url, method="GET", body=null) {
    const headers = { "Content-Type": "application/json", "X-Device-Id": myDevId };
    const opts = { method, headers };
    if(body) opts.body = JSON.stringify(body);
    const res = await fetch(url, opts);
    if(res.status === 403) {
      document.getElementById("banOverlay").style.display = "flex";
      throw new Error("Banned");
    }
    return res.json();
  }

  // 1. Sayfa Açılışı ve Döngü
  async function init() {
    try {
      const data = await apiCall("/api/init");
      document.getElementById("myTitle").innerText = "Ben: " + data.nickname;
      
      // Her 1.5 saniyede bir verileri çek (Garanti Çalışan Polling)
      setInterval(fetchData, 1500);
      fetchData();
    } catch(e) {}
  }

  // 2. Mesajları ve Kullanıcıları Çek
  async function fetchData() {
    try {
      const data = await apiCall("/api/sync?target=" + activeTarget);
      
      // Kullanıcı Listesini Güncelle
      const uBar = document.getElementById("userBar");
      let html = `<div class="user-chip ${activeTarget==='GLOBAL'?'active':''}" onclick="selectUser('GLOBAL')">🌐 Genel</div>`;
      
      data.users.forEach(u => {
        if(u.id !== myDevId) {
          html += `<div class="user-chip ${activeTarget===u.id?'active':''}" onclick="selectUser('${u.id}')">💬 ${u.nickname}</div>`;
        }
      });
      uBar.innerHTML = html;

      // Mesajları Bas
      const cArea = document.getElementById("chatArea");
      cArea.innerHTML = "";
      data.messages.forEach(m => {
        const isMe = m.sender === myDevId;
        const div = document.createElement("div");
        div.className = `msg ${isMe ? 'out' : 'in'}`;
        div.innerHTML = `<div>${escapeHtml(m.text)}</div><div class="time">${m.timestamp}</div>`;
        cArea.appendChild(div);
      });
      cArea.scrollTop = cArea.scrollHeight;

    } catch(e) {}
  }

  function selectUser(targetId) {
    activeTarget = targetId;
    fetchData();
  }

  // 3. Mesaj Gönder
  async function sendMsg() {
    const inp = document.getElementById("msgInput");
    const txt = inp.value.trim();
    if(!txt) return;

    inp.value = "";
    await apiCall("/api/send", "POST", { target: activeTarget, text: txt });
    fetchData();
  }

  // 4. Admin İşlemleri
  async function openAdmin() {
    const pwd = prompt("Admin Şifresi:");
    if(!pwd) return;
    
    try {
      const data = await fetch(`/api/admin/devices?auth=${pwd}`).then(r => r.json());
      adminPass = pwd;
      document.getElementById("adminModal").style.display = "flex";
      
      const list = document.getElementById("adminDevList");
      list.innerHTML = "";
      data.devices.forEach(d => {
        list.innerHTML += `
          <div class="dev-item">
            <div><b>${d.nickname}</b> (${d.ip})</div>
            ${d.banned ? '<span style="color:red">BANLI</span>' : `<button onclick="ban('${d.id}')" style="background:red; color:white; border:none; padding:2px 6px; border-radius:4px; cursor:pointer;">BANLA</button>`}
          </div>
        `;
      });
    } catch(e) { alert("Hatalı Şifre!"); }
  }

  async function ban(id) {
    await fetch("/api/admin/ban", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ password: adminPass, targetId: id })
    });
    openAdmin();
  }

  function downloadLog(type) {
    window.open(`/api/admin/logs/${type}?password=${adminPass}`, '_blank');
  }

  function escapeHtml(t) { return t.replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

  window.onload = init;
</script>
</body>
</html>
"""

# ----------------------------------------------------
# API ENDPOINTS
# ----------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTML_CONTENT

@app.get("/api/init")
async def init_device(request: Request):
    dev_id = request.headers.get("X-Device-Id", "DEV-UNKNOWN")
    client_ip = request.client.host if request.client else "127.0.0.1"

    if dev_id in db.banned_devices:
        raise HTTPException(status_code=403, detail="Banned")

    if dev_id not in db.devices:
        db.devices[dev_id] = {
            "nickname": f"User_{dev_id[-4:]}",
            "last_seen": datetime.now().strftime("%H:%M:%S"),
            "ip": client_ip
        }
        db.log(f"Yeni cihaz kaydoldu: {dev_id} ({db.devices[dev_id]['nickname']})")

    return {"nickname": db.devices[dev_id]["nickname"]}

@app.get("/api/sync")
async def sync_data(request: Request, target: str = "GLOBAL"):
    dev_id = request.headers.get("X-Device-Id")
    if dev_id in db.banned_devices:
        raise HTTPException(status_code=403, detail="Banned")

    # Son görülmeyi güncelle
    if dev_id in db.devices:
        db.devices[dev_id]["last_seen"] = datetime.now().strftime("%H:%M:%S")

    # Aktif Kullanıcı Listesi
    users = [{"id": k, "nickname": v["nickname"]} for k, v in db.devices.items()]

    # Mesajları Filtrele (GLOBAL ya da Özel DM)
    filtered_msgs = []
    for m in db.messages:
        if target == "GLOBAL" and m["receiver"] == "GLOBAL":
            filtered_msgs.append(m)
        elif target != "GLOBAL":
            # Birebir DM Filtresi: Gönderen/Alıcı eşleşmesi
            if (m["sender"] == dev_id and m["receiver"] == target) or (m["sender"] == target and m["receiver"] == dev_id):
                filtered_msgs.append(m)

    return {"users": users, "messages": filtered_msgs}

@app.post("/api/send")
async def send_message(request: Request, payload: dict):
    dev_id = request.headers.get("X-Device-Id")
    if dev_id in db.banned_devices:
        raise HTTPException(status_code=403, detail="Banned")

    text = payload.get("text", "").strip()
    target = payload.get("target", "GLOBAL")

    if text:
        msg = {
            "id": str(uuid.uuid4()),
            "sender": dev_id,
            "receiver": target,
            "text": text,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        db.messages.append(msg)
        db.log(f"MESAJ [{dev_id} -> {target}]: {text}")

    return {"status": "ok"}

# ----------------------------------------------------
# ADMIN ENDPOINTS
# ----------------------------------------------------

@app.get("/api/admin/devices")
async def get_admin_devices(auth: str):
    if auth != "456456456":
        raise HTTPException(status_code=403, detail="Yetkisiz")
    
    devs = []
    for k, v in db.devices.items():
        devs.append({
            "id": k,
            "nickname": v["nickname"],
            "ip": v["ip"],
            "banned": k in db.banned_devices
        })
    return {"devices": devs}

@app.post("/api/admin/ban")
async def ban_device(payload: dict):
    if payload.get("password") != "456456456":
        raise HTTPException(status_code=403, detail="Yetkisiz")
    
    target_id = payload.get("targetId")
    if target_id:
        db.banned_devices.add(target_id)
        db.log(f"ADMIN BAN: {target_id}")
        return {"status": "ok"}

@app.get("/api/admin/logs/txt", response_class=PlainTextResponse)
async def get_txt_logs(password: str):
    if password != "456456456":
        raise HTTPException(status_code=403, detail="Yetkisiz")
    return "\n".join(db.system_logs)

@app.get("/api/admin/logs/json")
async def get_json_logs(password: str):
    if password != "456456456":
        raise HTTPException(status_code=403, detail="Yetkisiz")
    return {
        "logs": db.system_logs,
        "messages": db.messages,
        "devices": db.devices,
        "banned": list(db.banned_devices)
    }
