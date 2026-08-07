"""Read a PyTorch ``.pt`` file into plain numpy arrays, without importing torch.

Why this exists
---------------
``engine_v2/model_params/`` ships three files the serving process never
loads: ``artist_model_state.pt``, ``track_model_state.pt`` and
``genre_features.pt``. Two of the tensors inside them are not redundant --
``artist_bias`` and ``user_bias`` are part of the artist model's scoring
function::

    score(u, a) = user_emb[u] . artist_emb[a] + user_bias[u] + artist_bias[a]

but ``engine_v2/recommender.py`` ranks artists with the dot product alone,
because the biases were never exported to ``.npy``. That is a train/serve
mismatch (see ANALYSIS.md, finding S-1). We want the biases in the serving
bundle -- but we do *not* want torch in the serving venv, and we do not want
it in the conversion step either: a ~900 MB dependency to recover 25 KB of
floats is a bad trade for a build tool that runs once per retrain.

A ``.pt`` file is just a zip archive: one pickle describing the tensors, plus
one flat binary blob per storage. Rebuilding numpy arrays from that needs
about eighty lines of custom unpickling, which is what this module is.

Supported: ``torch.save`` of a ``state_dict`` or a single tensor, dense
CPU/CUDA tensors of the common dtypes, both the modern zip format and
sharded storages. Not supported (and rejected loudly): sparse tensors,
``torch.jit`` archives, and the pre-1.6 non-zip legacy format -- none of
which the training notebook produces.
"""
from __future__ import annotations

import pickle
import zipfile
from pathlib import Path

import numpy as np

# torch storage class name -> numpy dtype. Only the dtypes the training
# notebook can actually emit (it saves float32 weights) plus the handful that
# cost nothing to support.
_DTYPES = {
    "FloatStorage": np.dtype("float32"),
    "DoubleStorage": np.dtype("float64"),
    "HalfStorage": np.dtype("float16"),
    "LongStorage": np.dtype("int64"),
    "IntStorage": np.dtype("int32"),
    "ShortStorage": np.dtype("int16"),
    "CharStorage": np.dtype("int8"),
    "ByteStorage": np.dtype("uint8"),
    "BoolStorage": np.dtype("bool"),
}


class _Storage:
    """Stand-in for a torch storage: the key of its blob inside the zip."""

    def __init__(self, key: str, dtype: np.dtype):
        self.key = key
        self.dtype = dtype


def _rebuild_tensor_v2(storage, storage_offset, size, stride, *_rest):
    """Replacement for ``torch._utils._rebuild_tensor_v2``.

    Called by the unpickler with a ``_Storage`` in place of the real thing;
    returns the (offset, size, stride) recipe, which `load` then resolves
    against the actual bytes once they're read out of the zip.
    """
    return ("tensor", storage, int(storage_offset), tuple(size), tuple(stride))


class _OrderedDict(dict):
    """Plain dict standing in for ``collections.OrderedDict``.

    ``OrderedDict.__reduce__`` ships an (often empty) instance ``__dict__`` as
    pickle state, and pickle's BUILD opcode would try to write it onto a bare
    dict, which has no ``__dict__``. Swallowing the state here keeps the
    items -- the only part we want -- and drops the rest.
    """

    def __setstate__(self, state):  # noqa: D105 - see class docstring
        return None


class _Unpickler(pickle.Unpickler):
    """Resolves torch's global names to the shims above instead of importing torch."""

    def find_class(self, module: str, name: str):
        if module == "torch._utils" and name in ("_rebuild_tensor_v2", "_rebuild_tensor"):
            return _rebuild_tensor_v2
        if module == "torch" and name in _DTYPES:
            return name  # storage class, referenced by name only
        if module == "collections" and name == "OrderedDict":
            return _OrderedDict
        raise pickle.UnpicklingError(
            f"refusing to resolve {module}.{name} while reading a .pt file without torch; "
            "this file uses a feature torch_pickle.py does not support"
        )

    def persistent_load(self, pid):
        # torch writes storages as persistent ids:
        #   ('storage', <storage_type>, <key>, <device>, <numel>)
        if not (isinstance(pid, tuple) and pid and pid[0] == "storage"):
            raise pickle.UnpicklingError(f"unsupported persistent id in .pt file: {pid!r}")
        _, storage_type, key, _device, _numel = pid
        name = storage_type if isinstance(storage_type, str) else getattr(storage_type, "__name__", "")
        if name not in _DTYPES:
            raise pickle.UnpicklingError(f"unsupported storage dtype in .pt file: {name!r}")
        return _Storage(str(key), _DTYPES[name])


def _as_array(node, blobs: dict[str, bytes], byteorder: str):
    """Turn one unpickled node into a numpy array (or recurse into containers)."""
    if isinstance(node, tuple) and node and node[0] == "tensor":
        _, storage, offset, size, stride = node
        raw = blobs[storage.key]
        dtype = storage.dtype.newbyteorder("<" if byteorder == "little" else ">")
        flat = np.frombuffer(raw, dtype=dtype)
        n = int(np.prod(size)) if size else 1
        if stride and size:
            # as_strided over the storage handles non-contiguous tensors; the
            # state dicts here are always contiguous, but this costs nothing.
            itemsize = dtype.itemsize
            view = np.lib.stride_tricks.as_strided(
                flat[offset:], shape=size, strides=tuple(s * itemsize for s in stride)
            )
            return np.ascontiguousarray(view)
        return flat[offset : offset + n].reshape(size).copy()
    if isinstance(node, dict):
        return {k: _as_array(v, blobs, byteorder) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return type(node)(_as_array(v, blobs, byteorder) for v in node)
    return node


def load(path: str | Path) -> dict | np.ndarray:
    """Read ``path`` and return its tensors as numpy arrays.

    A saved ``state_dict`` comes back as ``{param_name: np.ndarray}``; a saved
    single tensor comes back as one array.
    """
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise ValueError(
            f"{path} is not a zip-format .pt file (torch < 1.6 legacy format is not supported)"
        )

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        try:
            pickle_name = next(n for n in names if n.endswith("data.pkl"))
        except StopIteration:
            raise ValueError(f"{path} contains no data.pkl -- is it a torch.jit archive?") from None
        prefix = pickle_name[: -len("data.pkl")]

        byteorder = "little"
        if f"{prefix}byteorder" in names:
            byteorder = zf.read(f"{prefix}byteorder").decode().strip() or "little"

        # Storage blobs live under "<prefix>data/<key>"; read them all up front,
        # they are the bulk of the file anyway.
        blobs = {
            n[len(prefix) + len("data/") :]: zf.read(n)
            for n in names
            if n.startswith(f"{prefix}data/")
        }

        with zf.open(pickle_name) as fh:
            tree = _Unpickler(fh).load()

    return _as_array(tree, blobs, byteorder)
