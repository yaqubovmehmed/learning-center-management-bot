-- Excellence LC boshqaruv boti sxemasi (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id      INTEGER NOT NULL UNIQUE,
    role       TEXT NOT NULL CHECK (role IN ('superadmin', 'admin', 'teacher', 'parent')),
    full_name  TEXT NOT NULL,
    username   TEXT,
    phone      TEXT,
    language   TEXT NOT NULL DEFAULT 'uz',
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    last_seen  TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role, is_active);

CREATE TABLE IF NOT EXISTS teachers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
    name       TEXT NOT NULL,
    phone      TEXT,
    subject    TEXT NOT NULL DEFAULT 'English',
    hired_at   TEXT,
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes      TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_teachers_active ON teachers(is_active);

CREATE TABLE IF NOT EXISTS groups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    course       TEXT,
    level        TEXT,
    teacher_id   INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    room         TEXT,
    days         TEXT NOT NULL DEFAULT '',          -- 'mon,wed,fri'
    time         TEXT,                              -- '18:00'
    duration_min INTEGER NOT NULL DEFAULT 90,
    start_date   TEXT,
    end_date     TEXT,
    monthly_fee  INTEGER,
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    notes        TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_groups_teacher ON groups(teacher_id, status);

CREATE TABLE IF NOT EXISTS students (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name  TEXT NOT NULL,
    phone      TEXT,
    birth_date TEXT,
    group_id   INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    status     TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'frozen', 'left')),
    joined_at  TEXT,
    left_at    TEXT,
    notes      TEXT,
    created_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_students_group ON students(group_id, status);
CREATE INDEX IF NOT EXISTS idx_students_name ON students(full_name);

CREATE TABLE IF NOT EXISTS parents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
    full_name    TEXT NOT NULL,
    phone        TEXT NOT NULL UNIQUE,
    language     TEXT NOT NULL DEFAULT 'uz',
    notif_absent INTEGER NOT NULL DEFAULT 1 CHECK (notif_absent IN (0, 1)),
    notif_late   INTEGER NOT NULL DEFAULT 1 CHECK (notif_late IN (0, 1)),
    notif_results INTEGER NOT NULL DEFAULT 1 CHECK (notif_results IN (0, 1)),
    notif_weekly INTEGER NOT NULL DEFAULT 1 CHECK (notif_weekly IN (0, 1)),
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS student_parents (
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    parent_id  INTEGER NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    relation   TEXT NOT NULL DEFAULT 'ota-ona',
    is_primary INTEGER NOT NULL DEFAULT 1 CHECK (is_primary IN (0, 1)),
    PRIMARY KEY (student_id, parent_id)
);
CREATE INDEX IF NOT EXISTS idx_sp_parent ON student_parents(parent_id);

CREATE TABLE IF NOT EXISTS invites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    role       TEXT NOT NULL CHECK (role IN ('teacher', 'parent')),
    target_id  INTEGER NOT NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    used_by    INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_invites_target ON invites(role, target_id, used_at);

CREATE TABLE IF NOT EXISTS lessons (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id   INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    teacher_id INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    date       TEXT NOT NULL,                       -- YYYY-MM-DD (markaz vaqti)
    topic      TEXT,
    status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_at TEXT NOT NULL,
    UNIQUE (group_id, date)
);
CREATE INDEX IF NOT EXISTS idx_lessons_date ON lessons(date);

CREATE TABLE IF NOT EXISTS attendance (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lesson_id    INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    student_id   INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'present'
                 CHECK (status IN ('present', 'absent', 'late', 'excused')),
    check_in     TEXT,
    check_out    TEXT,
    minutes_late INTEGER NOT NULL DEFAULT 0,
    note         TEXT,
    marked_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    marked_at    TEXT NOT NULL,
    UNIQUE (lesson_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_att_student ON attendance(student_id);

CREATE TABLE IF NOT EXISTS tests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id     INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    teacher_id   INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    title        TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'test'
                 CHECK (kind IN ('test', 'mock', 'quiz', 'exam')),
    date         TEXT NOT NULL,
    max_score    REAL NOT NULL DEFAULT 100 CHECK (max_score > 0),
    scale        TEXT NOT NULL DEFAULT 'percent'
                 CHECK (scale IN ('percent', 'ielts', 'cefr')),
    notes        TEXT,
    published_at TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tests_group ON tests(group_id, date);

CREATE TABLE IF NOT EXISTS test_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id    INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    score      REAL,
    band       REAL,
    is_absent  INTEGER NOT NULL DEFAULT 0 CHECK (is_absent IN (0, 1)),
    note       TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (test_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_results_student ON test_results(student_id);

CREATE TABLE IF NOT EXISTS absence_reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    parent_id  INTEGER REFERENCES parents(id) ON DELETE SET NULL,
    date       TEXT NOT NULL,
    reason     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'seen')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_absence_reports_date ON absence_reports(date, status);

CREATE TABLE IF NOT EXISTS outbox (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    recipient_tg INTEGER NOT NULL,
    parent_id    INTEGER REFERENCES parents(id) ON DELETE SET NULL,
    student_id   INTEGER REFERENCES students(id) ON DELETE SET NULL,
    dedupe_key   TEXT UNIQUE,
    text         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    created_at   TEXT NOT NULL,
    next_try_at  TEXT NOT NULL,
    sent_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_ready ON outbox(status, next_try_at);
CREATE INDEX IF NOT EXISTS idx_outbox_created ON outbox(created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id    INTEGER,
    actor_tg    INTEGER,
    action      TEXT NOT NULL,
    target_type TEXT,
    target_id   TEXT,
    details     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

PRAGMA user_version = 1;
