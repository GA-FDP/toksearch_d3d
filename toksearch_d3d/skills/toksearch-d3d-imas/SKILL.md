---
name: toksearch-d3d-imas
description: ImasSignal for DIII-D IMAS IDS data — leaf/prefix paths, layout= control over ragged/jagged arrays (compact/filled/ragged/awkward), channel splitting, dimension control, and shared ImasComposer
user-invocable: false
license: Apache-2.0
compatibility: Claude Code
metadata:
  author: GA-FDP
  version: "2.0"
  url: https://ga-fdp.github.io/toksearch/
---

# TokSearch DIII-D ImasSignal

The canonical ImasSignal documentation lives in the `toksearch_d3d` package docstring.

Access it with: `help(toksearch_d3d)` or `python -c "help(toksearch_d3d)"`

For detailed constructor parameters: `help(toksearch_d3d.ImasSignal)`

Covers: leaf vs prefix paths, `layout=` shape control (`compact`/`filled`/`ragged`/`awkward`, defaulting to `compact` for leaf paths and `filled` for prefix paths), ragged arrays, split_by='channel', dims, dim_scales, NBI power recipe, ImasComposer sharing, list_imas_fields(), and common IDS paths.

Note: `core_profiles.profiles_1d` quantities are jagged under imas_composer
0.2.4 (one shared time axis, empty slots where a quantity has no data).
`layout=` is how you get a rectangular array back — see `help(toksearch_d3d)`.
