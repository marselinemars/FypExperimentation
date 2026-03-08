import hashlib
import random

import numpy as np


def _normalize_seed(seed_value):
    if seed_value is None:
        return None
    return int(seed_value) % (2 ** 32)


def set_global_seeds(python_seed=None, numpy_seed=None):
    python_seed = _normalize_seed(python_seed)
    numpy_seed = _normalize_seed(numpy_seed)

    if python_seed is not None:
        random.seed(python_seed)
    if numpy_seed is not None:
        np.random.seed(numpy_seed)


def derive_seed(base_seed, *parts):
    base_seed = _normalize_seed(base_seed)
    if base_seed is None:
        return None

    payload = "|".join([str(base_seed)] + [str(part) for part in parts]).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return int(digest[:8], 16)
