create table if not exists public.participant_meta (
    participant_id text primary key,
    package_id text not null,
    consent text,
    study_stage text,
    programming_background text,
    python_familiarity text,
    framework_familiarity text,
    dl_course_taken text,
    familiar_topics text,
    started_at timestamptz,
    submitted_at timestamptz,
    attention_check_score integer,
    attention_check_passed boolean,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.item_ratings (
    participant_id text not null references public.participant_meta(participant_id) on delete cascade,
    package_id text not null,
    blind_exercise_id text not null,
    item_order integer not null,
    task_goal_clarity integer,
    key_support integer,
    course_relevance integer,
    learning_help integer,
    info_load integer,
    search_effort integer,
    active_engagement integer,
    mental_effort integer,
    open_comment text,
    saved_at timestamptz not null default timezone('utc', now()),
    primary key (participant_id, blind_exercise_id)
);

create table if not exists public.batch_feedback (
    participant_id text primary key references public.participant_meta(participant_id) on delete cascade,
    package_id text not null,
    overall_usefulness integer,
    overall_ease integer,
    continued_use_intention integer,
    overall_quality integer,
    final_comment text,
    rating_time_seconds double precision,
    saved_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_participant_meta_package_id
    on public.participant_meta(package_id);

create index if not exists idx_item_ratings_package_id
    on public.item_ratings(package_id);

create index if not exists idx_batch_feedback_package_id
    on public.batch_feedback(package_id);
