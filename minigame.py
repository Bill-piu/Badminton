# -*- coding: utf-8 -*-
"""
MINI GAME CÀO THẺ TRÚNG THƯỞNG - Streamlit
===========================================
Cách chạy:
    pip install streamlit qrcode pillow
    streamlit run scratch_game.py

Cách dùng:
1. Người tổ chức (Host) mở app này trên máy tính/laptop (KHÔNG thêm tham số gì
   trên URL) -> thấy màn hình quản trị.
2. Host tạo 1 "trận" mới: nhập số người chơi tối đa và số người PHẢI trúng
   thưởng trong trận đó, nội dung khi trúng / không trúng.
3. App sẽ hiện mã QR. Người chơi dùng điện thoại quét QR -> nhập tên -> cào thẻ.
   QR có thể quét bao nhiêu lần cũng được (mỗi lượt quét/mở trình duyệt mới
   coi như 1 lượt chơi mới), nhưng khi đã đủ số người chơi tối đa thì sẽ
   không cho chơi thêm nữa.
4. Hệ thống đảm bảo tổng số người trúng thưởng trong trận = đúng số host nhập,
   với điều kiện trận chơi được lấp đầy đủ số người chơi tối đa. Nếu Host
   bấm "Đóng trận" sớm khi chưa đủ người, số người trúng thực tế có thể ít
   hơn số yêu cầu (vì chưa phát hết thẻ) - phần này sẽ được cảnh báo rõ.
5. Khi Host bấm "Đóng trận" -> trận đó kết thúc, không ai cào thẻ được nữa.

Lưu ý kỹ thuật:
- Dữ liệu được lưu vào 1 file JSON đơn giản (scratch_rounds.json) trên máy
  chạy app. Phù hợp cho 1 sự kiện chạy local / 1 tiến trình streamlit duy
  nhất. Không phù hợp để scale nhiều server cùng lúc.
- Để điện thoại người chơi quét QR truy cập được, máy host và điện thoại
  phải chung mạng wifi/LAN, và cần nhập đúng "Base URL" (địa chỉ IP LAN của
  máy host) ở phần cấu hình trong app.
"""

import streamlit as st
import streamlit.components.v1 as components
import json
import os
import socket
import random
import threading
import uuid
from datetime import datetime
from urllib.parse import urlencode

import qrcode
from io import BytesIO

# --------------------------------------------------------------------------
# CẤU HÌNH & LƯU TRỮ DỮ LIỆU (JSON file + lock để tránh ghi đè khi nhiều
# người cùng cào thẻ 1 lúc)
# --------------------------------------------------------------------------

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch_rounds.json")
_lock = threading.Lock()


def _load_data():
    if not os.path.exists(DATA_FILE):
        return {"rounds": {}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"rounds": {}}


def _save_data(data):
    tmp_path = DATA_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DATA_FILE)


def get_round(round_id):
    data = _load_data()
    return data["rounds"].get(round_id)


def list_rounds():
    data = _load_data()
    # Sắp xếp theo thời gian tạo, mới nhất trước
    items = list(data["rounds"].items())
    items.sort(key=lambda kv: kv[1].get("created_at", ""), reverse=True)
    return items


