# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Interpret a phase's parameter blocks as the data items pcssetup names.

A static data item ``D`` (a waveform-list entry whose description starts
with ``StaticData``) is a group of parameter blocks whose names start
with ``D``. pcsapi's editors read them by name (d3d_pcs
``core/infra/pcsapi/editorInfo.cpp``), and so does this module:

==============  ==============================================  =========
kind            blocks                                          pcsapi
==============  ==============================================  =========
``generic``     ``D :data``, ``D :labels``                      Generic
``values``      ``D :data`` only (labels not archived)          (Generic)
``labels``      ``D :labels`` only (values not archived)        (Generic)
``file``        ``D :file name``                                File
``matrix``      ``D dimensions``/``row names``/``col names``/   Matrix
                ``names``/``data``
``opsetup``     ``D :infra``, ``D :infra cpu``                  OpSetUp
``opaque``      anything else (the blocks stay readable)        --
==============  ==============================================  =========

pcsapi picks an editor from the item's ``EDITOR`` keyword, which is
compiled into the PCS and not archived. Here the kind is inferred from
which blocks exist, which matches pcsapi's choice for the editors it
decodes (checked against waveserver snapshots; see the spec).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .model import ParamBlock, ParamField, Phase


class ItemDecodeError(ValueError):
    """The blocks of a static data item are inconsistent."""


def strings(raw: bytes) -> list:
    """pcsapi interpretStrings: NUL-separated strings, empty ones dropped."""
    return [s.decode("latin-1") for s in raw.split(b"\0") if s]


def field_values(f: ParamField) -> list:
    """A descriptor's values the way pcsapi's pdbItems returns them."""
    if f.type == "char":
        return strings(bytes(f.value)) or [""]
    if f.type == "float":
        return [float(x) for x in np.asarray(f.value, np.float32)]
    if f.type == "double":
        return [float(x) for x in np.asarray(f.value)]
    return [int(x) for x in np.asarray(f.value)]


def block_values(b: ParamBlock) -> list:
    """All values of a block, flattened in descriptor order."""
    out = []
    for f in b.fields:
        out.extend(field_values(f))
    return out


# --------------------------------------------------------------------------
# Generic editor (editorInfo.cpp Generic::build, lines 243-410)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class GenericItem:
    title: str
    value: object
    label: str  # the raw label, keywords and all
    widget: str  # Text | ComboBox | List | CheckBox | Radio
    options: Optional[dict]  # value -> sublabel for choice widgets


def _label_items(labels: list, values: list) -> list:
    if len(labels) != len(values):
        raise ItemDecodeError(
            f"{len(labels)} labels for {len(values)} values (pcsapi: "
            "'mismatch labels and data count')")
    out = []
    prev = None  # (type, base, sublabels) of the previous item, for SAME
    for label, value in zip(labels, values):
        elems = label.split(",")[0].split("|")
        same = "SAME" in elems
        if same and prev is not None:
            typ, base, sublabels = prev[0], prev[1], list(prev[2])
        else:
            typ, base, sublabels = "", 0, []
        title, parsed, found_title = "", [], False
        for elem in elems:
            if elem == "SAME":
                continue
            kv = elem.split(":")
            if len(kv) >= 2:
                key = kv[0].upper()
                rest = elem[len(key) + 1:]
                if key == "BASE":
                    base = _int_prefix(rest, base)
                elif key == "TITLE":
                    title, found_title = rest, True
                elif key == "TYPE":
                    typ = rest
                # TAB, FACTOR, MIN, MAX only shape the editor display
            elif not title and typ not in ("LIST", "DROPLIST"):
                title = elem
            else:
                parsed.append(elem)
        if parsed:
            sublabels = parsed
        typ = typ.upper()
        if typ == "" and not sublabels:
            widget = "Text"
        elif (typ == "" and sublabels) or typ == "DROPLIST":
            widget = "ComboBox"
        elif typ == "LIST":
            widget, title = "List", ""
        elif typ == "BUTTON":
            widget = "Radio" if sublabels else "CheckBox"
        else:
            raise ItemDecodeError(f"label {label!r}: unknown widget type {typ!r}")
        options = None
        if widget in ("ComboBox", "List", "Radio"):
            options = {}
            for i, sub in enumerate(sublabels):
                kv = sub.split("=")
                key = kv[1] if len(kv) == 2 else i + base
                if isinstance(value, float):
                    key = float(key)
                elif isinstance(value, int):
                    key = _int_prefix(str(key))
                options[key] = sub
        out.append(GenericItem(title=title, value=value, label=label,
                               widget=widget, options=options))
        prev = (typ, base, sublabels)
    return out


