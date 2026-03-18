from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from supabase import Client, create_client


PROJECT_ROOT = Path(__file__).resolve().parent
CURATED_PACKET_DIR = PROJECT_ROOT / "results" / "curated" / "human_eval_packets"
STUDENT_PACKAGES_DIR = CURATED_PACKET_DIR / "student_packages"
STUDENT_PACKAGE_MANIFEST = (
    CURATED_PACKET_DIR / "student_package_manifest.curated.v1.csv"
)
EXPORT_DIR = PROJECT_ROOT / "data" / "human_eval"
STUDENT_META_EXPORT = EXPORT_DIR / "student_meta.csv"
STUDENT_RATINGS_EXPORT = EXPORT_DIR / "student_ratings.csv"
STUDENT_BATCH_EXPORT = EXPORT_DIR / "student_batch.csv"

PARTICIPANT_META_TABLE = "participant_meta"
ITEM_RATINGS_TABLE = "item_ratings"
BATCH_FEEDBACK_TABLE = "batch_feedback"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_participant_id() -> str:
    return (
        f"STU-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
        f"{uuid.uuid4().hex[:6].upper()}"
    )


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_package_manifest() -> pd.DataFrame:
    return read_csv(STUDENT_PACKAGE_MANIFEST)


def package_exists(package_id: str) -> bool:
    manifest = load_package_manifest()
    if manifest.empty or "package_id" not in manifest.columns:
        return False
    return package_id in manifest["package_id"].astype(str).tolist()


def load_package_items(package_id: str) -> pd.DataFrame:
    packet_path = (
        STUDENT_PACKAGES_DIR / package_id / "student_eval_packet.curated.v1.csv"
    )
    packet = read_csv(packet_path)
    if packet.empty:
        return packet
    if "display_order" in packet.columns:
        packet = packet.sort_values("display_order").reset_index(drop=True)
    return packet


def normalize_text(value: Any, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    return str(value)


def _secret_or_env(name: str) -> str:
    value = ""
    try:
        secret_value = st.secrets.get(name, "")
        if secret_value is not None:
            value = str(secret_value).strip()
    except Exception:
        value = ""
    if not value:
        value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Set it locally or in Streamlit secrets before running the survey app."
        )
    return value


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    url = _secret_or_env("SUPABASE_URL")
    key = ""
    for name in ["SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY", "SUPABASE_ANON_KEY"]:
        try:
            key = _secret_or_env(name)
            if key:
                break
        except RuntimeError:
            continue
    if not key:
        raise RuntimeError(
            "Missing Supabase API key. Set SUPABASE_SERVICE_ROLE_KEY "
            "(recommended for server-side use) or SUPABASE_KEY."
        )
    return create_client(url, key)


def init_db() -> None:
    # Supabase tables are expected to be created ahead of time via SQL.
    get_supabase_client()


