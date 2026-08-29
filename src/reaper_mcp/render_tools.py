import os
import logging
from pathlib import Path

import reapy
from reapy import reascript_api as RPR

from reaper_mcp.connection import get_project
from reaper_mcp.track_utils import set_solo

logger = logging.getLogger("reaper_mcp.render_tools")

# REAPER RENDER_FORMAT codes
FORMAT_CODES = {
    "wav":  0,
    "mp3":  3,
    "ogg":  4,
    "flac": 5,
}

# REAPER RENDER_FORMAT2 codes for WAV bit depth
BIT_DEPTH_CODES = {
    16: 0,
    24: 2,
    32: 4,
}

# REAPER RENDER_BOUNDSFLAG values (from the Render dialog's "Bounds" dropdown).
# Note these do NOT start at 0=entire project as the names might suggest —
# 0 is "custom time range" (silently renders nothing if RENDER_STARTPOS/
# RENDER_ENDPOS aren't also set).
BOUNDS_ENTIRE_PROJECT = 1
BOUNDS_TIME_SELECTION = 2

DEFAULT_SAMPLE_RATE = 48000


def _resolve_sample_rate(project, sample_rate: int) -> int:
    """
    Resolve a sample_rate argument of 0 to the project's actual rate.

    Rendering at a rate that doesn't match the project forces REAPER to
    resample every track before summing — and on at least some REAPER
    builds, summing multiple simultaneously-resampled tracks during an
    offline render silently produces total silence (each track alone
    renders fine; 2+ together doesn't, even after restarting REAPER).
    Defaulting to the project's own rate avoids the resample-and-sum path
    entirely for the common case.
    """
    if sample_rate:
        return sample_rate
    rate = RPR.GetSetProjectInfo(project.id, "PROJECT_SRATE", 0, False)
    return int(rate) if rate else DEFAULT_SAMPLE_RATE


def _set_render_settings(
    output_path: str,
    format: str,
    sample_rate: int,
    bit_depth: int,
    channels: int,
    bounds: int,
) -> str:
    """
    Configure REAPER's render settings and return the actual path REAPER will
    write to.

    RENDER_FILE is a DIRECTORY, not a full file path — REAPER derives the
    filename from RENDER_PATTERN (project name by default) and always
    appends its own extension for the chosen format. Passing a full file
    path as RENDER_FILE makes REAPER treat it as a directory and silently
    render under the project's name instead. So output_path is split here:
    its directory becomes RENDER_FILE, and its extension-stripped basename
    becomes RENDER_PATTERN (a literal name, not a wildcard).
    """
    fmt = format.lower()
    fmt_code = FORMAT_CODES.get(fmt, 0)
    bdepth_code = BIT_DEPTH_CODES.get(bit_depth, 2)
    directory = os.path.dirname(output_path)
    pattern = os.path.splitext(os.path.basename(output_path))[0]
    RPR.GetSetProjectInfo_String(0, "RENDER_FILE", directory, True)
    RPR.GetSetProjectInfo_String(0, "RENDER_PATTERN", pattern, True)
    RPR.GetSetProjectInfo(0, "RENDER_FORMAT", fmt_code, True)
    RPR.GetSetProjectInfo(0, "RENDER_FORMAT2", bdepth_code, True)
    RPR.GetSetProjectInfo(0, "RENDER_SRATE", float(sample_rate), True)
    RPR.GetSetProjectInfo(0, "RENDER_CHANNELS", float(channels), True)
    RPR.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", float(bounds), True)
    return os.path.join(directory, f"{pattern}.{fmt}")


def render_to_temp_file(sample_rate: int = 0) -> str:
    """
    Render the current project to a temporary WAV file and return its path.
    Used by analysis and mastering tools. Caller is responsible for deleting the file.
    sample_rate: 0 (default) renders at the project's own sample rate; see
    _resolve_sample_rate for why that matters.
    """
    import tempfile
    project = get_project()
    sample_rate = _resolve_sample_rate(project, sample_rate)
    tmp = tempfile.mktemp(suffix=".wav")
    real_path = _set_render_settings(tmp, "wav", sample_rate, 24, 2, bounds=BOUNDS_ENTIRE_PROJECT)
    RPR.Main_OnCommand(41824, 0)
    return real_path