def create_round(max_players, must_win, win_text, lose_text, title):
    with _lock:
        data = _load_data()
        round_id = uuid.uuid4().hex[:8]
        deck = [True] * must_win + [False] * (max_players - must_win)
        random.shuffle(deck)
        data["rounds"][round_id] = {
            "id": round_id,
            "title": title or f"Trận {round_id}",
            "status": "open",  # open | closed
            "max_players": max_players,
            "must_win": must_win,
            "win_text": win_text,
            "lose_text": lose_text,
            "deck": deck,
            "players": {},  # token -> {name, is_win, time}
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        _save_data(data)
        return round_id


def close_round(round_id):
    with _lock:
        data = _load_data()
        if round_id in data["rounds"]:
            data["rounds"][round_id]["status"] = "closed"
            _save_data(data)


def reopen_round(round_id):
    with _lock:
        data = _load_data()
        if round_id in data["rounds"]:
            data["rounds"][round_id]["status"] = "open"
            _save_data(data)


def join_and_scratch(round_id, token, name):
    """
    Trả về dict: {"ok": True/False, "message": str, "is_win": bool (nếu ok),
                  "already_played": bool}
    """
    with _lock:
        data = _load_data()
        rnd = data["rounds"].get(round_id)
        if rnd is None:
            return {"ok": False, "message": "Trận không tồn tại."}

        # Nếu token này đã chơi rồi -> trả lại kết quả cũ, không cấp thẻ mới
        if token in rnd["players"]:
            p = rnd["players"][token]
            return {"ok": True, "is_win": p["is_win"], "already_played": True,
                     "name": p["name"], "message": "Bạn đã cào thẻ này rồi."}

        if rnd["status"] != "open":
            return {"ok": False, "message": "Trận đã kết thúc, không thể tham gia."}

        if len(rnd["players"]) >= rnd["max_players"]:
            return {"ok": False, "message": "Trận đã đủ số người chơi tối đa."}

        slot_index = len(rnd["players"])
        is_win = rnd["deck"][slot_index]
        rnd["players"][token] = {
            "name": name.strip() or "Người chơi ẩn danh",
            "is_win": is_win,
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        _save_data(data)
        return {"ok": True, "is_win": is_win, "already_played": False, "name": name}


def guess_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def make_qr_image(url: str):
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------
# GIAO DIỆN THẺ CÀO (HTML/JS canvas) - chỉ mang tính hiệu ứng, kết quả đã
# được xác định ở backend từ trước nên không thể gian lận qua giao diện.
# --------------------------------------------------------------------------

def render_scratch_card(result_text: str, is_win: bool, key: str):
    bg_color = "#ffd966" if is_win else "#e0e0e0"
    cover_text = "CÀO Ở ĐÂY 👆"
    safe_result = json.dumps(result_text)  # escape an toàn cho JS
    html = f"""
    <div style="display:flex; justify-content:center;">
      <div style="position:relative; width:320px; height:170px; border-radius:16px;
                  overflow:hidden; box-shadow:0 4px 14px rgba(0,0,0,0.25); margin:10px 0;">
        <div id="prize-{key}" style="position:absolute; inset:0; display:flex;
             align-items:center; justify-content:center; text-align:center;
             background:{bg_color}; font-family:sans-serif; font-weight:700;
             font-size:20px; padding:12px; color:#222;">
          {result_text}
        </div>
        <canvas id="canvas-{key}" width="320" height="170"
                style="position:absolute; inset:0; touch-action:none; cursor:pointer;"></canvas>
      </div>
    </div>
    <script>
      (function() {{
        const canvas = document.getElementById("canvas-{key}");
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#9e9e9e";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = "#616161";
        for (let i = 0; i < canvas.width; i += 14) {{
          ctx.fillRect(i, 0, 2, canvas.height);
        }}
        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 20px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("{cover_text}", canvas.width / 2, canvas.height / 2);

        let drawing = false;
        let erasedPixels = 0;
        const totalPixels = canvas.width * canvas.height;
        let revealed = false;

        function pos(e) {{
          const rect = canvas.getBoundingClientRect();
          const cx = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
          const cy = (e.touches ? e.touches[0].clientY : e.clientY) - rect.top;
          return [cx * canvas.width / rect.width, cy * canvas.height / rect.height];
        }}

        function scratch(x, y) {{
          ctx.globalCompositeOperation = "destination-out";
          ctx.beginPath();
          ctx.arc(x, y, 18, 0, Math.PI * 2);
          ctx.fill();
        }}

        function checkReveal() {{
          if (revealed) return;
          erasedPixels += 400;
          if (erasedPixels > totalPixels * 0.45) {{
            revealed = true;
            ctx.clearRect(0, 0, canvas.width, canvas.height);
          }}
        }}

        canvas.addEventListener("mousedown", (e) => {{ drawing = true; const [x,y]=pos(e); scratch(x,y); checkReveal(); }});
        canvas.addEventListener("mousemove", (e) => {{ if (drawing) {{ const [x,y]=pos(e); scratch(x,y); checkReveal(); }} }});
        window.addEventListener("mouseup", () => drawing = false);

        canvas.addEventListener("touchstart", (e) => {{ drawing = true; const [x,y]=pos(e); scratch(x,y); checkReveal(); e.preventDefault(); }}, {{passive:false}});
        canvas.addEventListener("touchmove", (e) => {{ if (drawing) {{ const [x,y]=pos(e); scratch(x,y); checkReveal(); }} e.preventDefault(); }}, {{passive:false}});
        canvas.addEventListener("touchend", () => drawing = false);
      }})();
    </script>
    """
    components.html(html, height=200)


# --------------------------------------------------------------------------
# GIAO DIỆN HOST (NGƯỜI TỔ CHỨC)
# --------------------------------------------------------------------------

def host_view():
    st.set_page_config(page_title="Host - Mini game cào thẻ", page_icon="🎟️", layout="centered")
    st.title("🎟️ Quản trị trận cào thẻ")

    with st.sidebar:
        st.header("⚙️ Cấu hình đường dẫn QR")
        default_ip = guess_local_ip()
        base_url = st.text_input(
            "Base URL (địa chỉ máy host để điện thoại quét vào)",
            value=f"http://{default_ip}:8501",
            help="Điện thoại người chơi và máy host phải chung mạng Wifi/LAN. "
                 "Nếu deploy lên server thật thì nhập domain/URL công khai tại đây.",
        )
        st.caption("Ví dụ: http://192.168.1.10:8501")

    st.subheader("➕ Tạo trận mới")
    with st.form("create_round_form"):
        title = st.text_input("Tên trận (tuỳ chọn)", placeholder="VD: Minigame sáng khai trương")
        col1, col2 = st.columns(2)
        with col1:
            max_players = st.number_input("Số người chơi tối đa", min_value=1, value=20, step=1)
        with col2:
            must_win = st.number_input("Số người BẮT BUỘC trúng thưởng", min_value=0, value=5, step=1)
        win_text = st.text_area("Nội dung hiển thị khi TRÚNG", value="🎉 CHÚC MỪNG BẠN ĐÃ TRÚNG THƯỞNG!")
        lose_text = st.text_area("Nội dung hiển thị khi KHÔNG trúng", value="😢 Chúc bạn may mắn lần sau!")
        submitted = st.form_submit_button("Tạo trận", type="primary")
        if submitted:
            if must_win > max_players:
                st.error("Số người bắt buộc trúng không được lớn hơn số người chơi tối đa.")
            else:
                rid = create_round(int(max_players), int(must_win), win_text, lose_text, title)
                st.session_state["active_round"] = rid
                st.success(f"Đã tạo trận mới, mã trận: {rid}")
                st.rerun()

    st.divider()
    st.subheader("📋 Danh sách các trận")
    rounds = list_rounds()
    if not rounds:
        st.info("Chưa có trận nào. Hãy tạo trận mới ở trên.")
        return

    options = {f"{v['title']}  ·  [{v['status'].upper()}]  ·  {k}": k for k, v in rounds}
    default_key = None
    if "active_round" in st.session_state:
        for label, rid in options.items():
            if rid == st.session_state["active_round"]:
                default_key = label
                break
    chosen_label = st.selectbox("Chọn trận để quản lý", list(options.keys()),
                                 index=list(options.keys()).index(default_key) if default_key else 0)
    round_id = options[chosen_label]
    rnd = get_round(round_id)

    st.markdown(f"### 🎯 {rnd['title']}  —  Mã trận: `{round_id}`")

    num_players = len(rnd["players"])
    num_winners = sum(1 for p in rnd["players"].values() if p["is_win"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Người chơi", f"{num_players} / {rnd['max_players']}")
    c2.metric("Đã trúng", f"{num_winners} / {rnd['must_win']}")
    c3.metric("Trạng thái", "🟢 ĐANG MỞ" if rnd["status"] == "open" else "🔴 ĐÃ ĐÓNG")

    if rnd["status"] == "open" and num_players < rnd["max_players"]:
        st.caption(
            f"⚠️ Chưa đủ {rnd['max_players']} người chơi. Nếu đóng trận bây giờ, "
            f"số người trúng có thể chưa đạt đủ {rnd['must_win']} người như yêu cầu."
        )

    if rnd["status"] == "open":
        player_url = f"{base_url}?{urlencode({'role': 'player', 'round': round_id})}"
        st.markdown("#### 📱 Mã QR cho người chơi quét")
        qr_bytes = make_qr_image(player_url)
        st.image(qr_bytes, caption=player_url, width=260)

        colA, colB = st.columns(2)
        with colA:
            if st.button("🔄 Làm mới"):
                st.rerun()
        with colB:
            if st.button("🔒 Đóng trận", type="primary"):
                close_round(round_id)
                st.rerun()
    else:
        st.info("Trận này đã đóng, không ai cào thẻ thêm được nữa.")
        if st.button("↩️ Mở lại trận (cẩn thận khi dùng)"):
            reopen_round(round_id)
            st.rerun()

    st.markdown("#### 👥 Danh sách người chơi")
    if rnd["players"]:
        rows = []
        for token, p in rnd["players"].items():
            rows.append({
                "Tên": p["name"],
                "Kết quả": "🎉 Trúng" if p["is_win"] else "Không trúng",
                "Thời gian": p["time"],
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("Chưa có ai chơi.")


# --------------------------------------------------------------------------
# GIAO DIỆN NGƯỜI CHƠI
# --------------------------------------------------------------------------

def player_view(round_id):
    st.set_page_config(page_title="Cào thẻ trúng thưởng", page_icon="🎁", layout="centered")
    st.title("🎁 Cào thẻ trúng thưởng")

    rnd = get_round(round_id)
    if rnd is None:
        st.error("Trận chơi không tồn tại hoặc đường dẫn không hợp lệ.")
        return

    # Token gắn với phiên trình duyệt hiện tại -> mỗi người chơi chỉ cào 1 lần
    # trên 1 lượt quét/mở trình duyệt. Quét lại QR ở trình duyệt/thiết bị khác
    # sẽ tạo token mới = 1 lượt chơi mới.
    if "player_token" not in st.session_state:
        st.session_state["player_token"] = uuid.uuid4().hex

    token = st.session_state["player_token"]

    # Nếu người này đã cào rồi -> hiện lại kết quả cũ, không cho cào nữa
    if token in rnd["players"]:
        p = rnd["players"][token]
        st.success(f"Xin chào {p['name']}, bạn đã cào thẻ trong trận này rồi.")
        result_text = rnd["win_text"] if p["is_win"] else rnd["lose_text"]
        render_scratch_card(result_text, p["is_win"], key="replay")
        return

    if rnd["status"] != "open":
        st.warning("Trận chơi này đã kết thúc. Hẹn bạn ở trận sau nhé!")
        return

    if len(rnd["players"]) >= rnd["max_players"]:
        st.warning("Rất tiếc, trận chơi đã đủ số người tham gia tối đa.")
        return

    st.write(f"Trận: **{rnd['title']}**")
    name = st.text_input("Nhập tên của bạn để tham gia", max_chars=40)

    if st.button("🖐️ Vào cào thẻ", type="primary", disabled=(name.strip() == "")):
        res = join_and_scratch(round_id, token, name)
        if not res["ok"]:
            st.error(res["message"])
        else:
            st.session_state["last_result"] = res
            st.rerun()

    if "last_result" in st.session_state and token in get_round(round_id)["players"]:
        res = st.session_state["last_result"]
        rnd2 = get_round(round_id)
        result_text = rnd2["win_text"] if res["is_win"] else rnd2["lose_text"]
        st.balloons() if res["is_win"] else None
        render_scratch_card(result_text, res["is_win"], key="new")


# --------------------------------------------------------------------------
# ĐIỀU HƯỚNG CHÍNH: dựa vào query params trên URL để quyết định hiển thị
# giao diện Host hay giao diện Người chơi
# --------------------------------------------------------------------------

def main():
    try:
        qp = st.query_params
    except Exception:
        qp = st.experimental_get_query_params()
        qp = {k: (v[0] if isinstance(v, list) else v) for k, v in qp.items()}

    role = qp.get("role", "host")
    round_id = qp.get("round", None)

    if role == "player" and round_id:
        player_view(round_id)
    else:
        host_view()


if __name__ == "__main__":
    main()