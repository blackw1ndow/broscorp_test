CREATE EXTENSION IF NOT EXISTS vector;

-- Places: the whole forest, its 3 parts and the 8 mittens (рукавички)
CREATE TABLE places (
    code  text PRIMARY KEY,
    level text NOT NULL CHECK (level IN ('forest', 'part', 'mitten')),
    name  text NOT NULL UNIQUE
);

-- Forest map (R18): which parts of the forest a mitten belongs to
CREATE TABLE mitten_parts (
    mitten_code text NOT NULL REFERENCES places (code),
    part_code   text NOT NULL REFERENCES places (code),
    PRIMARY KEY (mitten_code, part_code)
);

INSERT INTO places (code, level, name) VALUES
    ('forest',           'forest', 'Весь ліс'),
    ('coniferous',       'part',   'Хвойний ліс'),
    ('deciduous',        'part',   'Листяний ліс'),
    ('river',            'part',   'Біля річки'),
    ('pid_yalynoyu',     'mitten', 'Під ялиною'),
    ('u_sosnakh',        'mitten', 'У соснах'),
    ('bilia_murashnyka', 'mitten', 'Біля мурашника'),
    ('pid_dubom',        'mitten', 'Під дубом'),
    ('u_lishchyni',      'mitten', 'У ліщині'),
    ('pid_verboyu',      'mitten', 'Під вербою'),
    ('bilia_hrebli',     'mitten', 'Біля бобрової греблі'),
    ('na_uzlissi',       'mitten', 'На узліссі');

INSERT INTO mitten_parts (mitten_code, part_code) VALUES
    ('pid_yalynoyu',     'coniferous'),
    ('u_sosnakh',        'coniferous'),
    ('bilia_murashnyka', 'coniferous'),
    ('pid_dubom',        'deciduous'),
    ('u_lishchyni',      'deciduous'),
    ('pid_verboyu',      'deciduous'),
    ('pid_verboyu',      'river'),
    ('bilia_hrebli',     'river');
    -- 'na_uzlissi' belongs to no part of the forest

CREATE TABLE users (
    telegram_id  bigint PRIMARY KEY,
    display_name text,                                  -- "справжнє ім'я" (R15)
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id           bigserial PRIMARY KEY,
    title        text NOT NULL,
    doc_type     text NOT NULL,                         -- title without the place (D24)
    place_code   text NOT NULL REFERENCES places (code),
    source       text NOT NULL CHECK (source IN ('archive', 'user')),
    author_id    bigint REFERENCES users (telegram_id), -- NULL for the archive (D20)
    file_name    text NOT NULL,
    file_sha256  text NOT NULL,
    extraction   text NOT NULL CHECK (extraction IN ('text', 'ocr')),
    full_text    text NOT NULL,
    status       text NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active', 'superseded', 'deleted')),
    replaces_id  bigint REFERENCES documents (id),
    uploaded_at  timestamptz NOT NULL,                  -- archive: 2026-10-13 (D13)
    CHECK (source = 'archive' OR author_id IS NOT NULL)
);

-- At most one active document of a type per place (R11)
CREATE UNIQUE INDEX documents_one_active_version
    ON documents (doc_type, place_code) WHERE status = 'active';
CREATE UNIQUE INDEX documents_archive_file
    ON documents (file_sha256) WHERE source = 'archive';
CREATE INDEX documents_author ON documents (author_id) WHERE status = 'active';

CREATE TABLE chunks (
    id          bigserial PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    position    int NOT NULL,
    content     text NOT NULL,
    embedding   vector(384) NOT NULL,
    UNIQUE (document_id, position)
);
-- Hundreds of documents, not millions: exact search beats an ANN index here.

-- Short conversation history for follow-up questions (D8)
CREATE TABLE messages (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users (telegram_id),
    role       text NOT NULL CHECK (role IN ('user', 'assistant')),
    content    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_user_time ON messages (user_id, created_at DESC);

-- aiogram FSM state (waiting for a name / a place), survives restarts
CREATE TABLE fsm_state (
    key   text PRIMARY KEY,
    state text,
    data  jsonb NOT NULL DEFAULT '{}'
);
