import xml.etree.ElementTree as ET


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def parse_rss_items(xml_text: str) -> list[dict[str, str]]:
    """Распарсить <item>-элементы RSS 2.0 в плоские dict {local_tag: text}.
    Namespace-префиксы (dc:creator) схлопываются до локального имени. Повторный
    тег с уже занятым непустым значением игнорируется (Djinni отдаёт
    <category>X</category><category/> — берём первое непустое)."""
    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for item_el in root.iter("item"):
        fields: dict[str, str] = {}
        for child in item_el:
            name = _local_name(child.tag)
            text = (child.text or "").strip()
            if text and name not in fields:
                fields[name] = text
        items.append(fields)
    return items
