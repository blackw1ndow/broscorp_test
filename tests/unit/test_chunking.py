from forest_bot.ingestion.chunking import SINGLE_CHUNK_MAX_CHARS, TARGET_CHUNK_CHARS, chunk_text


def test_short_document_is_one_chunk_with_title_once():
    chunks = chunk_text("Правила толоки", "Правила толоки\n\nТолоку скликає Мишка.")
    assert chunks == ["Правила толоки\n\nТолоку скликає Мишка."]


def test_long_document_is_split_and_every_chunk_has_the_title():
    paragraphs = [f"Порада номер {i}. " + "Гриби шукай після дощу. " * 12 for i in range(12)]
    text = "\n\n".join(paragraphs)
    assert len(text) > SINGLE_CHUNK_MAX_CHARS

    chunks = chunk_text("Великий путівник", text)

    assert len(chunks) > 1
    assert all(chunk.startswith("Великий путівник\n\n") for chunk in chunks)
    assert all(len(chunk) < TARGET_CHUNK_CHARS * 2 for chunk in chunks)
    for i in range(12):
        assert any(f"Порада номер {i}." in chunk for chunk in chunks)


def test_huge_paragraph_is_split_by_sentences():
    text = "Речення про ліс. " * 300
    chunks = chunk_text("Т", text)
    assert len(chunks) > 1
    assert all(len(chunk) < TARGET_CHUNK_CHARS * 2 for chunk in chunks)


def test_table_without_punctuation_is_still_split():
    # Review #4: a DOCX table joins rows with single newlines and has no sentence ends.
    # One huge chunk would push the answer prompt past Groq's request limit.
    rows = [
        f"Рукавичка {i} | Чергує Кабан | Приносить 3 жолуді | Щосуботи зранку" for i in range(200)
    ]
    chunks = chunk_text("Графік", "\n".join(rows))
    assert len(chunks) > 1
    assert all(len(chunk) < TARGET_CHUNK_CHARS * 2 for chunk in chunks)
    for i in (0, 99, 199):
        assert any(f"Рукавичка {i} |" in chunk for chunk in chunks)


def test_text_without_any_spaces_is_still_split():
    chunks = chunk_text("Т", "ґ" * 10_000)
    assert all(len(chunk) < TARGET_CHUNK_CHARS * 2 for chunk in chunks)
    assert sum(chunk.count("ґ") for chunk in chunks) >= 10_000
