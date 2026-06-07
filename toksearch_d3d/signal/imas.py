# Copyright 2024 General Atomics
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Signal classes that expose imas_composer output through the toksearch Pipeline API.

Requires imas_composer to be installed (optional dependency).
"""

import numpy as np
from urllib.parse import urlparse

from toksearch import Signal
from toksearch.signal.mds import MdsSignal, MdsTreeRegistry, MdsConnectionRegistry, MdsTreePath
from toksearch_d3d.signal.ptdata import PtDataSignal
from imas_composer import ImasComposer

try:
    import awkward as ak
    _AWKWARD_AVAILABLE = True
except ImportError:
    _AWKWARD_AVAILABLE = False
    ak = None

_PTDATA_TREENAME = "__ptdata__"


def _to_numpy(val):
    """Convert a compose() value to a numpy array.

    For regular arrays or uniformly-shaped ak.Array: returns np.ndarray.
    For ragged ak.Array: returns a numpy object array whose elements are
    1-D numpy arrays, one per outer entry (e.g. one per channel or time slice).
    """
    if _AWKWARD_AVAILABLE and isinstance(val, ak.Array):
        try:
            return np.asarray(val)
        except (ValueError, TypeError):
            return np.array([np.asarray(row) for row in val], dtype=object)
    return np.asarray(val)


def list_imas_fields(ids=None, composer=None):
    """Return IMAS IDS fields supported by imas_composer.

    Args:
        ids: Optional IDS name (e.g. ``'ece'``, ``'equilibrium'``).
            When given, returns the sorted list of leaf paths for that IDS.
            When omitted, returns a dict mapping every IDS name to its sorted
            list of leaf paths.
        composer: Optional :class:`~imas_composer.ImasComposer` instance.
            If not provided, a default instance is created with
            ``ImasComposer()``. Pass a shared composer to avoid re-initialising
            mapper tables when one already exists.

    Returns:
        dict or list: A ``dict`` when ``ids`` is ``None``; a ``list`` of
        strings when ``ids`` is specified.

    Raises:
        ValueError: If ``ids`` is specified but is not a recognised IDS name.

    Example::

        from toksearch_d3d import list_imas_fields

        # All IDS names and their fields
        fields = list_imas_fields()
        print(list(fields.keys()))   # ['ece', 'equilibrium', ...]

        # Fields for a single IDS
        print(list_imas_fields('ece'))
        # ['ece.channel.name', 'ece.channel.t_e.data', ...]
    """
    if composer is None:
        composer = ImasComposer()

    # _mappers is private but is the only way to enumerate registered IDS names
    # without constructing dummy paths.  Its keys are the IDS names accepted by
    # get_supported_fields().
    ids_names = sorted(composer._mappers.keys())

    if ids is not None:
        if ids not in composer._mappers:
            raise ValueError(
                f"Unknown IDS '{ids}'. Available: {ids_names}"
            )
        return sorted(composer.get_supported_fields(ids))

    return {name: sorted(composer.get_supported_fields(name)) for name in ids_names}


class ImasSignal(Signal):
    """Fetch one or more IMAS IDS fields as a toksearch Signal.

    Wraps imas_composer's three-stage resolve/fetch/compose cycle and exposes
    the result through the standard Signal interface (`fetch` returns a dict with
    `'data'` and zero or more named dimension arrays, all as numpy arrays).

    `ids_path` may be either a **leaf path** or a **prefix path**:

    - **Leaf path** (`'ece.channel.t_e.data'`): fetches that single field.
      Returns `{'data': ndarray, ...dims}` as usual.
    - **Prefix path** (`'ece.channel'` or `'ece'`): fetches all supported fields
      under that subtree in one batched compose call.
      Returns `{full_ids_path: ndarray, ...}` — one plain array per leaf.

    For IDS fields that return ragged data (e.g. Thomson channel time series,
    equilibrium boundary outlines), `data` will be a numpy object array whose
    elements are 1-D numpy arrays.  Pass `split_by='channel'` to instead
    receive a dict keyed by channel name (or integer index).

    Args:
        ids_path: Full IMAS leaf path or prefix, e.g.
            `'equilibrium.time_slice.global_quantities.ip'` or `'ece.channel'`.
        composer: Optional shared `ImasComposer` instance.  If not supplied a
            default instance is created from the remaining keyword arguments.
            Sharing one composer across many `ImasSignal` objects avoids
            repeated mapper initialisation.
        efit_tree: Passed to `ImasComposer` when `composer=None`.
        efit_run_id: Passed to `ImasComposer` when `composer=None`.
        profiles_tree: Passed to `ImasComposer` when `composer=None`.
        profiles_run_id: Passed to `ImasComposer` when `composer=None`.
        fast_ece: Passed to `ImasComposer` when `composer=None`.
        location: MDSplus tree location. One of:

            - `None` — use environment variables (`{TREENAME}_path` or
              `default_tree_path`).
            - A path string, e.g. `'/path/to/trees'` — local trees at that path.
            - `'remote://atlas.gat.com'` — remote MDSplus server.
            - An `MdsTreePath` object — passed directly to `MdsSignal`.

        max_resolve_iterations: Maximum number of resolve/fetch iterations
            before giving up.
        split_by: How to handle channel-indexed data.

            - `None` (default) — return `{'data': ndarray, ...dims}` as usual;
              ragged fields become numpy object arrays.
            - `'channel'` — split the composed array along the channel axis and
              return a dict keyed by channel name (or integer index when names
              are unavailable).

        dims: Dict mapping dimension name to IDS path spec for supplementary
            arrays to fetch alongside `data`.  Default: `{"times": "auto"}`.

            Each value is either `'auto'` or an explicit IDS path string.

            `'auto'` resolution order:

            1. If `ids_path` ends in `.data` or `.data_error_upper`: replace
               that suffix with `.{dim_name}` (e.g. `channel.n_e.data` →
               `channel.n_e.time` for dim `"times"`).
            2. Otherwise fall back to `{ids_name}.{dim_name}` (e.g.
               `equilibrium.time` for dim `"times"` on an equilibrium path).

        dim_scales: Dict mapping dimension name to numeric scale factor applied
            to the fetched array.  Default: `{'times': 1000.0}`, which converts
            IMAS time arrays from seconds to milliseconds (matching the PTDATA /
            toksearch convention).  Pass `{'times': 1.0}` to keep raw IMAS seconds.
        units: Dict included verbatim as the `'units'` key in every per-channel
            entry when `split_by='channel'`.  Keys are dimension names, e.g.
            `{'data': 'm^-3', 'times': 'ms'}`.  Defaults to `{}`.
        as_awkward: If `True`, return the raw composed value from imas_composer
            without converting to numpy.  The result may be an `ak.Array`
            (regular or ragged) or a plain `np.ndarray` depending on the field.
            Useful for preserving ragged structure instead of receiving a numpy
            object array.  Defaults to `False` (numpy output).

    Example:
        ```python
        sig = ImasSignal('equilibrium.time_slice.global_quantities.ip')
        result = sig.fetch(202161)
        # result = {'data': array(shape=(n_time,)), 'times': array(shape=(n_time,))}
        ```
    """

    def __init__(
        self,
        ids_path,
        composer=None,
        efit_tree='EFIT01',
        efit_run_id='',
        profiles_tree='ZIPFIT01',
        profiles_run_id='',
        fast_ece=False,
        location=None,
        max_resolve_iterations=10,
        split_by=None,
        dims=None,
        dim_scales=None,
        units=None,
        as_awkward=False,
    ):
        super().__init__()
        self.set_dims(['times'])
        self.ids_path = ids_path
        self._composer = composer or ImasComposer(
            efit_tree=efit_tree,
            efit_run_id=efit_run_id,
            profiles_tree=profiles_tree,
            profiles_run_id=profiles_run_id,
            fast_ece=fast_ece,
        )
        self._max_iter = max_resolve_iterations
        self._as_awkward = as_awkward
        self._split_by = split_by
        self._dims = dims if dims is not None else {"times": "auto"}
        self._dim_scales = dim_scales if dim_scales is not None else {"times": 1000.0}
        self._units = units if units is not None else {}
        self._parse_location(location)

        # Detect leaf vs prefix path.
        leaf_paths = self._composer.get_supported_fields(ids_path)
        if len(leaf_paths) == 1 and leaf_paths[0] == ids_path:
            self._leaf_paths = None  # leaf mode — existing single-field behaviour
        elif len(leaf_paths) > 1:
            if split_by is not None:
                raise ValueError(
                    "split_by is not supported for prefix IDS paths"
                )
            self._leaf_paths = leaf_paths  # prefix mode — multi-field batch
        else:
            raise ValueError(f"No supported fields found for '{ids_path}'")

    def _parse_location(self, location):
        """Store location and determine cleanup mode."""
        self._location = location
        if isinstance(location, str):
            parsed = urlparse(location)
            self._is_remote = parsed.scheme == 'remote'
            self._server = parsed.netloc if self._is_remote else None
        else:
            self._is_remote = False
            self._server = None

    def _fetch_requirement(self, req):
        """Fetch a single imas_composer Requirement using MdsSignal or PtDataSignal."""
        if req.treename == _PTDATA_TREENAME:
            sig = PtDataSignal(req.mds_path, keep_header=True, fetch_units=False)
            result = sig.gather(req.shot)
            return {
                'data': result['data'],
                'times': result['times'],
                'rarray': result['header'].rarray.copy(),
            }
        elif self._is_remote:
            # Remote: use cached connection; connection.get() is a full TDI
            # evaluator so dim_of() and other expressions work fine.
            conn = MdsConnectionRegistry().connect(self._server)
            conn.openTree(req.treename, req.shot)
            return conn.get(req.mds_path).value
        else:
            # Local/Pelican: use cached tree from MdsTreeRegistry then evaluate
            # via tdiExecute(), which handles arbitrary TDI expressions
            # (dim_of(), scalars, node paths) unlike tree.getNode().
            tree = MdsTreeRegistry().open_tree(
                req.treename, req.shot, treepath=self._location
            )
            return tree.tdiExecute(req.mds_path).data()

    # Toksearch uses "times" as the conventional dim name, but the IMAS schema
    # names the field "time" (singular).  This map translates dim names to the
    # IDS component name used when constructing auto paths.
    _DIM_IDS_NAME = {"times": "time"}

    def _resolve_dim_ids_path(self, dim_name, dim_spec):
        """Return ordered candidate IDS paths that supply dimension ``dim_name``.

        Returns a list so callers can try each in turn until one resolves.

        ``dim_spec != 'auto'``:  returns ``[dim_spec]``.

        ``dim_spec == 'auto'`` and ``ids_path`` ends in ``.data`` or
        ``.data_error_upper``:
          Traverses from the most-specific sibling up to the IDS top level.
          E.g. for ``dim_name='times'`` and
          ``ids_path='ece.channel.t_e.data'``::

              ['ece.channel.t_e.time',   # strip .data, append .time
               'ece.channel.time',        # one level up
               'ece.time']               # IDS top level

        ``dim_spec == 'auto'`` otherwise:  returns
        ``['{ids_name}.{ids_component}']``.
        """
        if dim_spec != 'auto':
            return [dim_spec]
        ids_component = self._DIM_IDS_NAME.get(dim_name, dim_name)
        path = self.ids_path
        ids_name = path.split('.')[0]
        for suffix in ('.data_error_upper', '.data'):
            if path.endswith(suffix):
                base = path[:-len(suffix)]
                parts = base.split('.')
                candidates = [
                    '.'.join(parts[:i]) + f'.{ids_component}'
                    for i in range(len(parts), 0, -1)
                ]
                top = f'{ids_name}.{ids_component}'
                if top not in candidates:
                    candidates.append(top)
                return candidates
        return [f'{ids_name}.{ids_component}']

    def _fetch_dim(self, dim_path, shot, raw_data):
        """Resolve and compose a single dim path; return composed value or None."""
        try:
            ts, tr = {}, []
            for _ in range(self._max_iter):
                ts, tr = self._composer.resolve([dim_path], shot, raw_data)
                if ts.get(dim_path):
                    break
                for req in tr:
                    raw_data[req.as_key()] = self._fetch_requirement(req)
            if ts.get(dim_path):
                return self._composer.compose([dim_path], shot, raw_data)[dim_path]
        except Exception:
            pass
        return None

    def _fetch_all_dims(self, shot, raw_data):
        """Fetch, convert, and scale all ``self._dims``; return ``{dim_name: ndarray}``.

        For each dim, candidate IDS paths from ``_resolve_dim_ids_path`` are
        tried in priority order.  Any path equal to ``self.ids_path`` is
        skipped.  Dims that fail to resolve are omitted from the result.
        """
        result = {}
        for dim_name, dim_spec in self._dims.items():
            val = None
            for dim_path in self._resolve_dim_ids_path(dim_name, dim_spec):
                if dim_path == self.ids_path:
                    continue
                val = self._fetch_dim(dim_path, shot, raw_data)
                if val is not None:
                    break
            if val is not None:
                arr = _to_numpy(val)
                scale = self._dim_scales.get(dim_name, 1.0)
                result[dim_name] = arr * scale
        return result

    def _split_by_channel(self, shot, composed_val, raw_data):
        """Split a channel-indexed composed value into a dict keyed by channel name."""
        ids_name = self.ids_path.split('.')[0]

        # --- channel names ---
        names = None
        val = self._fetch_dim(f'{ids_name}.channel.name', shot, raw_data)
        if val is not None:
            names = np.asarray(val)

        # --- per-channel dimension arrays (already converted and scaled) ---
        dim_arrs = self._fetch_all_dims(shot, raw_data)

        # --- build result ---
        result = {}
        for i, row in enumerate(composed_val):
            key = str(names[i]) if (names is not None and i < len(names)) else str(i)
            entry = {'data': np.asarray(row), 'units': dict(self._units)}
            for dim_name, dim_arr in dim_arrs.items():
                try:
                    entry[dim_name] = np.asarray(dim_arr[i])
                except Exception:
                    pass
            result[key] = entry
        return result

    def _gather_prefix(self, shot):
        """Fetch and compose all leaf fields under the prefix path in one batch."""
        raw_data = {}

        for _ in range(self._max_iter):
            status, requirements = self._composer.resolve(
                self._leaf_paths, shot, raw_data
            )
            if all(status.values()):
                break
            for req in requirements:
                raw_data[req.as_key()] = self._fetch_requirement(req)

        composed = self._composer.compose(self._leaf_paths, shot, raw_data)
        convert = (lambda v: v) if self._as_awkward else _to_numpy
        return {path: convert(val) for path, val in composed.items()}

    def gather(self, shot):
        """Fetch and compose the IDS field(s) for the given shot.

        Returns:
            dict: When `ids_path` is a **leaf path** and `split_by` is `None`:
                `{'data': ndarray, ...dims}`.
                When `split_by='channel'`: a dict keyed by channel name,
                each value `{'data': ndarray, 'units': dict, ...dims}`.
                When `ids_path` is a **prefix path**: a dict keyed by full
                leaf path, each value a plain ndarray.
        """
        if self._leaf_paths is not None:
            return self._gather_prefix(shot)

        raw_data = {}

        # Phase 1: iteratively resolve and fetch requirements for the primary path
        for _ in range(self._max_iter):
            status, requirements = self._composer.resolve(
                [self.ids_path], shot, raw_data
            )
            if status[self.ids_path]:
                break
            for req in requirements:
                raw_data[req.as_key()] = self._fetch_requirement(req)

        # Phase 2: compose the primary path
        results = self._composer.compose([self.ids_path], shot, raw_data)
        composed = results[self.ids_path]

        if self._split_by == 'channel':
            return self._split_by_channel(shot, composed, raw_data)

        out = {'data': composed if self._as_awkward else _to_numpy(composed)}

        # Phase 3: supplementary dimension arrays
        out.update(self._fetch_all_dims(shot, raw_data))

        return out

    def fetch_as_xarray(self, shot):
        """Fetch and compose the IDS field, returning an xarray object.

        Returns:
            xr.DataArray: When `split_by` is `None` and data is a regular ndarray.
                Dimension names come from resolved `dims` entries; any data axes
                without a matching dim array receive a generic `'dim_N'` label.
            xr.Dataset: When `split_by='channel'`. One DataArray per channel;
                scalar dims (e.g. r, z channel positions) appear as variable
                attributes.

        Raises:
            NotImplementedError: When `split_by` is `None` and the data is a ragged
                object array (e.g. un-split Thomson channel time series).
                Use `fetch()` instead.

        Note:
            **Ragged data** (`split_by=None`, `dtype=object`): IDS fields that
                return a numpy object array — such as
                `thomson_scattering.channel.n_e.data` or
                `equilibrium.time_slice.boundary.outline.r` — raise
                `NotImplementedError`.  Use `fetch()` to get the raw dict.

            **Ambiguous axis assignment for N-D data**: Each 1-D dim array is
                matched to the first unused data axis of equal length.  If two axes
                have the same length the assignment may be wrong.  Supply explicit
                dim paths via the `dims` kwarg to resolve the ambiguity, or use
                `fetch()` and construct the `DataArray` manually.

            **Heterogeneous time bases with** `split_by='channel'`: Channels are
                merged with `xr.merge(..., join='outer')`, producing a unified
                `'times'` coordinate across the whole Dataset.  Channels that have
                no data at a particular time are NaN there.  Call `Pipeline.align()`
                on the result if you need a uniform, interpolated time base.
        """
        import xarray as xr

        if self._leaf_paths is not None:
            raise NotImplementedError(
                f"fetch_as_xarray() is not supported for prefix IDS paths "
                f"('{self.ids_path}'). Use fetch() instead."
            )

        result = self.gather(shot)

        if self._split_by == 'channel':
            return self._channel_result_to_dataset(result)

        data = result['data']

        if data.dtype == object:
            raise NotImplementedError(
                f"fetch_as_xarray() does not support ragged (object-array) "
                f"data from '{self.ids_path}'. Use fetch() instead."
            )

        # Match each 1-D dim array to the first unused data axis of equal
        # length.  Remaining axes get the generic label 'dim_N'.
        axis_dims   = {}  # ax → dim_name
        axis_coords = {}  # dim_name → array
        used_axes   = set()

        for dim_name in self._dims:
            if dim_name not in result:
                continue
            dim_arr = np.asarray(result[dim_name])
            if dim_arr.ndim != 1:
                continue
            for ax in range(data.ndim):
                if ax not in used_axes and data.shape[ax] == len(dim_arr):
                    axis_dims[ax]         = dim_name
                    axis_coords[dim_name] = dim_arr
                    used_axes.add(ax)
                    break

        xr_dims = [axis_dims.get(ax, f'dim_{ax}') for ax in range(data.ndim)]

        attrs = {}
        units = result.get('units', {})
        if 'data' in units:
            attrs['units'] = units['data']

        da = xr.DataArray(data, coords=axis_coords, dims=xr_dims, attrs=attrs)
        for dim_name in axis_coords:
            if dim_name in units:
                da[dim_name].attrs = {'units': units[dim_name]}
        return da

    def _channel_result_to_dataset(self, result):
        """Convert a channel-split ``gather()`` result to an ``xr.Dataset``.

        Each channel entry becomes one ``DataArray``.  1-D dim arrays aligned
        with the channel data become coordinates; scalar dims (e.g. r, z
        positions) become variable attributes.

        Channels are merged iteratively with ``xr.merge(..., join='outer')``,
        mirroring the approach used by ``Pipeline.fetch_dataset``.  Channels
        with heterogeneous time bases are represented by the union of all time
        values; entries with no data at a given time are NaN.
        """
        import xarray as xr

        ds = xr.Dataset()
        for ch_name, ch_entry in result.items():
            arr      = ch_entry['data']
            coords   = {}
            var_dims = []
            attrs    = {}

            for dim_name in self._dims:
                if dim_name not in ch_entry:
                    continue
                dim_arr = np.asarray(ch_entry[dim_name])
                if dim_arr.ndim == 1 and len(dim_arr) == len(arr):
                    # 1-D array aligned with data → coordinate
                    coords[dim_name] = dim_arr
                    var_dims.append(dim_name)
                elif dim_arr.ndim == 0 or (dim_arr.ndim == 1 and len(dim_arr) == 1):
                    # Scalar (e.g. r, z position) → attribute
                    attrs[dim_name] = float(dim_arr.flat[0])

            units = ch_entry.get('units', {})
            if 'data' in units:
                attrs['units'] = units['data']

            da = xr.DataArray(
                arr,
                coords=coords,
                dims=var_dims if var_dims else [f'{ch_name}__index'],
                attrs=attrs,
            )
            ds = xr.merge([ds, da.to_dataset(name=ch_name)], join="outer")

        return ds

    def cleanup_shot(self, shot):
        if self._is_remote:
            try:
                MdsConnectionRegistry().connect(self._server).closeAllTrees()
            except Exception:
                pass
        else:
            MdsTreeRegistry().close_all_trees()

    def cleanup(self):
        if self._is_remote:
            try:
                MdsConnectionRegistry().disconnect(self._server)
            except Exception:
                pass
        else:
            MdsTreeRegistry().close_all_trees()


# Device-prefixed alias for cross-device symmetry with other device packages
# (e.g. toksearch_mast.MastImasSignal). ``D3dImasSignal`` is exactly
# equivalent to ``ImasSignal``; the unprefixed name is preserved for
# backward compatibility.
D3dImasSignal = ImasSignal
