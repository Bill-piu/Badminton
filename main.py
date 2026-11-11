# -*- coding: utf-8 -*-
"""
APP XẾP CẶP CẦU LÔNG (bản dùng class Player, KHÔNG gán sân cố định)
---------------------------------------------------------------------
Chạy bằng lệnh:
    pip install streamlit pandas
    streamlit run badminton_app.py

So với bản trước: người chơi KHÔNG còn bị gán cứng vào 1 sân. Tất cả
người đang rảnh (status == "resting") nằm chung 1 HÀNG CHỜ DUY NHẤT.
Mỗi khi 1 sân trống (chưa có trận hoặc vừa đấu xong), app chọn 4 người
TỐT NHẤT từ hàng chờ chung đó để xếp vào sân ấy — người chơi có thể
"trộn qua lại" giữa các sân tuỳ theo trận nào cân bằng nhất, miễn đúng
thứ tự ưu tiên bên dưới.

Quy tắc xếp trận (áp dụng theo đúng thứ tự ưu tiên):
1. GIỚI HẠN CHỜ: không ai được "rảnh" (không chơi, không ở sân nào) liên
   tục quá 2 trận (waiting_set >= 2) — người này BẮT BUỘC phải được xếp
   vào trận kế tiếp, ở BẤT KỲ sân nào trống, ưu tiên tuyệt đối.
2. CÂN BẰNG TRÌNH + GIỚI TÍNH khi chọn 4 người và chia 2 đội:
   - Ưu tiên cao nhất: 4 nam hoặc 4 nữ (đội cùng giới gặp đội cùng giới).
   - Ưu tiên thứ hai: 2 nam + 2 nữ, ghép thành 2 đội hỗn hợp (mix) gặp nhau.
   - Rất hạn chế: 3-1 (vì sẽ sinh ra cặp đấu Nam-Nam với đội mix) — chỉ
     dùng khi không còn cách nào khác.
   - Trong mỗi kiểu, chọn cách chia đội để tổng điểm trình (đã quy đổi
     theo giới tính) của 2 đội lệch nhau ít nhất.
3. Mỗi nam chỉ đánh tối đa N trận đôi mix (mặc định 2 trận, chỉnh được).
4. Hạn chế lặp lại 1 cặp đồng đội quá N lần (chỉnh được).
5. TÍNH TRƯỚC 2 trận kế tiếp (trên toàn bộ hàng chờ chung) khi chọn trận
   hiện tại, để tránh trường hợp "trận này đẹp nhưng trận sau bị kẹt lệch
   trình / lệch giới".

Có thể sửa tên / giới tính / điểm trình ngay trong bảng; nếu người đó
đang thi đấu, trận hiện tại (chưa đấu xong) ở sân của họ sẽ tự chia lại
đội theo dữ liệu mới.
"""

from itertools import combinations
import pandas as pd
import streamlit as st

# =========================================================
#                        HẰNG SỐ
# =========================================================
MIN_COURTS = 2
MAX_COURTS = 7
MAX_CONSECUTIVE_REST = 2        # không ai được "rảnh" liên tục quá số trận này

MIN_SKILL = 1.0
MAX_SKILL = 12.0
SKILL_STEP = 0.5

PENALTY_GENDER_MISMATCH = 40    # phạt RẤT nặng: đôi Nam-Nam đấu với đôi mix
PENALTY_CROSS_CATEGORY = 16     # phạt khá nặng: ghép khác loại (không phải NAM-MIX)
PENALTY_MIX_CAP_EXCEEDED = 60   # phạt CỰC nặng: 1 nam vượt quá số trận mix tối đa
PENALTY_OVER_CAP = 5            # phạt nặng mỗi lần VƯỢT quá giới hạn lặp cặp
PENALTY_PER_REPEAT = 0.3        # phạt nhẹ để vẫn ưu tiên cặp mới khi các lựa chọn ngang nhau
LOOKAHEAD_WEIGHT_1 = 0.7        # trọng số trận kế tiếp (+1)
LOOKAHEAD_WEIGHT_2 = 0.4        # trọng số trận sau đó nữa (+2)

SEX_LABEL = {"male": "Nam", "female": "Nữ"}
LABEL_SEX = {"Nam": "male", "Nữ": "female"}

st.set_page_config(page_title="Xếp cặp cầu lông", layout="wide")


