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
    ("task_goal_clarity", "这道题清楚说明了我需要完成的任务目标。"),
    ("key_support", "这道题提供了开始作答所需的关键信息与支持。"),
    ("course_relevance", "这道题与深度学习课程内容或实际编程任务相关。"),
    ("learning_help", "这道题对我的学习有明显帮助。"),
    ("info_load", "完成这道题时，我需要同时处理很多信息。"),
    ("search_effort", "阅读这道题时，我需要额外花力气去找出最重要的信息。"),
    ("active_engagement", "完成这道题时，我会主动投入思考和理解。"),
    ("mental_effort", "总体来说，完成这道题需要我投入较高的心理努力。"),
]

BATCH_FIELDS = [
    ("overall_usefulness", "这批练习题有助于提高我对深度学习知识的理解。"),
    ("overall_ease", "整体上，这批练习题比较容易上手。"),
    ("continued_use_intention", "如果后续课程继续使用这类练习题，我愿意继续使用。"),
    ("overall_quality", "总体而言，这批练习题的质量较高。"),
]

WELCOME_PAGE = "welcome"
CONSENT_PAGE = "consent"
BACKGROUND_PAGE = "background"
ATTENTION_PAGE = "attention"
BATCH_PAGE = "batch"
SUCCESS_PAGE = "success"
LIKERT_OPTIONS = [1, 2, 3, 4, 5]
LIKERT_HELP = "1 = 非常不同意，5 = 非常同意"
LIKERT_LABELS = {
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
}


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


def read_language() -> str:
    language_value = st.query_params.get("lang")
    if isinstance(language_value, list):
        language_value = language_value[0]
    language = str(language_value or "").strip()
    return language or "zh-CN"


def build_sequence(package_df: pd.DataFrame) -> list[str]:
    item_ids = package_df["blind_exercise_id"].astype(str).tolist()
    sequence = [WELCOME_PAGE, CONSENT_PAGE, BACKGROUND_PAGE]
    if item_ids:
        sequence.extend(item_ids[:3])
        sequence.append(ATTENTION_PAGE)
        sequence.extend(item_ids[3:])
    else:
        sequence.append(ATTENTION_PAGE)
    sequence.extend([BATCH_PAGE, SUCCESS_PAGE])
    return sequence


def move_page(delta: int, sequence: list[str]) -> None:
    next_index = max(0, min(st.session_state["student_page_index"] + delta, len(sequence) - 1))
    st.session_state["student_page_index"] = next_index


def render_exercise(row: pd.Series) -> None:
    st.markdown(f"**练习编号：** {normalize_text(row.get('blind_exercise_id'), '未编号')}")
    st.markdown(f"**主题：** {normalize_text(row.get('topic'), '未标注')}")
    st.markdown(f"**题目标题：** {normalize_text(row.get('title'), '无标题')}")
    st.markdown("**题目描述：**")
    st.write(normalize_text(row.get("instruction_text"), "无"))
    st.markdown("**输入输出要求：**")
    st.write(normalize_text(row.get("expected_output"), "无"))
    st.markdown("**约束条件：**")
    st.write(normalize_text(row.get("constraints_text"), "无"))
    st.markdown("**起始代码（如有）：**")
    starter_code = normalize_text(row.get("starter_code"))
    if starter_code.strip():
        st.code(starter_code, language="python")
    else:
        st.write("无")
    st.markdown("**测试样例（如有）：**")
    st.write(normalize_text(row.get("test_cases_text"), "无"))


def render_likert(prompt: str, key: str, *, missing: bool = False) -> None:
    if missing:
        st.caption(":red[这一项还没有作答，请补充后继续。]")
    st.radio(
        prompt,
        options=LIKERT_OPTIONS,
        index=None,
        key=key,
        help=LIKERT_HELP,
        horizontal=True,
        format_func=lambda value: LIKERT_LABELS[value],
    )


def is_likert_answered(key: str) -> bool:
    return st.session_state.get(key) in LIKERT_OPTIONS


def clear_missing_state(*keys: str) -> None:
    for key in keys:
        st.session_state.pop(key, None)


