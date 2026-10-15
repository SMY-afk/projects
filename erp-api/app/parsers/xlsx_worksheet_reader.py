from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable
from xml.etree import ElementTree

MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
_XML_NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_first_worksheet(content: bytes) -> Iterable[list[object | None]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as error:
        raise ValueError("Creator export is not valid XLSX") from error
    with archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Creator export expands beyond limit")
        worksheets = sorted(
            name
            for name in archive.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        if not worksheets:
            raise ValueError("Creator export has no worksheet")
        shared = _shared_strings(archive)
        root = ElementTree.fromstring(archive.read(worksheets[0]))
        for row in root.iter(f"{_XML_NAMESPACE}row"):
            values: list[object | None] = []
            for cell in row.findall(f"{_XML_NAMESPACE}c"):
                column = _column_index(cell.get("r", ""))
                while len(values) < column:
                    values.append(None)
                values[column - 1] = _cell_value(cell, shared)
            yield values


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{_XML_NAMESPACE}t"))
        for item in root.findall(f"{_XML_NAMESPACE}si")
    ]


def _cell_value(cell, shared: list[str]) -> object | None:
    if cell.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{_XML_NAMESPACE}t"))
    value = cell.findtext(f"{_XML_NAMESPACE}v")
    if value is None:
        return None
    if cell.get("t") == "s":
        try:
            return shared[int(value)]
        except (IndexError, ValueError) as error:
            raise ValueError("Invalid shared string index") from error
    return value


def _column_index(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference.upper())
    if match is None:
        raise ValueError("Invalid worksheet cell reference")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - 64
    if result > 256:
        raise ValueError("Creator export exceeds column limit")
    return result
