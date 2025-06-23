import logging
import os.path
import shutil
import subprocess
import sys
from argparse import ArgumentParser
from datetime import date
from enum import IntEnum
from typing import Optional, Collection

import platformdirs

from kzam.config import Config
from kzam.datamodel import ArchiveDetails, ArchiveReference, ArchiveEntry
from kzam.db import DbManager
from kzam.download import Downloader
from kzam.log import get_logger


def parse_date(s: str) -> date:
    """Convert a date in the format "YYYY-MM" to a `date` object (using 1 for the `day` value)."""
    y, m = s.split("-")
    return date(
        year=int(y),
        month=int(m),
        day=1
    )

class FileSizeSuffix(IntEnum):
    B = 1
    KB = 1024
    MB = 1_048_576
    GB = 1_073_741_824
    TB = 1_099_511_627_776

def str_to_bytes(s: str) -> int:
    """Convert a human-readable description of a file size like "2.34 GB" to bytes."""
    n, suf = s.split()
    n = float(n)
    mul = int(FileSizeSuffix[suf])
    return int(n * mul)

def bytes_to_str(b: int) -> str:
    """Convert a number of bytes to a human-readable description like "2.34 GB"."""
    if b < 0:
        raise ValueError(f"Negative value for number of bytes: {b}.")
    for suf in reversed(FileSizeSuffix):
        if b >= suf:
            div = round(b / suf, 2)
            return f"{div} {suf.name}"
    return f"{b} B"


class ArchiveManager:

    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        # Lazy initiate these as they may not be needed depending on the subcommands run
        self._db_manager: Optional[DbManager] = None
        self._dl_manager: Optional[Downloader] = None
        if os.path.isfile(config.base_dir):
            raise FileExistsError(f"Already a non-directory file at {config.base_dir}.")
        if os.path.isfile(config.archive_dir):
            raise FileExistsError(f"Already a non-directory file at {config.archive_dir}.")
        if not os.path.exists(config.archive_dir):
            os.makedirs(config.archive_dir)

    @property
    def dl_manager(self) -> Downloader:
        if self._dl_manager is None:
            self._dl_manager = Downloader(self.config, self.logger)
        return self._dl_manager

    @property
    def db_manager(self) -> DbManager:
        if self._db_manager is None:
            self._db_manager = DbManager(self.config.db_path)
        return self._db_manager

    def add_to_library(self, archive: ArchiveDetails):
        archive_path = os.path.join(self.config.archive_dir, archive.file_name)
        subprocess.run([self.config.kiwix_manage_exec, self.config.library_path, "add", archive_path])

    def get_zim_id(self, archive: ArchiveDetails) -> Optional[str]:
        output = subprocess.run(
            [self.config.kiwix_manage_exec, self.config.library_path, "show"],
            capture_output=True
        ).stdout.decode()
        relevant_path = os.path.join(self.config.archive_dir, archive.file_name)
        lines = output.splitlines()
        latest_id: Optional[str] = None
        for line in lines:
            line = line.strip()
            if line.startswith("id:"):
                latest_id = line.split()[1]
            elif line.startswith("path:"):
                if line.split()[1] == relevant_path:
                    return latest_id
        return None

    def remove_from_library(self, archive: ArchiveDetails):
        zim_id = self.get_zim_id(archive)
        if zim_id is not None:
            subprocess.run([self.config.kiwix_manage_exec, self.config.library_path, "remove", zim_id])

    def get_new(self) -> tuple[list[ArchiveEntry], list[ArchiveDetails]]:
        # Map archive references to archive details
        archive_refs: dict[ArchiveReference, Optional[ArchiveDetails]] = {r: None for r in self.config.archives}
        # Get archives that we have already downloaded
        current_archives = self.db_manager.all_archives()
        to_delete: list[ArchiveDetails] = []
        for a in current_archives:
            # For each downloaded archive, if specified in the config, associate its reference with its details,
            # otherwise, flag it for deletion (as presumably it was previously specified in the config but is no longer)
            r = a.reference
            if r in archive_refs:
                archive_refs[r] = a
            else:
                to_delete.append(a)

        # Get the set of all languages mentioned in any archive reference in the config, so we can restrict our search
        # to those languages
        lang: set[str] = set()
        for r in archive_refs:
            lang |= r.language
        from_server = self.dl_manager.search(lang)
        new: list[ArchiveEntry] = []
        for e in from_server:
            ref = e.to_reference()
            if ref in archive_refs:
                if (archive_refs[ref] is None) or (archive_refs[ref].updated < e.updated):
                    new.append(e)
        return new, to_delete

    def get_archive_configs(
            self,
            lang: Optional[Collection[str]] = None,
            category: Optional[str] = None,
            query: Optional[str] = None
    ) -> str:
        return "\n\n".join((e.to_reference().to_config() for e in self.dl_manager.search(lang, category, query)))

    def update(self, prompt: bool = False, quiet: bool = False):
        to_download, to_delete = self.get_new()
        self.logger.info(f"Found {len(to_download)} updated archives to download.")
        if to_download:
            if prompt:
                n_downloads = len(to_download)
                print(f"Will download {n_downloads} archive(s). Proceed? [y/N] ", file=sys.stderr, end="")
                proceed = input()
                if proceed.lower() != "y":
                    self.logger.info("Aborting.")
                    return
            downloaded = self.dl_manager.download_all(to_download, quiet=quiet)
            for d in downloaded:
                self.db_manager.insert_archive(d)
                self.add_to_library(d)
        else:
            self.logger.info("Nothing to download.")
        if to_delete:
            self.logger.info(f"{len(to_delete)} archives will be deleted as they no longer appear in the configuration file.")
            for d in to_delete:
                fpath = os.path.join(self.config.archive_dir, d.file_name)
                if os.path.exists(fpath):
                    self.logger.info(f"Deleting file at {fpath}.")
                    os.remove(fpath)
                self.db_manager.delete_archive(d)
                self.remove_from_library(d)

    def add_file(
            self,
            filepath: str,
            ref: ArchiveReference,
            date_created: Optional[date] = None,
            copy: bool = True
    ) -> ArchiveDetails:
        if date_created is None:
            # Try parse from filepath
            date_str = filepath.removesuffix(".zim").split("_")[-1]
            date_created = parse_date(date_str)
        if self.db_manager.archive_exists(ref, date_created):
            raise ValueError(f"Archive already exists in database: f{ref}")
        archive_filename = ref.to_file_name(date_created)
        archive_filepath = os.path.join(self.config.archive_dir, archive_filename)
        if os.path.exists(archive_filepath):
            raise FileExistsError(f"File already exists: {archive_filepath}")
        archive = ArchiveDetails(
            ref,
            date_created,
            archive_filename,
        )
        if copy:
            shutil.copyfile(filepath, archive_filepath)
        else:
            os.rename(filepath, archive_filepath)
        self.db_manager.insert_archive(archive)
        if ref not in self.config.archives:
            with open(self.config.config_file_path, "a") as f:
                f.write("\n")
                f.write(ref.to_config())
                f.write("\n")
            self.config.archives.append(ref)
        self.logger.info(f"Added {filepath} to archive as {archive_filename}.")
        return archive