# =========================================================
#                       LỚP NGƯỜI CHƠI
# =========================================================
class Player:
    def __init__(self, name, sex, level, status,
                 matches_played=0, waiting_set=0,
                 court=None, mix_matches_played=0):
        if sex not in ["male", "female"]:
            raise ValueError("Sex must be 'male' or 'female'")
        if status not in ["playing", "resting"]:
            raise ValueError("Status must be 'playing' or 'resting'")
        self.name = name
        self.sex = sex
        self.level = level
        self.status = status
        self.matches_played = matches_played
        self.waiting_set = waiting_set              # số trận đã "rảnh" LIÊN TIẾP
        self.mix_matches_played = mix_matches_played  # số trận đôi Nam-Nữ đã đánh
        self.court = court                           # sân đang đấu (None nếu đang rảnh)
        self.id = st.session_state["next_id"]
        st.session_state["next_id"] += 1

    def display_level(self):
        return f"{float(self.level):g}"

    def display_name(self):
        return f"{self.name} ({self.display_level()}đ)"

    def effective_level(self, handicap_nu):
        """Điểm dùng để SO SÁNH cân bằng (không đổi điểm đã nhập): nữ bị
        trừ handicap_nu điểm so với điểm đã chấm, vì cùng 1 mức điểm thì nữ
        thường đánh nhẹ hơn nam một chút."""
        if self.sex == "female":
            return self.level - handicap_nu
        return self.level


# =========================================================
#                   KHỞI TẠO SESSION STATE
# =========================================================
def init_state():
    ss = st.session_state
    ss.setdefault("next_id", 1)
    ss.setdefault("players", {})           # id -> Player
    ss.setdefault("num_courts", MIN_COURTS)
    ss.setdefault("max_repeat", 3)          # số lần tối đa 1 cặp được đánh chung
    ss.setdefault("max_mix_per_man", 2)     # mỗi nam tối đa bấy nhiêu trận mix
    ss.setdefault("gender_handicap_nu", 1.5)
    ss.setdefault("partner_count", {})      # frozenset({id1,id2}) -> số lần đã là đồng đội
    ss.setdefault("current_match", {})      # court -> {team1, team2, round} hoặc None
    ss.setdefault("round_counters", {})     # court -> số trận đã tạo cho sân đó
    ss.setdefault("history", [])
    ss.setdefault("session_minutes", 120)
    ss.setdefault("avg_match_minutes", 10)


init_state()


# =========================================================
#                        HÀM TIỆN ÍCH
# =========================================================
def available_players():
    """Hàng chờ chung: tất cả người chơi đang rảnh (không ở sân nào)."""
    return [pid for pid, p in st.session_state.players.items() if p.status == "resting"]


def name_of(pid):
    p = st.session_state.players.get(pid)
    return p.display_name() if p else "?"


def auto_fill_empty_courts():
    """Lấp đầy MỌI sân đang trống bằng người từ hàng chờ chung (nếu đủ)."""
    for c in range(1, st.session_state.num_courts + 1):
        if not st.session_state.current_match.get(c):
            generate_match(c)


def free_court(court):
    """Giải phóng 1 sân: đưa toàn bộ 4 người trong trận hiện tại (nếu có)
    về lại hàng chờ chung mà KHÔNG tính là đã đấu xong (dùng khi xoá 1
    người giữa trận, hoặc khi giảm số sân)."""
    match = st.session_state.current_match.get(court)
    if not match:
        return
    players = st.session_state.players
    for pid in match["team1"] + match["team2"]:
        if pid in players:
            players[pid].status = "resting"
            players[pid].court = None
    st.session_state.current_match[court] = None


# ---------------------------------------------------------
#        RÀNG BUỘC GIỚI TÍNH KHI CHIA ĐỘI (2 vs 2)
# ---------------------------------------------------------
def team_gender_category(team, players):
    """'NAM' (2 nam), 'NU' (2 nữ), hoặc 'MIX' (1 nam 1 nữ)."""
    s1 = players[team[0]].sex
    s2 = players[team[1]].sex
    if s1 == s2 == "male":
        return "NAM"
    if s1 == s2 == "female":
        return "NU"
    return "MIX"


def category_label(cat):
    return {"NAM": "Đôi Nam-Nam", "NU": "Đôi Nữ-Nữ", "MIX": "Đôi Nam-Nữ"}.get(cat, cat)


