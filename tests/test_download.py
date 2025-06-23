import os
import xml.etree.ElementTree as ET
from shutil import rmtree

import requests

from kzam import Config
from kzam.download import Downloader
from kzam.xml_utils import ENTRIES_NSMAP

TEST_DATA_DIR = "test_data"
TEST_CONFIG = os.path.join(TEST_DATA_DIR, "config.toml")

TEST_OUTPUT_DIR = "test_output"
if os.path.exists(TEST_OUTPUT_DIR):
    rmtree(TEST_OUTPUT_DIR)
os.makedirs(TEST_OUTPUT_DIR)

def test_01_search():
    config = Config.from_toml_file(TEST_CONFIG)
    downloader = Downloader(config)
    actual = downloader.search(["eng", "fra"], None, "prep")
    expected = ET.fromstring(
        requests.get("https://browse.library.kiwix.org/catalog/v2/entries?lang=eng,fra&q=prep&count=-1").text
    ).findall("atom:entry", ENTRIES_NSMAP)
    assert expected
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert a.name == e.find("atom:name", ENTRIES_NSMAP).text
        assert a.id == e.find("atom:id", ENTRIES_NSMAP).text
        assert a.meta_link

def test_02_download():
    config = Config.from_toml_file(TEST_CONFIG)
    config.archive_dir = TEST_OUTPUT_DIR
    downloader = Downloader(config)
    archives = downloader.search(["eng", "fra"], query="arch")
    #print(archives)
    for a in archives:
        dst_path = downloader.download_archive(a, True)
        assert dst_path.endswith(f".zim")
        assert os.path.isfile(dst_path)