def main():
    arg_parser = ArgumentParser(description="Fetch new ZIM archives from library.kiwix.org.")
    arg_parser.add_argument("-c", "--config", metavar="PATH", help="Path to config file to use.")
    arg_parser.add_argument("-d", "--debug", action="store_true", help="Debug mode (verbose logging).")
    arg_parser.add_argument("-q", "--quiet", action="store_true", help="Disable console output.")
    subparsers = arg_parser.add_subparsers(required=True)
    update_parser = subparsers.add_parser("update", help="Update archives.")
    update_parser.add_argument("-p", "--prompt", action="store_true",
                               help="Prompt for confirmation (once) before downloading.")
    update_parser.set_defaults(func=lambda mgr, ns: mgr.update(ns.prompt, quiet=ns.quiet))
    find_archives_parser = subparsers.add_parser("find-archives",
                                                 help="Get a list of all available archives, in an appropriate format "
                                                      "for inclusion in a config file.")
    find_archives_parser.add_argument("--lang", help="Language to filter by.", default="eng")
    find_archives_parser.set_defaults(func=lambda mgr, ns: print(mgr.get_archive_configs(ns.lang.split(","))))
    add_parser = subparsers.add_parser("add", help="Add a file to the library.")
    add_parser.add_argument("file", help="Path to file to add.")
    add_parser.add_argument("project", help="Project name of archive.")
    add_parser.add_argument("language", help="Language of archive.")
    add_parser.add_argument("flavor", help="Flavour of archive.")
    add_parser.add_argument("date", help="Date archive was created, in YYYY-MM format.", nargs="?")
    add_parser.add_argument("--copy", action="store_true",
                            help="Copy file to archives directory, rather than moving it.")
    add_parser.set_defaults(func=lambda mgr, ns: mgr.add_file(
        ns.file,
        ArchiveReference(ns.project, ns.language, ns.flavour),
        parse_date(ns.date) if ns.date is not None else None,
        ns.copy
    ))

    args = arg_parser.parse_args()

    logger = get_logger(__name__, args.quiet)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    default_conf_file = os.path.join(platformdirs.user_config_dir(appname="uzak"), "config.toml")
    conf_file = args.config or default_conf_file
    if not os.path.isfile(conf_file):
        raise FileNotFoundError(f"Could not find configuration file at {conf_file}")
    config = Config.from_toml_file(conf_file)
    manager = ArchiveManager(config, logger)
    args.func(manager, args)


if __name__ == "__main__":
    main()
