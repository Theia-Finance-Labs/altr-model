"""Shared parameter validation for pipeline nodes.

Every switch validated through here selects between behaviours that move
published numbers. Each one was reached by an `if x == "a": ... else: ...`,
so a misspelling did not raise — it silently took the other arm and the run
completed, reporting a different model than the config asked for. The nodes
call `validate_choice` at entry instead, so a typo fails loudly at the top of
the node rather than quietly at the bottom of a spreadsheet.
"""


def validate_choice(name: str, value: str, allowed: tuple[str, ...]) -> str:
    """Return ``value`` unchanged, or raise naming every legal option.

    Args:
        name: The parameter as a reader finds it in ``conf/`` — including its
            ``dcf.`` prefix where it has one — so the error points at the line
            to edit rather than at a Python argument.
        value: What the config supplied.
        allowed: The legal values, in the order the documentation lists them.
    """
    if value not in allowed:
        options = ", ".join(repr(option) for option in allowed)
        raise ValueError(
            f"{name} must be one of {options}; got {value!r}. "
            "An unrecognised value is rejected rather than falling through to "
            "a default branch, which would silently change the model."
        )
    return value
