# -*- coding: utf-8 -*-
"""
APP XẾP CẶP CẦU LÔNG
---------------------
Chạy bằng lệnh:
    pip install streamlit pandas
    streamlit run badminton_app.py

Tính năng:
- Mỗi lần thêm người chơi, app TỰ ĐỘNG xếp người đó vào sân đang ít người
  nhất trong số các sân đang mở hôm đó. Có nút "Phân bổ lại toàn bộ" để
  cân lại nếu cần.
- Mỗi sân tối đa 8 người, tự ghép 4 người thành 2 đội (2 vs 2) sao cho tổng
  điểm trình hai đội càng gần nhau càng tốt.
- THANG ĐIỂM TRÌNH có cả số lẻ: 0, 0.5, 1, 1.5, 2, ... đến 10.
- QUY ĐỔI GIỚI TÍNH khi so trình: vì cùng 1 mức điểm thì nữ thường đánh nhẹ
  hơn nam một chút, nên khi TÍNH CÂN BẰNG (không đổi điểm đã nhập), app sẽ
  trừ 1.5 điểm vào trình của các bạn nữ để so sánh cho công bằng hơn giữa
  các đội có giới tính khác nhau.
- QUY TẮC GIỚI TÍNH khi chia đội, theo 3 mức ưu tiên từ cao xuống thấp:
    (1) ƯU TIÊN NHẤT: đôi cùng loại gặp nhau — Nam-Nam gặp Nam-Nam, Nữ-Nữ
        gặp Nữ-Nữ, mix gặp mix. App sẽ cố gắng chọn kiểu này trước nếu
        không ảnh hưởng quá nhiều đến cân bằng trình.
    (2) Nếu không đủ người để ghép cùng loại, mới cho phép ghép khác loại
        (Nam-Nam gặp Nữ-Nữ, hoặc Nữ-Nữ gặp mix) — bị phạt điểm nhẹ để vẫn
        ưu tiên cùng loại khi có thể, nhưng không bị cấm.
    (3) CHỈ THẬT SỰ TRÁNH (phạt rất nặng, gần như cấm): Nam-Nam đấu với
        mix. Chỉ khi số nữ đang lẻ và KHÔNG CÒN CÁCH NÀO KHÁC thì app mới
        chấp nhận xếp kiểu này (phá lệ), và sẽ cảnh báo rõ khi việc đó
        xảy ra.
  Mức ưu tiên cho đôi cùng loại (Nam-Nam/Nam-Nam, Nữ-Nữ/Nữ-Nữ) được đặt
  khá mạnh, nên app sẽ cố gắng tạo CÀNG NHIỀU trận Nam-Nam gặp Nam-Nam và
  Nữ-Nữ gặp Nữ-Nữ càng tốt, chỉ ghép khác loại khi không còn cách nào
  tốt hơn.
- GIỚI HẠN SỐ TRẬN MIX CHO NAM: mỗi nam chỉ được đánh tối đa
  MAX_MIX_MATCHES_PER_MAN (mặc định 2) trận đôi Nam-Nữ (mix) — sau khi đã
  đủ số trận này, app sẽ tránh xếp người đó vào đội mix ở các trận sau
  (trừ khi không còn cách nào khác). Giới hạn này không áp dụng cho nữ.
- GIỚI HẠN CHỜ: KHÔNG ai phải ngồi nghỉ liên tục quá 2 vòng. Hễ ai đã nghỉ
  đủ 2 vòng liên tiếp, vòng kế tiếp app sẽ BẮT BUỘC xếp người đó vào sân
  (ưu tiên tuyệt đối, vượt trên cả cân bằng trình/giới tính/lặp cặp).
- Hạn chế lặp lại 1 cặp đồng đội quá N lần (chỉnh được, mặc định 3).
- TÍNH TRƯỚC 2 VÒNG KẾ TIẾP khi chọn trận cho vòng hiện tại, để tránh
  tình trạng "vòng này đẹp nhưng 1-2 vòng sau bị kẹt lệch trình".
- Có thể sửa điểm trình bất cứ lúc nào ngay trong bảng -> trận hiện tại
  (chưa đấu) của các sân liên quan sẽ TỰ ĐỘNG chia lại đội theo điểm mới.
- Ước tính mục tiêu số trận mỗi người nên đánh, dựa trên tổng thời gian
  chơi và thời gian trung bình 1 trận.
- Lưu lịch sử các trận đã đấu + thống kê số trận / số vòng đã chờ.
"""

