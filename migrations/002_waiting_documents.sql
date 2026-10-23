-- Documents waiting for the animal's answer (D26): one row per document, so several can wait
-- at once and a document from an album is never overwritten by the next one
CREATE TABLE waiting_documents (
    id         bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users (telegram_id),
    waits_for  text NOT NULL CHECK (waits_for IN ('name', 'place')),
    data       jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX waiting_documents_user ON waiting_documents (user_id);