def is_valid_gender_split(a, b, players):
    """Chỉ cấm (gần như không cho) đúng 1 trường hợp: đôi Nam-Nam gặp đôi mix."""
    cat_a = team_gender_category(a, players)
    cat_b = team_gender_category(b, players)
    return {cat_a, cat_b} != {"NAM", "MIX"}


def gender_category_penalty(a, b, players):
    cat_a = team_gender_category(a, players)
    cat_b = team_gender_category(b, players)
    if cat_a == cat_b:
        return 0
    if {cat_a, cat_b} == {"NAM", "MIX"}:
        return PENALTY_GENDER_MISMATCH
    return PENALTY_CROSS_CATEGORY


def mix_cap_penalty(team, players, mix_map, max_mix_per_man):
    if team_gender_category(team, players) != "MIX":
        return 0
    penalty = 0
    for pid in team:
        if players[pid].sex == "male":
            count = mix_map.get(pid, 0)
            overflow = max(0, count - max_mix_per_man + 1)
            penalty += PENALTY_MIX_CAP_EXCEEDED * overflow
    return penalty


def quartet_has_valid_split(quartet, players):
    p1, p2, p3, p4 = quartet
    for a, b in (((p1, p2), (p3, p4)), ((p1, p3), (p2, p4)), ((p1, p4), (p2, p3))):
        if is_valid_gender_split(a, b, players):
            return True
    return False


def split_score(a, b, players, partner_map, max_repeat, mix_map, handicap_nu, max_mix_per_man):
    """Điểm cho 1 cách chia đội — càng THẤP càng tốt."""
    skill_a = sum(players[x].effective_level(handicap_nu) for x in a)
    skill_b = sum(players[x].effective_level(handicap_nu) for x in b)
    diff = abs(skill_a - skill_b)

    gender_penalty = gender_category_penalty(a, b, players)
    mix_penalty = (mix_cap_penalty(a, players, mix_map, max_mix_per_man)
                   + mix_cap_penalty(b, players, mix_map, max_mix_per_man))

    rep_a = partner_map.get(frozenset(a), 0)
    rep_b = partner_map.get(frozenset(b), 0)
    overflow_a = max(0, rep_a - max_repeat + 1)
    overflow_b = max(0, rep_b - max_repeat + 1)

    return (
        diff
        + gender_penalty
        + mix_penalty
        + PENALTY_OVER_CAP * (overflow_a + overflow_b)
        + PENALTY_PER_REPEAT * (rep_a + rep_b)
    )


# ---------------------------------------------------------
#     GIỚI HẠN CHỜ TỐI ĐA + CHỌN NGƯỜI CHO TRẬN KẾ TIẾP
# ---------------------------------------------------------
def get_forced_players(pool, waiting_map):
    """Ai đã rảnh liên tục đủ MAX_CONSECUTIVE_REST trận thì BẮT BUỘC phải
    được xếp vào trận tới (ở bất kỳ sân nào)."""
    forced = [p for p in pool if waiting_map.get(p, 0) >= MAX_CONSECUTIVE_REST]
    if len(forced) > 4:
        forced = sorted(forced, key=lambda p: -waiting_map.get(p, 0))[:4]
    return forced


def fill_group_has_valid_quartet(fill_group, forced, players, needed):
    if len(fill_group) < needed:
        return False
    for combo in combinations(fill_group, needed):
        quartet = tuple(forced) + combo
        if len(set(quartet)) == 4 and quartet_has_valid_split(quartet, players):
            return True
    return False


def build_fill_pool(fill_source, forced, matches_map, players, needed):
    """Chọn dần theo tier (số trận ít nhất trước) để ghép cùng 'forced' đủ
    4 người, mở rộng tier cho tới khi có ít nhất 1 cách ghép đúng quy tắc
    giới tính, hoặc đã dùng hết fill_source."""
    if needed <= 0 or not fill_source:
        return []
    levels = sorted(set(matches_map.get(p, 0) for p in fill_source))
    eligible = []
    for lvl in levels:
        eligible.extend([p for p in fill_source if matches_map.get(p, 0) == lvl])
        if len(eligible) >= needed:
            if fill_group_has_valid_quartet(eligible, forced, players, needed) or set(eligible) == set(fill_source):
                break
    return eligible