from itertools import combinations
import pandas as pd
import streamlit as st

MAX_PER_COURT = 8
MAX_CONSECUTIVE_REST = 2       # không ai được nghỉ liên tục quá số vòng này
MAX_MIX_MATCHES_PER_MAN = 2    # mỗi nam chỉ được đánh tối đa bấy nhiêu trận đôi Nam-Nữ (mix)

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
    ss.setdefault("mix_games_played", {})  # id -> số trận đôi Nam-Nữ (mix) đã đánh (chủ yếu theo dõi cho nam)
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


def format_skill(x):
    """Hiển thị điểm trình gọn gàng: 5.0 -> '5', 5.5 -> '5.5'."""
    return f"{float(x):g}"


def name_of(pid):
    p = st.session_state.players.get(pid)
    if not p:
        return "?"
    return f'{p["name"]} ({format_skill(p["skill"])}đ)'


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


# ---------------------------------------------------------
#   QUY ĐỔI ĐIỂM TRÌNH THEO GIỚI TÍNH (chỉ dùng để SO SÁNH)
# ---------------------------------------------------------
GENDER_HANDICAP_NU = 1.5  # nữ bị trừ bấy nhiêu điểm khi so sánh cân bằng


def effective_skill(pid, players):
    """Điểm trình dùng để SO SÁNH cân bằng (không ghi đè điểm đã nhập):
    nữ bị trừ 1.5 điểm so với điểm đã chấm."""
    p = players[pid]
    skill = p["skill"]
    if p["gender"] == "Nữ":
        return skill - GENDER_HANDICAP_NU
    return skill


# ---------------------------------------------------------
#        RÀNG BUỘC GIỚI TÍNH KHI CHIA ĐỘI (2 vs 2)
# ---------------------------------------------------------
def team_gender_category(team, players):
    """Trả về loại đôi: 'NAM' (2 nam), 'NU' (2 nữ), hoặc 'MIX' (1 nam 1 nữ)."""
    g1 = players[team[0]]["gender"]
    g2 = players[team[1]]["gender"]
    if g1 == g2 == "Nam":
        return "NAM"
    if g1 == g2 == "Nữ":
        return "NU"
    return "MIX"


def category_label(cat):
    return {"NAM": "Đôi Nam-Nam", "NU": "Đôi Nữ-Nữ", "MIX": "Đôi Nam-Nữ"}.get(cat, cat)


def is_valid_gender_split(a, b, players):
    """CHỈ cấm (phạt rất nặng, gần như không cho) đúng 1 trường hợp: đôi
    Nam-Nam gặp đôi Nam-Nữ (mix). Mọi kiểu ghép khác đều được coi là
    "hợp lệ" theo nghĩa không bị cấm — dù vẫn có kiểu được ƯU TIÊN hơn
    (xem gender_category_penalty)."""
    cat_a = team_gender_category(a, players)
    cat_b = team_gender_category(b, players)
    return {cat_a, cat_b} != {"NAM", "MIX"}


def gender_category_penalty(a, b, players):
    """Mức phạt điểm theo 3 bậc ưu tiên:
    - Cùng loại (Nam-Nam/Nam-Nam, Nữ-Nữ/Nữ-Nữ, mix/mix): không phạt — đây
      là kiểu được ƯU TIÊN chọn nhất.
    - Khác loại nhưng KHÔNG phải Nam-Nam-gặp-mix (tức Nam-Nam/Nữ-Nữ hoặc
      Nữ-Nữ/mix): phạt nhẹ, vẫn cho phép nếu cần để cân bằng trình hoặc
      khi không đủ người ghép cùng loại.
    - Nam-Nam gặp mix: phạt RẤT nặng, chỉ chấp nhận khi không còn lựa
      chọn nào khác (thường do số nữ đang lẻ)."""
    cat_a = team_gender_category(a, players)
    cat_b = team_gender_category(b, players)
    if cat_a == cat_b:
        return 0
    if {cat_a, cat_b} == {"NAM", "MIX"}:
        return PENALTY_GENDER_MISMATCH
    return PENALTY_CROSS_CATEGORY


