"""Shared helpers for reading/writing REAPER track parameters via reapy.

reapy's Track objects expose no .volume/.pan properties, and .mute/.solo are
methods that unconditionally engage (no argument) rather than settable
attributes — assigning to them silently shadows the method instead of
raising, so these must go through get_info_value/set_info_value and the
mute()/unmute()/solo()/unsolo() methods instead.
"""

import math

MIN_DB = -150.0


def db_to_linear(db: float) -> float:
    return 10 ** (db / 20)


def linear_to_db(linear: float) -> float:
    return MIN_DB if linear <= 0 else 20 * math.log10(linear)


def get_volume_db(track) -> float:
    return linear_to_db(track.get_info_value("D_VOL"))


def set_volume_db(track, volume_db: float) -> None:
    track.set_info_value("D_VOL", db_to_linear(volume_db))


def get_pan(track) -> float:
    return track.get_info_value("D_PAN")


def set_mute(track, muted: bool) -> None:
    # track.mute()/unmute() are wrapped by reapy's @inside_reaper() dispatch
    # and are unreliable over the distant API; B_MUTE via set_info_value is
    # the mechanism that actually works consistently outside REAPER.
    track.set_info_value("B_MUTE", 1 if muted else 0)


def set_solo(track, soloed: bool) -> None:
    # Same story as set_mute: track.solo()/unsolo()/toggle_solo() silently
    # no-op over the distant API. I_SOLO via set_info_value works reliably.
    track.set_info_value("I_SOLO", 1 if soloed else 0)


def get_item_name(item) -> str:
    """Item has no .name of its own — the name lives on its active take."""
    take = item.active_take
    return take.name if take else ""