def _fetch_all_rows(table_name: str, page_size: int = 1000) -> list[dict[str, Any]]:
    client = get_supabase_client()
    offset = 0
    rows: list[dict[str, Any]] = []
    while True:
        response = (
            client.table(table_name)
            .select("*")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def get_participant_meta(participant_id: str) -> dict[str, Any] | None:
    init_db()
    response = (
        get_supabase_client()
        .table(PARTICIPANT_META_TABLE)
        .select("*")
        .eq("participant_id", participant_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def participant_already_submitted(participant_id: str) -> bool:
    record = get_participant_meta(participant_id)
    if not record:
        return False
    submitted_at = record.get("submitted_at")
    return bool(submitted_at and str(submitted_at).strip())


def upsert_participant_meta(payload: dict[str, Any]) -> None:
    init_db()
    timestamp = now_iso()
    row = {
        "participant_id": payload["participant_id"],
        "package_id": payload["package_id"],
        "consent": payload.get("consent", ""),
        "study_stage": payload.get("study_stage", ""),
        "programming_background": payload.get("programming_background", ""),
        "python_familiarity": payload.get("python_familiarity", ""),
        "framework_familiarity": payload.get("framework_familiarity", ""),
        "dl_course_taken": payload.get("dl_course_taken", ""),
        "familiar_topics": payload.get("familiar_topics", ""),
        "started_at": payload.get("started_at", timestamp),
        "submitted_at": payload.get("submitted_at"),
        "attention_check_score": payload.get("attention_check_score"),
        "attention_check_passed": payload.get("attention_check_passed"),
        "created_at": payload.get("created_at", timestamp),
        "updated_at": timestamp,
    }
    (
        get_supabase_client()
        .table(PARTICIPANT_META_TABLE)
        .upsert(row, on_conflict="participant_id")
        .execute()
    )


def upsert_item_rating(payload: dict[str, Any]) -> None:
    init_db()
    row = {
        "participant_id": payload["participant_id"],
        "package_id": payload["package_id"],
        "blind_exercise_id": payload["blind_exercise_id"],
        "item_order": payload.get("item_order"),
        "task_goal_clarity": payload.get("task_goal_clarity"),
        "key_support": payload.get("key_support"),
        "course_relevance": payload.get("course_relevance"),
        "learning_help": payload.get("learning_help"),
        "info_load": payload.get("info_load"),
        "search_effort": payload.get("search_effort"),
        "active_engagement": payload.get("active_engagement"),
        "mental_effort": payload.get("mental_effort"),
        "open_comment": payload.get("open_comment", ""),
        "saved_at": payload.get("saved_at", now_iso()),
    }
    (
        get_supabase_client()
        .table(ITEM_RATINGS_TABLE)
        .upsert(row, on_conflict="participant_id,blind_exercise_id")
        .execute()
    )


def upsert_batch_feedback(payload: dict[str, Any]) -> None:
    init_db()
    row = {
        "participant_id": payload["participant_id"],
        "package_id": payload["package_id"],
        "overall_usefulness": payload.get("overall_usefulness"),
        "overall_ease": payload.get("overall_ease"),
        "continued_use_intention": payload.get("continued_use_intention"),
        "overall_quality": payload.get("overall_quality"),
        "final_comment": payload.get("final_comment", ""),
        "rating_time_seconds": payload.get("rating_time_seconds"),
        "saved_at": payload.get("saved_at", now_iso()),
    }
    (
        get_supabase_client()
        .table(BATCH_FEEDBACK_TABLE)
        .upsert(row, on_conflict="participant_id")
        .execute()
    )


def export_csvs() -> dict[str, Path]:
    init_db()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    meta_df = pd.DataFrame(_fetch_all_rows(PARTICIPANT_META_TABLE))
    item_df = pd.DataFrame(_fetch_all_rows(ITEM_RATINGS_TABLE))
    batch_df = pd.DataFrame(_fetch_all_rows(BATCH_FEEDBACK_TABLE))

    meta_export = pd.DataFrame(
        columns=[
            "participant_id",
            "package_id",
            "consent",
            "study_stage",
            "programming_background",
            "python_familiarity",
            "framework_familiarity",
            "dl_course_taken",
            "familiar_topics",
            "started_at",
            "submitted_at",
            "attention_check_passed",
        ]
    )
    if not meta_df.empty:
        meta_export = meta_df[
            [
                "participant_id",
                "package_id",
                "consent",
                "study_stage",
                "programming_background",
                "python_familiarity",
                "framework_familiarity",
                "dl_course_taken",
                "familiar_topics",
                "started_at",
                "submitted_at",
                "attention_check_passed",
            ]
        ]

    ratings_export = pd.DataFrame(
        columns=[
            "rating_id",
            "student_id",
            "blind_exercise_id",
            "task_goal_clarity",
            "key_support",
            "course_relevance",
            "learning_help",
            "info_load",
            "search_effort",
            "active_engagement",
            "mental_effort",
            "open_comment",
            "goal_orientation",
            "support_sufficiency",
            "learning_helpfulness",
            "intrinsic_load",
            "extraneous_load",
            "notes",
            "dataset_split",
        ]
    )
    if not item_df.empty:
        ratings_export = item_df.rename(
            columns={
                "participant_id": "student_id",
                "open_comment": "notes",
                "task_goal_clarity": "goal_orientation",
                "key_support": "support_sufficiency",
                "learning_help": "learning_helpfulness",
                "info_load": "intrinsic_load",
                "search_effort": "extraneous_load",
            }
        )
        ratings_export["rating_id"] = ratings_export.apply(
            lambda row: f"{row['student_id']}__{row['blind_exercise_id']}",
            axis=1,
        )
        ratings_export["dataset_split"] = "formal"
        ratings_export["task_goal_clarity"] = ratings_export["goal_orientation"]
        ratings_export["key_support"] = ratings_export["support_sufficiency"]
        ratings_export["learning_help"] = ratings_export["learning_helpfulness"]
        ratings_export["info_load"] = ratings_export["intrinsic_load"]
        ratings_export["search_effort"] = ratings_export["extraneous_load"]
        ratings_export["open_comment"] = ratings_export["notes"]
        ratings_export = ratings_export[
            [
                "rating_id",
                "student_id",
                "blind_exercise_id",
                "task_goal_clarity",
                "key_support",
                "course_relevance",
                "learning_help",
                "info_load",
                "search_effort",
                "active_engagement",
                "mental_effort",
                "open_comment",
                "goal_orientation",
                "support_sufficiency",
                "course_relevance",
                "learning_helpfulness",
                "intrinsic_load",
                "extraneous_load",
                "active_engagement",
                "mental_effort",
                "notes",
                "dataset_split",
            ]
        ]

    batch_export = pd.DataFrame(
        columns=[
            "student_id",
            "package_id",
            "overall_usefulness",
            "overall_ease",
            "continued_use_intention",
            "overall_quality",
            "overall_batch_quality",
            "questionnaire_suggestions",
            "rating_time_seconds",
            "tam_usefulness",
            "tam_ease_of_use",
            "tam_behavioral_intention",
        ]
    )
    if not batch_df.empty:
        batch_export = batch_df.rename(
            columns={
                "participant_id": "student_id",
                "final_comment": "questionnaire_suggestions",
                "overall_usefulness": "tam_usefulness",
                "overall_ease": "tam_ease_of_use",
                "continued_use_intention": "tam_behavioral_intention",
                "overall_quality": "overall_batch_quality",
            }
        )
        batch_export["overall_usefulness"] = batch_export["tam_usefulness"]
        batch_export["overall_ease"] = batch_export["tam_ease_of_use"]
        batch_export["continued_use_intention"] = batch_export[
            "tam_behavioral_intention"
        ]
        batch_export["overall_quality"] = batch_export["overall_batch_quality"]
        batch_export = batch_export[
            [
                "student_id",
                "package_id",
                "overall_usefulness",
                "overall_ease",
                "continued_use_intention",
                "overall_quality",
                "overall_batch_quality",
                "questionnaire_suggestions",
                "rating_time_seconds",
                "tam_usefulness",
                "tam_ease_of_use",
                "tam_behavioral_intention",
            ]
        ]

    meta_export.to_csv(STUDENT_META_EXPORT, index=False, encoding="utf-8-sig")
    ratings_export.to_csv(STUDENT_RATINGS_EXPORT, index=False, encoding="utf-8-sig")
    batch_export.to_csv(STUDENT_BATCH_EXPORT, index=False, encoding="utf-8-sig")

    return {
        "student_meta": STUDENT_META_EXPORT,
        "student_ratings": STUDENT_RATINGS_EXPORT,
        "student_batch": STUDENT_BATCH_EXPORT,
    }