def register_tools(mcp):

    @mcp.tool()
    def render_project(
        output_path: str,
        format: str = "wav",
        sample_rate: int = 0,
        bit_depth: int = 24,
        channels: int = 2,
    ) -> dict:
        """
        Render the entire project to a file.
        format: wav, flac, mp3 (requires LAME), ogg.
        sample_rate: e.g. 44100, 48000, 96000. 0 (default) uses the project's
        own sample rate — recommended, since rendering at a mismatched rate
        can trigger silent output on projects with mixed-rate source audio.
        bit_depth: 16, 24, or 32 (WAV only; ignored for mp3/ogg/flac).
        channels: 1 (mono) or 2 (stereo).
        """
        try:
            output_path = str(Path(output_path).expanduser().resolve())
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            project = get_project()
            sample_rate = _resolve_sample_rate(project, sample_rate)
            output_path = _set_render_settings(
                output_path, format, sample_rate, bit_depth, channels, bounds=BOUNDS_ENTIRE_PROJECT
            )
            RPR.Main_OnCommand(41824, 0)  # File: Render project to disk (no dialog)
            if not os.path.exists(output_path):
                return {"success": False, "error": "Render command completed but output file not found"}
            return {
                "success": True,
                "output_path": output_path,
                "format": format,
                "sample_rate": sample_rate,
                "bit_depth": bit_depth,
                "channels": channels,
                "file_size_bytes": os.path.getsize(output_path),
            }
        except Exception as e:
            logger.error(f"render_project failed: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_time_selection(
        output_path: str,
        start: float,
        end: float,
        format: str = "wav",
        sample_rate: int = 0,
        bit_depth: int = 24,
        channels: int = 2,
    ) -> dict:
        """
        Render a specific time range of the project to a file.
        sample_rate: 0 (default) uses the project's own sample rate.
        """
        try:
            output_path = str(Path(output_path).expanduser().resolve())
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            project = get_project()
            project.time_selection = (start, end)
            sample_rate = _resolve_sample_rate(project, sample_rate)
            output_path = _set_render_settings(
                output_path, format, sample_rate, bit_depth, channels, bounds=BOUNDS_TIME_SELECTION
            )
            RPR.Main_OnCommand(41824, 0)
            if not os.path.exists(output_path):
                return {"success": False, "error": "Render completed but output file not found"}
            return {
                "success": True,
                "output_path": output_path,
                "start": start,
                "end": end,
                "format": format,
                "file_size_bytes": os.path.getsize(output_path),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def render_stems(
        output_directory: str,
        track_indices: list = None,
        format: str = "wav",
        sample_rate: int = 0,
        bit_depth: int = 24,
    ) -> dict:
        """
        Render each track as a separate stem file by soloing each track individually.
        track_indices: list of track indices, or null to render all tracks.
        Files are named after the track names in the output directory.
        sample_rate: 0 (default) uses the project's own sample rate.
        """
        try:
            output_directory = str(Path(output_directory).expanduser().resolve())
            os.makedirs(output_directory, exist_ok=True)
            project = get_project()
            sample_rate = _resolve_sample_rate(project, sample_rate)
            indices = track_indices if track_indices is not None else list(range(project.n_tracks))
            rendered = []

            for idx in indices:
                track = project.tracks[idx]
                track_name = track.name or f"Track_{idx}"
                # Solo this track exclusively
                for j in range(project.n_tracks):
                    set_solo(project.tracks[j], j == idx)
                # Sanitize filename
                safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in track_name)
                stem_path = os.path.join(output_directory, f"{safe_name}.{format}")
                stem_path = _set_render_settings(
                    stem_path, format, sample_rate, bit_depth, 2, bounds=BOUNDS_ENTIRE_PROJECT
                )
                RPR.Main_OnCommand(41824, 0)
                rendered.append({
                    "track_index": idx,
                    "track_name": track_name,
                    "output_path": stem_path,
                    "exists": os.path.exists(stem_path),
                })

            # Unsolo all tracks
            for j in range(project.n_tracks):
                set_solo(project.tracks[j], False)

            return {
                "success": True,
                "output_directory": output_directory,
                "stems": rendered,
            }
        except Exception as e:
            # Always unsolo on error
            try:
                proj = get_project()
                for j in range(proj.n_tracks):
                    set_solo(proj.tracks[j], False)
            except Exception:
                pass
            logger.error(f"render_stems failed: {e}")
            return {"success": False, "error": str(e)}
