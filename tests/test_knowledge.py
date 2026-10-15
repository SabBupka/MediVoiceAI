from app.knowledge import LocalKnowledgeBase


def knowledge_base():
    return LocalKnowledgeBase(
        "docs_tz/registrature_reglament.docx",
        [
            "docs_tz/tz_kratkoe.txt",
            "docs_tz/tz_voice_assistant.txt",
            "docs_tz/openapi.json",
        ],
    )


def test_docx_table_rows_are_loaded_as_contextual_chunks():
    kb = knowledge_base()
    found = [
        chunk for chunk in kb.chunks
        if "Подразделение / услуга: Поликлиника" in chunk.text
    ]
    assert found
    assert found[0].source_status == "conditional_example"


def test_dynamic_address_is_not_given_without_registry_verification():
    result = knowledge_base().answer("Какой адрес поликлиники?")
    assert result["found"] is False
    assert result["requires_verification"] is True
    assert result["sources"]


def test_unmatched_question_escalates_without_invented_answer():
    result = knowledge_base().answer("Есть ли у клиники вертолётная площадка?")
    assert result["found"] is False
    assert result["grounded"] is False
    assert result["sources"] == []
    assert "не найден" in result["answer"].lower()


def test_returned_fact_is_verbatim_and_has_source_metadata():
    result = knowledge_base().answer("Как отключить запись разговора?")
    assert result["found"] is True
    assert "отключена" in result["answer"]
    assert result["sources"][0]["source"].endswith(".docx")
    assert result["sources"][0]["score"] > 0


def test_dynamic_or_placeholder_price_is_not_presented_as_fact():
    result = knowledge_base().answer("Сколько стоит УЗИ?")
    assert result["found"] is False
    assert result["requires_verification"] is True


def test_manifest_indexes_reference_requirements_and_openapi():
    manifest = knowledge_base().manifest()
    assert manifest["mode"] == "extractive-local-rag"
    assert manifest["chunks"] > 900
    assert set(manifest["documents"]) == {
        "docs_tz/registrature_reglament.docx",
        "docs_tz/tz_kratkoe.txt",
        "docs_tz/tz_voice_assistant.txt",
        "docs_tz/openapi.json",
    }