def candidate_matches(pool, players, matches_map, waiting_map, partner_map, mix_map,
                       max_repeat, handicap_nu, max_mix_per_man, top_k=None):
    """Duyệt các cách chọn 4 người (bắt buộc gồm ai đã rảnh đủ
    MAX_CONSECUTIVE_REST trận) + mọi cách chia đội, trả về danh sách
    (điểm, quartet, (team1, team2), còn_lại) đã sắp từ tốt nhất tới tệ nhất."""
    forced = get_forced_players(pool, waiting_map)
    needed = max(0, 4 - len(forced))
    fill_source = [p for p in pool if p not in forced]

    if needed == 0:
        quartets = [tuple(forced)]
    else:
        fill_eligible = build_fill_pool(fill_source, forced, matches_map, players, needed)
        if len(fill_eligible) < needed:
            return []
        quartets = [tuple(forced) + combo for combo in combinations(fill_eligible, needed)]

    results = []
    for quartet in quartets:
        if len(set(quartet)) != 4:
            continue
        p1, p2, p3, p4 = quartet
        for a, b in (((p1, p2), (p3, p4)), ((p1, p3), (p2, p4)), ((p1, p4), (p2, p3))):
            score = split_score(a, b, players, partner_map, max_repeat, mix_map, handicap_nu, max_mix_per_man)
            con_lai = [p for p in pool if p not in quartet]
            results.append((score, quartet, (a, b), con_lai))
    results.sort(key=lambda t: t[0])
    return results[:top_k] if top_k else results


def simulate_apply(quartet, split, con_lai, players, matches_map, waiting_map, partner_map, mix_map):
    """Giả lập áp dụng 1 trận (không đụng vào Player thật) để tính trước
    các trận kế tiếp."""
    sim_matches = dict(matches_map)
    sim_waiting = dict(waiting_map)
    sim_partner = dict(partner_map)
    sim_mix = dict(mix_map)
    for pid in quartet:
        sim_matches[pid] = sim_matches.get(pid, 0) + 1
        sim_waiting[pid] = 0
    for pid in con_lai:
        sim_waiting[pid] = sim_waiting.get(pid, 0) + 1
    a, b = split
    k1, k2 = frozenset(a), frozenset(b)
    sim_partner[k1] = sim_partner.get(k1, 0) + 1
    sim_partner[k2] = sim_partner.get(k2, 0) + 1
    for team in (a, b):
        if team_gender_category(team, players) == "MIX":
            for pid in team:
                sim_mix[pid] = sim_mix.get(pid, 0) + 1
    return sim_matches, sim_waiting, sim_partner, sim_mix


def best_next_score(pool, players, matches_map, waiting_map, partner_map, mix_map,
                     max_repeat, handicap_nu, max_mix_per_man):
    cands = candidate_matches(pool, players, matches_map, waiting_map, partner_map, mix_map,
                               max_repeat, handicap_nu, max_mix_per_man, top_k=1)
    if not cands:
        return None
    return cands[0]


def choose_match(pool, players, matches_map, waiting_map, partner_map, mix_map,
                  max_repeat, handicap_nu, max_mix_per_man):
    """Chọn trận kế tiếp (cho 1 sân bất kỳ), có TÍNH TRƯỚC 2 trận kế tiếp
    trên toàn bộ hàng chờ chung."""
    top_candidates = candidate_matches(pool, players, matches_map, waiting_map, partner_map, mix_map,
                                        max_repeat, handicap_nu, max_mix_per_man, top_k=6)
    if not top_candidates:
        return None

    if len(pool) <= 4:
        best = top_candidates[0]
        return best[1], best[2], best[3]

    best_total = None
    best_choice = None
    for score, quartet, split, con_lai in top_candidates:
        total = score

        sim_matches, sim_waiting, sim_partner, sim_mix = simulate_apply(
            quartet, split, con_lai, players, matches_map, waiting_map, partner_map, mix_map
        )

        next1 = best_next_score(con_lai, players, sim_matches, sim_waiting, sim_partner, sim_mix,
                                 max_repeat, handicap_nu, max_mix_per_man)
        if next1:
            n1_score, n1_quartet, n1_split, n1_conlai = next1
            total += LOOKAHEAD_WEIGHT_1 * n1_score

            sim_matches2, sim_waiting2, sim_partner2, sim_mix2 = simulate_apply(
                n1_quartet, n1_split, n1_conlai, players, sim_matches, sim_waiting, sim_partner, sim_mix
            )
            next2 = best_next_score(n1_conlai, players, sim_matches2, sim_waiting2, sim_partner2, sim_mix2,
                                     max_repeat, handicap_nu, max_mix_per_man)
            if next2:
                total += LOOKAHEAD_WEIGHT_2 * next2[0]

        if best_total is None or total < best_total:
            best_total = total
            best_choice = (quartet, split, con_lai)

    return best_choice