def _int_prefix(text: str, default: int = 0) -> int:
    """std::from_chars for int: a leading [-]digits run, else ``default``."""
    n = text[1:] if text[:1] == "-" else text
    digits = len(n) - len(n.lstrip("0123456789"))
    if digits == 0:
        return default
    return int(text[:digits + (len(text) - len(n))])


# --------------------------------------------------------------------------
# Item values
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class GenericValue:
    items: tuple  # (GenericItem, ...)

    def as_dict(self) -> dict:
        """{title: value}, as pcssetup's snapshot records a generic item."""
        return {it.title: it.value for it in self.items}


@dataclass(frozen=True)
class MatrixValue:
    names: tuple
    row_names: tuple
    col_names: tuple
    data: np.ndarray  # float32, shape (n_matrices, n_rows, n_cols)


@dataclass(frozen=True)
class OpSetupValue:
    shot_num: int
    time_to_stop: int
    op_mode: str
    sim_host: str
    sim_port: int
    cpus: tuple  # one dict per CPU block in the file

    @property
    def n_samples(self) -> tuple:
        return tuple(c["num_samples"] for c in self.cpus)


OP_MODES = ("normal", "software", "simulation", "setup", "hardware")
_CPU_FIELDS = ("first_sample_time", "num_samples", "sample_interval",
               "fast_data_start", "num_fast_samples", "save_routine_id",
               "save_s_file")


def item_kind(phase: Phase, name: str) -> str:
    have = {b.name for b in phase.param_blocks}
    if f"{name} :infra" in have and f"{name} :infra cpu" in have:
        return "opsetup"
    if f"{name} :data" in have and f"{name} :labels" in have:
        return "generic"
    if f"{name} :data" in have:
        return "values"  # labels not archived: values without titles
    if f"{name} :labels" in have:
        return "labels"  # values not archived: titles only
    if f"{name} :file name" in have:
        return "file"
    if all(f"{name} {s}" in have for s in
           ("dimensions", "row names", "col names", "names", "data")):
        return "matrix"
    return "opaque"


def item_blocks(phase: Phase, name: str) -> tuple:
    """The parameter blocks that belong to static data item ``name``."""
    return tuple(b for b in phase.param_blocks
                 if b.name == name or b.name.startswith(name + " "))


def decode_item(phase: Phase, name: str):
    """(kind, value) for static data item ``name`` of ``phase``."""
    kind = item_kind(phase, name)
    blk = {b.name: b for b in phase.param_blocks}
    if kind == "generic":
        labels = field_values(blk[f"{name} :labels"].fields[0])
        values = block_values(blk[f"{name} :data"])
        return kind, GenericValue(tuple(_label_items(labels, values)))
    if kind == "values":
        return kind, tuple(block_values(blk[f"{name} :data"]))
    if kind == "labels":
        labels = field_values(blk[f"{name} :labels"].fields[0])
        items = _label_items(labels, [None] * len(labels))
        return kind, {it.title: None for it in items}
    if kind == "file":
        return kind, field_values(blk[f"{name} :file name"].fields[0])[0]
    if kind == "matrix":
        dims = block_values(blk[f"{name} dimensions"])
        nmat, nrow, ncol = dims[0], dims[1], dims[2]
        data = np.asarray(blk[f"{name} data"].fields[0].value, np.float32)
        if data.size < nmat * nrow * ncol:
            raise ItemDecodeError(
                f"matrix {name!r}: {data.size} values for {nmat}x{nrow}x{ncol}")
        return kind, MatrixValue(
            names=tuple(field_values(blk[f"{name} names"].fields[0])),
            row_names=tuple(field_values(blk[f"{name} row names"].fields[0])),
            col_names=tuple(field_values(blk[f"{name} col names"].fields[0])),
            data=data[:nmat * nrow * ncol].reshape(nmat, nrow, ncol))
    if kind == "opsetup":
        infra = [field_values(f) for f in blk[f"{name} :infra"].fields]
        cpu = [field_values(f)[0] for f in blk[f"{name} :infra cpu"].fields]
        hardware, software = infra[0][0], infra[1][0]
        mode = "hardware" if hardware == 1 else (
            OP_MODES[software] if 0 <= software < len(OP_MODES) else str(software))
        cpus = tuple(dict(zip(_CPU_FIELDS, cpu[i:i + 7]))
                     for i in range(0, len(cpu) - 6, 7))
        return kind, OpSetupValue(shot_num=infra[2][0], time_to_stop=infra[3][0],
                                  op_mode=mode, sim_host=infra[5][0],
                                  sim_port=infra[4][0], cpus=cpus)
    return kind, item_blocks(phase, name)
