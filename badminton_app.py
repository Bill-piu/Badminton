# -*- coding: utf-8 -*-
"""
APP XẾP CẶP CẦU LÔNG
---------------------
Chạy bằng lệnh:
    pip install streamlit pandas
    streamlit run badminton_app.py

Tính năng:
- Mỗi lần thêm người chơi, app TỰ ĐỘNG xếp người đó vào sân đang ít người
  nhất trong số các sân đang mở hôm đó (không cần chọn sân tay). Có nút
  "Phân bổ lại toàn bộ" để cân lại nếu cần.
- Mỗi sân tối đa 8 người, tự ghép 4 người thành 2 đội (2 vs 2) sao cho tổng
  điểm trình hai đội càng gần nhau càng tốt (không quan tâm giới tính).
- Ưu tiên chọn người vào sân theo thứ tự: (1) ai đã đấu ÍT trận nhất,
  (2) nếu bằng nhau thì ai đã NGHỈ liên tục nhiều vòng nhất được ưu tiên
  vào sân trước -> không ai phải chờ quá lâu.
- Hạn chế lặp lại 1 cặp đồng đội quá N lần (chỉnh được, mặc định 3).
- Có thể sửa điểm trình bất cứ lúc nào ngay trong bảng -> trận hiện tại
  (chưa đấu) sẽ tự cân bằng lại theo điểm mới.
- Ước tính mục tiêu số trận mỗi người nên đánh, dựa trên tổng thời gian
  chơi và thời gian trung bình 1 trận, để bạn theo dõi xem có ai bị
  thiệt trận hay không. Người vào trễ tự nhiên sẽ đánh ít trận hơn vì có
  ít thời gian còn lại, đó là bình thường và không cần can thiệp thêm.
- Lưu lịch sử các trận đã đấu + thống kê số trận / số vòng đã chờ.
"""

from itertools import combinations
import pandas as pd
import streamlit as st

MAX_PER_COURT = 8

st.set_page_config(page_title="Xếp cặp cầu lông", layout="wide")

# =========================================================
#                   KHỞI TẠO SESSION STATE
# =========================================================
def init_state():
    ss = st.session_state
    ss.setdefault("players", {})          # id -> {name, gender, skill, court}
    ss.setdefault("next_id", 1)
    ss.setdefault("num_courts", 2)
    ss.setdefault("max_repeat", 3)         # số lần tối đa 1 cặp được đánh chung
    ss.setdefault("games_played", {})      # id -> số trận đã đấu
    ss.setdefault("rounds_resting", {})    # id -> số vòng đã nghỉ LIÊN TIẾP
    ss.setdefault("partner_count", {})     # frozenset({id1,id2}) -> số lần đã là đồng đội
    ss.setdefault("current_match", {})     # court -> {team1, team2, resting, round}
    ss.setdefault("history", [])           # list các trận đã kết thúc
    ss.setdefault("session_minutes", 120)
    ss.setdefault("avg_match_minutes", 10)


init_state()


# =========================================================
#                        HÀM TIỆN ÍCH
# =========================================================
def get_pool(court):
    """Danh sách id người chơi đang được gán vào 1 sân."""
    return [pid for pid, p in st.session_state.players.items() if p["court"] == court]


def name_of(pid):
    p = st.session_state.players.get(pid)
    if not p:
        return "?"
    return f'{p["name"]} ({p["skill"]}đ)'


def best_court_for_new_player():
    """Tìm sân đang ít người nhất (và chưa đầy) để xếp người mới vào."""
    n = st.session_state.num_courts
    counts = {c: len(get_pool(c)) for c in range(1, n + 1)}
    candidates = [c for c, cnt in counts.items() if cnt < MAX_PER_COURT]
    if not candidates:
        return None
    return min(candidates, key=lambda c: (counts[c], c))


def redistribute_all_courts():
    """Xếp lại TOÀN BỘ người chơi vào các sân cho đều số lượng, đồng thời
    trộn đều trình (người trình cao/thấp xen kẽ các sân) bằng cách sắp xếp
    theo trình rồi chia vòng tròn qua từng sân."""
    n = st.session_state.num_courts
    pids = sorted(
        st.session_state.players.keys(),
        key=lambda pid: -st.session_state.players[pid]["skill"],
    )
    for idx, pid in enumerate(pids):
        st.session_state.players[pid]["court"] = (idx % n) + 1
    for c in range(1, n + 1):
        st.session_state.current_match[c] = None
        generate_match(c)