def save_background() -> None:
    payload = {
        "participant_id": st.session_state["student_participant_id"],
        "package_id": st.session_state["student_package_id"],
        "consent": "是",
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
        "final_comment": st.session_state.get("batch_final_comment", "").strip(),
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
    st.title("深度学习练习题学习体验评估问卷（学生版）")
    st.write("您好！本问卷用于了解学生对深度学习练习题的学习体验与评价。")
    st.write("问卷匿名填写，仅用于学术研究。整个问卷预计需要 8-12 分钟。")
    st.write("请根据题目本身作答，不必猜测题目来源。")
    st.info("本链接已经为您固定了题包，请在同一设备完成填写。")
    st.caption("当前默认显示简体中文题面。如需查看英文原版，可在链接后加上 `&lang=en`。")
    if st.button("开始填写", use_container_width=True):
        st.session_state["student_page_index"] = 1
        st.rerun()


def render_consent(sequence: list[str]) -> None:
    st.title("知情同意")
    choice = st.radio("您是否知情同意参与本研究？", ["是", "否"], horizontal=True)
    col1, col2 = st.columns(2)
    back = col1.button("返回", use_container_width=True)
    next_step = col2.button("继续", use_container_width=True)
    if back:
        move_page(-1, sequence)
        st.rerun()
    if next_step:
        if choice != "是":
            st.session_state["student_batch_response"] = {"declined": True}
            st.session_state["student_page_index"] = len(sequence) - 1
            st.rerun()
        move_page(1, sequence)
        st.rerun()


def render_background(sequence: list[str]) -> None:
    st.title("背景信息")
    with st.form("background_form"):
        st.selectbox(
            "您目前所处的学习阶段是？",
            ["本科低年级", "本科高年级", "硕士研究生", "博士研究生", "其他"],
            key="bg_study_stage",
        )
        st.selectbox(
            "您的编程学习背景如何？",
            ["几乎没有编程基础", "学过基础编程", "学过机器学习或深度学习基础", "有较多相关课程或项目经验"],
            key="bg_programming_background",
        )
        st.radio(
            "您对 Python 的熟悉程度如何？",
            options=["非常不熟悉", "不太熟悉", "一般", "比较熟悉", "非常熟悉"],
            index=None,
            key="bg_python_familiarity",
            horizontal=True,
        )
        st.radio(
            "您对深度学习框架（如 PyTorch、TensorFlow）的熟悉程度如何？",
            options=["非常不熟悉", "不太熟悉", "一般", "比较熟悉", "非常熟悉"],
            index=None,
            key="bg_framework_familiarity",
            horizontal=True,
        )
        st.radio(
            "您是否学习过深度学习相关课程？",
            options=["是", "否"],
            index=None,
            horizontal=True,
            key="bg_dl_course_taken",
        )
        st.multiselect(
            "您对以下哪些主题相对更熟悉？（可多选）",
            options=["CNN", "RNN / LSTM", "Transformer", "优化与训练分析", "都不太熟悉"],
            key="bg_familiar_topics",
        )
        col1, col2 = st.columns(2)
        back = col1.form_submit_button("返回", use_container_width=True)
        next_step = col2.form_submit_button("保存并开始答题", use_container_width=True)
    if back:
        move_page(-1, sequence)
        st.rerun()
    if next_step:
        missing_fields = []
        if not st.session_state.get("bg_study_stage"):
            missing_fields.append("学习阶段")
        if not st.session_state.get("bg_programming_background"):
            missing_fields.append("编程背景")
        if not st.session_state.get("bg_python_familiarity"):
            missing_fields.append("Python 熟悉程度")
        if not st.session_state.get("bg_framework_familiarity"):
            missing_fields.append("深度学习框架熟悉程度")
        if not st.session_state.get("bg_dl_course_taken"):
            missing_fields.append("是否学过深度学习课程")
        if not st.session_state.get("bg_familiar_topics"):
            missing_fields.append("熟悉主题")
        if missing_fields:
            st.warning(f"请先完成这些必答项：{'、'.join(missing_fields)}")
            return
        save_background()
        move_page(1, sequence)
        st.rerun()


def render_item(sequence: list[str], package_df: pd.DataFrame, blind_exercise_id: str) -> None:
    row = package_df.loc[package_df["blind_exercise_id"].astype(str) == str(blind_exercise_id)].iloc[0]
    display_order = int(row.get("display_order", 0)) or 0
    total_items = len(package_df)
    missing_fields = set(st.session_state.get(f"{blind_exercise_id}_missing_fields", []))
    st.title(f"练习 {display_order} / {total_items}")
    render_exercise(row)
    st.caption(LIKERT_HELP)
    if missing_fields:
        st.info("还有少量评分题未完成，我已经在对应题目上方标出来了。")
    with st.form(f"item_form_{blind_exercise_id}"):
        for field_name, prompt in ITEM_FIELDS:
            render_likert(
                prompt,
                f"{blind_exercise_id}_{field_name}",
                missing=field_name in missing_fields,
            )
        st.text_area("如果只能修改一个地方，你最希望改哪里？（可选）", key=f"{blind_exercise_id}_open_comment")
        col1, col2 = st.columns(2)
        back = col1.form_submit_button("上一题", use_container_width=True)
        next_step = col2.form_submit_button("保存并继续", use_container_width=True)
    if back:
        clear_missing_state(f"{blind_exercise_id}_missing_fields")
        move_page(-1, sequence)
        st.rerun()
    if next_step:
        missing_field_names = [
            field_name
            for field_name, prompt in ITEM_FIELDS
            if not is_likert_answered(f"{blind_exercise_id}_{field_name}")
        ]
        if missing_field_names:
            st.session_state[f"{blind_exercise_id}_missing_fields"] = missing_field_names
            st.rerun()
        clear_missing_state(f"{blind_exercise_id}_missing_fields")
        save_item(row)
        move_page(1, sequence)
        st.rerun()


def render_attention(sequence: list[str]) -> None:
    attention_missing = st.session_state.get("attention_missing", False)
    st.title("注意力检测")
    st.write("为确认您在认真作答，请本题选择 4 分（同意）。")
    with st.form("attention_form"):
        render_likert("请选择最符合的选项", "attention_check_score", missing=attention_missing)
        col1, col2 = st.columns(2)
        back = col1.form_submit_button("上一页", use_container_width=True)
        next_step = col2.form_submit_button("保存并继续", use_container_width=True)
    if back:
        clear_missing_state("attention_missing")
        move_page(-1, sequence)
        st.rerun()
    if next_step:
        if not is_likert_answered("attention_check_score"):
            st.session_state["attention_missing"] = True
            st.rerun()
        clear_missing_state("attention_missing")
        save_attention()
        move_page(1, sequence)
        st.rerun()


def render_batch(sequence: list[str]) -> None:
    missing_fields = set(st.session_state.get("batch_missing_fields", []))
    st.title("整体评价")
    st.write("以下题目请基于您刚刚完成的这一批练习题整体体验作答。")
    st.caption(LIKERT_HELP)
    if missing_fields:
        st.info("还有少量整体评价未完成，我已经在对应题目上方标出来了。")
    for field_name, prompt in BATCH_FIELDS:
        render_likert(prompt, f"batch_{field_name}", missing=field_name in missing_fields)
    st.text_area("你对本问卷或本批练习题还有什么建议？", key="batch_final_comment")
    back = st.button("上一页", key="batch_back", use_container_width=True)
    submit = st.button("提交问卷", key="batch_submit", type="primary", use_container_width=True)
    if back:
        clear_missing_state("batch_missing_fields")
        move_page(-1, sequence)
        st.rerun()
    if submit:
        missing_field_names = [
            field_name for field_name, prompt in BATCH_FIELDS if not is_likert_answered(f"batch_{field_name}")
        ]
        if missing_field_names:
            st.session_state["batch_missing_fields"] = missing_field_names
            st.rerun()
        clear_missing_state("batch_missing_fields")
        save_batch()
        move_page(1, sequence)
        st.rerun()

def render_success() -> None:
    if st.session_state.get("student_batch_response", {}).get("declined"):
        st.title("问卷已结束")
        st.info("您选择了不同意参与，本次不会记录正式答卷。感谢查看。")
        return
    st.title("提交成功")
    st.success("感谢参与，您的问卷已提交成功。")
    st.write("现在可以关闭页面。")


def render_already_submitted(package_id: str, participant_id: str) -> None:
    st.title("问卷已提交")
    st.info("这个答卷链接已经提交过，不需要重复填写。")
    st.write(f"参与者编号：`{participant_id}`")
    st.write(f"题包编号：`{package_id}`")


def render_invalid_link(message: str) -> None:
    st.title("问卷链接无效")
    st.error(message)
    st.write("请联系研究者获取正确的专属问卷链接。")


def apply_student_page_style() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"] {display: none;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .block-container {max-width: 900px; padding-top: 2rem; padding-bottom: 3rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="Student Survey", page_icon=":memo:", layout="wide")
    apply_student_page_style()
    init_db()
    package_id = read_package_id()
    participant_id = read_participant_id()
    language = read_language()
    if not package_id:
        render_invalid_link("当前链接缺少 package 参数，无法进入正式问卷。")
        st.stop()
    if not package_exists(package_id):
        render_invalid_link("当前链接中的 package 无效。")
        st.stop()
    if not participant_id:
        render_invalid_link("当前链接缺少 pid 参数，无法绑定参与者编号。")
        st.stop()
    if participant_already_submitted(participant_id):
        render_already_submitted(package_id, participant_id)
        st.stop()
    initialize_state(package_id, participant_id)
    existing_meta = get_participant_meta(participant_id)
    if existing_meta and existing_meta.get("package_id") and existing_meta["package_id"] != package_id:
        render_invalid_link("这个参与者编号已经绑定到其他题包，不能重复用于当前链接。")
        st.stop()
    package_df = load_package_items(package_id, language=language)
    if package_df.empty:
        render_invalid_link("当前题包为空，暂时无法作答。")
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



