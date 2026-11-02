from typing import Annotated
from pydantic import StringConstraints

Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=50,
        pattern=r"^[a-z0-9_.-]+$",
    ),
]