def generate_match(court):
    """Tạo trận mới cho 1 sân ĐANG TRỐNG, lấy người từ hàng chờ chung
    (không đụng tới sân nào đang có trận dở)."""
    if st.session_state.current_match.get(court):
        return  # sân đang có trận, không ghi đè

    pool = available_players()
    if len(pool) < 4:
        return

    players = st.session_state.players
    matches_map = {pid: players[pid].matches_played for pid in pool}
    waiting_map = {pid: players[pid].waiting_set for pid in pool}
    mix_map = {pid: players[pid].mix_matches_played for pid in pool}
    partner_map = st.session_state.partner_count
    handicap_nu = st.session_state.gender_handicap_nu
    max_repeat = st.session_state.max_repeat
    max_mix_per_man = st.session_state.max_mix_per_man

    result = choose_match(pool, players, matches_map, waiting_map, partner_map, mix_map,
                           max_repeat, handicap_nu, max_mix_per_man)
    if result is None:
        return

    quartet, (team1, team2), _con_lai = result
    rc = st.session_state.round_counters
    rc[court] = rc.get(court, 0) + 1
    st.session_state.current_match[court] = {
        "team1": list(team1),
        "team2": list(team2),
        "round": rc[court],
    }
    for pid in quartet:
        players[pid].status = "playing"
        players[pid].court = court


def rebalance_current(court):
    """Giữ nguyên 4 người đang xếp ở trận hiện tại (chưa đấu), chỉ tính
    lại cách chia đội cho vừa cân bằng điểm trình mới vừa đúng quy tắc
    giới tính."""
    match = st.session_state.current_match.get(court)
    if not match:
        return
    p1, p2, p3, p4 = match["team1"] + match["team2"]
    players = st.session_state.players
    partner_map = st.session_state.partner_count
    mix_map = {pid: players[pid].mix_matches_played for pid in (p1, p2, p3, p4)}
    max_repeat = st.session_state.max_repeat
    handicap_nu = st.session_state.gender_handicap_nu
    max_mix_per_man = st.session_state.max_mix_per_man

    best_score, best_split = None, None
    for a, b in (((p1, p2), (p3, p4)), ((p1, p3), (p2, p4)), ((p1, p4), (p2, p3))):
        score = split_score(a, b, players, partner_map, max_repeat, mix_map, handicap_nu, max_mix_per_man)
        if best_score is None or score < best_score:
            best_score, best_split = score, (a, b)
    match["team1"], match["team2"] = list(best_split[0]), list(best_split[1])


def confirm_and_next(court):
    """Chốt trận ở 1 sân là đã đấu xong: 4 người đó trở lại hàng chờ
    chung (với số trận +1, hết rảnh liên tục), những ai khác đang rảnh ở
    hàng chờ chung thì +1 số trận đã "rảnh liên tục". Sau đó lấp lại sân
    này ngay nếu đủ người."""
    match = st.session_state.current_match.get(court)
    if not match:
        return
    players = st.session_state.players
    quartet = match["team1"] + match["team2"]

    # những ai đang rảnh (ở hàng chờ chung, không thi đấu ở sân khác) TRƯỚC
    # khi chốt trận này -> họ vừa phải chờ thêm 1 trận nữa
    dang_cho_truoc_do = [pid for pid, p in players.items() if p.status == "resting" and pid not in quartet]

    for pid in quartet:
        players[pid].matches_played += 1
        players[pid].waiting_set = 0
        players[pid].status = "resting"
        players[pid].court = None

    for pid in dang_cho_truoc_do:
        players[pid].waiting_set += 1

    partner_map = st.session_state.partner_count
    k1, k2 = frozenset(match["team1"]), frozenset(match["team2"])
    partner_map[k1] = partner_map.get(k1, 0) + 1
    partner_map[k2] = partner_map.get(k2, 0) + 1

    for team in (match["team1"], match["team2"]):
        if team_gender_category(team, players) == "MIX":
            for pid in team:
                players[pid].mix_matches_played += 1

    st.session_state.history.append({
        "Sân": court,
        "Trận": match["round"],
        "Đội 1": " & ".join(name_of(p) for p in match["team1"]),
        "Đội 2": " & ".join(name_of(p) for p in match["team2"]),
    })

    st.session_state.current_match[court] = None
    generate_match(court)


