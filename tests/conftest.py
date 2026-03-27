"""Shared fixtures for test suite."""

import pytest
from pathlib import Path


@pytest.fixture
def sample_episode():
    """Standard episode dictionary for testing."""
    return {
        "title": "Naruhodo #400 - Por que gostamos de música?",
        "episode_number": "400",
        "date": "2024-01-15",
        "duration": "01:23:45",
        "description": "Neste episódio exploramos a ciência por trás do prazer musical.",
        "summary": "Exploramos a ciência por trás do prazer musical.",
        "guest": "",
        "link": "https://naruhodo.b9.com.br/naruhodo-400",
        "youtube_link": "https://www.youtube.com/watch?v=abc123def45",
        "references": ["https://doi.org/10.1000/example"],
    }


@pytest.fixture
def sample_interview():
    """Interview episode dictionary for testing."""
    return {
        "title": "Entrevista #50: Dr. Maria Santos - Neurociência e Comportamento",
        "episode_number": "50",
        "date": "2024-01-20",
        "duration": "45:30",
        "description": "Entrevista com a neurocientista Dr. Maria Santos sobre seu trabalho.",
        "summary": "Entrevista: Dr. Maria Santos, neurocientista e pesquisadora.",
        "guest": "Dr. Maria Santos - Neurociência e Comportamento",
        "link": "https://naruhodo.b9.com.br/entrevista-50",
        "youtube_link": "https://www.youtube.com/watch?v=xyz789abc12",
        "references": ["https://lattes.cnpq.br/1234567890"],
    }


@pytest.fixture
def transcripts_dir(tmp_path):
    """Temporary directory with sample VTT files."""
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()

    # Create sample VTT files
    files = [
        "001 - Naruhodo #1 - Primeiro Episódio.pt.vtt",
        "002 - Naruhodo #2 - Segundo Episódio.pt.vtt",
        "003 - Entrevista #1 - Dr. João Silva.pt.vtt",
        "004 - Naruhodo #100 - Episódio Especial.pt.vtt",
    ]

    for filename in files:
        (transcripts / filename).write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nSample transcript text.",
            encoding="utf-8",
        )

    return transcripts


@pytest.fixture
def sample_rss_xml():
    """Sample RSS feed content for testing."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
    xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
    xmlns:content="http://purl.org/rss/1.0/modules/content/">
    <channel>
        <title>Naruhodo!</title>
        <item>
            <title>Naruhodo #400 - Por que gostamos de música?</title>
            <pubDate>Mon, 15 Jan 2024 10:00:00 -0300</pubDate>
            <itunes:duration>5025</itunes:duration>
            <description>Episódio sobre música e neurociência.</description>
            <content:encoded><![CDATA[
                <p>Neste episódio exploramos a ciência por trás do prazer musical.</p>
                <p>Confira o artigo: https://doi.org/10.1000/example</p>
                <p>* APOIO: https://insider.com/cupom</p>
            ]]></content:encoded>
            <link>https://naruhodo.b9.com.br/naruhodo-400</link>
        </item>
        <item>
            <title>Entrevista #50: Dr. Maria Santos</title>
            <pubDate>Sat, 20 Jan 2024 10:00:00 -0300</pubDate>
            <itunes:duration>2730</itunes:duration>
            <description>Entrevista com a neurocientista.</description>
            <content:encoded><![CDATA[
                <p>Chegou a vez da neurocientista Dr. Maria Santos, pesquisadora da USP.</p>
                <p>Lattes: https://lattes.cnpq.br/1234567890</p>
            ]]></content:encoded>
            <link>https://naruhodo.b9.com.br/entrevista-50</link>
        </item>
    </channel>
</rss>"""


@pytest.fixture
def episodes_json(tmp_path):
    """Temporary episodes.json file path."""
    return tmp_path / "data" / "episodes.json"
