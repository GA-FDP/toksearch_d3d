# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Data model for a decoded PCS setup."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# pcsapi Util::SetUp::PhsItem::EntryBhvr (core/infra/pcsapi/util.hpp
# lines 113-118); the values are the PCS entrybehavior flags
# (core/infra/serverdefs.h lines 676-679).
ENTRY_BEHAVIORS = {1: "beginOfPhs", 2: "timeOfLastExit", 3: "timePhsReach",
                   4: "anchorTimePhsReach"}


@dataclass(frozen=True)
class WaveformDef:
    """One entry of an algorithm's waveform list (struct waveform).

    The PCS lists static (parameter) data items in the same list as
    waveforms; their description starts with ``StaticData``
    (pcsapi ``Util::SetUp::DataItem::type``, util.cpp lines 195-200).
    """

    name: str
    description: str
    subset: int  # 1-based index into the algorithm's subset names
    subset_name: Optional[str]

    @property
    def is_param_data(self) -> bool:
        return self.description.startswith("StaticData")


@dataclass(frozen=True)
class Algorithm:
    name: str
    identifier: str
    version: int
    category: str
    number: int  # 1-based algorithm number within the category
    subsets: tuple
    waveforms: tuple  # (WaveformDef, ...)


@dataclass(frozen=True)
class ParamField:
    """One descriptor of a parameter block: ``size`` values of ``type``."""

    type: str  # char | short | int | uint32 | long | float | double
    size: int
    offset: int  # byte offset in the block as laid out on the archiving host
    value: object  # numpy array, or bytes for char

    def values(self) -> list:
        """The field's values as Python scalars (chars as one bytes)."""
        if self.type == "char":
            return [self.value]
        return np.asarray(self.value).tolist()


@dataclass(frozen=True)
class ParamBlock:
    """A parameter data block of one phase, as pcs_forarchive stored it."""

    name: str
    data_size: int
    flags: int
    insert_order: int
    mem_align: int
    fields: tuple  # (ParamField, ...)


@dataclass(frozen=True)
class PhaseWaveform:
    definition: WaveformDef
    access_control: int
    vertices: tuple  # ((t, v), ...)


@dataclass(frozen=True)
class Phase:
    category: str
    name: str
    number: int
    entry_behavior: int
    anchor_time: float
    access_control: int
    algorithm: Optional[Algorithm]
    waveforms: tuple  # (PhaseWaveform, ...) in algorithm waveform order
    param_blocks: tuple  # (ParamBlock, ...)

    @property
    def alg(self) -> Optional[str]:
        return None if self.algorithm is None else self.algorithm.name

    @property
    def entry_behavior_name(self) -> str:
        return ENTRY_BEHAVIORS.get(self.entry_behavior, str(self.entry_behavior))

    def block(self, name: str) -> Optional[ParamBlock]:
        for b in self.param_blocks:
            if b.name == name:
                return b
        return None


@dataclass(frozen=True)
class Sequence:
    """A category's phase sequence waveform."""

    name: str
    waveform: Optional[WaveformDef]
    vertices: tuple


@dataclass(frozen=True)
class Category:
    name: str
    identifier: str
    version: int
    algorithms: tuple
    phases: tuple
    sequences: tuple


SEP = "|"


def split_path(path) -> tuple:
    """'C|P|S|D' (or a tuple of parts) -> tuple of 1-4 stripped parts."""
    parts = tuple(path) if isinstance(path, (tuple, list)) else tuple(
        p.strip() for p in str(path).split(SEP))
    if not 1 <= len(parts) <= 4 or any(p == "" for p in parts):
        raise ValueError(f"setup path needs 1-4 non-empty '|'-separated parts: {path!r}")
    return parts


@dataclass(frozen=True)
class DataItem:
    """One data item: a phase's waveform or static (parameter) data item."""

    path: str  # 'Category|Phase|Subset|Data item'
    phase: Phase
    waveform: PhaseWaveform

    @property
    def name(self) -> str:
        return self.waveform.definition.name

    @property
    def description(self) -> str:
        return self.waveform.definition.description

    @property
    def is_param_data(self) -> bool:
        return self.waveform.definition.is_param_data

    def read(self):
        """(kind, value).

        kind is ``waveform`` (value: vertices), or for static data
        ``generic`` | ``values`` | ``labels`` | ``file`` | ``matrix`` |
        ``opsetup`` | ``opaque``
        (see :mod:`toksearch_d3d.pcssetup.items`); an inconsistent item
        gives ``unreadable`` and the reason.
        """
        if not self.is_param_data:
            return "waveform", self.waveform.vertices
        from .items import ItemDecodeError, decode_item
        try:
            return decode_item(self.phase, self.name)
        except (ItemDecodeError, IndexError, KeyError) as e:
            return "unreadable", str(e)


