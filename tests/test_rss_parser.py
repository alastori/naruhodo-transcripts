"""Tests for rss_parser module."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import requests

from src.rss_parser import (
    clean_html,
    parse_duration,
    extract_episode_number,
    extract_guest,
    format_date,
    is_sponsor_context,
    is_sponsor_domain,
    extract_references,
    synthesize_summary,
    parse_rss,
    load_episodes,
    save_episodes,
    merge_episodes,
    fetch_rss_feed,
)


class TestCleanHtml:
    """Tests for clean_html function."""

    def test_empty_string(self):
        assert clean_html("") == ""

    def test_none_input(self):
        assert clean_html(None) == ""

    def test_removes_html_tags(self):
        assert clean_html("<p>Hello</p>") == "Hello"
        assert clean_html("<b>Bold</b> and <i>italic</i>") == "Bold and italic"

    def test_removes_complex_tags(self):
        assert clean_html('<a href="http://example.com">Link</a>') == "Link"
        assert clean_html('<div class="content">Text</div>') == "Text"

    def test_unescapes_html_entities(self):
        assert clean_html("&amp;") == "&"
        assert clean_html("&lt;tag&gt;") == "<tag>"
        assert clean_html("&quot;quoted&quot;") == '"quoted"'
        assert clean_html("&apos;") == "'"

    def test_collapses_whitespace(self):
        assert clean_html("  multiple   spaces  ") == "multiple spaces"
        assert clean_html("\n\nlines\n\n") == "lines"
        assert clean_html("\t\ttabs\t\t") == "tabs"

    def test_combined_cleaning(self):
        html = "<p>Hello &amp; <b>World</b></p>  \n\n  More text"
        assert clean_html(html) == "Hello & World More text"


class TestParseDuration:
    """Tests for parse_duration function."""

    def test_empty_string(self):
        assert parse_duration("") == ""

    def test_none_like_empty(self):
        assert parse_duration("") == ""

    def test_already_formatted(self):
        assert parse_duration("01:23:45") == "01:23:45"
        assert parse_duration("10:30") == "10:30"

    def test_seconds_to_minutes(self):
        assert parse_duration("90") == "01:30"
        assert parse_duration("3600") == "01:00:00"

    def test_seconds_to_hours(self):
        assert parse_duration("7200") == "02:00:00"
        assert parse_duration("5025") == "01:23:45"

    def test_short_duration(self):
        assert parse_duration("30") == "00:30"
        assert parse_duration("59") == "00:59"

    def test_invalid_input(self):
        assert parse_duration("invalid") == "invalid"
        assert parse_duration("abc123") == "abc123"


class TestExtractEpisodeNumber:
    """Tests for extract_episode_number function."""

    def test_regular_episode(self):
        assert extract_episode_number("Naruhodo #400 - Topic") == "400"
        assert extract_episode_number("Naruhodo #1 - First") == "1"

    def test_interview_episode(self):
        assert extract_episode_number("Entrevista #50: Guest") == "50"
        assert extract_episode_number("Entrevista #1: First Interview") == "1"

    def test_no_number(self):
        assert extract_episode_number("Special Episode") == ""
        assert extract_episode_number("Bonus Content") == ""

    def test_multiple_numbers(self):
        # Should extract the first #number pattern
        assert extract_episode_number("Naruhodo #100 - Top 10 Lists") == "100"

    def test_number_in_middle(self):
        assert extract_episode_number("Special Naruhodo #99 Edition") == "99"


class TestExtractGuest:
    """Tests for extract_guest function."""

    def test_interview_with_guest(self):
        title = "Entrevista #50: Dr. Maria Santos"
        assert extract_guest(title, "") == "Dr. Maria Santos"

    def test_interview_with_long_guest(self):
        title = "Entrevista #10: Professor João Silva - Universidade de São Paulo"
        assert extract_guest(title, "") == "Professor João Silva - Universidade de São Paulo"

    def test_regular_episode_no_guest(self):
        title = "Naruhodo #400 - Por que gostamos de música?"
        assert extract_guest(title, "") == ""

    def test_interview_format_variations(self):
        assert extract_guest("Entrevista #1: Name", "") == "Name"
        # Regex matches [:\s]+ so dash with spaces also works
        assert extract_guest("Entrevista #2: Name", "") == "Name"

    def test_empty_title(self):
        assert extract_guest("", "") == ""


class TestFormatDate:
    """Tests for format_date function."""

    def test_empty_string(self):
        assert format_date("") == ""

    def test_rfc2822_with_timezone(self):
        date_str = "Mon, 15 Jan 2024 10:00:00 -0300"
        assert format_date(date_str) == "2024-01-15"

    def test_rfc2822_positive_timezone(self):
        date_str = "Tue, 20 Feb 2024 15:30:00 +0100"
        assert format_date(date_str) == "2024-02-20"

    def test_rfc2822_without_timezone(self):
        date_str = "Wed, 25 Mar 2024 12:00:00"
        assert format_date(date_str) == "2024-03-25"

    def test_invalid_format_passthrough(self):
        assert format_date("invalid date") == "invalid date"
        assert format_date("2024-01-15") == "2024-01-15"

    def test_whitespace_handling(self):
        date_str = "  Mon, 15 Jan 2024 10:00:00 -0300  "
        assert format_date(date_str) == "2024-01-15"


class TestIsSponsorContext:
    """Tests for is_sponsor_context function."""

    def test_sponsor_patterns_detected(self):
        text = "Apoie o podcast em apoia.se/naruhodo - https://example.com"
        assert is_sponsor_context(text, text.find("https://")) is True

    def test_cupom_pattern(self):
        text = "Use o cupom NARUHODO para desconto em https://sponsor.com"
        assert is_sponsor_context(text, text.find("https://")) is True

    def test_patrocinio_pattern(self):
        # Pattern uses "patrocin" which matches "patrocínio" via re.IGNORECASE
        text = "Este episodio tem patrocinio de https://sponsor.com"
        assert is_sponsor_context(text, text.find("https://")) is True

    def test_non_sponsor_context(self):
        text = "Confira o artigo científico em https://doi.org/10.1000/example"
        assert is_sponsor_context(text, text.find("https://")) is False

    def test_context_window_limit(self):
        # URL is more than 200 chars from sponsor word
        sponsor_text = "Apoie o podcast"
        padding = "x" * 250
        url_text = "https://example.com"
        text = sponsor_text + padding + url_text
        url_start = text.find("https://")
        assert is_sponsor_context(text, url_start) is False

    def test_context_window_within_limit(self):
        sponsor_text = "Apoie o podcast"
        padding = "x" * 100
        url_text = "https://example.com"
        text = sponsor_text + padding + url_text
        url_start = text.find("https://")
        assert is_sponsor_context(text, url_start) is True


class TestIsSponsorDomain:
    """Tests for is_sponsor_domain function."""

    def test_insider_domain(self):
        assert is_sponsor_domain("https://insider.com/something") is True
        assert is_sponsor_domain("https://www.insiderstore.com/produto") is True

    def test_patreon_domain(self):
        assert is_sponsor_domain("https://patreon.com/naruhodo") is True

    def test_apoiase_domain(self):
        assert is_sponsor_domain("https://apoia.se/naruhodo") is True

    def test_catarse_domain(self):
        assert is_sponsor_domain("https://catarse.me/naruhodo") is True

    def test_orelo_domain(self):
        assert is_sponsor_domain("https://orelo.cc/cupom") is True

    def test_non_sponsor_domain(self):
        assert is_sponsor_domain("https://doi.org/10.1000/example") is False
        assert is_sponsor_domain("https://wikipedia.org/article") is False
        assert is_sponsor_domain("https://youtube.com/watch") is False


class TestExtractReferences:
    """Tests for extract_references function."""

    def test_empty_description(self):
        assert extract_references("") == []
        assert extract_references(None) == []

    def test_extracts_academic_urls(self):
        desc = "See https://doi.org/10.1000/example for more info"
        refs = extract_references(desc)
        assert "https://doi.org/10.1000/example" in refs

    def test_filters_sponsor_domains(self):
        desc = "Check https://patreon.com/naruhodo for support"
        refs = extract_references(desc)
        # patreon.com is a sponsor domain and should be filtered
        assert "https://patreon.com/naruhodo" not in refs
        assert len(refs) == 0

    def test_filters_sponsor_context(self):
        # "Apoie" triggers sponsor context for URLs within 200 chars
        # Make sure the non-sponsor URL is far enough away
        padding = "x" * 250
        desc = f"Apoie o podcast: https://generic.com/support {padding} Artigo: https://paper.example.org/article"
        refs = extract_references(desc)
        assert "https://generic.com/support" not in refs
        # paper.example.org should be outside the sponsor context window
        assert any("paper.example.org" in ref for ref in refs)

    def test_removes_duplicates(self):
        desc = "Link: https://example.com and again https://example.com"
        refs = extract_references(desc)
        assert len(refs) == 1
        assert refs[0] == "https://example.com"

    def test_removes_trailing_punctuation(self):
        desc = "Check https://example.com. Also https://other.org!"
        refs = extract_references(desc)
        assert "https://example.com" in refs
        assert "https://other.org" in refs

    def test_filters_naruhodo_self_references(self):
        desc = "Visit https://naruhodo.b9.com.br and https://naruhodo.b9.com.br/episode-400 and https://doi.org/paper1"
        refs = extract_references(desc)
        # All naruhodo.b9.com.br URLs are self-references, filtered from flat list
        assert "https://naruhodo.b9.com.br" not in refs
        assert "https://naruhodo.b9.com.br/episode-400" not in refs
        # External references are kept
        assert "https://doi.org/paper1" in refs

    def test_multiple_references(self):
        desc = """
        Paper 1: https://doi.org/paper1
        Paper 2: https://pubmed.ncbi.nlm.nih.gov/123
        Wikipedia: https://en.wikipedia.org/wiki/Topic
        """
        refs = extract_references(desc)
        assert len(refs) == 3


class TestSynthesizeSummary:
    """Tests for synthesize_summary function."""

    def test_empty_description(self):
        assert synthesize_summary("", "Title") == ""

    def test_interview_credentials(self):
        desc = "Chegou a vez da neurocientista Dr. Maria Santos, pesquisadora da USP."
        title = "Entrevista #50: Dr. Maria Santos"
        summary = synthesize_summary(desc, title)
        assert "Entrevista:" in summary

    def test_removes_sponsor_sections(self):
        desc = "Episódio interessante. * APOIO: Sponsor text."
        title = "Naruhodo #100"
        summary = synthesize_summary(desc, title)
        assert "APOIO" not in summary
        assert "Sponsor" not in summary

    def test_removes_podcast_intro(self):
        desc = "Great content. Naruhodo! é o podcast de ciência."
        title = "Naruhodo #100"
        summary = synthesize_summary(desc, title)
        assert "é o podcast" not in summary

    def test_removes_urls(self):
        desc = "Content about https://example.com topic."
        title = "Naruhodo #100"
        summary = synthesize_summary(desc, title)
        assert "https://" not in summary

    def test_truncation_at_max_chars(self):
        long_desc = "This is a very long description. " * 20
        title = "Naruhodo #100"
        summary = synthesize_summary(long_desc, title, max_chars=100)
        assert len(summary) <= 103  # Some buffer for ellipsis

    def test_skips_short_sentences(self):
        desc = "Hi. This is a proper sentence about the topic."
        title = "Naruhodo #100"
        summary = synthesize_summary(desc, title)
        assert "Hi" not in summary

    def test_skips_host_mentions(self):
        desc = "Ken Fujioka e Altay de Souza discutem ciência. Topic discussion here."
        title = "Naruhodo #100"
        summary = synthesize_summary(desc, title)
        assert "Ken Fujioka" not in summary


class TestParseRss:
    """Tests for parse_rss function."""

    def test_parses_episodes_from_xml(self, sample_rss_xml):
        episodes = parse_rss(sample_rss_xml)
        assert len(episodes) == 2

    def test_extracts_title(self, sample_rss_xml):
        episodes = parse_rss(sample_rss_xml)
        assert episodes[0]["title"] == "Naruhodo #400 - Por que gostamos de música?"

    def test_extracts_episode_number(self, sample_rss_xml):
        episodes = parse_rss(sample_rss_xml)
        assert episodes[0]["episode_number"] == "400"
        assert episodes[1]["episode_number"] == "50"

    def test_formats_date(self, sample_rss_xml):
        episodes = parse_rss(sample_rss_xml)
        assert episodes[0]["date"] == "2024-01-15"

    def test_parses_duration_from_seconds(self, sample_rss_xml):
        episodes = parse_rss(sample_rss_xml)
        assert episodes[0]["duration"] == "01:23:45"  # 5025 seconds

    def test_cleans_description(self, sample_rss_xml):
        episodes = parse_rss(sample_rss_xml)
        assert "<p>" not in episodes[0]["description"]

    def test_extracts_references(self, sample_rss_xml):
        episodes = parse_rss(sample_rss_xml)
        # Should have doi.org but not insider.com
        assert any("doi.org" in ref for ref in episodes[0]["references"])
        assert not any("insider.com" in ref for ref in episodes[0]["references"])

    def test_no_status_in_parsed_output(self, sample_rss_xml):
        episodes = parse_rss(sample_rss_xml)
        assert "status" not in episodes[0]

    def test_extracts_link(self, sample_rss_xml):
        episodes = parse_rss(sample_rss_xml)
        assert episodes[0]["link"] == "https://naruhodo.b9.com.br/naruhodo-400"


class TestLoadSaveEpisodes:
    """Tests for load_episodes and save_episodes functions."""

    def test_load_nonexistent_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        assert load_episodes(path) == []

    def test_save_and_load_episodes(self, tmp_path, sample_episode):
        path = tmp_path / "data" / "episodes.json"
        episodes = [sample_episode]

        save_episodes(episodes, path)
        loaded = load_episodes(path)

        assert len(loaded) == 1
        assert loaded[0]["title"] == sample_episode["title"]

    def test_save_creates_parent_directories(self, tmp_path, sample_episode):
        path = tmp_path / "nested" / "dir" / "episodes.json"
        save_episodes([sample_episode], path)
        assert path.exists()

    def test_save_with_unicode(self, tmp_path):
        path = tmp_path / "episodes.json"
        episodes = [{"title": "Episódio com acentuação"}]
        save_episodes(episodes, path)
        loaded = load_episodes(path)
        assert loaded[0]["title"] == "Episódio com acentuação"


class TestMergeEpisodes:
    """Tests for merge_episodes function."""

    def test_preserves_youtube_link(self, sample_episode):
        existing = [sample_episode.copy()]
        existing[0]["youtube_link"] = "https://youtube.com/existing"

        new = [sample_episode.copy()]
        new[0]["youtube_link"] = ""

        merged = merge_episodes(existing, new)
        assert merged[0]["youtube_link"] == "https://youtube.com/existing"

    def test_adds_new_episodes(self, sample_episode, sample_interview):
        existing = [sample_episode]
        new = [sample_episode, sample_interview]

        merged = merge_episodes(existing, new)
        assert len(merged) == 2

    def test_handles_empty_existing(self, sample_episode):
        merged = merge_episodes([], [sample_episode])
        assert len(merged) == 1
        assert merged[0]["title"] == sample_episode["title"]

    def test_handles_empty_new(self, sample_episode):
        merged = merge_episodes([sample_episode], [])
        assert len(merged) == 1  # Existing episodes preserved when not in new feed

    def test_updates_other_fields(self, sample_episode):
        existing = [sample_episode.copy()]
        existing[0]["summary"] = "Old summary"

        new = [sample_episode.copy()]
        new[0]["summary"] = "New summary"

        merged = merge_episodes(existing, new)
        # Summary comes from new episode
        assert merged[0]["summary"] == "New summary"
        # YouTube link preserved from existing
        assert merged[0]["youtube_link"] == sample_episode["youtube_link"]


class TestFetchRssFeed:
    """Tests for fetch_rss_feed function with retry logic."""

    @patch("src.rss_parser.requests.get")
    def test_successful_fetch(self, mock_get):
        mock_response = MagicMock()
        mock_response.text = "<rss>content</rss>"
        mock_get.return_value = mock_response

        result = fetch_rss_feed("https://example.com/feed")

        assert result == "<rss>content</rss>"
        mock_get.assert_called_once()

    @patch("src.rss_parser.requests.get")
    def test_caches_to_file(self, mock_get, tmp_path):
        mock_response = MagicMock()
        mock_response.text = "<rss>cached</rss>"
        mock_get.return_value = mock_response

        cache_path = tmp_path / "cache.xml"
        result = fetch_rss_feed("https://example.com/feed", cache_path=cache_path)

        assert result == "<rss>cached</rss>"
        assert cache_path.exists()
        assert cache_path.read_text() == "<rss>cached</rss>"

    @patch("src.rss_parser.time.sleep")
    @patch("src.rss_parser.requests.get")
    def test_retries_on_timeout(self, mock_get, mock_sleep):
        # First call times out, second succeeds
        mock_response = MagicMock()
        mock_response.text = "<rss>success</rss>"
        mock_get.side_effect = [
            requests.Timeout("Connection timed out"),
            mock_response,
        ]

        result = fetch_rss_feed("https://example.com/feed")

        assert result == "<rss>success</rss>"
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("src.rss_parser.time.sleep")
    @patch("src.rss_parser.requests.get")
    def test_retries_on_connection_error(self, mock_get, mock_sleep):
        # First two calls fail, third succeeds
        mock_response = MagicMock()
        mock_response.text = "<rss>success</rss>"
        mock_get.side_effect = [
            requests.ConnectionError("Connection refused"),
            requests.ConnectionError("Connection reset"),
            mock_response,
        ]

        result = fetch_rss_feed("https://example.com/feed")

        assert result == "<rss>success</rss>"
        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("src.rss_parser.time.sleep")
    @patch("src.rss_parser.requests.get")
    def test_raises_after_max_retries(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.Timeout("Connection timed out")

        with pytest.raises(requests.Timeout):
            fetch_rss_feed("https://example.com/feed")

        assert mock_get.call_count == 3  # RSS_MAX_RETRIES

    @patch("src.rss_parser.requests.get")
    def test_does_not_retry_client_errors(self, mock_get):
        # Client errors (4xx) should not trigger retries
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = requests.HTTPError("404 Not Found", response=mock_response)
        mock_response.raise_for_status.side_effect = http_error
        mock_get.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            fetch_rss_feed("https://example.com/feed")

        mock_get.assert_called_once()  # No retries for 4xx

    @patch("src.rss_parser.time.sleep")
    @patch("src.rss_parser.requests.get")
    def test_retries_server_errors(self, mock_get, mock_sleep):
        # Server errors (5xx) should trigger retries
        mock_error_response = MagicMock()
        mock_error_response.status_code = 500
        http_error = requests.HTTPError("500 Internal Server Error", response=mock_error_response)

        mock_success_response = MagicMock()
        mock_success_response.text = "<rss>recovered</rss>"

        mock_get.side_effect = [
            MagicMock(raise_for_status=MagicMock(side_effect=http_error)),
            mock_success_response,
        ]

        result = fetch_rss_feed("https://example.com/feed")

        assert result == "<rss>recovered</rss>"
        assert mock_get.call_count == 2