PENALTY_OVER_CAP = 5      # phạt nặng mỗi lần VƯỢT quá giới hạn lặp cặp
PENALTY_PER_REPEAT = 0.3   # phạt nhẹ để vẫn ưu tiên cặp mới khi các lựa chọn ngang nhau
LOOKAHEAD_WEIGHT = 0.7     # trọng số của vòng kế tiếp khi tính trước


def split_score(a, b, players, partner_count, max_repeat):
    """Điểm cho 1 cách chia đội (a, b là 2 tuple 2 người). Điểm càng THẤP
    càng tốt: ưu tiên số 1 là cân bằng trình, lặp cặp chỉ bị phạt điểm chứ
    không bị cấm tuyệt đối."""
    skill_a = sum(players[x]["skill"] for x in a)
    skill_b = sum(players[x]["skill"] for x in b)
    diff = abs(skill_a - skill_b)
    rep_a = partner_count.get(frozenset(a), 0)
    rep_b = partner_count.get(frozenset(b), 0)
    overflow_a = max(0, rep_a - max_repeat + 1)
    overflow_b = max(0, rep_b - max_repeat + 1)
    return diff + PENALTY_OVER_CAP * (overflow_a + overflow_b) + PENALTY_PER_REPEAT * (rep_a + rep_b)


def eligible_group(pool, games_played):
    """Nhóm người được PHÉP xét để đánh vòng tới: bắt đầu từ những ai có số
    trận ÍT NHẤT, gộp thêm từng mức kế tiếp (nguyên cả nhóm hoà hạng, không
    cắt nửa chừng) cho tới khi đủ ít nhất 4 người để có chỗ chọn lựa."""
    if not pool:
        return []
    levels = sorted(set(games_played.get(p, 0) for p in pool))
    eligible = []
    for lvl in levels:
        eligible.extend([p for p in pool if games_played.get(p, 0) == lvl])
        if len(eligible) >= 4:
            break
    return eligible


def candidate_matches(pool, players, games_played, partner_count, max_repeat, top_k=None):
    """Duyệt MỌI cách chọn 4 người trong nhóm hoà hạng + mọi cách chia đội,
    trả về danh sách (điểm, quartet, (team1, team2), resting) đã sắp xếp
    từ tốt nhất tới tệ nhất."""
    eligible = eligible_group(pool, games_played)
    if len(eligible) < 4:
        return []
    results = []
    for quartet in combinations(eligible, 4):
        p1, p2, p3, p4 = quartet
        for a, b in (((p1, p2), (p3, p4)), ((p1, p3), (p2, p4)), ((p1, p4), (p2, p3))):
            score = split_score(a, b, players, partner_count, max_repeat)
            resting = [p for p in pool if p not in quartet]
            results.append((score, quartet, (a, b), resting))
    results.sort(key=lambda t: t[0])
    return results[:top_k] if top_k else results


def choose_match(pool, players, games_played, rounds_resting, partner_count, max_repeat):
    """Chọn trận cho vòng tới, có TÍNH TRƯỚC 1 vòng kế tiếp: lấy vài phương
    án tốt nhất của vòng này, mô phỏng áp dụng mỗi phương án rồi xem vòng
    SAU đó sẽ cân bằng tới đâu, cộng điểm 2 vòng lại, chọn phương án có
    tổng điểm thấp nhất. Nhờ vậy tránh được tình trạng "vòng này đẹp nhưng
    vòng sau bị kẹt lệch trình"."""
    top_candidates = candidate_matches(pool, players, games_played, partner_count, max_repeat, top_k=6)
    if not top_candidates:
        return None

    if len(pool) <= 4:
        # Chỉ có 1 nhóm cố định, tính trước cũng không có gì để chọn thêm
        best = top_candidates[0]
        return best[1], best[2], best[3]

    best_total = None
    best_choice = None
    for score, quartet, split, resting in top_candidates:
        a, b = split
        sim_games = dict(games_played)
        sim_rest = dict(rounds_resting)
        sim_partner = dict(partner_count)
        for pid in quartet:
            sim_games[pid] = sim_games.get(pid, 0) + 1
            sim_rest[pid] = 0
        for pid in resting:
            sim_rest[pid] = sim_rest.get(pid, 0) + 1
        k1, k2 = frozenset(a), frozenset(b)
        sim_partner[k1] = sim_partner.get(k1, 0) + 1
        sim_partner[k2] = sim_partner.get(k2, 0) + 1

        next_best = candidate_matches(pool, players, sim_games, sim_partner, max_repeat, top_k=1)
        next_score = next_best[0][0] if next_best else 0
        total = score + LOOKAHEAD_WEIGHT * next_score
        if best_total is None or total < best_total:
            best_total = total
            best_choice = (quartet, split, resting)
    return best_choice


