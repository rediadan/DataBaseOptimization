import sys
import zipfile
import xml.etree.ElementTree as ET


NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def shared_strings(zf):
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values = []
    for item in root.findall("a:si", NS):
        values.append("".join(text.text or "" for text in item.findall(".//a:t", NS)))
    return values


def cell_value(cell, strings):
    kind = cell.attrib.get("t")
    value = cell.find("a:v", NS)
    if kind == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//a:t", NS))
    if value is None:
        return ""
    raw = value.text or ""
    if kind == "s" and raw:
        return strings[int(raw)]
    return raw


def main():
    path = sys.argv[1]
    with zipfile.ZipFile(path) as zf:
        strings = shared_strings(zf)
        root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        for row in root.findall(".//a:row", NS):
            values = []
            for cell in row.findall("a:c", NS):
                value = cell_value(cell, strings)
                if value != "":
                    values.append(f"{cell.attrib.get('r')}={value}")
            if values:
                print(" | ".join(values))


if __name__ == "__main__":
    main()
