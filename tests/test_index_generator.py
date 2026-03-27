"""Tests for index_generator module."""

import pytest
from pathlib import Path

from src.index_generator import (
    get_downloaded_episodes,
    update_episode_status,
    format_references,
    generate_index_markdown,
    save_index,
)


class TestGetDownloadedEpisodes:
    """Tests for get_downloaded_episodes function."""

    def test_empty_directory(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        numbers, titles = get_downloaded_episodes(empty_dir)
        assert len(numbers) == 0
        assert len(titles) == 0

    def test_nonexistent_directory(self, tmp_path):
        nonexistent = tmp_path / "nonexistent"
        numbers, titles = get_downloaded_episodes(nonexistent)
        assert len(numbers) == 0
        assert len(titles) == 0

    def test_extracts_regular_episode_numbers(self, transcripts_dir):
        numbers, _ = get_downloaded_episodes(transcripts_dir)
        assert "N1" in numbers
        assert "N2" in numbers
        assert "N100" in numbers

    def test_extracts_interview_numbers(self, transcripts_dir):
        numbers, _ = get_downloaded_episodes(transcripts_dir)
        assert "E1" in numbers

    def test_normalizes_titles(self, transcripts_dir):
        _, titles = get_downloaded_episodes(transcripts_dir)
        assert len(titles) > 0
        # Check that at least one title was extracted
        assert any("Naruhodo" in t or "Entrevista" in t for t in titles)

    def test_ignores_non_vtt_files(self, tmp_path):
        transcripts = tmp_path / "transcripts"
        transcripts.mkdir()
        (transcripts / "Naruhodo #99.txt").write_text("text file")
        (transcripts / "readme.md").write_text("readme")

        numbers, titles = get_downloaded_episodes(transcripts)
        assert len(numbers) == 0
        assert len(titles) == 0

    def test_handles_special_characters_in_title(self, tmp_path):
        transcripts = tmp_path / "transcripts"
        transcripts.mkdir()
        # VTT file with fullwidth punctuation (as created by downloader)
        (transcripts / "001 - Naruhodo #1 - O que é？.pt.vtt").write_text("WEBVTT")

        numbers, titles = get_downloaded_episodes(transcripts)
        assert "N1" in numbers
        # Title should normalize the fullwidth chars
        assert any("Naruhodo #1" in t for t in titles)


class TestUpdateEpisodeStatus:
    """Tests for update_episode_status function."""

    def test_matches_by_episode_number(self, transcripts_dir):
        episodes = [
            {"title": "Naruhodo #1 - First Episode", "episode_number": "1", "status": "⬜ Pending", "youtube_link": "https://youtube.com/1"},
            {"title": "Naruhodo #999 - Not Downloaded", "episode_number": "999", "status": "⬜ Pending", "youtube_link": "https://youtube.com/999"},
        ]

        downloaded, pending, no_link = update_episode_status(episodes, transcripts_dir)

        assert downloaded == 1
        assert pending == 1
        assert no_link == 0
        assert episodes[0]["status"] == "✅ Downloaded"
        assert episodes[1]["status"] == "⬜ Pending"

    def test_matches_interview(self, transcripts_dir):
        episodes = [
            {"title": "Entrevista #1: Dr. João Silva", "episode_number": "1", "status": "⬜ Pending", "youtube_link": "https://youtube.com/1"},
            {"title": "Entrevista #99: Not Downloaded", "episode_number": "99", "status": "⬜ Pending", "youtube_link": "https://youtube.com/99"},
        ]

        downloaded, pending, no_link = update_episode_status(episodes, transcripts_dir)

        assert downloaded == 1
        assert pending == 1
        assert no_link == 0
        assert episodes[0]["status"] == "✅ Downloaded"
        assert episodes[1]["status"] == "⬜ Pending"

    def test_fallback_to_title_matching(self, tmp_path):
        transcripts = tmp_path / "transcripts"
        transcripts.mkdir()
        (transcripts / "001 - Special Episode.pt.vtt").write_text("WEBVTT")

        episodes = [
            {"title": "Special Episode", "episode_number": "", "status": "⬜ Pending", "youtube_link": "https://youtube.com/1"},
        ]

        downloaded, pending, no_link = update_episode_status(episodes, transcripts)

        assert downloaded == 1
        assert episodes[0]["status"] == "✅ Downloaded"

    def test_title_matching_with_special_chars(self, tmp_path):
        transcripts = tmp_path / "transcripts"
        transcripts.mkdir()
        # File with fullwidth chars (as created by downloader)
        (transcripts / "001 - Naruhodo #1 - O que é isso？.pt.vtt").write_text("WEBVTT")

        episodes = [
            {"title": "Naruhodo #1 - O que é isso?", "episode_number": "1", "status": "⬜ Pending", "youtube_link": "https://youtube.com/1"},
        ]

        downloaded, pending, no_link = update_episode_status(episodes, transcripts)

        assert downloaded == 1

    def test_all_pending_when_no_files(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        episodes = [
            {"title": "Episode 1", "episode_number": "1", "status": "✅ Downloaded", "youtube_link": "https://youtube.com/1"},
            {"title": "Episode 2", "episode_number": "2", "status": "✅ Downloaded", "youtube_link": "https://youtube.com/2"},
        ]

        downloaded, pending, no_link = update_episode_status(episodes, empty_dir)

        assert downloaded == 0
        assert pending == 2
        assert no_link == 0

    def test_no_link_status_when_missing_youtube_link(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        episodes = [
            {"title": "Episode 1", "episode_number": "1", "status": "⬜ Pending", "youtube_link": ""},
            {"title": "Episode 2", "episode_number": "2", "status": "⬜ Pending", "youtube_link": "https://youtube.com/2"},
            {"title": "Episode 3", "episode_number": "3", "status": "⬜ Pending"},  # No youtube_link key
        ]

        downloaded, pending, no_link = update_episode_status(episodes, empty_dir)

        assert downloaded == 0
        assert pending == 1
        assert no_link == 2
        assert episodes[0]["status"] == "🔗 No Link"
        assert episodes[1]["status"] == "⬜ Pending"
        assert episodes[2]["status"] == "🔗 No Link"


class TestFormatReferences:
    """Tests for format_references function."""

    def test_empty_list(self):
        assert format_references([]) == ""

    def test_lattes_label(self):
        refs = ["https://lattes.cnpq.br/1234567890"]
        result = format_references(refs)
        assert "[Lattes]" in result
        assert "lattes.cnpq.br" in result

    def test_paper_label(self):
        refs = ["https://doi.org/10.1000/example"]
        result = format_references(refs)
        assert "[Paper]" in result

    def test_pubmed_label(self):
        refs = ["https://pubmed.ncbi.nlm.nih.gov/123"]
        result = format_references(refs)
        assert "[Paper]" in result

    def test_twitter_label(self):
        refs = ["https://twitter.com/user"]
        result = format_references(refs)
        assert "[Twitter]" in result

    def test_x_twitter_label(self):
        refs = ["https://x.com/user"]
        result = format_references(refs)
        assert "[Twitter]" in result

    def test_video_label(self):
        refs = ["https://youtube.com/watch?v=abc"]
        result = format_references(refs)
        assert "[Video]" in result

    def test_wiki_label(self):
        refs = ["https://en.wikipedia.org/wiki/Topic"]
        result = format_references(refs)
        assert "[Wiki]" in result

    def test_tese_label(self):
        refs = ["https://teses.usp.br/tese/123"]
        result = format_references(refs)
        assert "[Tese]" in result

    def test_scielo_label(self):
        refs = ["https://www.scielo.br/article/123"]
        result = format_references(refs)
        assert "[SciELO]" in result

    def test_max_refs_limit(self):
        refs = [f"https://example{i}.com" for i in range(10)]
        result = format_references(refs, max_refs=3)
        # Should only include 3 references
        assert result.count("[Ref") == 3

    def test_multiple_papers_numbered(self):
        refs = [
            "https://doi.org/paper1",
            "https://doi.org/paper2",
        ]
        result = format_references(refs)
        assert "[Paper]" in result
        assert "[Paper2]" in result

    def test_generic_ref_label(self):
        refs = ["https://randomsite.org/page"]
        result = format_references(refs)
        assert "[Ref1]" in result


class TestGenerateIndexMarkdown:
    """Tests for generate_index_markdown function."""

    def test_includes_header(self, sample_episode):
        content = generate_index_markdown([sample_episode], 1, 0, 0)
        assert "# Naruhodo Podcast - Episode Index" in content

    def test_includes_episode_count(self, sample_episode):
        content = generate_index_markdown([sample_episode])
        assert "Total episodes: 1" in content

    def test_includes_table_header(self, sample_episode):
        content = generate_index_markdown([sample_episode], 1, 0, 0)
        assert "| # | Title | Date |" in content

    def test_includes_episode_row(self, sample_episode):
        content = generate_index_markdown([sample_episode], 1, 0, 0)
        assert "400" in content
        assert "Por que gostamos" in content

    def test_escapes_pipe_in_title(self):
        episode = {
            "title": "Episode | With Pipe",
            "episode_number": "1",
            "date": "2024-01-01",
            "duration": "30:00",
            "guest": "",
            "summary": "Summary",
            "status": "⬜ Pending",
            "references": [],
        }
        content = generate_index_markdown([episode], 0, 1, 0)
        assert "\\|" in content


class TestSaveIndex:
    """Tests for save_index function."""

    def test_creates_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "index.md"
        save_index("# Test", path)
        assert path.exists()

    def test_writes_content(self, tmp_path):
        path = tmp_path / "index.md"
        content = "# Naruhodo Index\n\nTest content"
        save_index(content, path)
        assert path.read_text(encoding="utf-8") == content

    def test_overwrites_existing(self, tmp_path):
        path = tmp_path / "index.md"
        path.write_text("Old content")
        save_index("New content", path)
        assert path.read_text() == "New content"