def generate_match(court):
    """Tạo trận mới cho 1 sân (chọn người + chia đội, có tính trước 1 vòng)."""
    pool = get_pool(court)
    if len(pool) < 4:
        st.session_state.current_match[court] = None
        return
    result = choose_match(
        pool,
        st.session_state.players,
        st.session_state.games_played,
        st.session_state.rounds_resting,
        st.session_state.partner_count,
        st.session_state.max_repeat,
    )
    if result is None:
        st.session_state.current_match[court] = None
        return
    quartet, (team1, team2), resting = result
    prev = st.session_state.current_match.get(court)
    prev_round = prev["round"] if prev else 0
    st.session_state.current_match[court] = {
        "team1": list(team1),
        "team2": list(team2),
        "resting": resting,
        "round": prev_round + 1,
    }


def rebalance_current(court):
    """Giữ nguyên 4 người đang được xếp ở trận hiện tại, nhưng tính lại
    cách chia đội cho cân bằng (dùng khi vừa sửa điểm trình)."""
    match = st.session_state.current_match.get(court)
    if not match:
        return
    p1, p2, p3, p4 = match["team1"] + match["team2"]
    players = st.session_state.players
    pc = st.session_state.partner_count
    max_repeat = st.session_state.max_repeat
    best_score, best_split_choice = None, None
    for a, b in (((p1, p2), (p3, p4)), ((p1, p3), (p2, p4)), ((p1, p4), (p2, p3))):
        score = split_score(a, b, players, pc, max_repeat)
        if best_score is None or score < best_score:
            best_score, best_split_choice = score, (a, b)
    match["team1"], match["team2"] = list(best_split_choice[0]), list(best_split_choice[1])


def confirm_and_next(court):
    """Chốt trận hiện tại là đã đấu xong, cập nhật thống kê (số trận,
    reset bộ đếm chờ cho người vừa đấu, tăng bộ đếm chờ cho người nghỉ),
    rồi tạo trận kế tiếp."""
    match = st.session_state.current_match.get(court)
    if not match:
        return
    gp = st.session_state.games_played
    rw = st.session_state.rounds_resting
    for pid in match["team1"] + match["team2"]:
        gp[pid] = gp.get(pid, 0) + 1
        rw[pid] = 0
    for pid in match["resting"]:
        rw[pid] = rw.get(pid, 0) + 1

    pc = st.session_state.partner_count
    k1, k2 = frozenset(match["team1"]), frozenset(match["team2"])
    pc[k1] = pc.get(k1, 0) + 1
    pc[k2] = pc.get(k2, 0) + 1
    st.session_state.history.append(
        {
            "Sân": court,
            "Vòng": match["round"],
            "Đội 1": " & ".join(name_of(p) for p in match["team1"]),
            "Đội 2": " & ".join(name_of(p) for p in match["team2"]),
        }
    )
    generate_match(court)


