# `kzam`

`kzam` (**K**iwix **Z**im **A**rchive **M**anager) is an unofficial Python script to manage and update
[ZIM archives](https://wiki.openzim.org/wiki/OpenZIM) from the
[Kiwix library](https://wiki.kiwix.org/wiki/Content_in_all_languages). It is not affiliated with the Kiwix project or
organisation.

Kiwix makes available a large number of ZIM files representing snapshots of popular websites, in different languages. These
files can be downloaded and viewed through software developed by Kiwix, including
[`kiwix-serve`](https://wiki.kiwix.org/wiki/Kiwix-serve), which serves the files over HTTP.

The snapshots provided by Kiwix are updated from time to time (some more frequently than others). With `kzam`, you can
create a configuration file specifying all the archives you want to download. `kzam` will download them and add them
to a library file which can be served by `kiwix-serve`. Subsequent runs of `kzam` will check the Kiwix website for
updated versions of those archives and, if found, download them, add them to the archives and delete the old
versions.

## Installation

Clone this repository and install using `pip`.

```shell
git clone git@github.com:bunburya/kzam.git
pip install kzam
```

You may need to (and in any event, probably should) do this from within a
[virtual environment](https://docs.python.org/3/tutorial/venv.html). 

## Configuration

Configuration is primarily through a [TOML](https://toml.io/en/) file. You can specify a particular config file to use
with the `--config` command line option. Otherwise, `kzam` will look for a config file in the usual place depending on
your operating system (for example, on most Linux systems, it will look for `$HOME/.config/kzam/config.toml`).

A sample `config.toml`, with comments, is included in this repo, which should be fairly self-explanatory. Basically, you
have a few "top level" configuration options which specify the behaviour of `kzam` (where to store the files, etc),
followed by one or more `[[archive]]` sections which specify the archives to download.

Each `[[archive]]` section should specify three things, which should correspond to the relevant values in the
[entries RSS feed](https://browse.library.kiwix.org/catalog/v2/entries) on the Kiwix website. Each archive will have an
`entry` element containing the relevant information.

- `name`, which should correspond to the project's name in the "entries" RSS feed,
- `language`, which should correspond to the "language" element in the RSS feed, and
- `flavour` (note the UK spelling), which should correspond to the "flavour" element in the RSS feed.

You can include as many `[[archive]]` sections as you like.

## Usage

The main subcommand is `update`, which will check the website for the latest version of each relevant archive, download
each new archive, check its integrity using the sha256 hash provided by Kiwix, and finally add it to the library file.
If the `--prompt` argument is passed, then before downloading anything it will display the number of new archives to be
downloaded and the total download size and ask for confirmation before proceeding. If `delete_old` is set to `true` in 
the config file, then any old versions of the archive that were previously downloaded will be deleted.

Once downloaded, the ZIM files themselves will be stored in the `archives` subdirectory of the directory you specified
in the config file (`base_dir`). A Kiwix library file, `library.xml`, will be stored directly within `base_dir`. If you
run `kiwix-serve` with the `--library` argument and specify that library file, it will serve all of your downloaded
archives over HTTP (see the documentation for `kiwix-serve` for more information). Also within `base_dir` you will find
`archives.db`, an sqlite3 database file used to keep track of what archives have been downloaded. **NOTE**: You should
not edit any of the files within `base_dir` yourself as this may prevent `kzam` from keeping track of them.

Example:
```shell
kzam -c my_config.toml update --prompt
```

There is another subcommand, `search`, which will output an `[[archive]]` section (see "Configuration" above) for
each archive listed on the website. This can be used to browse the available archives from your terminal and the output
can be appended to a config file to fetch all of those archives. **NOTE**, however, that there are a lot of archives,
and some of them are quite big, so it is not advised to blindly append the output of `find-archives` to your config file
unless you know what you are doing. A check in July 2024 revealed that the Kiwix web page listed 3,273 archives,
totalling approximately 4.14 TB. You can restrict your search by providing optional `--lang`, `--category` and/or
`--query` arguments, that will filter search results by language, category or title/description, respectively.

Example:
```shell
kzam search --lang eng
```

Call `kzam -h` to find more information about available options.

## Dependencies

`kzam` is a Python script, targeting Python 3.11 or above. Python dependencies are listed in the Pipfile. You also need
to have `kiwix-manage` installed, as it invokes this tool to update your Kiwix library file.

More broadly, of course, it depends on the Kiwix RSS feed linked above remaining available, and in substantially the
same format. Any changes to that page may break `kzam` unexpectedly. Please file an issue with as much information as
possible if you encounter any issues.