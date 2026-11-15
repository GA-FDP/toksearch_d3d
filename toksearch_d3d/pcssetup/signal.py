# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""``PcsSetupSignal``: selected PCS setup items per shot, for a Pipeline."""

from __future__ import annotations

from typing import Iterable, Optional

from toksearch import Signal


class PcsSetupSignal(Signal):
    """Read items of each shot's PCS setup (pointname ``PCSSETUP``).

    ::

        from toksearch import Pipeline
        from toksearch_d3d.pcssetup import PcsSetupSignal

        p = Pipeline([204019, 206863])
        p.fetch("setup", PcsSetupSignal([
            "Discharge Shape|ShotStart",                        # phase
            "Discharge Shape|ShotStart|Discharge shape|Rp",     # waveform
            "Error Field|Icontrol|Shared EF & RWM waveforms|Parameters",
        ]))
        rec = p.compute_serial()[0]
        rec["setup"]["data"]["Discharge Shape|ShotStart"]["alg"]

    ``data`` is ``{path: value}`` with the values of
    :meth:`toksearch_d3d.pcssetup.Setup.read`. A path the shot's setup
    does not have maps to ``None`` (setups differ from shot to shot), so
    one missing item does not drop the shot. Pass ``scope`` instead of
    ``paths`` to get :meth:`Setup.snapshot` of everything under a
    category, phase or subset: ``{path: (kind, value)}``.

    Each shot fetches the whole ``PCSSETUP`` point (1-5 MB) once,
    however many paths are asked for. Run under ``fdp run``.
    """

    def __init__(self, paths: Optional[Iterable[str]] = None,
                 scope: Optional[str] = None):
        super().__init__()
        if (paths is None) == (scope is None):
            raise ValueError("pass exactly one of paths= or scope=")
        self.paths = None if paths is None else tuple(paths)
        self.scope = scope
        self.set_dims(None)
        self.with_units = False

    def _spec_fields(self):
        return {"paths": self.paths, "scope": self.scope}

    def gather(self, shot):
        from . import pcssetup
        setup = pcssetup(int(shot))
        if self.scope is not None:
            data = setup.snapshot(self.scope)
        else:
            data = {}
            for path in self.paths:
                try:
                    data[path] = setup.read(path)
                except KeyError:
                    data[path] = None
        return {"data": data}

    def cleanup_shot(self, shot):
        pass

    def cleanup(self):
        pass