def remove_player(pid):
    players = st.session_state.players
    p = players.get(pid)
    if p is None:
        return
    court_to_refill = None
    if p.status == "playing" and p.court:
        court = p.court
        match = st.session_state.current_match.get(court)
        if match:
            # 3 đồng đội còn lại trở về hàng chờ chung (KHÔNG tính là đã đấu xong)
            for tid in match["team1"] + match["team2"]:
                if tid != pid:
                    players[tid].status = "resting"
                    players[tid].court = None
            st.session_state.current_match[court] = None
            court_to_refill = court

    players.pop(pid, None)
    st.session_state.partner_count = {
        k: v for k, v in st.session_state.partner_count.items() if pid not in k
    }
    if court_to_refill:
        generate_match(court_to_refill)


# =========================================================
#                        SIDEBAR
# =========================================================
with st.sidebar:
    st.header("⚙️ Cài đặt")

    new_num_courts = st.slider("Số sân đang mở hôm nay", MIN_COURTS, MAX_COURTS, st.session_state.num_courts)
    if new_num_courts != st.session_state.num_courts:
        if new_num_courts < st.session_state.num_courts:
            # các sân bị bỏ bớt: giải phóng người đang đấu ở đó về hàng chờ chung
            for c in range(new_num_courts + 1, st.session_state.num_courts + 1):
                free_court(c)
                st.session_state.current_match.pop(c, None)
        st.session_state.num_courts = new_num_courts
        auto_fill_empty_courts()
        st.rerun()

    st.session_state.max_repeat = st.slider(
        "Số lần tối đa 1 cặp được đánh chung", 1, 5, st.session_state.max_repeat,
        help="Mức ưu tiên, không phải luật cấm tuyệt đối: nếu cân bằng trình tốt hơn "
             "hẳn thì app vẫn có thể lặp cặp thêm 1 lần.",
    )
    st.session_state.max_mix_per_man = st.slider(
        "Mỗi nam tối đa bao nhiêu trận đôi mix (Nam-Nữ)", 0, 10, st.session_state.max_mix_per_man,
    )
    st.session_state.gender_handicap_nu = st.slider(
        "Trừ điểm trình nữ khi so cân bằng (không đổi điểm đã nhập)",
        0.0, 5.0, st.session_state.gender_handicap_nu, step=0.5,
    )

    st.caption(
        f"Thang điểm trình {MIN_SKILL:g}-{MAX_SKILL:g} (lẻ {SKILL_STEP}). Người chơi dùng CHUNG 1 "
        f"hàng chờ cho mọi sân — không bị gán cứng vào 1 sân. Không ai rảnh liên tục quá "
        f"{MAX_CONSECUTIVE_REST} trận. Ưu tiên mạnh ghép đôi cùng giới gặp nhau (Nam-Nam/Nam-Nam, "
        "Nữ-Nữ/Nữ-Nữ); chỉ ghép Nam-Nam với mix khi thật sự không còn cách nào khác."
    )

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
    if st.button("🔁 Xếp trận cho tất cả sân đang trống", type="primary"):
        auto_fill_empty_courts()
        st.rerun()
    if st.button("🔄 Làm mới toàn bộ dữ liệu"):
        st.session_state.clear()
        st.rerun()


st.title("🏸 Xếp cặp cầu lông")
st.caption(
    f"Thêm người chơi vào hàng chờ chung. Nhập điểm trình ({MIN_SKILL:g}-{MAX_SKILL:g}, có số lẻ "
    f"{SKILL_STEP}), app tự chọn người + ghép đội 2 vs 2 cân bằng trình nhất có thể cho bất kỳ sân "
    "nào đang trống — người chơi có thể đổi sân qua lại giữa các trận, miễn đúng thứ tự ưu tiên: "
    f"không ai chờ quá {MAX_CONSECUTIVE_REST} trận liên tục, ưu tiên đôi cùng giới, giới hạn số "
    "trận mix mỗi nam, hạn chế lặp cặp."
)