def mix_cap_penalty(team, players, mix_games_played):
    """Nếu team này là đôi mix, phạt RẤT nặng cho mỗi nam trong team đã
    đánh đủ (hoặc vượt) MAX_MIX_MATCHES_PER_MAN trận mix rồi — gần như
    không cho đánh thêm trận mix nữa, trừ khi không còn cách nào khác.
    Giới hạn này chỉ áp dụng cho nam, không áp dụng cho nữ."""
    if team_gender_category(team, players) != "MIX":
        return 0
    penalty = 0
    for pid in team:
        if players[pid]["gender"] == "Nam":
            count = mix_games_played.get(pid, 0)
            overflow = max(0, count - MAX_MIX_MATCHES_PER_MAN + 1)
            penalty += PENALTY_MIX_CAP_EXCEEDED * overflow
    return penalty


def quartet_has_valid_split(quartet, players):
    """Quartet này có ÍT NHẤT 1 cách chia đội đúng quy tắc giới tính không?"""
    p1, p2, p3, p4 = quartet
    for a, b in (((p1, p2), (p3, p4)), ((p1, p3), (p2, p4)), ((p1, p4), (p2, p3))):
        if is_valid_gender_split(a, b, players):
            return True
    return False


PENALTY_GENDER_MISMATCH = 40    # phạt RẤT nặng nếu phải ghép Nam-Nam gặp mix
PENALTY_CROSS_CATEGORY = 16     # phạt khá nặng nếu phải ghép khác loại (không phải Nam-Nam/mix), để ƯU TIÊN MẠNH đôi cùng loại (Nam-Nam/Nam-Nam, Nữ-Nữ/Nữ-Nữ) trước
PENALTY_MIX_CAP_EXCEEDED = 60   # phạt CỰC nặng nếu 1 nam phải đánh vượt quá MAX_MIX_MATCHES_PER_MAN trận mix
PENALTY_OVER_CAP = 5            # phạt nặng mỗi lần VƯỢT quá giới hạn lặp cặp
PENALTY_PER_REPEAT = 0.3      # phạt nhẹ để vẫn ưu tiên cặp mới khi các lựa chọn ngang nhau
LOOKAHEAD_WEIGHT_1 = 0.7      # trọng số vòng kế tiếp (vòng +1) khi tính trước
LOOKAHEAD_WEIGHT_2 = 0.4      # trọng số vòng sau đó nữa (vòng +2) khi tính trước


def split_score(a, b, players, partner_count, max_repeat, mix_games_played):
    """Điểm cho 1 cách chia đội (a, b là 2 tuple 2 người). Điểm càng THẤP
    càng tốt. Ưu tiên theo thứ tự: (1) ƯU TIÊN MẠNH đôi cùng loại giới
    tính gặp nhau (Nam-Nam/Nam-Nam, Nữ-Nữ/Nữ-Nữ, mix/mix) — khác loại bị
    phạt khá nặng, Nam-Nam gặp mix bị phạt rất nặng; (1b) nam đã đủ số
    trận mix tối đa bị phạt cực nặng nếu phải ghép mix thêm; (2) cân bằng
    trình (đã quy đổi theo giới tính); (3) hạn chế lặp cặp đồng đội."""
    skill_a = sum(effective_skill(x, players) for x in a)
    skill_b = sum(effective_skill(x, players) for x in b)
    diff = abs(skill_a - skill_b)

    gender_penalty = gender_category_penalty(a, b, players)
    mix_penalty = mix_cap_penalty(a, players, mix_games_played) + mix_cap_penalty(b, players, mix_games_played)

    rep_a = partner_count.get(frozenset(a), 0)
    rep_b = partner_count.get(frozenset(b), 0)
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
#     GIỚI HẠN CHỜ TỐI ĐA + CHỌN NGƯỜI CHO VÒNG KẾ TIẾP
# ---------------------------------------------------------
def get_forced_players(pool, rounds_resting):
    """Những ai đã nghỉ liên tục đủ MAX_CONSECUTIVE_REST vòng thì BẮT BUỘC
    phải được xếp vào vòng tới (nếu không sẽ vi phạm giới hạn chờ). Nếu số
    người này nhiều hơn 4 (hiếm khi xảy ra), ưu tiên người chờ lâu nhất."""
    forced = [p for p in pool if rounds_resting.get(p, 0) >= MAX_CONSECUTIVE_REST]
    if len(forced) > 4:
        forced = sorted(forced, key=lambda p: -rounds_resting.get(p, 0))[:4]
    return forced


