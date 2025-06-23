import hashlib
import os
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256, sha1, md5
from logging import Logger
from threading import RLock
from typing import Optional, Collection

import psutil
import requests
from tqdm import tqdm

from kzam import Config, ArchiveDetails
from kzam.datamodel import ArchiveEntry, ArchiveMeta, Mirror
from kzam.xml_utils import ENTRIES_NSMAP

class DownloadError(Exception):
    pass

class VerificationFailed(DownloadError):
    pass

class MirrorDownloadFailed(DownloadError):
    """Could not download a file from a specific mirror."""
    pass

class Downloader:
    def __init__(self, config: Config, logger: Logger):
        self.base_url = config.rss_base_url
        self.archive_dir = config.archive_dir
        self.logger = logger

    def _build_url(
            self,
            lang: Optional[Collection[str]] = None,
            category: Optional[str] = None,
            query: Optional[str] = None
    ) -> str:
        params = {}
        if lang is not None:
            params["lang"] = ",".join(lang)
        if category is not None:
            params["category"] = category
        if query is not None:
            params["q"] = query
        return f"{self.base_url}?{urllib.parse.urlencode(params)}"

    def search(
            self,
            lang: Optional[Collection[str]] = None,
            category: Optional[str] = None,
            query: Optional[str] = None
    ) -> list[ArchiveEntry]:
        params = {"count": "-1"}
        if lang is not None:
            params["lang"] = ",".join(lang)
        if category is not None:
            params["category"] = category
        if query is not None:
            params["q"] = query
        result = requests.get(self.base_url, params)
        self.logger.info(f"Queried URL {result.url}, status: {result.status_code}.")
        result.raise_for_status()
        xml = ET.fromstring(result.text)
        entries = [ArchiveEntry.from_xml(e) for e in xml.findall("atom:entry", ENTRIES_NSMAP)]
        self.logger.info(f"Found {len(entries)} results.")
        return entries

    def verify(self, fpath: str, hashes: dict[str, str]):
        """Verify a file against one of the given hashes."""
        if "sha-256" in hashes:
            hash_fn = sha256
            expected = hashes["sha-256"]
        elif "sha-1" in hashes:
            hash_fn = sha1
            expected = hashes["sha-1"]
        elif "md5" in hashes:
            hash_fn = md5
            expected = hashes["md5"]
        else:
            raise ValueError("No supported hash found.")

        self.logger.info(f"Verifying file using {hash_fn.__name__} algorithm.")

        with open(fpath, "rb") as f:
            h = hashlib.file_digest(f, hash_fn).hexdigest()
        if h != expected:
            raise VerificationFailed(f"File at {fpath} failed verification using {hash_fn.__name__} algorithm. "
                                     f"Expected {expected} but got {h}")


    def try_mirror(
            self,
            dst_path: str,
            mirror: Mirror,
            meta: ArchiveMeta,
            check_length: bool = True,
            quiet: bool = False,
            pbar_position: Optional[int] = None
    ):

        if check_length:
            head_response = requests.head(mirror.url)
            head_response.raise_for_status()
            if not ("Content-Length" in head_response.headers):
                raise MirrorDownloadFailed("Could not get content length. Aborting download.")
            size = int(head_response.headers["Content-Length"])
            if psutil.disk_usage(self.archive_dir).free < size:
                raise DownloadError("File would not fit on disk. Aborting download.")
        else:
            size = meta.size

        part_path = dst_path + ".part"
        content_response = requests.get(mirror.url, stream=True)
        if not content_response.ok:
            raise MirrorDownloadFailed("Could not download content. Aborting.")

        with tqdm(
                total=size,
                unit='B',
                unit_scale=True,
                desc=meta.file_name,
                position=pbar_position,
                leave=(pbar_position is None),  # Only leave traces if we're not in multithreaded environment
                disable=quiet
        ):
            with open(part_path, 'wb') as f:
                for chunk in content_response.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)

        os.rename(part_path, dst_path)

        return dst_path

    def download_archive(
            self,
            entry: ArchiveEntry,
            verify: bool = True,
            check_length: bool = True,
            quiet: bool = False,
            pbar_position: Optional[int] = None
    ) -> ArchiveDetails:
        meta_xml = ET.fromstring(requests.get(entry.meta_link).text)
        meta = ArchiveMeta.from_xml(meta_xml)
        dst = os.path.join(self.archive_dir, meta.file_name)
        for mirror in sorted(meta.mirrors, key=lambda m: m.priority):
            try:
                dst_path = self.try_mirror(dst, mirror, meta, check_length, quiet, pbar_position)
                if verify:
                    self.verify(dst_path, meta.hashes)
                return ArchiveDetails(entry.to_reference(), entry.updated, meta.file_name)
            except MirrorDownloadFailed:
                continue
        raise DownloadError("Could not download content from any mirror.")

    def download_all(
            self,
            entries: list[ArchiveEntry],
            verify: bool = True,
            check_length: bool = True,
            quiet: bool = False
    ) -> list[ArchiveDetails]:
        if len(entries) == 1:
            # If there is only one archive to download, do it the non-multithreaded way, as the output from tqdm
            # isn't great in a multithreaded context
            return [self.download_archive(entries[0], verify)]
        tqdm.set_lock(RLock())
        # below is attempt to address https://github.com/tqdm/tqdm/issues/670 but doesn't seem to work...
        posn_range = range(1, len(entries) + 1)
        with ThreadPoolExecutor(initializer=tqdm.set_lock, initargs=(tqdm.get_lock(),)) as p:
            return list(p.map(
                lambda e, posn: self.download_archive(e, verify, check_length, quiet, posn),
                entries, posn_range
            ))