# =========================================================
#                 THÊM / XOÁ NGƯỜI CHƠI
# =========================================================
with st.expander("➕ Thêm người chơi mới", expanded=True):
    with st.form("add_player_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Tên")
        gender_label = c2.selectbox("Giới tính", ["Nam", "Nữ"])
        skill = c3.slider("Trình (1-12)", MIN_SKILL, MAX_SKILL, 6.0, step=SKILL_STEP)
        submitted = st.form_submit_button("Thêm vào hàng chờ")
        if submitted:
            if not name.strip():
                st.warning("Vui lòng nhập tên.")
            else:
                player = Player(
                    name=name.strip(),
                    sex=LABEL_SEX[gender_label],
                    level=float(skill),
                    status="resting",
                )
                st.session_state.players[player.id] = player
                auto_fill_empty_courts()
                st.toast(f"Đã thêm {player.name} vào hàng chờ", icon="✅")
                st.rerun()

if st.session_state.players:
    rm_c1, rm_c2 = st.columns([3, 1])
    options = {f'{p.name} ({SEX_LABEL[p.sex]}, {p.display_level()}đ)': pid
               for pid, p in st.session_state.players.items()}
    sel = rm_c1.selectbox("Chọn người để xoá khỏi danh sách", list(options.keys()))
    if rm_c2.button("🗑️ Xoá người này"):
        remove_player(options[sel])
        st.rerun()

# =========================================================
#              BẢNG DANH SÁCH NGƯỜI CHƠI (SỬA ĐƯỢC)
# =========================================================
st.subheader("📋 Danh sách người chơi")

if not st.session_state.players:
    st.info("Chưa có người chơi nào. Hãy thêm người chơi ở trên.")
else:
    players = st.session_state.players
    df = pd.DataFrame(
        [
            {
                "ID": pid,
                "Tên": p.name,
                "Giới tính": SEX_LABEL[p.sex],
                "Trình": float(p.level),
                "Trạng thái": (f"Đang đấu (Sân {p.court})" if p.status == "playing" else "Đang chờ"),
                "Số trận đã đấu": p.matches_played,
                "Số trận mix": p.mix_matches_played,
                "Đang chờ (trận)": p.waiting_set,
            }
            for pid, p in players.items()
        ]
    ).sort_values(["Trạng thái", "ID"])

    edited = st.data_editor(
        df,
        column_config={
            "ID": st.column_config.NumberColumn(disabled=True),
            "Trạng thái": st.column_config.TextColumn(disabled=True),
            "Số trận đã đấu": st.column_config.NumberColumn(disabled=True),
            "Số trận mix": st.column_config.NumberColumn(disabled=True),
            "Đang chờ (trận)": st.column_config.NumberColumn(disabled=True),
            "Giới tính": st.column_config.SelectboxColumn(options=["Nam", "Nữ"]),
            "Trình": st.column_config.NumberColumn(min_value=MIN_SKILL, max_value=MAX_SKILL, step=SKILL_STEP, format="%.1f"),
        },
        hide_index=True,
        width='stretch',
        key="player_editor",
    )

    changed = False
    courts_to_rebalance = set()
    for _, row in edited.iterrows():
        pid = int(row["ID"])
        p = players.get(pid)
        if p is None:
            continue
        new_skill = float(row["Trình"])
        new_sex = LABEL_SEX[row["Giới tính"]]
        new_name = str(row["Tên"])

        if (p.level, p.sex, p.name) != (new_skill, new_sex, new_name):
            p.level, p.sex, p.name = new_skill, new_sex, new_name
            changed = True
            if p.status == "playing" and p.court:
                courts_to_rebalance.add(p.court)

    if changed:
        for c in courts_to_rebalance:
            rebalance_current(c)
        st.rerun()

    st.download_button(
        "⬇️ Tải danh sách người chơi (CSV)",
        df.to_csv(index=False).encode("utf-8-sig"),
        file_name="danh_sach_nguoi_choi.csv",
        mime="text/csv",
    )

st.divider()

# =========================================================
#              HÀNG CHỜ CHUNG (DÙNG CHO MỌI SÂN)
# =========================================================
st.subheader("⏳ Hàng chờ chung")
cho_ids = sorted(available_players(), key=lambda pid: -st.session_state.players[pid].waiting_set)
if not cho_ids:
    st.caption("Hiện không có ai đang chờ.")
