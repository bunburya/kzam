import os
import tomllib
from dataclasses import dataclass, field

from kzam.datamodel import ArchiveReference


@dataclass
class Config:
    config_file_path: str
    rss_base_url: str
    base_dir: str
    kiwix_manage_exec: str
    archives: list[ArchiveReference]
    archive_dir: str = field(init=False)
    library_path: str = field(init=False)
    db_path: str = field(init=False)

    def __post_init__(self):
        self.archive_dir = os.path.join(self.base_dir, "archives")
        self.library_path = os.path.join(self.base_dir, "library.xml")
        self.db_path = os.path.join(self.base_dir, "archives.db")

    @classmethod
    def from_toml_file(cls, toml_file_path: str) -> "Config":
        with open(toml_file_path, "rb") as f:
            c = tomllib.load(f)
        return Config(
            config_file_path=toml_file_path,
            rss_base_url=c["rss_base_url"],
            base_dir=c["base_dir"],
            kiwix_manage_exec=c["kiwix_manage_exec"],
            archives=[ArchiveReference(a["name"], frozenset(a["language"].split(",")), a.get("flavour")) for a in c.get("archive", [])]
        )