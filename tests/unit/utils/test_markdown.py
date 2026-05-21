from src.utils.markdown import MarkdownConverter


class FakeMarkItDown:
    def convert_stream(self, stream, file_extension=None, url=None):
        body = stream.read().decode("utf-8")
        assert "<h1>Hello</h1>" in body
        assert file_extension == ".html"
        assert url == "https://example.com"

        class Result:
            text_content = "# Hello"

        return Result()


def test_markdown_converter_uses_binary_stream():
    converter = MarkdownConverter(markitdown=FakeMarkItDown())

    assert converter.html_to_markdown("<h1>Hello</h1>", "https://example.com") == "# Hello"