def fill_group_has_valid_quartet(fill_group, forced, players, needed):
    """Trong fill_group, có tồn tại cách chọn đủ 'needed' người để ghép
    cùng 'forced' thành 1 quartet chia đội đúng quy tắc giới tính không?"""
    if len(fill_group) < needed:
        return False
    for combo in combinations(fill_group, needed):
        quartet = tuple(forced) + combo
        if len(set(quartet)) == 4 and quartet_has_valid_split(quartet, players):
            return True
    return False


def build_fill_pool(fill_source, forced, games_played, players, needed):
    """Chọn dần theo tier (số trận ít nhất trước) những người sẽ ghép cùng
    'forced' để đủ 4 người/trận, mở rộng tier cho tới khi có ít nhất 1 cách
    ghép đúng quy tắc giới tính, hoặc đã dùng hết fill_source."""
    if needed <= 0 or not fill_source:
        return []
    levels = sorted(set(games_played.get(p, 0) for p in fill_source))
    eligible = []
    for lvl in levels:
        eligible.extend([p for p in fill_source if games_played.get(p, 0) == lvl])
        if len(eligible) >= needed:
            if fill_group_has_valid_quartet(eligible, forced, players, needed) or set(eligible) == set(fill_source):
                break
    return eligible


def candidate_matches(pool, players, games_played, rounds_resting, partner_count, mix_games_played, max_repeat, top_k=None):
    """Duyệt các cách chọn 4 người (BẮT BUỘC gồm những ai đã nghỉ đủ
    MAX_CONSECUTIVE_REST vòng) + mọi cách chia đội, trả về danh sách
    (điểm, quartet, (team1, team2), resting) đã sắp xếp từ tốt nhất tới
    tệ nhất."""
    forced = get_forced_players(pool, rounds_resting)
    needed = max(0, 4 - len(forced))
    fill_source = [p for p in pool if p not in forced]

    if needed == 0:
        quartets = [tuple(forced)]
    else:
        fill_eligible = build_fill_pool(fill_source, forced, games_played, players, needed)
        if len(fill_eligible) < needed:
            return []
        quartets = [tuple(forced) + combo for combo in combinations(fill_eligible, needed)]

    results = []
    for quartet in quartets:
        if len(set(quartet)) != 4:
            continue
        p1, p2, p3, p4 = quartet
        for a, b in (((p1, p2), (p3, p4)), ((p1, p3), (p2, p4)), ((p1, p4), (p2, p3))):
            score = split_score(a, b, players, partner_count, max_repeat, mix_games_played)
            resting = [p for p in pool if p not in quartet]
            results.append((score, quartet, (a, b), resting))
    results.sort(key=lambda t: t[0])
    return results[:top_k] if top_k else results


