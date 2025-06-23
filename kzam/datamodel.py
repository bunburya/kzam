import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from xml.etree.ElementTree import Element

from kzam.xml_utils import ENTRIES_NSMAP, META_NSMAP


@dataclass(eq=True, frozen=True)
class ArchiveEntry:
    """Details of a single archive according to its entry in the Kiwix RSS feed."""
    id: str
    title: str
    updated: datetime
    summary: str
    language: frozenset[str]
    name: str
    flavor: Optional[str]
    category: Optional[str]
    tags: frozenset[str]
    article_count: int
    media_count: int
    author_name: str
    publisher_name: str
    meta_link: str

    def to_reference(self) -> "ArchiveReference":
        return ArchiveReference(
            self.name,
            self.language,
            self.flavor
        )

    @classmethod
    def from_xml(cls, elem: Element) -> "ArchiveEntry":
        #print(list(elem))
        for link in elem.findall("atom:link", ENTRIES_NSMAP):
            if link.attrib["type"] == "application/x-zim":
                meta_link = link.attrib["href"]
                break
        else:
            raise ValueError("Could not find meta link.")
        return cls(
            elem.find("atom:id", ENTRIES_NSMAP).text,
            elem.find("atom:title", ENTRIES_NSMAP).text,
            datetime.fromisoformat(elem.find("atom:updated", ENTRIES_NSMAP).text),
            elem.find("atom:summary", ENTRIES_NSMAP).text,
            frozenset(elem.find("atom:language", ENTRIES_NSMAP).text.split(",")),
            elem.find("atom:name", ENTRIES_NSMAP).text,
            elem.find("atom:flavour", ENTRIES_NSMAP).text or None,
            elem.find("atom:category", ENTRIES_NSMAP).text or None,
            frozenset(elem.find("atom:tags", ENTRIES_NSMAP).text.split(";")),
            int(elem.find("atom:articleCount", ENTRIES_NSMAP).text),
            int(elem.find("atom:mediaCount", ENTRIES_NSMAP).text),
            elem.find("atom:author", ENTRIES_NSMAP).find("atom:name", ENTRIES_NSMAP).text,
            elem.find("atom:publisher", ENTRIES_NSMAP).find("atom:name", ENTRIES_NSMAP).text,
            meta_link
        )


@dataclass(eq=True, frozen=True)
class ArchiveReference:
    """Dataclass representing a reference to an archive (ie, the static details necessary to identify an archive
    on the website, not tied to a specific version).
    """
    name: str
    language: frozenset[str]
    flavour: str

    def to_file_name(self, updated: Optional[datetime] = None) -> str:
        if updated is None:
            return f"{self.name}.zim"
        else:
            return f"{self.name}_{updated.isoformat()}.zim"

    def to_config(self) -> str:
        lines = [
            "[[archive]]",
            f'name = "{self.name}"',
            f'language = "{','.join(self.language)}"'
        ]
        if self.flavour:
            lines.append(f'flavour = "{self.flavour}"')
        return "\n".join(lines)


@dataclass
class ArchiveDetails:
    """Dataclass containing details of a specific downloaded archive."""
    reference: ArchiveReference
    updated: datetime
    file_name: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ArchiveDetails":
        """Create an instance of this class from an `sqlite3.Row` object obtained from the database."""
        reference = ArchiveReference(
            row["name"],
            frozenset(row["language"].split(",")),
            row["flavour"]
        )
        return cls(
            reference=reference,
            updated=datetime.fromisoformat(row["updated"]),
            file_name=row["file_name"]
        )

@dataclass
class Mirror:
    location: str
    priority: int
    url: str

@dataclass
class ArchiveMeta:
    file_name: str
    size: int
    hashes: dict[str, str]
    mirrors: list[Mirror]

    @classmethod
    def from_xml(cls, elem: Element) -> "ArchiveMeta":
        file_elem = elem.find("metalink:file", META_NSMAP)
        file_name = file_elem.attrib["name"]
        size = int(file_elem.find("metalink:size", META_NSMAP).text)
        hashes = {}
        for h in file_elem.findall("metalink:hash", META_NSMAP):
            hashes[h.attrib["type"]] = h.text
        mirrors = []
        for u in file_elem.findall("metalink:url", META_NSMAP):
            mirrors.append(Mirror(
                u.attrib["location"],
                int(u.attrib["priority"]),
                u.text
            ))
        return ArchiveMeta(file_name, size, hashes, mirrors)
