"""Légifrance XML parser."""
import xml.etree.ElementTree as ET
from typing import Dict, Optional
from datetime import datetime


class XMLParseError(Exception):
    pass


def parse_legifrance_xml(xml_content: bytes) -> Dict:
    """Parse Légifrance XML and extract metadata + content.
    
    Returns:
        {
            "xml_id": "JURITEXT000048201",
            "nature": "Arrêt",
            "juridiction": "Cour d'appel de Paris",
            "date_decision": 1736812800,  # timestamp or None
            "numero": "24/01234",
            "content": "Texte complet...",
            "metadata": {...}
        }
    """
    try:
        root = ET.fromstring(xml_content.decode('utf-8'))
    except ET.ParseError as e:
        raise XMLParseError(f"Parse error: {e}")
    except UnicodeDecodeError as e:
        raise XMLParseError(f"Decode error: {e}")
    
    metadata = extract_metadata(root)
    content = extract_content_blocks(root)
    
    return {
        "xml_id": metadata.get("id", ""),
        "nature": metadata.get("nature", ""),
        "juridiction": metadata.get("juridiction"),
        "date_decision": metadata.get("date_decision"),
        "numero": metadata.get("numero"),
        "content": content,
        "metadata": metadata
    }


def extract_metadata(root: ET.Element) -> Dict:
    """Extract metadata from <META> section."""
    metadata = {}
    
    # Common
    meta_commun = root.find(".//META_COMMUN")
    if meta_commun is not None:
        metadata["id"] = _get_text(meta_commun, "ID")
        metadata["nature"] = _get_text(meta_commun, "NATURE")
        metadata["origine"] = _get_text(meta_commun, "ORIGINE")
    
    # Jurisprudence
    meta_juri = root.find(".//META_JURI")
    if meta_juri is not None:
        metadata["juridiction"] = _get_text(meta_juri, "JURIDICTION")
        metadata["numero"] = _get_text(meta_juri, "NUMERO")
        date_str = _get_text(meta_juri, "DATE_DECISION")
        if date_str:
            metadata["date_decision"] = _parse_date(date_str)
    
    # Code
    meta_article = root.find(".//META_ARTICLE")
    if meta_article is not None:
        metadata["num_article"] = _get_text(meta_article, "NUM")
        date_debut = _get_text(meta_article, "DATE_DEBUT")
        date_fin = _get_text(meta_article, "DATE_FIN")
        if date_debut:
            metadata["date_debut"] = _parse_date(date_debut)
        if date_fin:
            metadata["date_fin"] = _parse_date(date_fin)
    
    return metadata


def extract_content_blocks(root: ET.Element) -> str:
    """Extract and concatenate all <CONTENU> blocks."""
    content_blocks = root.findall(".//CONTENU")
    texts = [block.text.strip() for block in content_blocks if block.text and block.text.strip()]
    return "\n\n".join(texts)


def _get_text(element: ET.Element, tag: str) -> Optional[str]:
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _parse_date(date_str: str) -> Optional[int]:
    """Parse date to Unix timestamp."""
    if not date_str:
        return None
    
    for fmt in ["%Y-%m-%d", "%Y%m%d"]:
        try:
            dt = datetime.strptime(date_str, fmt)
            return int(dt.timestamp())
        except ValueError:
            continue
    
    return None
