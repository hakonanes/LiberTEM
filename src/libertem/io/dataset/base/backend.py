import logging
from typing import Dict, Optional, Type
import contextlib

import numpy as np

from .fileset import FileSet

log = logging.getLogger(__name__)


class IOBackend:
    registry: Dict[str, Type["IOBackend"]] = {}
    id_: Optional[str] = None

    def __init_subclass__(cls, id_: Optional[str] = None):
        super().__init_subclass__()
        if id_ is not None:
            cls.registry[id_] = cls
            cls.id_ = id_

    @classmethod
    def get_cls_by_id(cls, id_):
        return cls.registry.get(id_)

    @classmethod
    def get_supported(cls):
        return [
            k
            for k in cls.registry.keys()
            if cls.registry[k].platform_supported()
        ]

    def __init__(self):
        pass

    def get_impl(self) -> 'IOBackendImpl':
        raise NotImplementedError()

    @classmethod
    def platform_supported(cls):
        return True

    @classmethod
    def from_json(cls, msg):
        """
        Construct an instance from the already-decoded `msg`.
        """
        raise NotImplementedError()


class IOBackendImpl:
    def __init__(self):
        pass

    @contextlib.contextmanager
    def open_files(self, fileset: FileSet):
        """
        Open files, yielding a list of implementation-specific file objects
        representing these open files.

        Parameters
        ----------
        fileset : FileSet
            [description]
        """
        raise NotImplementedError()

    def need_copy(
        self, decoder, roi, native_dtype, read_dtype, tiling_scheme=None, fileset=None,
        sync_offset=0, corrections=None,
    ) -> bool:
        # checking conditions in which "straight mmap" is not possible
        # straight mmap means our dataset can just return views into the underlying mmap object
        # as tiles and use them as they are in the UDFs

        # 1) if a roi is given, straight mmap doesn't work because there are gaps in the navigation
        # axis:
        if roi is not None:
            log.debug("have roi, need copy")
            return True

        # 2) if we need to decode data, or do dtype conversion, we can't return
        # views into the underlying file:
        if self._need_decode(decoder, native_dtype, read_dtype):
            log.debug("have decode, need copy")
            return True

        # 3) if we have less number of frames per file than tile depth, we need to copy
        if tiling_scheme and fileset:
            fileset_arr = fileset.get_as_arr()
            if np.min(fileset_arr[:, 1] - fileset_arr[:, 0]) < tiling_scheme.depth:
                log.debug("too large for fileset, need copy")
                return True

        # 4) if we apply corrections, we need to copy
        if corrections is not None and corrections.have_corrections():
            log.debug("have corrections, need copy")
            return True

        # 5) if a negative offset is given, we need to copy
        if sync_offset < 0:
            log.debug("negative offset is set, need copy")
            return True

        return False

    def get_max_io_size(self):
        return 2**20  # default: 1MiB blocks

    def _need_decode(self, decoder, native_dtype, read_dtype):
        # FIXME: even with dtype "mismatch", we can possibly do dtype
        # conversion, if the tile size is small enough! maybe benchmark this
        # vs. _get_tiles_w_copy?
        if native_dtype != read_dtype:
            return True
        if decoder is not None:
            return True
        return False

    def preprocess(self, data, tile_slice, corrections):
        if corrections is None:
            return
        corrections.apply(data, tile_slice)

    def get_tiles(
        self, tiling_scheme, fileset, read_ranges, roi, native_dtype, read_dtype, decoder,
        sync_offset, corrections,
    ):
        """
        Read tiles from `fileset`, as specified by the parameters.

        Usually, this is used to read the data for a single partition.

        Parameters
        ----------

        tiling_scheme : TilingScheme
            Specifies how the tiles should be shaped

        fileset : FileSet
            The files that should be read from. Note that the order in the `FileSet` is important,
            it must match the indices on the `read_ranges`.

        read_ranges : np.ndarray
            Read ranges, as generated by :meth:`FileSet.get_read_ranges`

        roi : np.ndarray
            Boolean array specifying which data should be read

        native_dtype : np.dtype
            The native on-disk data type. If there is no direct match to
            a numpy dtype, specify the closest dtype.

        read_dtype : np.dtype
            The data dtype into which the data is converted when reading

        decoder : libertem.io.dataset.base.Decoder

        sync_offset : int
            if positive, number of frames to skip from the start
            if negative, number of blank frames to insert at the start

        corrections
            A set of corrections to apply in a preprocesing step
        """
        raise NotImplementedError()
