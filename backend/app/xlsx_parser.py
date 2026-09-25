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


def parse_sbi_nifty50_etf(xlsx_path: str | Path) -> list[dict]:
    """
    Parse SBI Nifty 50 ETF disclosure.
    Uses a flexible approach to extract holding data from XLSX files.
    """
    rows = _parse_xlsx_sheet(xlsx_path, 0)
    holdings = []

    for row_idx, row_data in enumerate(rows):
        # Skip empty rows
        if not row_data or len(row_data) == 0:
            continue

        # Convert row to string for easier searching
        row_str = " ".join(str(cell) for cell in row_data if cell is not None)
        row_str_lower = row_str.lower()

        # Skip summary/total rows
        if any(x in row_str_lower for x in ["grand total", "non-traded", "thinly traded", "total value", "net assets"]):
            continue

        # Look for ISIN-like patterns in the row
        isin_found = None
        isin_pos = -1
        
        for i, cell in enumerate(row_data):
            if cell is not None:
                cell_str = str(cell).strip()
                # Check if this cell contains an ISIN (starts with INE followed by alphanumeric)
                if len(cell_str) >= 9 and cell_str.startswith("INE") and cell_str[3:].isalnum():
                    isin_found = cell_str
                    isin_pos = i
                    break

        if not isin_found:
            continue

        # Try to extract name, industry, quantity, market value, %NAV from surrounding cells
        name = ""
        industry = ""
        quantity = 0.0
        market_value = 0.0
        percentage_nav = 0.0

        # Look for name (typically near ISIN, often before or after)
        # Check cells before ISIN
        for i in range(max(0, isin_pos - 3), isin_pos):
            if i < len(row_data) and row_data[i] is not None:
                cell_val = str(row_data[i]).strip()
                if cell_val and len(cell_val) > 2 and not cell_val.replace('.', '').replace('-', '').isdigit():
                    # Likely a name if it's not just numbers
                    name = cell_val
                    break

        # If not found before, check after ISIN
        if not name:
            for i in range(isin_pos + 1, min(len(row_data), isin_pos + 4)):
                if i < len(row_data) and row_data[i] is not None:
                    cell_val = str(row_data[i]).strip()
                    if cell_val and len(cell_val) > 2 and not cell_val.replace('.', '').replace('-', '').isdigit():
                        # Likely a name if it's not just numbers
                        name = cell_val
                        break

        # Look for industry (often near name or ISIN)
        # Check a few positions around ISIN for text that's not a number
        for offset in [-2, -1, 1, 2, 3]:
            check_pos = isin_pos + offset
            if 0 <= check_pos < len(row_data) and row_data[check_pos] is not None:
                cell_val = str(row_data[check_pos]).strip()
                if cell_val and len(cell_val) > 2 and not cell_val.replace('.', '').replace('-', '').isdigit() and cell_val != name:
                    industry = cell_val
                    break

        # Look for numeric values (quantity, market value, %NAV)
        numeric_cells = []
        for i, cell in enumerate(row_data):
            if cell is not None:
                cell_str = str(cell).strip()
                try:
                    val = float(cell_str)
                    numeric_cells.append((i, val))
                except (ValueError, TypeError):
                    pass

        # Assign numeric values based on typical order: quantity, market value, %NAV
        if len(numeric_cells) >= 3:
            # Sort by position to maintain order
            numeric_cells.sort(key=lambda x: x[0])
            quantity = numeric_cells[0][1]
            market_value = numeric_cells[1][1]
            percentage_nav = numeric_cells[2][1]
        elif len(numeric_cells) == 2:
            numeric_cells.sort(key=lambda x: x[0])
            quantity = numeric_cells[0][1]
            market_value = numeric_cells[1][1]
        elif len(numeric_cells) == 1:
            quantity = numeric_cells[0][1]

        # Validate: we need at least an ISIN and a name
        if isin_found and name:
            holdings.append({
                "isin": isin_found,
                "name": name,
                "industry": industry,
                "quantity": quantity,
                "market_value": market_value,  # in Lacs
                "percentage_nav": percentage_nav,
            })

    return holdings


