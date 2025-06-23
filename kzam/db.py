import sqlite3
from datetime import date, datetime

from kzam.datamodel import ArchiveReference, ArchiveDetails

sqlite3.register_adapter(date, lambda d: d.strftime("%Y-%m-%d"))
sqlite3.register_converter("DATE", lambda b: datetime.strptime(b.decode(), "%Y-%m-%d").date())


class DbManager:
    """Class for managing the sqlite3 database. Designed to be used as a context manager."""

    CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS archives (
            name TEXT NOT NULL,
            language TEXT NOT NULL,
            flavour TEXT,
            updated DATETIME NOT NULL,
            file_name TEXT NOT NULL,
            PRIMARY KEY (name, language, flavour)
        )
    """

    SELECT_ARCHIVES = """
        SELECT * FROM archives
        WHERE
            name = ?
            AND language = ?
            AND flavour = ?
        ORDER BY updated DESC
    """

    SELECT_ALL_ARCHIVES = """
        SELECT * FROM archives
    """

    INSERT_ARCHIVE = """
        INSERT INTO archives
        VALUES (?, ?, ?, ?, ?)
    """

    SELECT_OLDER = """
        SELECT * FROM archives
        WHERE
            name = ?
            AND language = ?
            AND flavour = ?
            AND updated < ?
    """

    DELETE_ARCHIVE = """
        DELETE FROM archives
        WHERE
            name = ?
            AND language = ?
            AND flavour = ?
            AND updated = ?
    """

    ARCHIVE_EXISTS = """
        SELECT EXISTS(
            SELECT 1 FROM archives
                WHERE
                    name = ?
                    AND language = ?
                    AND flavour = ?
                    AND updated = ?
        )
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        self.conn.row_factory = sqlite3.Row
        self.create_table()

    def create_table(self):
        with self.conn:
            self.conn.execute(self.CREATE_TABLE)

    def find_archives(self, ref: ArchiveReference) -> list[ArchiveDetails]:
        with self.conn:
            result = self.conn.execute(
                self.SELECT_ARCHIVES,
                (ref.name, ",".join(sorted(ref.language)), ref.flavour)
            )
        return [ArchiveDetails.from_row(r) for r in result]

    def all_archives(self) -> list[ArchiveDetails]:
        with self.conn:
            result = self.conn.execute(
                self.SELECT_ALL_ARCHIVES,
            )
        return [ArchiveDetails.from_row(r) for r in result]

    def archive_exists(self, ref: ArchiveReference, updated: datetime) -> bool:
        with self.conn:
            return bool(self.conn.execute(self.ARCHIVE_EXISTS, (
                ref.name,
                ",".join(sorted(ref.language)),
                ref.flavour,
                updated
            )).fetchone()[0])

    def get_older(self, ref: ArchiveReference, older_than: date) -> list[ArchiveDetails]:
        with self.conn:
            return [ArchiveDetails.from_row(r) for r in self.conn.execute(self.SELECT_OLDER, (
                ref.name,
                ",".join(sorted(ref.language)),
                ref.flavour,
                older_than
            ))]

    def delete_archive(self, archive: ArchiveDetails):
        with self.conn:
            self.conn.execute(self.DELETE_ARCHIVE, (
                archive.reference.name,
                ",".join(sorted(archive.reference.language)),
                archive.reference.flavour,
                archive.updated
            ))

    def insert_archive(self, archive: ArchiveDetails):
        with self.conn:
            self.conn.execute(self.INSERT_ARCHIVE, (
                archive.reference.name,
                ",".join(sorted(archive.reference.language)),
                archive.reference.flavour,
                archive.updated,
                archive.file_name
            ))
