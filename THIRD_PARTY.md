# Third-party components

The project's original application code is covered by the root [MIT license](LICENSE). Third-party libraries, fonts, provider services and source content retain their own terms. The project license does not relicense them, and no endorsement by their authors is implied.

## Bundled DejaVu Sans fonts

The repository includes three unchanged TrueType files from the official **DejaVu fonts 2.37** binary release: `DejaVuSans.ttf`, `DejaVuSans-Bold.ttf` and `DejaVuSans-Oblique.ttf`.

- Project: [DejaVu Fonts](https://dejavu-fonts.github.io/).
- Release: [version 2.37](https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37), 30 July 2016.
- Copyright: Bitstream, Inc. (2003) and Tavmjong Bah (2006); the upstream notice states that DejaVu changes are in the public domain.
- Full upstream notices: [fonts/LICENSE.txt](fonts/LICENSE.txt). This includes the Bitstream Vera and Arev terms. They are separate from the application's MIT license.
- Exact source archive and file checksums: [fonts/PROVENANCE.json](fonts/PROVENANCE.json).

The font licenses permit copying and redistribution with their copyright, trademark and permission notices. They restrict the names used for modified fonts and prohibit selling the typefaces on their own. This project does not modify the glyphs or rename the fonts. Keep the complete upstream license alongside redistributed font files.

The three files were copied byte for byte from the official release archive, whose SHA-256 matches the checksum published by the DejaVu project. No local font build is required. A system-font substitution may change layout and Cyrillic coverage; the bundled, identified fonts make the PDF demo more reproducible.

## Python dependencies

The source repository does not vendor Python packages or a virtual environment. `requirements.txt` pins the five direct packages. [`requirements.lock`](requirements.lock) fixes all 18 resolved runtime packages and includes only official PyPI wheel hashes for those exact versions. Source distributions are excluded.

The selected CPython 3.12/macOS arm64 wheels were checked against official PyPI metadata by filename, version, length and SHA-256. Their ZIP paths and modes, every RECORD entry, and the absence of automatic import/install hooks were inspected without installing or importing the packages. [`third_party/DEPENDENCIES.json`](third_party/DEPENDENCIES.json) records the selected files and the limits of that review. Wheels for other platforms are hash-pinned from PyPI metadata but were not inspected or tested in this environment.

| Direct dependency | Pinned version | Retained upstream license |
| --- | --- | --- |
| ReportLab | 5.1.0 | [BSD-style license for the library code](third_party/licenses/reportlab-5.1.0-LICENSE.txt) |
| Requests | 2.34.2 | [Apache-2.0](third_party/licenses/requests-2.34.2-LICENSE.txt), with its [NOTICE](third_party/licenses/requests-2.34.2-NOTICE.txt) |
| python-dotenv | 1.2.4 | [BSD-3-Clause](third_party/licenses/python-dotenv-1.2.4-LICENSE.txt) |
| duckduckgo-search | 8.1.1 | [MIT](third_party/licenses/duckduckgo-search-8.1.1-LICENSE.txt) |
| Flask | 3.1.3 | [BSD-3-Clause](third_party/licenses/flask-3.1.3-LICENSE.txt) |

These notice texts were taken from the exact selected, verified wheels. The original `duckduckgo_search` import and package name remain pinned. Its publisher reports a rename to `ddgs`; migration to that different distribution is not implied by this archive.

Transitive dependencies retain their own terms. In particular, certifi identifies MPL-2.0, Pillow identifies MIT-CMU, and native components are present in charset-normalizer, lxml, MarkupSafe, Pillow and primp. The selected primp wheel identifies MIT in its metadata but contains no separate license file, so the [license from the exact upstream v2.0.1 tag](third_party/licenses/primp-2.0.1-LICENSE.txt) is retained here.

ReportLab's wheel also includes optional font files with separate Bitstream and DarkGarden notices, including a GPL notice. Those are not the three DejaVu files vendored by this project and are not reclassified under the library's BSD license. A redistribution of a packaged Python environment must retain the terms of the actual included package assets and native dependencies. This review does not claim exhaustive closure of every bundled native-library notice.

## External services and content

No language-model weights are bundled. Search, LLM-provider and Telegram integrations are adapters; their presence does not grant rights to third-party services or retrieved articles. Demonstration output should be identified as synthetic when it uses fictional inputs. Any real source material retains its authors' rights.