def parse_nippon_largecap(xlsx_path: str | Path) -> list[dict]:
    """
    Parse Nippon India Large Cap Fund disclosure.
    Assumes structure similar to ICICI Large Cap.
    Header row: ["Company/Issuer/Instrument Name", "ISIN", "Coupon", "Industry/Rating", "Quantity", ...]
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

        # Column mapping for Nippon India Large Cap (assuming similar to ICICI):
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


def parse_kotak_largemidcap(xlsx_path: str | Path) -> list[dict]:
    """
    Parse Kotak Large & Mid Cap Fund disclosure.
    Uses a flexible approach to extract holding data from XLSX files.
    """
    rows = _parse_xlsx_sheet(xlsx_path, 0)
    holdings = []

    for row_idx, row_data in enumerate(rows):
        # Skip empty rows
        if not row_data or len(row_data) == 0:
            continue

        # Convert row to string for easier searching
        row_str = " ".join(str(cell) for cell in row_data if cell is not None)
        row_str_lower = row_str.lower()

        # Skip summary/total rows
        if any(x in row_str_lower for x in ["grand total", "non-traded", "thinly traded", "total value", "net assets"]):
            continue

        # Look for ISIN-like patterns in the row
        isin_found = None
        isin_pos = -1
        
        for i, cell in enumerate(row_data):
            if cell is not None:
                cell_str = str(cell).strip()
                # Check if this cell contains an ISIN (starts with INE followed by alphanumeric)
                if len(cell_str) >= 9 and cell_str.startswith("INE") and cell_str[3:].isalnum():
                    isin_found = cell_str
                    isin_pos = i
                    break

        if not isin_found:
            continue

        # Try to extract name, industry, quantity, market value, %NAV from surrounding cells
        name = ""
        industry = ""
        quantity = 0.0
        market_value = 0.0
        percentage_nav = 0.0

        # Look for name (typically near ISIN, often before or after)
        # Check cells before ISIN
        for i in range(max(0, isin_pos - 3), isin_pos):
            if i < len(row_data) and row_data[i] is not None:
                cell_val = str(row_data[i]).strip()
                if cell_val and len(cell_val) > 2 and not cell_val.replace('.', '').replace('-', '').isdigit():
                    # Likely a name if it's not just numbers
                    name = cell_val
                    break

        # If not found before, check after ISIN
        if not name:
            for i in range(isin_pos + 1, min(len(row_data), isin_pos + 4)):
                if i < len(row_data) and row_data[i] is not None:
                    cell_val = str(row_data[i]).strip()
                    if cell_val and len(cell_val) > 2 and not cell_val.replace('.', '').replace('-', '').isdigit():
                        # Likely a name if it's not just numbers
                        name = cell_val
                        break

        # Look for industry (often near name or ISIN)
        # Check a few positions around ISIN for text that's not a number
        for offset in [-2, -1, 1, 2, 3]:
            check_pos = isin_pos + offset
            if 0 <= check_pos < len(row_data) and row_data[check_pos] is not None:
                cell_val = str(row_data[check_pos]).strip()
                if cell_val and len(cell_val) > 2 and not cell_val.replace('.', '').replace('-', '').isdigit() and cell_val != name:
                    industry = cell_val
                    break

        # Look for numeric values (quantity, market value, %NAV)
        numeric_cells = []
        for i, cell in enumerate(row_data):
            if cell is not None:
                cell_str = str(cell).strip()
                try:
                    val = float(cell_str)
                    numeric_cells.append((i, val))
                except (ValueError, TypeError):
                    pass

        # Assign numeric values based on typical order: quantity, market value, %NAV
        if len(numeric_cells) >= 3:
            # Sort by position to maintain order
            numeric_cells.sort(key=lambda x: x[0])
            quantity = numeric_cells[0][1]
            market_value = numeric_cells[1][1]
            percentage_nav = numeric_cells[2][1]
        elif len(numeric_cells) == 2:
            numeric_cells.sort(key=lambda x: x[0])
            quantity = numeric_cells[0][1]
            market_value = numeric_cells[1][1]
        elif len(numeric_cells) == 1:
            quantity = numeric_cells[0][1]

        # Validate: we need at least an ISIN and a name
        if isin_found and name:
            holdings.append({
                "isin": isin_found,
                "name": name,
                "industry": industry,
                "quantity": quantity,
                "market_value": market_value,  # in Lacs, not Crores
                "percentage_nav": percentage_nav,
            })

    return holdings
