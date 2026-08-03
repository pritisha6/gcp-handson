"""Unit tests for DocumentProcessor."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.services.document_processor import DocumentProcessor
from app.utils.errors import DocumentProcessingError, FileTooLargeError, UnsupportedFileTypeError


@pytest.fixture
def settings() -> Settings:
    return Settings(
        GROQ_API_KEY="k",
        GCP_PROJECT_ID="p",
        PINECONE_API_KEY="k",
        OPENAI_API_KEY="k",
        CHUNK_SIZE_TOKENS=512,
        CHUNK_OVERLAP_TOKENS=50,
        MAX_UPLOAD_FILE_SIZE_MB=500,
    )


@pytest.fixture
def pinecone_client() -> MagicMock:
    mock = MagicMock()
    mock.upsert_documents.return_value = []
    return mock


@pytest.fixture
def processor(pinecone_client: MagicMock, settings: Settings) -> DocumentProcessor:
    return DocumentProcessor(pinecone_client=pinecone_client, settings=settings)


# --- Chunking ---


def test_chunk_text_respects_target_size(processor: DocumentProcessor):
    text = " ".join(f"word{i}" for i in range(2000))
    windows = processor._chunk_text(text, chunk_size=512, overlap=50)

    assert len(windows) > 1
    for chunk_text, token_count in windows[:-1]:
        assert token_count == 512
        assert processor._encoding.decode(processor._encoding.encode(chunk_text)) == chunk_text


def test_chunk_text_overlap_between_consecutive_windows(processor: DocumentProcessor):
    text = " ".join(f"word{i}" for i in range(2000))
    windows = processor._chunk_text(text, chunk_size=512, overlap=50)

    first_tokens = processor._encoding.encode(windows[0][0])
    second_tokens = processor._encoding.encode(windows[1][0])
    # The last `overlap` tokens of window 0 should equal the first `overlap` tokens of window 1.
    assert first_tokens[-50:] == second_tokens[:50]


def test_chunk_text_empty_string_returns_no_chunks(processor: DocumentProcessor):
    assert processor._chunk_text("", chunk_size=512, overlap=50) == []


def test_chunk_text_short_text_returns_single_chunk(processor: DocumentProcessor):
    windows = processor._chunk_text("hello world", chunk_size=512, overlap=50)
    assert len(windows) == 1
    assert windows[0][0] == "hello world"


# --- Format-specific extraction (mocked libraries) ---


def test_process_pdf_extracts_text_per_page(processor: DocumentProcessor, tmp_path):
    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    fake_pages = [SimpleNamespace(extract_text=lambda: "Page one text"), SimpleNamespace(extract_text=lambda: "")]
    with patch("app.services.document_processor.PdfReader") as mock_reader:
        mock_reader.return_value = SimpleNamespace(pages=fake_pages)
        result = processor.process_pdf(str(file_path))

    assert result == ["Page one text", ""]


def test_process_pdf_raises_on_corrupt_file(processor: DocumentProcessor, tmp_path):
    file_path = tmp_path / "corrupt.pdf"
    file_path.write_bytes(b"not a real pdf")

    with patch("app.services.document_processor.PdfReader", side_effect=ValueError("bad pdf")):
        with pytest.raises(DocumentProcessingError):
            processor.process_pdf(str(file_path))


def test_process_pptx_extracts_text_per_slide(processor: DocumentProcessor, tmp_path):
    file_path = tmp_path / "deck.pptx"
    file_path.write_bytes(b"fake pptx")

    shape = SimpleNamespace(has_text_frame=True, text_frame=SimpleNamespace(text="Slide content"))
    slide = SimpleNamespace(shapes=[shape])
    with patch("app.services.document_processor.Presentation") as mock_presentation:
        mock_presentation.return_value = SimpleNamespace(slides=[slide])
        result = processor.process_pptx(str(file_path))

    assert result == ["Slide content"]


def test_process_excel_extracts_headers_and_rows(processor: DocumentProcessor, tmp_path):
    file_path = tmp_path / "book.xlsx"
    file_path.write_bytes(b"fake xlsx")

    sheet = SimpleNamespace(
        title="Sheet1",
        iter_rows=lambda values_only: iter([("name", "size_gb"), ("orders_db", 42), (None, None)]),
    )
    fake_workbook = SimpleNamespace(worksheets=[sheet], close=lambda: None)
    with patch("app.services.document_processor.load_workbook", return_value=fake_workbook):
        result = processor.process_excel(str(file_path))

    assert result == [
        {"sheet_name": "Sheet1", "headers": ["name", "size_gb"], "rows": [{"name": "orders_db", "size_gb": 42}]}
    ]


def test_process_html_strips_scripts_and_returns_visible_text(processor: DocumentProcessor, tmp_path):
    file_path = tmp_path / "page.html"
    file_path.write_text(
        "<html><body><h1>Title</h1><script>evil()</script><p>Body text</p></body></html>",
        encoding="utf-8",
    )

    result = processor.process_html(str(file_path))

    assert "Title" in result
    assert "Body text" in result
    assert "evil()" not in result


def test_process_text_or_csv_reads_file_contents(processor: DocumentProcessor, tmp_path):
    file_path = tmp_path / "data.csv"
    file_path.write_text("a,b\n1,2\n", encoding="utf-8")

    assert processor.process_text_or_csv(str(file_path)) == "a,b\n1,2\n"


# --- File size / type guards ---


def test_check_file_size_raises_when_over_limit(pinecone_client: MagicMock, settings: Settings, tmp_path):
    settings.MAX_UPLOAD_FILE_SIZE_MB = 0
    processor = DocumentProcessor(pinecone_client=pinecone_client, settings=settings)
    file_path = tmp_path / "big.txt"
    file_path.write_text("some content", encoding="utf-8")

    with pytest.raises(FileTooLargeError):
        processor.process_text_or_csv(str(file_path))


def test_process_file_raises_for_unsupported_extension(processor: DocumentProcessor, tmp_path):
    file_path = tmp_path / "archive.zip"
    file_path.write_bytes(b"fake zip")

    with pytest.raises(UnsupportedFileTypeError):
        processor.process_file(str(file_path))


# --- Orchestration: process_file end-to-end (text path, no external libs to mock) ---


def test_process_file_builds_chunks_with_expected_structure(
    processor: DocumentProcessor, pinecone_client: MagicMock, tmp_path
):
    file_path = tmp_path / "notes.txt"
    file_path.write_text(" ".join(f"word{i}" for i in range(1200)), encoding="utf-8")

    result = processor.process_file(str(file_path))

    assert result["filename"] == "notes.txt"
    assert result["source_type"] == "txt"
    assert result["total_chunks"] == len(result["chunks"]) > 1
    assert result["warnings"] == []

    for i, chunk in enumerate(result["chunks"]):
        assert chunk.chunk_index == i
        assert chunk.chunk_id == f"{result['document_id']}-{i}"
        assert chunk.document_id == result["document_id"]
        assert chunk.token_count > 0

    # Pinecone upload was invoked with one dict per chunk.
    pinecone_client.upsert_documents.assert_called_once()
    (uploaded_chunks,), _ = pinecone_client.upsert_documents.call_args
    assert len(uploaded_chunks) == result["total_chunks"]
    assert all("chunk_id" in c and "text" in c for c in uploaded_chunks)


def test_process_file_empty_file_produces_no_chunks_and_a_warning(processor: DocumentProcessor, tmp_path):
    file_path = tmp_path / "empty.txt"
    file_path.write_text("", encoding="utf-8")

    result = processor.process_file(str(file_path))

    assert result["total_chunks"] == 0
    assert result["chunks"] == []
    assert "empty" in result["warnings"][0].lower()