else:
    players = st.session_state.players
    labels = []
    for pid in cho_ids:
        p = players[pid]
        flag = " ⏳" if p.waiting_set >= MAX_CONSECUTIVE_REST else ""
        labels.append(f"{p.display_name()} [{SEX_LABEL[p.sex]}] — chờ {p.waiting_set} trận{flag}")
    st.caption(", ".join(labels))

st.divider()

# =========================================================
#                     CÁC SÂN & TRẬN ĐẤU
# =========================================================
st.subheader("🏸 Các sân đang mở")

cols = st.columns(st.session_state.num_courts)
for i in range(1, st.session_state.num_courts + 1):
    with cols[i - 1]:
        st.markdown(f"#### Sân {i}")
        match = st.session_state.current_match.get(i)

        if not match:
            st.info("Sân đang trống.")
            if st.button("🎲 Tạo trận cho sân này", key=f"start_{i}"):
                generate_match(i)
                st.rerun()
            continue

        t1, t2 = match["team1"], match["team2"]
        players = st.session_state.players
        handicap_nu = st.session_state.gender_handicap_nu
        skill1 = sum(players[p].effective_level(handicap_nu) for p in t1)
        skill2 = sum(players[p].effective_level(handicap_nu) for p in t2)
        cat1 = team_gender_category(t1, players)
        cat2 = team_gender_category(t2, players)
        gender_ok = is_valid_gender_split(t1, t2, players)
        same_category = cat1 == cat2

        st.markdown(f"**Trận {match['round']}**")
        st.write(f"🔵 Đội 1 ({category_label(cat1)}): {', '.join(name_of(p) for p in t1)}")
        st.write(f"🔴 Đội 2 ({category_label(cat2)}): {', '.join(name_of(p) for p in t2)}")
        st.write(f"Tổng trình quy đổi: {skill1:g} — {skill2:g} (chênh lệch {abs(skill1 - skill2):g})")

        if not gender_ok:
            st.error(
                "⚠️ Phá lệ: phải xếp đôi Nam-Nam đấu với đôi mix vì không còn cách nào khác "
                "(thường do số nữ đang lẻ). Đây là lựa chọn bắt buộc tốt nhất hiện có."
            )
        elif same_category and abs(skill1 - skill2) <= 2:
            st.success("Cùng loại giới tính & cân bằng trình ✅")
        elif same_category:
            st.warning("Cùng loại giới tính, nhưng hơi lệch trình — lựa chọn tốt nhất với 4 người hiện có.")
        elif abs(skill1 - skill2) <= 2:
            st.info("ℹ️ Không đủ người để ghép cùng loại giới tính lúc này, nên đã ghép khác loại — bù lại cân bằng trình tốt.")
        else:
            st.warning("⚠️ Không đủ người để ghép cùng loại giới tính, đã ghép khác loại và cũng hơi lệch trình.")

        bc1, bc2 = st.columns(2)
        if bc1.button("✅ Kết thúc & trận kế tiếp", key=f"next_{i}"):
            confirm_and_next(i)
            st.rerun()
        if bc2.button("♻️ Cân bằng lại", key=f"rebalance_{i}",
                      help="Giữ nguyên 4 người, chỉ chia lại đội cho cân trình & đúng giới tính"):
            rebalance_current(i)
            st.rerun()

st.divider()

# =========================================================
#                   LỊCH SỬ & THỐNG KÊ
# =========================================================
with st.expander("📊 Lịch sử các trận đã đấu & thống kê số trận", expanded=False):
    if st.session_state.history:
        hist_df = pd.DataFrame(st.session_state.history)
        st.dataframe(hist_df, width='stretch', hide_index=True)
        st.download_button(
            "⬇️ Tải lịch sử (CSV)",
            hist_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="lich_su_dau.csv",
            mime="text/csv",
        )
    else:
        st.caption("Chưa có trận nào kết thúc.")

    if st.session_state.players:
        players = st.session_state.players
        stat_df = pd.DataFrame(
            [
                {
                    "Tên": p.name,
                    "Giới tính": SEX_LABEL[p.sex],
                    "Số trận đã đấu": p.matches_played,
                    "Số trận mix": p.mix_matches_played,
                    "Đang chờ (trận)": p.waiting_set,
                }
                for p in players.values()
            ]
        ).sort_values(["Số trận đã đấu"])
        st.dataframe(stat_df, width='stretch', hide_index=True)