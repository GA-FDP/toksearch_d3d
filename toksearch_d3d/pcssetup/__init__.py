# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Offline reader for DIII-D PCS setup files (``.wa10``).

The plasma control system stores each shot's whole setup in PTDATA as
pointname ``PCSSETUP``. This package decodes it with no waveserver:
categories, phases, the algorithm of each phase, entry behaviour,
anchor times, waveform vertices and parameter (static data) values,
addressed by the setup paths pcssetup uses, ``'Category|Phase|Subset|
Data item'``.

::

    from toksearch_d3d.pcssetup import read_wa10, pcssetup

    s = read_wa10("204019.wa10")          # a file path or bytes
    s = pcssetup(204019)                  # fetch PCSSETUP, under `fdp run`

    s.read("Discharge Shape|ShotStart")   # {'alg': ..., 'entry_behavior': ...,
                                          #  'anchor_time': ...}
    s.read("Discharge Shape|ShotStart|Discharge shape|Rp")   # ((t, v), ...)
    s.read("Error Field|Icontrol|Shared EF & RWM waveforms|Parameters")
                                          # {item title: value, ...}
    s.paths("Gas")                        # every phase and data path under Gas
    s.snapshot()                          # {path: (kind, value)}, pcssetup's shape

The values are what the setup held when it was archived, interpreted
with the definitions archived with it. A waveserver restoring the same
shot into a newer PCS can show different values where an algorithm
changed since (renamed items, new items filled with defaults).
"""

from __future__ import annotations

from . import decode as _decode_module  # keep the submodule name free
from .model import (Algorithm, Category, DataItem, ParamBlock, ParamField,
                    Phase, PhaseWaveform, Sequence, Setup, WaveformDef)
from .wa10 import Wa10FormatError, load_bytes, split_sections


def __getattr__(name):
    # Lazy: the decoder works without toksearch; only the Signal needs it.
    if name == "PcsSetupSignal":
        from .signal import PcsSetupSignal
        return PcsSetupSignal
    raise AttributeError(name)

__all__ = ["read_wa10", "PcsSetupSignal", "pcssetup", "pcssetup_wa10_bytes", "Setup",
           "Category", "Phase", "Algorithm", "WaveformDef", "PhaseWaveform",
           "DataItem", "ParamBlock", "ParamField", "Sequence",
           "Wa10FormatError"]


def read_wa10(source, strict: bool = True) -> Setup:
    """Decode a PCS setup file (path or bytes) into a :class:`Setup`.

    ``strict`` checks every structure's index record, as the PCS does
    when it reads the file; set it False to decode past a mismatch.
    """
    return _decode_module.decode(split_sections(load_bytes(source)), strict=strict)


def pcssetup_wa10_bytes(shot: int) -> bytes:
    """The ``.wa10`` bytes of ``shot``'s setup, rebuilt from PTDATA ``PCSSETUP``."""
    from .fetch import pcssetup_wa10_bytes as _fetch
    return _fetch(shot)


def pcssetup(shot: int, strict: bool = True) -> Setup:
    """Fetch ``shot``'s ``PCSSETUP`` point and decode it. Run under ``fdp run``."""
    return read_wa10(pcssetup_wa10_bytes(shot), strict=strict)