def simulate_apply(quartet, split, resting, players, games_played, rounds_resting, partner_count, mix_games_played):
    """Giả lập áp dụng 1 trận (không ghi vào session_state thật) để tính
    trước các vòng kế tiếp sẽ ra sao, bao gồm cả số trận mix đã đánh."""
    sim_games = dict(games_played)
    sim_rest = dict(rounds_resting)
    sim_partner = dict(partner_count)
    sim_mix = dict(mix_games_played)
    for pid in quartet:
        sim_games[pid] = sim_games.get(pid, 0) + 1
        sim_rest[pid] = 0
    for pid in resting:
        sim_rest[pid] = sim_rest.get(pid, 0) + 1
    a, b = split
    k1, k2 = frozenset(a), frozenset(b)
    sim_partner[k1] = sim_partner.get(k1, 0) + 1
    sim_partner[k2] = sim_partner.get(k2, 0) + 1
    for team in (a, b):
        if team_gender_category(team, players) == "MIX":
            for pid in team:
                sim_mix[pid] = sim_mix.get(pid, 0) + 1
    return sim_games, sim_rest, sim_partner, sim_mix


def best_next_score(pool, players, games_played, rounds_resting, partner_count, mix_games_played, max_repeat):
    """Trả về ứng viên tốt nhất (score, quartet, split, resting) cho 1
    vòng giả định, dùng để tính trước."""
    cands = candidate_matches(pool, players, games_played, rounds_resting, partner_count, mix_games_played, max_repeat, top_k=1)
    if not cands:
        return None
    score, quartet, split, resting = cands[0]
    return score, quartet, split, resting


def choose_match(pool, players, games_played, rounds_resting, partner_count, mix_games_played, max_repeat):
    """Chọn trận cho vòng tới, có TÍNH TRƯỚC 2 VÒNG KẾ TIẾP: lấy vài
    phương án tốt nhất của vòng này (đã tôn trọng giới hạn chờ tối đa), mô
    phỏng áp dụng mỗi phương án rồi xem vòng SAU đó (+1) và vòng sau nữa
    (+2) sẽ cân bằng tới đâu, cộng điểm 3 vòng lại (trọng số giảm dần),
    chọn phương án có tổng điểm thấp nhất."""
    top_candidates = candidate_matches(pool, players, games_played, rounds_resting, partner_count, mix_games_played, max_repeat, top_k=6)
    if not top_candidates:
        return None

    if len(pool) <= 4:
        best = top_candidates[0]
        return best[1], best[2], best[3]

    best_total = None
    best_choice = None
    for score, quartet, split, resting in top_candidates:
        total = score

        sim_games, sim_rest, sim_partner, sim_mix = simulate_apply(
            quartet, split, resting, players, games_played, rounds_resting, partner_count, mix_games_played
        )

        # Tính trước vòng +1
        next1 = best_next_score(pool, players, sim_games, sim_rest, sim_partner, sim_mix, max_repeat)
        if next1:
            n1_score, n1_quartet, n1_split, n1_resting = next1
            total += LOOKAHEAD_WEIGHT_1 * n1_score

            # Tính trước thêm vòng +2
            sim_games2, sim_rest2, sim_partner2, sim_mix2 = simulate_apply(
                n1_quartet, n1_split, n1_resting, players, sim_games, sim_rest, sim_partner, sim_mix
            )
            next2 = best_next_score(pool, players, sim_games2, sim_rest2, sim_partner2, sim_mix2, max_repeat)
            if next2:
                n2_score = next2[0]
                total += LOOKAHEAD_WEIGHT_2 * n2_score

        if best_total is None or total < best_total:
            best_total = total
            best_choice = (quartet, split, resting)

    return best_choice


