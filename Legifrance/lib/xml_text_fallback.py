"""Text extraction helpers with fallback.

Goal:
- Primary extraction: <CONTENU>
- Fallback: itertext() (all text nodes)

This is intended to fix data loss for XMLs where text is not in <CONTENU>.
"""
import xml.etree.ElementTree as ET


def extract_text_contenu(root: ET.Element) -> str:
    blocks = root.findall(".//CONTENU")
    texts = [b.text.strip() for b in blocks if b.text and b.text.strip()]
    return "\n\n".join(texts)


def extract_text_itertext(root: ET.Element) -> str:
    parts = [t.strip() for t in root.itertext() if t and t.strip()]
    return " ".join(parts)


def extract_text_with_fallback(xml_bytes: bytes) -> str:
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    text = extract_text_contenu(root)
    if text.strip():
        return text
    return extract_text_itertext(root)


__all__ = ["extract_text_with_fallback", "extract_text_contenu", "extract_text_itertext"]