@dataclass(frozen=True)
class Setup:
    """A decoded PCS setup. Address it by pcssetup paths 'C|P|S|D'.

    ``categories`` keep the archive's order. Subsets and data items under
    a phase come from the phase's algorithm (subset names and waveform
    list), as the waveserver builds them (pcsapi ``Util::setUp``).
    """

    install: dict
    globals: dict
    change_history: tuple
    categories: tuple
    header: object = field(default=None, compare=False)

    # navigation ----------------------------------------------------------
    @property
    def shot(self) -> int:
        """Shot number in the file header (0 for a setup file not from a shot)."""
        return 0 if self.header is None else self.header.shot

    @property
    def release(self) -> str:
        """PCS release the setup was archived by (from release_identifier)."""
        lines = self.install.get("release_identifier", "").split("\n")
        return lines[1] if len(lines) > 1 else ""

    def category(self, name: str) -> Category:
        for c in self.categories:
            if c.name == name:
                return c
        raise KeyError(_missing("category", name, [c.name for c in self.categories]))

    def phase(self, ctgy: str, phs: str) -> Phase:
        c = self.category(ctgy)
        for p in c.phases:
            if p.name == phs:
                return p
        raise KeyError(_missing("phase", f"{ctgy}|{phs}", [p.name for p in c.phases]))

    def subsets(self, ctgy: str, phs: str) -> tuple:
        p = self.phase(ctgy, phs)
        return () if p.algorithm is None else p.algorithm.subsets

    def data_items(self, ctgy: str, phs: str, sub: Optional[str] = None) -> tuple:
        """DataItems of a phase (or of one subset), in waveform-list order."""
        p = self.phase(ctgy, phs)
        if sub is not None and sub not in self.subsets(ctgy, phs):
            raise KeyError(_missing("subset", f"{ctgy}|{phs}|{sub}",
                                    list(self.subsets(ctgy, phs))))
        out = []
        for w in p.waveforms:
            s = w.definition.subset_name
            if s is None or (sub is not None and s != sub):
                continue
            out.append(DataItem(path=SEP.join((ctgy, phs, s, w.definition.name)),
                                phase=p, waveform=w))
        return tuple(out)

    def item(self, path) -> DataItem:
        c, p, s, d = _four(path)
        for it in self.data_items(c, p, s):
            if it.name == d:
                return it
        raise KeyError(_missing("data item", SEP.join((c, p, s, d)),
                                [i.name for i in self.data_items(c, p, s)]))

    def paths(self, scope=None) -> list:
        """Phase paths and data paths in setup order, optionally under ``scope``."""
        out = []
        for _, path, _ in self._walk(scope):
            out.append(path)
        return out

    def _walk(self, scope=None):
        parts = split_path(scope) if scope is not None else ()
        cats = [self.category(parts[0])] if parts else self.categories
        for c in cats:
            phases = [self.phase(c.name, parts[1])] if len(parts) > 1 else c.phases
            for p in phases:
                if len(parts) <= 2:
                    yield "phase", f"{c.name}{SEP}{p.name}", p
                items = self.data_items(c.name, p.name, parts[2] if len(parts) > 2 else None)
                for it in items:
                    if len(parts) == 4 and it.name != parts[3]:
                        continue
                    yield "item", it.path, it
                if len(parts) == 4 and not any(i.name == parts[3] for i in items):
                    self.item(parts)  # raises with suggestions

    # values ------------------------------------------------------------------
    def read(self, path):
        """Phase path -> dict(alg, entry_behavior, anchor_time); data path -> value.

        Waveforms give their vertices ((t, v), ...); generic items a
        {title: value} dict (a tuple of values when the labels were not
        archived); file items the file name; matrices a
        :class:`~toksearch_d3d.pcssetup.items.MatrixValue`; the
        operating setup an :class:`~toksearch_d3d.pcssetup.items.OpSetupValue`;
        other static data the tuple of its parameter blocks.
        """
        parts = split_path(path)
        if len(parts) == 2:
            return _phase_value(self.phase(*parts))
        if len(parts) != 4:
            raise ValueError("read() takes a phase path 'C|P' or a data path 'C|P|S|D'")
        kind, value = self.item(parts).read()
        if kind == "generic":
            return value.as_dict()
        if kind == "unreadable":
            raise ValueError(f"{SEP.join(parts)}: {value}")
        return value

    def snapshot(self, scope=None) -> dict:
        """{path: (kind, value)} in the shape pcssetup's Session._snapshot uses.

        kind: phase | waveform | generic | values | labels | file |
        matrix | opsetup | opaque | unreadable. ``values`` is a generic
        item whose labels the PCS did not archive (a tuple of values, no
        titles); ``labels`` one whose values it did not archive
        ({title: None}; a waveserver shows the algorithm's defaults). pcssetup reports file and matrix items (and
        other editors it does not decode) as ``opaque`` with the editor
        name; this reader decodes those it can.
        """
        out = {}
        for kind, path, obj in self._walk(scope):
            if kind == "phase":
                out[path] = ("phase", _phase_value(obj))
                continue
            k, v = obj.read()
            if k == "generic":
                v = v.as_dict()
            elif k == "opsetup":
                v = {"time_to_stop": v.time_to_stop, "op_mode": v.op_mode,
                     "n_samples": v.n_samples}
            elif k == "opaque":
                v = obj.description
            out[path] = (k, v)
        return out


def _phase_value(p: Phase) -> dict:
    return {"alg": p.alg, "entry_behavior": p.entry_behavior_name,
            "anchor_time": float(p.anchor_time)}


def _four(path) -> tuple:
    parts = split_path(path)
    if len(parts) != 4:
        raise ValueError(f"a data path has four parts 'C|P|S|D': {path!r}")
    return parts


def _missing(level: str, name: str, available: list) -> str:
    import difflib
    leaf = name.split(SEP)[-1]
    close = difflib.get_close_matches(leaf, available, n=3, cutoff=0.5)
    hint = f"; did you mean {close}?" if close else ""
    shown = ", ".join(available[:20]) + (", ..." if len(available) > 20 else "")
    return f"{level} {name!r} not found{hint} (available: {shown})"
