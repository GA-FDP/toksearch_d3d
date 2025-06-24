import os
import sqlite3
from contextlib import closing
from toksearch import MdsSignal, MdsTreePath
from typing import Optional, Union, Iterable

_conn_cache = None


class CakeSignal(MdsSignal):
    def __init__(
        self,
        expression: str,
        treename: str,
        location: Optional[Union[str, MdsTreePath]] = None,
        dims: Iterable[str] = ("times",),
        data_order: Optional[Iterable[str]] = None,
        fetch_units: bool = True,
        cake_db_location: str | None = None,
    ):
        """Create a signal object that fetches CAKE data from MDSplus

        Arguments:
            expression: The tdi expression to fetch data from
            treename: The name of the tree to fetch from. Must be either
                "eq" or "prof"

            cake_db_location: Location of the cake sqlite db file. If None, it
                will attempt to read the environment variable CAKE_DB_PATH.
            location: The location of the tree.

                - If None, check if the environment variable TOKSEARCH_MDS_DEFAULT is
                set and use it, otherwise assume that the tree is on a local disk
                and that the treepath is available in the environment.

                - If a simple path is given
                (e.g. /some/path), then that will be used for the treepath. You can
                also specify a remote server by specifying the location as
                'remote://some.server'

                - If an MdsTreePath object is provided, then the signal data is
                fetched from a local disk according to the path specifications in
                the MdsTreePath object.
            dims: See documentation for the Signal class. Defaults to ('times',)
            data_order: See documentation for the Signal class. Defaults to the same
                as dims.
            fetch_units: See documentation for the Signal class. Defaults
                to True.
        """

        if treename == "eq" or treename == "efit":
            _treename = "efit"
        elif treename == "prof" or treename == "omfit_profs":
            _treename = "omfit_profs"
        else:
            msg = f"Invalid treename {treename}. Must eq, efit, prof, or omfit_profs"
            raise Exception(msg)

        super().__init__(
            expression,
            _treename,
            location=location,
            dims=dims,
            data_order=data_order,
            fetch_units=fetch_units,
        )

        self.treename = _treename

        self.cake_db_location = cake_db_location or os.getenv("CAKE_DB_PATH", None)

        if not self.cake_db_location:
            msg = f"cake_db_location not set"
            raise Exception(msg)

    def get_db_conn(self) -> sqlite3.Connection:
        # Use self.cake_db_location to get connection.
        # Check the cache first

        global _conn_cache

        if not _conn_cache:
            _conn_cache = sqlite3.connect(self.cake_db_location)

        return _conn_cache

    def get_upload_ids(self, shot: int) -> int:
        # Use shot number and self.sig.treename to get the upload_id

        conn = self.get_db_conn()

        with closing(conn.cursor()) as cursor:
            query = "select efit_upload_id, omfit_profs_upload_id from blessed_cakes where shot = ?"
            results = cursor.execute(query, (shot,))
            efit_upload_id, omfit_profs_upload_id = results.fetchone()

        return efit_upload_id, omfit_profs_upload_id

    def gather(self, shot):

        efit_upload_id, omfit_profs_upload_id = self.get_upload_ids(shot)

       
        if self.treename == "efit":
            upload_id = efit_upload_id
        elif self.treename == "omfit_profs":
            upload_id = omfit_profs_upload_id
        else:
            msg = f"Invalid treename {treename}. Must eq, efit, prof, or omfit_profs"
            raise Exception(msg)


        return super().gather(upload_id)

    def cleanup(self):
        if _conn_cache:
            try:
                _conn_cache.close()
            except Exception as e:
                print(f"Warning - Failed to close connection cache: {e}")
        super().cleanup()