# =========================================================
#                        SIDEBAR
# =========================================================
with st.sidebar:
    st.header("⚙️ Cài đặt")
    new_num_courts = st.slider("Số sân đang mở hôm nay", 1, 4, st.session_state.num_courts)
    if new_num_courts != st.session_state.num_courts:
        st.session_state.num_courts = new_num_courts
        st.info("Số sân vừa đổi — bấm 'Phân bổ lại toàn bộ' bên dưới để cân lại người.")

    st.session_state.max_repeat = st.slider(
        "Số lần tối đa 1 cặp được đánh chung", 1, 5, st.session_state.max_repeat,
        help="Đây là mức ƯU TIÊN, không phải luật cấm tuyệt đối: nếu cân bằng trình "
        "tốt hơn hẳn thì app vẫn có thể lặp cặp thêm 1 lần.",
    )
    st.caption(f"Mỗi sân tối đa {MAX_PER_COURT} người.")

    st.divider()
    st.subheader("⏱️ Ước tính số trận mỗi người")
    st.session_state.session_minutes = st.number_input(
        "Tổng thời gian chơi (phút)", min_value=30, max_value=300,
        value=st.session_state.session_minutes, step=10,
    )
    st.session_state.avg_match_minutes = st.number_input(
        "Thời gian trung bình 1 trận (phút)", min_value=3, max_value=30,
        value=st.session_state.avg_match_minutes, step=1,
    )
    total_players = len(st.session_state.players)
    if total_players > 0:
        total_slots = (st.session_state.session_minutes // st.session_state.avg_match_minutes) * st.session_state.num_courts
        target = (total_slots * 4) / total_players
        st.metric("Mục tiêu ~ mỗi người đánh", f"{target:.1f} trận")

    st.divider()
    if st.button("🔀 Phân bổ lại toàn bộ vào các sân cho đều", type="primary"):
        if st.session_state.players:
            redistribute_all_courts()
            st.rerun()
    if st.button("🔄 Làm mới toàn bộ dữ liệu"):
        st.session_state.clear()
        st.rerun()

st.title("🏸 Xếp cặp cầu lông")
st.caption(
    "Thêm người chơi — app tự xếp vào sân đang ít người nhất. Nhập điểm trình (0-10), "
    "app tự ghép đội 2 vs 2 cân bằng trình nhất có thể và không để ai chờ quá lâu."
)

# =========================================================
#                 THÊM / XOÁ NGƯỜI CHƠI
# =========================================================
with st.expander("➕ Thêm người chơi mới", expanded=True):
    with st.form("add_player_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Tên")
        gender = c2.selectbox("Giới tính", ["Nam", "Nữ"])
        skill = c3.slider("Trình (0-10)", 0, 10, 5)
        submitted = st.form_submit_button("Thêm vào danh sách (tự xếp sân)")
        if submitted:
            if not name.strip():
                st.warning("Vui lòng nhập tên.")
            else:
                court = best_court_for_new_player()
                if court is None:
                    st.warning(
                        "Tất cả các sân đã đủ người. Hãy mở thêm sân (bên sidebar) hoặc xoá bớt người."
                    )
                else:
                    pid = st.session_state.next_id
                    st.session_state.next_id += 1
                    st.session_state.players[pid] = {
                        "name": name.strip(),
                        "gender": gender,
                        "skill": skill,
                        "court": court,
                    }
                    st.session_state.games_played[pid] = 0
                    st.session_state.rounds_resting[pid] = 0
                    st.toast(f"Đã thêm {name.strip()} vào Sân {court}", icon="✅")
                    st.rerun()

if st.session_state.players:
    rm_c1, rm_c2 = st.columns([3, 1])
    options = {f'{p["name"]} - Sân {p["court"]}': pid for pid, p in st.session_state.players.items()}
    sel = rm_c1.selectbox("Chọn người để xoá khỏi danh sách", list(options.keys()))
    if rm_c2.button("🗑️ Xoá người này"):
        pid = options[sel]
        st.session_state.players.pop(pid, None)
        st.session_state.games_played.pop(pid, None)
        st.session_state.rounds_resting.pop(pid, None)
        st.session_state.partner_count = {
            k: v for k, v in st.session_state.partner_count.items() if pid not in k
        }
        for c in range(1, st.session_state.num_courts + 1):
            cm = st.session_state.current_match.get(c)
            if cm and pid in (cm["team1"] + cm["team2"] + cm["resting"]):
                generate_match(c)
        st.rerun()

# =========================================================
#              BẢNG DANH SÁCH NGƯỜI CHƠI (SỬA ĐƯỢC)
# =========================================================
st.subheader("📋 Danh sách người chơi")

if not st.session_state.players:
    st.info("Chưa có người chơi nào. Hãy thêm người chơi ở trên.")
else:
    df = pd.DataFrame(
        [
            {
                "ID": pid,
                "Tên": p["name"],
                "Giới tính": p["gender"],
                "Trình (0-10)": p["skill"],
                "Sân": p["court"],
                "Số trận đã đấu": st.session_state.games_played.get(pid, 0),
                "Đang chờ (vòng)": st.session_state.rounds_resting.get(pid, 0),
            }
            for pid, p in st.session_state.players.items()
        ]
    ).sort_values(["Sân", "ID"])

    edited = st.data_editor(
        df,
        column_config={
            "ID": st.column_config.NumberColumn(disabled=True),
            "Số trận đã đấu": st.column_config.NumberColumn(disabled=True),
            "Đang chờ (vòng)": st.column_config.NumberColumn(disabled=True),
            "Giới tính": st.column_config.SelectboxColumn(options=["Nam", "Nữ"]),
            "Trình (0-10)": st.column_config.NumberColumn(min_value=0, max_value=10, step=1),
            "Sân": st.column_config.SelectboxColumn(
                options=list(range(1, st.session_state.num_courts + 1)),
                help="Mặc định tự xếp theo người ít nhất, nhưng bạn có thể đổi tay ở đây.",
            ),
        },
        hide_index=True,
        use_container_width=True,
        key="player_editor",
    )

    changed = False
    for _, row in edited.iterrows():
        pid = int(row["ID"])
        p = st.session_state.players.get(pid)
        if p is None:
            continue
        new_skill = int(row["Trình (0-10)"])
        new_court = int(row["Sân"])
        new_gender = row["Giới tính"]
        new_name = str(row["Tên"])

        if new_court != p["court"] and len([x for x in get_pool(new_court) if x != pid]) >= MAX_PER_COURT:
            st.warning(f"Sân {new_court} đã đủ {MAX_PER_COURT} người, không thể chuyển {new_name}.")
            new_court = p["court"]

        if (p["skill"], p["court"], p["gender"], p["name"]) != (new_skill, new_court, new_gender, new_name):
            p["skill"], p["court"], p["gender"], p["name"] = new_skill, new_court, new_gender, new_name
            changed = True

    if changed:
        for c in range(1, st.session_state.num_courts + 1):
            rebalance_current(c)
        st.rerun()

st.divider()

# =========================================================
#                     CÁC SÂN & TRẬN ĐẤU
# =========================================================
st.subheader("🏸 Các sân đang mở")

cols = st.columns(st.session_state.num_courts)
for i in range(1, st.session_state.num_courts + 1):
    with cols[i - 1]:
        st.markdown(f"#### Sân {i}")
        pool = get_pool(i)
        st.caption(f"{len(pool)}/{MAX_PER_COURT} người ở sân này")

        if len(pool) < 4:
            st.info("Cần tối thiểu 4 người để xếp trận.")
            continue

        match = st.session_state.current_match.get(i)
        if not match:
            if st.button("🎲 Tạo trận đầu tiên", key=f"start_{i}"):
                generate_match(i)
                st.rerun()
            continue

        t1, t2 = match["team1"], match["team2"]
        skill1 = sum(st.session_state.players[p]["skill"] for p in t1)
        skill2 = sum(st.session_state.players[p]["skill"] for p in t2)

        st.markdown(f"**Vòng {match['round']}**")
        st.write(f"🔵 Đội 1: {', '.join(name_of(p) for p in t1)}")
        st.write(f"🔴 Đội 2: {', '.join(name_of(p) for p in t2)}")
        st.write(f"Tổng trình: {skill1} — {skill2} (chênh lệch {abs(skill1 - skill2)})")

        if abs(skill1 - skill2) <= 2:
            st.success("Cân bằng ✅")
        else:
            st.warning("Hơi lệch trình, nhưng đây là lựa chọn tốt nhất với 4 người hiện có.")

        if match["resting"]:
            resting_labels = [
                f'{name_of(p)} (chờ {st.session_state.rounds_resting.get(p, 0)} vòng)'
                for p in match["resting"]
            ]
            st.caption("😌 Nghỉ vòng này: " + ", ".join(resting_labels))

        bc1, bc2 = st.columns(2)
        if bc1.button("✅ Kết thúc & trận kế tiếp", key=f"next_{i}"):
            confirm_and_next(i)
            st.rerun()
        if bc2.button("♻️ Cân bằng lại", key=f"rebalance_{i}", help="Giữ nguyên 4 người, chỉ chia lại đội cho cân trình"):
            rebalance_current(i)
            st.rerun()

st.divider()

# =========================================================
#                   LỊCH SỬ & THỐNG KÊ
# =========================================================
with st.expander("📊 Lịch sử các trận đã đấu & thống kê số trận", expanded=False):
    if st.session_state.history:
        hist_df = pd.DataFrame(st.session_state.history)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Tải lịch sử (CSV)",
            hist_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="lich_su_dau.csv",
            mime="text/csv",
        )
    else:
        st.caption("Chưa có trận nào kết thúc.")

    if st.session_state.players:
        stat_df = pd.DataFrame(
            [
                {
                    "Tên": p["name"],
                    "Sân": p["court"],
                    "Số trận đã đấu": st.session_state.games_played.get(pid, 0),
                    "Đang chờ (vòng)": st.session_state.rounds_resting.get(pid, 0),
                }
                for pid, p in st.session_state.players.items()
            ]
        ).sort_values(["Sân", "Số trận đã đấu"])
        st.dataframe(stat_df, use_container_width=True, hide_index=True)