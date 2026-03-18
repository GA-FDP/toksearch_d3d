from pathlib import Path


def _parse_skill_md(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text) from a SKILL.md file."""
    text = path.read_text()
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        fm_dict = {}
        for line in fm.strip().splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm_dict[k.strip()] = v.strip()
        return fm_dict, body.lstrip("\n")
    return {}, text


def _skill_dirs() -> list[Path]:
    """Return sorted list of all skill directories from both packages."""
    import toksearch
    import toksearch_d3d as _tsd3d

    sources = [
        Path(toksearch.__file__).parent / "skills",
        Path(_tsd3d.__file__).parent / "skills",
    ]
    return [
        d
        for source in sources if source.exists()
        for d in sorted(source.iterdir()) if d.is_dir()
    ]


def list_skills() -> list[str]:
    """Return names of all available FDP skills."""
    return [d.name for d in _skill_dirs()]


def get_system_prompt(skills: list[str] | None = None) -> str:
    """Return skill markdown bodies concatenated into a single system-prompt string.

    Parameters
    ----------
    skills:
        Skill names to include.  ``None`` (default) includes all available skills.

    Returns
    -------
    str
        Concatenated markdown text, one skill per section, ready to pass as a
        system prompt to any LLM API (OpenAI, Anthropic, LangChain, etc.).

    Example
    -------
    >>> from toksearch_d3d.fdp.skills import get_system_prompt
    >>> import openai
    >>> client = openai.OpenAI()
    >>> response = client.chat.completions.create(
    ...     model="gpt-4o",
    ...     messages=[
    ...         {"role": "system", "content": get_system_prompt()},
    ...         {"role": "user", "content": "How do I fetch DIII-D data?"},
    ...     ],
    ... )
    """
    dirs = _skill_dirs()
    if skills is not None:
        skill_set = set(skills)
        dirs = [d for d in dirs if d.name in skill_set]

    parts = []
    for d in dirs:
        skill_md = d / "SKILL.md"
        if skill_md.exists():
            _, body = _parse_skill_md(skill_md)
            parts.append(body.strip())

    return "\n\n---\n\n".join(parts)
