from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st

from student_survey_db import (
    export_csvs,
    get_participant_meta,
    init_db,
    load_package_items,
    normalize_text,
    package_exists,
    participant_already_submitted,
    upsert_batch_feedback,
    upsert_item_rating,
    upsert_participant_meta,
)


ITEM_FIELDS = [
    ("task_goal_clarity", "杩欓亾棰樻竻妤氳鏄庝簡鎴戦渶瑕佸畬鎴愮殑浠诲姟鐩爣銆?),
    ("key_support", "杩欓亾棰樻彁渚涗簡寮€濮嬩綔绛旀墍闇€鐨勫叧閿俊鎭笌鏀寔銆?),
    ("course_relevance", "杩欓亾棰樹笌娣卞害瀛︿範璇剧▼鍐呭鎴栧疄闄呯紪绋嬩换鍔＄浉鍏炽€?),
    ("learning_help", "杩欓亾棰樺鎴戠殑瀛︿範鏈夋槑鏄惧府鍔┿€?),
    ("info_load", "瀹屾垚杩欓亾棰樻椂锛屾垜闇€瑕佸悓鏃跺鐞嗗緢澶氫俊鎭€?),
    ("search_effort", "闃呰杩欓亾棰樻椂锛屾垜闇€瑕侀澶栬姳鍔涙皵鍘绘壘鍑烘渶閲嶈鐨勪俊鎭€?),
    ("active_engagement", "瀹屾垚杩欓亾棰樻椂锛屾垜浼氫富鍔ㄦ姇鍏ユ€濊€冨拰鐞嗚В銆?),
    ("mental_effort", "鎬讳綋鏉ヨ锛屽畬鎴愯繖閬撻闇€瑕佹垜鎶曞叆杈冮珮鐨勫績鐞嗗姫鍔涖€?),
]

BATCH_FIELDS = [
    ("overall_usefulness", "杩欐壒缁冧範棰樻湁鍔╀簬鎻愰珮鎴戝娣卞害瀛︿範鐭ヨ瘑鐨勭悊瑙ｃ€?),
    ("overall_ease", "鏁翠綋涓婏紝杩欐壒缁冧範棰樻瘮杈冨鏄撲笂鎵嬨€?),
    ("continued_use_intention", "濡傛灉鍚庣画璇剧▼缁х画浣跨敤杩欑被缁冧範棰橈紝鎴戞効鎰忕户缁娇鐢ㄣ€?),
    ("overall_quality", "鎬讳綋鑰岃█锛岃繖鎵圭粌涔犻鐨勮川閲忚緝楂樸€?),
]

WELCOME_PAGE = "welcome"
CONSENT_PAGE = "consent"
BACKGROUND_PAGE = "background"
ATTENTION_PAGE = "attention"
BATCH_PAGE = "batch"
SUCCESS_PAGE = "success"
LIKERT_OPTIONS = [1, 2, 3, 4, 5]
LIKERT_CAPTION = "1 = 闈炲父涓嶅悓鎰? 5 = 闈炲父鍚屾剰"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_state(package_id: str, participant_id: str) -> None:
    defaults: dict[str, Any] = {
        "student_participant_id": participant_id,
        "student_package_id": package_id,
        "student_started_at": now_iso(),
        "student_page_index": 0,
        "student_background": {},
        "student_attention": {},
        "student_item_responses": {},
        "student_batch_response": {},
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    if (
        st.session_state.get("student_package_id") != package_id
        or st.session_state.get("student_participant_id") != participant_id
    ):
        reset_state(package_id, participant_id)


def reset_state(package_id: str, participant_id: str) -> None:
    st.session_state["student_participant_id"] = participant_id
    st.session_state["student_package_id"] = package_id
    st.session_state["student_started_at"] = now_iso()
    st.session_state["student_page_index"] = 0
    st.session_state["student_background"] = {}
    st.session_state["student_attention"] = {}
    st.session_state["student_item_responses"] = {}
    st.session_state["student_batch_response"] = {}


def read_package_id() -> str:
    package_value = st.query_params.get("package")
    if isinstance(package_value, list):
        return str(package_value[0]).strip()
    return str(package_value or "").strip()


def read_participant_id() -> str:
    participant_value = st.query_params.get("pid")
    if isinstance(participant_value, list):
        return str(participant_value[0]).strip()
    return str(participant_value or "").strip()


def build_sequence(package_df: pd.DataFrame) -> list[str]:
    item_ids = package_df["blind_exercise_id"].astype(str).tolist()
    sequence = [WELCOME_PAGE, CONSENT_PAGE, BACKGROUND_PAGE]
    if item_ids:
        prefix = item_ids[:3]
        suffix = item_ids[3:]
        sequence.extend(prefix)
        sequence.append(ATTENTION_PAGE)
        sequence.extend(suffix)
    else:
        sequence.append(ATTENTION_PAGE)
    sequence.extend([BATCH_PAGE, SUCCESS_PAGE])
    return sequence


def move_page(delta: int, sequence: list[str]) -> None:
    next_index = max(0, min(st.session_state["student_page_index"] + delta, len(sequence) - 1))
    st.session_state["student_page_index"] = next_index


def render_exercise(row: pd.Series) -> None:
    st.markdown(f"**缁冧範缂栧彿锛?* {normalize_text(row.get('blind_exercise_id'), '鏈紪鍙?)}")
    st.markdown(f"**棰樼洰鏍囬锛?* {normalize_text(row.get('title'), '鏃犳爣棰?)}")
    st.markdown(f"**涓婚锛?* {normalize_text(row.get('topic'), '鏈爣娉?)}")
    st.markdown("**棰樼洰鎻忚堪锛?*")
    st.write(normalize_text(row.get("instruction_text"), "鏃?))
    st.markdown("**杈撳叆杈撳嚭瑕佹眰锛?*")
    st.write(normalize_text(row.get("expected_output"), "鏃?))
    st.markdown("**绾︽潫鏉′欢锛?*")
    st.write(normalize_text(row.get("constraints_text"), "鏃?))
    st.markdown("**璧峰浠ｇ爜锛堝鏈夛級锛?*")
    starter_code = normalize_text(row.get("starter_code"))
    if starter_code.strip():
        st.code(starter_code, language="python")
    else:
        st.write("鏃?)
    st.markdown("**娴嬭瘯鏍蜂緥锛堝鏈夛級锛?*")
    st.write(normalize_text(row.get("test_cases_text"), "鏃?))


def render_likert(prompt: str, key: str) -> None:
    st.select_slider(
        prompt,
        options=LIKERT_OPTIONS,
        value=st.session_state.get(key, 3),
        key=key,
        help=LIKERT_CAPTION,
    )


def save_background() -> None:
    payload = {
        "participant_id": st.session_state["student_participant_id"],
        "package_id": st.session_state["student_package_id"],
        "consent": "鏄?,
        "study_stage": st.session_state["bg_study_stage"],
        "programming_background": st.session_state["bg_programming_background"],
        "python_familiarity": st.session_state["bg_python_familiarity"],
        "framework_familiarity": st.session_state["bg_framework_familiarity"],
        "dl_course_taken": st.session_state["bg_dl_course_taken"],
        "familiar_topics": "; ".join(st.session_state["bg_familiar_topics"]),
        "started_at": st.session_state["student_started_at"],
    }
    st.session_state["student_background"] = payload
    upsert_participant_meta(payload)


def save_item(row: pd.Series) -> None:
    blind_exercise_id = str(row["blind_exercise_id"])
    response = {
        "participant_id": st.session_state["student_participant_id"],
        "package_id": st.session_state["student_package_id"],
        "blind_exercise_id": blind_exercise_id,
        "item_order": int(row.get("display_order", 0)) or 0,
        "task_goal_clarity": st.session_state[f"{blind_exercise_id}_task_goal_clarity"],
        "key_support": st.session_state[f"{blind_exercise_id}_key_support"],
        "course_relevance": st.session_state[f"{blind_exercise_id}_course_relevance"],
        "learning_help": st.session_state[f"{blind_exercise_id}_learning_help"],
        "info_load": st.session_state[f"{blind_exercise_id}_info_load"],
        "search_effort": st.session_state[f"{blind_exercise_id}_search_effort"],
        "active_engagement": st.session_state[f"{blind_exercise_id}_active_engagement"],
        "mental_effort": st.session_state[f"{blind_exercise_id}_mental_effort"],
        "open_comment": st.session_state.get(f"{blind_exercise_id}_open_comment", "").strip(),
        "saved_at": now_iso(),
    }
    st.session_state["student_item_responses"][blind_exercise_id] = response
    upsert_item_rating(response)


def save_attention() -> None:
    score = st.session_state["attention_check_score"]
    st.session_state["student_attention"] = {
        "attention_check_score": score,
        "attention_check_passed": score == 4,
    }
    payload = {
        **st.session_state["student_background"],
        "participant_id": st.session_state["student_participant_id"],
        "package_id": st.session_state["student_package_id"],
        "started_at": st.session_state["student_started_at"],
        "attention_check_score": score,
        "attention_check_passed": score == 4,
    }
    upsert_participant_meta(payload)


def save_batch() -> None:
    started_at = datetime.fromisoformat(st.session_state["student_started_at"])
    elapsed_seconds = max(0.0, (datetime.now(timezone.utc) - started_at).total_seconds())
    batch_payload = {
        "participant_id": st.session_state["student_participant_id"],
        "package_id": st.session_state["student_package_id"],
        "overall_usefulness": st.session_state["batch_overall_usefulness"],
        "overall_ease": st.session_state["batch_overall_ease"],
        "continued_use_intention": st.session_state["batch_continued_use_intention"],
        "overall_quality": st.session_state["batch_overall_quality"],
        "final_comment": st.session_state["batch_final_comment"].strip(),
        "rating_time_seconds": round(elapsed_seconds, 2),
        "saved_at": now_iso(),
    }
    st.session_state["student_batch_response"] = batch_payload
    upsert_batch_feedback(batch_payload)
    meta_payload = {
        **st.session_state["student_background"],
        **st.session_state["student_attention"],
        "participant_id": st.session_state["student_participant_id"],
        "package_id": st.session_state["student_package_id"],
        "started_at": st.session_state["student_started_at"],
        "submitted_at": now_iso(),
    }
    upsert_participant_meta(meta_payload)
    export_csvs()


def render_welcome() -> None:
    st.title("娣卞害瀛︿範缁冧範棰樺涔犱綋楠岃瘎浼伴棶鍗凤紙瀛︾敓鐗堬級")
    st.write("鎮ㄥソ锛佹湰闂嵎鐢ㄤ簬浜嗚В瀛︾敓瀵规繁搴﹀涔犵粌涔犻鐨勫涔犱綋楠屼笌璇勪环銆?)
    st.write("闂嵎鍖垮悕濉啓锛屼粎鐢ㄤ簬瀛︽湳鐮旂┒銆傛暣涓棶鍗烽璁￠渶瑕?8-12 鍒嗛挓銆?)
    st.write("璇锋牴鎹鐩湰韬綔绛旓紝涓嶅繀鐚滄祴棰樼洰鏉ユ簮銆?)
    st.info("鏈摼鎺ュ凡缁忎负鎮ㄥ浐瀹氫簡棰樺寘锛岃鍦ㄥ悓涓€璁惧瀹屾垚濉啓銆?)
    if st.button("寮€濮嬪～鍐?, use_container_width=True):
        st.session_state["student_page_index"] = 1
        st.rerun()


def render_consent(sequence: list[str]) -> None:
    st.title("鐭ユ儏鍚屾剰")
    choice = st.radio("鎮ㄦ槸鍚︾煡鎯呭悓鎰忓弬涓庢湰鐮旂┒锛?, ["鏄?, "鍚?], horizontal=True)
    col1, col2 = st.columns(2)
    back = col1.button("杩斿洖", use_container_width=True)
    next_step = col2.button("缁х画", use_container_width=True)
    if back:
        move_page(-1, sequence)
        st.rerun()
    if next_step:
        if choice != "鏄?:
            st.session_state["student_page_index"] = len(sequence) - 1
            st.session_state["student_batch_response"] = {"declined": True}
            st.rerun()
        move_page(1, sequence)
        st.rerun()


def render_background(sequence: list[str]) -> None:
    st.title("鑳屾櫙淇℃伅")
    with st.form("background_form"):
        st.selectbox(
            "鎮ㄧ洰鍓嶆墍澶勭殑瀛︿範闃舵鏄紵",
            ["鏈浣庡勾绾?, "鏈楂樺勾绾?, "纭曞＋鐮旂┒鐢?, "鍗氬＋鐮旂┒鐢?, "鍏朵粬"],
            key="bg_study_stage",
        )
        st.selectbox(
            "鎮ㄧ殑缂栫▼瀛︿範鑳屾櫙濡備綍锛?,
            [
                "鍑犱箮娌℃湁缂栫▼鍩虹",
                "瀛﹁繃鍩虹缂栫▼",
                "瀛﹁繃鏈哄櫒瀛︿範鎴栨繁搴﹀涔犲熀纭€",
                "鏈夎緝澶氱浉鍏宠绋嬫垨椤圭洰缁忛獙",
            ],
            key="bg_programming_background",
        )
        st.select_slider(
            "鎮ㄥ Python 鐨勭啛鎮夌▼搴﹀浣曪紵",
            options=["闈炲父涓嶇啛鎮?, "涓嶅お鐔熸倝", "涓€鑸?, "姣旇緝鐔熸倝", "闈炲父鐔熸倝"],
            value="涓€鑸?,
            key="bg_python_familiarity",
        )
        st.select_slider(
            "鎮ㄥ娣卞害瀛︿範妗嗘灦锛堝 PyTorch銆乀ensorFlow锛夌殑鐔熸倝绋嬪害濡備綍锛?,
            options=["闈炲父涓嶇啛鎮?, "涓嶅お鐔熸倝", "涓€鑸?, "姣旇緝鐔熸倝", "闈炲父鐔熸倝"],
            value="涓€鑸?,
            key="bg_framework_familiarity",
        )
        st.radio(
            "鎮ㄦ槸鍚﹀涔犺繃娣卞害瀛︿範鐩稿叧璇剧▼锛?,
            options=["鏄?, "鍚?],
            horizontal=True,
            key="bg_dl_course_taken",
        )
        st.multiselect(
            "鎮ㄥ浠ヤ笅鍝簺涓婚鐩稿鏇寸啛鎮夛紵锛堝彲澶氶€夛級",
            options=["CNN", "RNN / LSTM", "Transformer", "浼樺寲涓庤缁冨垎鏋?, "閮戒笉澶啛鎮?],
            key="bg_familiar_topics",
        )
        col1, col2 = st.columns(2)
        back = col1.form_submit_button("杩斿洖", use_container_width=True)
        next_step = col2.form_submit_button("淇濆瓨骞跺紑濮嬬瓟棰?, use_container_width=True)
    if back:
        move_page(-1, sequence)
        st.rerun()
    if next_step:
        save_background()
        move_page(1, sequence)
        st.rerun()


def render_item(sequence: list[str], package_df: pd.DataFrame, blind_exercise_id: str) -> None:
    row = package_df.loc[
        package_df["blind_exercise_id"].astype(str) == str(blind_exercise_id)
    ].iloc[0]
    display_order = int(row.get("display_order", 0)) or 0
    total_items = len(package_df)
    st.title(f"绗?{display_order} / {total_items} 棰?)
    render_exercise(row)
    st.caption(LIKERT_CAPTION)

    with st.form(f"item_form_{blind_exercise_id}"):
        for field_name, prompt in ITEM_FIELDS:
            render_likert(prompt, f"{blind_exercise_id}_{field_name}")
        st.text_area(
            "濡傛灉鍙兘淇敼涓€涓湴鏂癸紝浣犳渶甯屾湜鏀瑰摢閲岋紵锛堝彲閫夛級",
            key=f"{blind_exercise_id}_open_comment",
        )
        col1, col2 = st.columns(2)
        back = col1.form_submit_button("涓婁竴棰?, use_container_width=True)
        next_step = col2.form_submit_button("淇濆瓨骞剁户缁?, use_container_width=True)

    if back or next_step:
        save_item(row)
        move_page(-1 if back else 1, sequence)
        st.rerun()


def render_attention(sequence: list[str]) -> None:
    st.title("娉ㄦ剰鍔涙娴?)
    st.write("涓虹‘璁ゆ偍鍦ㄨ鐪熶綔绛旓紝璇锋湰棰橀€夋嫨鈥滃悓鎰忊€濄€?)
    with st.form("attention_form"):
        st.select_slider(
            "璇烽€夋嫨鏈€绗﹀悎鐨勯€夐」",
            options=LIKERT_OPTIONS,
            value=4,
            key="attention_check_score",
            help="姝ｇ‘绛旀搴斾负 4锛堝悓鎰忥級銆?,
        )
        col1, col2 = st.columns(2)
        back = col1.form_submit_button("涓婁竴椤?, use_container_width=True)
        next_step = col2.form_submit_button("淇濆瓨骞剁户缁?, use_container_width=True)
    if back or next_step:
        save_attention()
        move_page(-1 if back else 1, sequence)
        st.rerun()


def render_batch(sequence: list[str]) -> None:
    st.title("鏁翠綋璇勪环")
    st.write("浠ヤ笅棰樼洰璇峰熀浜庝綘鍒氬垰瀹屾垚鐨勮繖涓€鎵圭粌涔犻鏁翠綋浣撻獙浣滅瓟銆?)
    st.caption(LIKERT_CAPTION)
    with st.form("batch_form"):
        for field_name, prompt in BATCH_FIELDS:
            render_likert(prompt, f"batch_{field_name}")
        st.text_area(
            "浣犲鏈棶鍗锋垨鏈壒缁冧範棰樿繕鏈変粈涔堝缓璁紵",
            key="batch_final_comment",
        )
        col1, col2 = st.columns(2)
        back = col1.form_submit_button("涓婁竴椤?, use_container_width=True)
        submit = col2.form_submit_button("鎻愪氦闂嵎", use_container_width=True)
    if back:
        move_page(-1, sequence)
        st.rerun()
    if submit:
        save_batch()
        move_page(1, sequence)
        st.rerun()


def render_success() -> None:
    if st.session_state.get("student_batch_response", {}).get("declined"):
        st.title("闂嵎宸茬粨鏉?)
        st.info("鎮ㄩ€夋嫨浜嗕笉鍚屾剰鍙備笌锛屾湰娆′笉浼氳褰曟寮忕瓟鍗枫€傛劅璋㈡煡鐪嬨€?)
        return
    st.title("鎻愪氦鎴愬姛")
    st.success("鎰熻阿鍙備笌锛屾偍鐨勯棶鍗峰凡鎻愪氦鎴愬姛銆?)
    st.write("璇峰叧闂〉闈㈠嵆鍙€?)


def render_already_submitted(package_id: str, participant_id: str) -> None:
    st.title("闂嵎宸叉彁浜?)
    st.info("杩欎釜绛斿嵎閾炬帴宸茬粡鎻愪氦杩囷紝涓嶉渶瑕侀噸澶嶅～鍐欍€?)
    st.write(f"鍙備笌鑰呯紪鍙凤細`{participant_id}`")
    st.write(f"棰樺寘缂栧彿锛歚{package_id}`")


def render_invalid_link(message: str) -> None:
    st.title("闂嵎閾炬帴鏃犳晥")
    st.error(message)
    st.write("璇疯仈绯荤爺绌惰€呰幏鍙栨纭殑涓撳睘闂嵎閾炬帴銆?)


def apply_student_page_style() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {display: none;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .block-container {max-width: 900px; padding-top: 2rem; padding-bottom: 3rem;}
        .survey-card {
            border: 1px solid #e5e7eb;
            border-radius: 16px;
            padding: 1rem 1.25rem;
            background: #ffffff;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Student Survey",
        page_icon=":memo:",
        layout="wide",
    )
    apply_student_page_style()
    init_db()

    package_id = read_package_id()
    participant_id = read_participant_id()
    if not package_id:
        render_invalid_link("褰撳墠閾炬帴缂哄皯 `package` 鍙傛暟锛屾棤娉曡繘鍏ユ寮忛棶鍗枫€?)
        st.stop()
    if not package_exists(package_id):
        render_invalid_link("褰撳墠閾炬帴涓殑 `package` 鏃犳晥銆?)
        st.stop()
    if not participant_id:
        render_invalid_link("褰撳墠閾炬帴缂哄皯 `pid` 鍙傛暟锛屾棤娉曠粦瀹氬弬涓庤€呯紪鍙枫€?)
        st.stop()
    if participant_already_submitted(participant_id):
        render_already_submitted(package_id, participant_id)
        st.stop()

    initialize_state(package_id, participant_id)
    existing_meta = get_participant_meta(participant_id)
    if existing_meta and existing_meta.get("package_id") and existing_meta["package_id"] != package_id:
        render_invalid_link("杩欎釜鍙備笌鑰呯紪鍙峰凡缁忕粦瀹氬埌鍏朵粬棰樺寘锛屼笉鑳介噸澶嶇敤浜庡綋鍓嶉摼鎺ャ€?)
        st.stop()

    package_df = load_package_items(package_id)
    if package_df.empty:
        render_invalid_link("褰撳墠棰樺寘涓虹┖锛屾殏鏃舵棤娉曚綔绛斻€?)
        st.stop()

    sequence = build_sequence(package_df)
    page_key = sequence[st.session_state["student_page_index"]]
    progress_steps = max(1, len(sequence) - 1)
    st.progress(min((st.session_state["student_page_index"] + 1) / progress_steps, 1.0))

    if page_key == WELCOME_PAGE:
        render_welcome()
    elif page_key == CONSENT_PAGE:
        render_consent(sequence)
    elif page_key == BACKGROUND_PAGE:
        render_background(sequence)
    elif page_key == ATTENTION_PAGE:
        render_attention(sequence)
    elif page_key == BATCH_PAGE:
        render_batch(sequence)
    elif page_key == SUCCESS_PAGE:
        render_success()
    else:
        render_item(sequence, package_df, page_key)


if __name__ == "__main__":
    main()

