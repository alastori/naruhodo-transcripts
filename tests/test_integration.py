"""Integration tests for the full workflow."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestFullWorkflow:
    """Integration tests for the complete workflow."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Create a workspace with necessary directories."""
        data_dir = tmp_path / "data"
        transcripts_dir = tmp_path / "transcripts"
        data_dir.mkdir()
        transcripts_dir.mkdir()
        return {
            "root": tmp_path,
            "data": data_dir,
            "transcripts": transcripts_dir,
            "episodes_json": data_dir / "episodes.json",
            "episode_index": data_dir / "episode-index.md",
        }

    def test_rss_to_index_workflow(self, workspace):
        """Test workflow from RSS parsing to index generation."""
        from src.rss_parser import parse_rss, save_episodes, merge_episodes
        from src.index_generator import (
            update_episode_status,
            generate_index_markdown,
            save_index,
        )

        # Sample RSS content
        rss_content = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
        <channel>
            <item>
                <title>Naruhodo #100 - Test Episode</title>
                <pubDate>Mon, 15 Jan 2024 12:00:00 +0000</pubDate>
                <itunes:duration>01:30:45</itunes:duration>
                <description>This is a test episode description.</description>
                <link>https://example.com/ep100</link>
            </item>
            <item>
                <title>Naruhodo #99 - Another Episode</title>
                <pubDate>Mon, 08 Jan 2024 12:00:00 +0000</pubDate>
                <itunes:duration>45:30</itunes:duration>
                <description>Another description here.</description>
                <link>https://example.com/ep99</link>
            </item>
        </channel>
        </rss>"""

        # Parse RSS
        episodes = parse_rss(rss_content)
        assert len(episodes) == 2
        assert episodes[0]["title"] == "Naruhodo #100 - Test Episode"
        assert episodes[0]["episode_number"] == "100"

        # Merge with empty existing
        merged = merge_episodes([], episodes)
        assert len(merged) == 2

        # Save episodes
        save_episodes(merged, workspace["episodes_json"])
        assert workspace["episodes_json"].exists()

        # Verify saved content
        saved = json.loads(workspace["episodes_json"].read_text())
        assert len(saved) == 2

        # Update status (no downloads yet)
        downloaded, pending, no_link = update_episode_status(
            merged, workspace["transcripts"]
        )
        assert downloaded == 0
        assert pending == 0  # No YouTube links
        assert no_link == 2

        # Generate index
        index_content = generate_index_markdown(merged, downloaded, pending, no_link)
        save_index(index_content, workspace["episode_index"])
        assert workspace["episode_index"].exists()

        # Verify index content
        index_text = workspace["episode_index"].read_text()
        assert "Naruhodo #100" in index_text
        assert "Total episodes: 2" in index_text

    def test_youtube_matching_workflow(self, workspace):
        """Test workflow for matching YouTube links to episodes."""
        from src.youtube_discovery import match_episodes, YouTubeVideo
        from src.rss_parser import parse_rss, save_episodes
        from src.index_generator import update_episode_status

        # Create episodes
        rss_content = """<?xml version="1.0"?>
        <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
        <channel>
            <item>
                <title>Naruhodo #100 - Test Episode</title>
                <pubDate>Mon, 15 Jan 2024 12:00:00 +0000</pubDate>
                <itunes:duration>01:30:45</itunes:duration>
                <description>Test description.</description>
            </item>
        </channel>
        </rss>"""

        episodes = parse_rss(rss_content)

        # Mock YouTube playlist data using YouTubeVideo dataclass
        youtube_videos = [
            YouTubeVideo(
                video_id="abc123",
                title="Naruhodo #100 - Test Episode",
                url="https://www.youtube.com/watch?v=abc123",
                episode_type="regular",
                episode_number="100",
            )
        ]

        # Match episodes
        matched, stats = match_episodes(episodes, youtube_videos)
        assert stats["matched"] == 1
        assert episodes[0]["youtube_link"] == "https://www.youtube.com/watch?v=abc123"

        # Update status after matching
        downloaded, pending, no_link = update_episode_status(
            episodes, workspace["transcripts"]
        )
        assert downloaded == 0
        assert pending == 1  # Now has YouTube link
        assert no_link == 0

    def test_download_status_update(self, workspace):
        """Test that download status updates correctly with files."""
        from src.rss_parser import parse_rss
        from src.index_generator import update_episode_status

        # Create episodes
        rss_content = """<?xml version="1.0"?>
        <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
        <channel>
            <item>
                <title>Naruhodo #100 - Downloaded Episode</title>
                <pubDate>Mon, 15 Jan 2024 12:00:00 +0000</pubDate>
                <itunes:duration>01:30:45</itunes:duration>
                <description>Test description.</description>
            </item>
            <item>
                <title>Naruhodo #99 - Not Downloaded</title>
                <pubDate>Mon, 08 Jan 2024 12:00:00 +0000</pubDate>
                <itunes:duration>45:30</itunes:duration>
                <description>Another description.</description>
            </item>
        </channel>
        </rss>"""

        episodes = parse_rss(rss_content)
        episodes[0]["youtube_link"] = "https://youtube.com/1"
        episodes[1]["youtube_link"] = "https://youtube.com/2"

        # Create a VTT file for episode #100
        vtt_file = workspace["transcripts"] / "001 - Naruhodo #100 - Downloaded Episode.pt.vtt"
        vtt_file.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nTest\n")

        # Update status
        downloaded, pending, no_link = update_episode_status(
            episodes, workspace["transcripts"]
        )

        assert downloaded == 1
        assert pending == 1
        assert no_link == 0
        assert episodes[0]["status"] == "✅ Downloaded"
        assert episodes[1]["status"] == "⬜ Pending"

    def test_preserves_existing_data_on_merge(self, workspace):
        """Test that merging preserves YouTube links from existing."""
        from src.rss_parser import merge_episodes

        existing = [
            {
                "title": "Episode 1",
                "youtube_link": "https://youtube.com/existing",
            }
        ]

        new = [
            {
                "title": "Episode 1",
                "youtube_link": "",
            }
        ]

        merged = merge_episodes(existing, new)

        # YouTube link should be preserved from existing
        assert merged[0]["youtube_link"] == "https://youtube.com/existing"
