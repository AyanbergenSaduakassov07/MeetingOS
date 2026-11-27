"""Stored paths must resolve back to the same file, wherever the data dir lives."""

from backend import config


def test_round_trips_inside_a_data_dir_nested_under_a_data_folder(tmp_path):
    previous = config.get_data_dir()
    data_dir = tmp_path / "data" / "demo"  # npm run demo uses ./data/demo
    config.set_data_dir(data_dir)
    try:
        audio = data_dir / "recordings" / "talk.mp3"
        stored = config.to_storage_path(audio)
        assert stored == "recordings/talk.mp3"
        assert config.resolve_storage_path(stored) == audio.resolve()
    finally:
        config.set_data_dir(previous)
