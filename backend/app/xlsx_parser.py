"""
Lightweight XLSX parser for fund disclosure holdings.
Uses only stdlib (zipfile, xml).
"""

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def _parse_xlsx_sheet(xlsx_path: str | Path, sheet_idx: int = 0) -> list:
    """
    Minimal XLSX parser — extracts one sheet as list of rows (lists).
    Handles shared strings but assumes simple flat structure.
    """
    with zipfile.ZipFile(xlsx_path) as z:
        # Load shared strings
        shared_strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss_xml = z.read("xl/sharedStrings.xml").decode("utf-8")
            root = ET.fromstring(ss_xml)
            for si in root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                t_elem = si.find(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                shared_strings.append(t_elem.text if t_elem is not None else "")

        # Load worksheet
        sheet_file = f"xl/worksheets/sheet{sheet_idx + 1}.xml"
        ws_xml = z.read(sheet_file).decode("utf-8")
        root = ET.fromstring(ws_xml)

        # Extract rows
        rows = []
        for row_elem in root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
            row_data = []
            for cell_elem in row_elem.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                v_elem = cell_elem.find(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                cell_type = cell_elem.get("t")

                if cell_type == "s" and v_elem is not None:
                    idx = int(v_elem.text)
                    value = shared_strings[idx] if idx < len(shared_strings) else ""
                elif v_elem is not None:
                    value = v_elem.text
                else:
                    value = ""
                row_data.append(value)
            rows.append(row_data)
        return rows


def parse_hdfc_flexi_cap(xlsx_path: str | Path) -> list[dict]:
    """
    Parse HDFC Flexi Cap Fund disclosure.
    Header row: [blank, "ISIN", "Coupon (%)", "Name Of the Instrument", "Industry+ /Rating", "Quantity", ...]
    Returns list of holding dicts with keys: isin, name, industry, quantity, market_value, percentage_nav
    """
    rows = _parse_xlsx_sheet(xlsx_path, 0)

    # Find header row (contains "ISIN")
    header_idx = -1
    for i, row in enumerate(rows):
        if len(row) > 1 and row[1] == "ISIN":
            header_idx = i
            break

    if header_idx < 0:
        return []

    headers = rows[header_idx]
    holdings = []

    # Parse rows after header until we hit a totals/summary row
    for row_data in rows[header_idx + 1 :]:
        if not row_data or len(row_data) < 2:
            continue

        # Skip if row contains markers like "GRAND TOTAL" or non-traded sections
        row_str = " ".join(str(v) for v in row_data if v).lower()
        if any(x in row_str for x in ["grand total", "non-traded", "thinly traded", "total value"]):
            continue

        # Column mapping for HDFC Flexi Cap:
        # [0]=blank, [1]=ISIN, [2]=Coupon, [3]=Name, [4]=Industry, [5]=Quantity, [6]=MktValue(Lacs), [7]=%NAV, ...
        isin = (str(row_data[1]) if len(row_data) > 1 and row_data[1] else "").strip()
        name = (str(row_data[3]) if len(row_data) > 3 and row_data[3] else "").strip()
        industry = (str(row_data[4]) if len(row_data) > 4 and row_data[4] else "").strip()
        qty_str = (str(row_data[5]) if len(row_data) > 5 and row_data[5] else "").strip()
        mv_str = (str(row_data[6]) if len(row_data) > 6 and row_data[6] else "").strip()
        pct_nav_str = (str(row_data[7]) if len(row_data) > 7 and row_data[7] else "").strip()

        # Validate: ISIN should look like INExxx, name should be non-empty
        if not isin or not isin.startswith("INE") or not name:
            continue

        # Parse numeric fields
        try:
            quantity = float(qty_str) if qty_str else 0
        except (ValueError, TypeError):
            quantity = 0

        try:
            market_value = float(mv_str) if mv_str else 0
        except (ValueError, TypeError):
            market_value = 0

        try:
            percentage_nav = float(pct_nav_str) if pct_nav_str else 0
        except (ValueError, TypeError):
            percentage_nav = 0

        if quantity > 0 or market_value > 0:
            holdings.append({
                "isin": isin,
                "name": name,
                "industry": industry,
                "quantity": quantity,
                "market_value": market_value,  # in Lacs, not Crores
                "percentage_nav": percentage_nav,
            })

    return holdings


def parse_icici_largecap(xlsx_path: str | Path) -> list[dict]:
    """
    Parse ICICI Prudential Large Cap Fund disclosure.
    Header row: ["Company/Issuer/Instrument Name", "ISIN", "Coupon", "Industry/Rating", "Quantity", ...]
    Note: different column order than HDFC.
    """
    rows = _parse_xlsx_sheet(xlsx_path, 0)

    # Find header row (contains "ISIN")
    header_idx = -1
    for i, row in enumerate(rows):
        if len(row) > 1 and row[1] == "ISIN":
            header_idx = i
            break

    if header_idx < 0:
        return []

    headers = rows[header_idx]
    holdings = []

    # Parse rows after header
    for row_data in rows[header_idx + 1 :]:
        if not row_data or len(row_data) < 2:
            continue

        row_str = " ".join(str(v) for v in row_data if v).lower()
        if any(x in row_str for x in ["grand total", "non-traded", "thinly traded", "total value"]):
            continue

        # Column mapping for ICICI Large Cap:
        # [0]=Company Name, [1]=ISIN, [2]=Coupon, [3]=Industry/Rating, [4]=Quantity, [5]=MktValue(Lakh), [6]=%NAV, ...
        name = (str(row_data[0]) if len(row_data) > 0 and row_data[0] else "").strip()
        isin = (str(row_data[1]) if len(row_data) > 1 and row_data[1] else "").strip()
        industry = (str(row_data[3]) if len(row_data) > 3 and row_data[3] else "").strip()
        qty_str = (str(row_data[4]) if len(row_data) > 4 and row_data[4] else "").strip()
        mv_str = (str(row_data[5]) if len(row_data) > 5 and row_data[5] else "").strip()
        pct_nav_str = (str(row_data[6]) if len(row_data) > 6 and row_data[6] else "").strip()

        if not isin or not isin.startswith("INE") or not name:
            continue

        try:
            quantity = float(qty_str) if qty_str else 0
        except (ValueError, TypeError):
            quantity = 0

        try:
            market_value = float(mv_str) if mv_str else 0
        except (ValueError, TypeError):
            market_value = 0

        try:
            percentage_nav = float(pct_nav_str) if pct_nav_str else 0
        except (ValueError, TypeError):
            percentage_nav = 0

        if quantity > 0 or market_value > 0:
            holdings.append({
                "isin": isin,
                "name": name,
                "industry": industry,
                "quantity": quantity,
                "market_value": market_value,  # in Lacs
                "percentage_nav": percentage_nav,
            })

    return holdings