def generate_match(court):
    """Tạo trận mới cho 1 sân (chọn người + chia đội, có tính trước 2 vòng)."""
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
        st.session_state.mix_games_played,
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
    """Giữ nguyên 4 người đang được xếp ở trận hiện tại (chưa đấu), nhưng
    tính lại cách chia đội cho vừa cân bằng điểm trình MỚI (đã quy đổi
    giới tính) vừa đúng quy tắc giới tính."""
    match = st.session_state.current_match.get(court)
    if not match:
        return
    p1, p2, p3, p4 = match["team1"] + match["team2"]
    players = st.session_state.players
    pc = st.session_state.partner_count
    mg = st.session_state.mix_games_played
    max_repeat = st.session_state.max_repeat
    best_score, best_split_choice = None, None
    for a, b in (((p1, p2), (p3, p4)), ((p1, p3), (p2, p4)), ((p1, p4), (p2, p3))):
        score = split_score(a, b, players, pc, max_repeat, mg)
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

    players = st.session_state.players
    mg = st.session_state.mix_games_played
    for team in (match["team1"], match["team2"]):
        if team_gender_category(team, players) == "MIX":
            for pid in team:
                mg[pid] = mg.get(pid, 0) + 1

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
    st.caption(
        f"Mỗi sân tối đa {MAX_PER_COURT} người. Không ai phải nghỉ liên tục quá "
        f"{MAX_CONSECUTIVE_REST} vòng. ƯU TIÊN MẠNH ghép đôi cùng loại giới tính "
        "gặp nhau (Nam-Nam/Nam-Nam, Nữ-Nữ/Nữ-Nữ); nếu không đủ người mới cho "
        "ghép khác loại (trừ Nam-Nam gặp mix — chỉ xếp khi số nữ lẻ và thật sự "
        f"không còn cách nào khác). Mỗi nam chỉ đánh tối đa "
        f"{MAX_MIX_MATCHES_PER_MAN} trận đôi mix. Khi so cân bằng trình, nữ "
        f"được quy đổi trừ {GENDER_HANDICAP_NU} điểm."
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
    if st.button("🔀 Phân bổ lại toàn bộ vào các sân cho đều", type="primary"):
        if st.session_state.players:
            redistribute_all_courts()
            st.rerun()
    if st.button("🔄 Làm mới toàn bộ dữ liệu"):
        st.session_state.clear()
        st.rerun()

st.title("🏸 Xếp cặp cầu lông")
st.caption(
    "Thêm người chơi — app tự xếp vào sân đang ít người nhất. Nhập điểm trình "
    "(0-10, có số lẻ 0.5), app tự ghép đội 2 vs 2 cân bằng trình nhất có thể, "
    "ưu tiên MẠNH đôi cùng loại giới tính gặp nhau (Nam-Nam/Nam-Nam, Nữ-Nữ/Nữ-Nữ), "
    f"mỗi nam chỉ đánh tối đa {MAX_MIX_MATCHES_PER_MAN} trận mix, tránh ghép "
    f"Nam-Nam với mix, và không để ai chờ quá {MAX_CONSECUTIVE_REST} vòng liên tục."
)

# =========================================================
#                 THÊM / XOÁ NGƯỜI CHƠI
# =========================================================
with st.expander("➕ Thêm người chơi mới", expanded=True):
    with st.form("add_player_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Tên")
        gender = c2.selectbox("Giới tính", ["Nam", "Nữ"])
        skill = c3.slider("Trình (0-10)", 0.0, 10.0, 5.0, step=0.5)
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
                        "skill": float(skill),
                        "court": court,
                    }
                    st.session_state.games_played[pid] = 0
                    st.session_state.mix_games_played[pid] = 0
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
        st.session_state.mix_games_played.pop(pid, None)
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
                "Trình (0-10)": float(p["skill"]),
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
            "Trình (0-10)": st.column_config.NumberColumn(min_value=0.0, max_value=10.0, step=0.5, format="%.1f"),
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
    courts_to_rebalance = set()
    for _, row in edited.iterrows():
        pid = int(row["ID"])
        p = st.session_state.players.get(pid)
        if p is None:
            continue
        new_skill = float(row["Trình (0-10)"])
        new_court = int(row["Sân"])
        new_gender = row["Giới tính"]
        new_name = str(row["Tên"])

        if new_court != p["court"] and len([x for x in get_pool(new_court) if x != pid]) >= MAX_PER_COURT:
            st.warning(f"Sân {new_court} đã đủ {MAX_PER_COURT} người, không thể chuyển {new_name}.")
            new_court = p["court"]

        if (p["skill"], p["court"], p["gender"], p["name"]) != (new_skill, new_court, new_gender, new_name):
            old_court = p["court"]
            p["skill"], p["court"], p["gender"], p["name"] = new_skill, new_court, new_gender, new_name
            changed = True
            # Trận chưa đấu ở sân cũ VÀ sân mới (nếu đổi sân) đều cần xếp lại
            courts_to_rebalance.add(old_court)
            courts_to_rebalance.add(new_court)

    if changed:
        # Chỉ cần xếp lại các trận HIỆN TẠI (chưa đấu) theo điểm/giới tính mới;
        # các vòng sau đó sẽ tự dùng dữ liệu mới khi được tạo.
        for c in courts_to_rebalance:
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
        players = st.session_state.players
        skill1 = sum(effective_skill(p, players) for p in t1)
        skill2 = sum(effective_skill(p, players) for p in t2)
        cat1 = team_gender_category(t1, players)
        cat2 = team_gender_category(t2, players)
        gender_ok = is_valid_gender_split(t1, t2, players)
        same_category = cat1 == cat2

        st.markdown(f"**Vòng {match['round']}**")
        st.write(f"🔵 Đội 1 ({category_label(cat1)}): {', '.join(name_of(p) for p in t1)}")
        st.write(f"🔴 Đội 2 ({category_label(cat2)}): {', '.join(name_of(p) for p in t2)}")
        st.write(
            f"Tổng trình quy đổi: {skill1:g} — {skill2:g} (chênh lệch {abs(skill1 - skill2):g})"
        )

        if not gender_ok:
            st.error(
                "⚠️ Phá lệ: phải xếp đôi Nam-Nam đấu với đôi Nam-Nữ (mix) vì không "
                "còn cách nào khác (thường do số nữ đang lẻ). Đây là lựa chọn bắt "
                "buộc tốt nhất hiện có."
            )
        elif same_category and abs(skill1 - skill2) <= 2:
            st.success("Cùng loại giới tính & cân bằng trình ✅")
        elif same_category:
            st.warning("Cùng loại giới tính, nhưng hơi lệch trình — đây là lựa chọn tốt nhất với 4 người hiện có.")
        elif abs(skill1 - skill2) <= 2:
            st.info(
                "ℹ️ Không đủ người để ghép cùng loại giới tính lúc này, nên đã ghép "
                "khác loại (vẫn đúng quy tắc, chỉ không phải lựa chọn ưu tiên nhất) — bù lại cân bằng trình rất tốt."
            )
        else:
            st.warning(
                "⚠️ Không đủ người để ghép cùng loại giới tính lúc này, nên đã ghép "
                "khác loại và cũng hơi lệch trình — đây là lựa chọn tốt nhất với 4 người hiện có."
            )

        if match["resting"]:
            resting_labels = []
            for p in match["resting"]:
                waited = st.session_state.rounds_resting.get(p, 0)
                flag = " ⏳" if waited >= MAX_CONSECUTIVE_REST else ""
                resting_labels.append(f"{name_of(p)} (chờ {waited} vòng{flag})")
            st.caption("😌 Nghỉ vòng này: " + ", ".join(resting_labels))

        bc1, bc2 = st.columns(2)
        if bc1.button("✅ Kết thúc & trận kế tiếp", key=f"next_{i}"):
            confirm_and_next(i)
            st.rerun()
        if bc2.button("♻️ Cân bằng lại", key=f"rebalance_{i}", help="Giữ nguyên 4 người, chỉ chia lại đội cho cân trình & đúng giới tính"):
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
                    "Giới tính": p["gender"],
                    "Sân": p["court"],
                    "Số trận đã đấu": st.session_state.games_played.get(pid, 0),
                    "Số trận mix": st.session_state.mix_games_played.get(pid, 0),
                    "Đang chờ (vòng)": st.session_state.rounds_resting.get(pid, 0),
                }
                for pid, p in st.session_state.players.items()
            ]
        ).sort_values(["Sân", "Số trận đã đấu"])
        st.dataframe(stat_df, use_container_width=True, hide_index=True)