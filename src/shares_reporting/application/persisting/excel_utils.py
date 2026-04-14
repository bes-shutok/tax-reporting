"""Shared Excel utilities: auto-width calculation and safe file removal."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from os import PathLike

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ...infrastructure.logging_config import create_module_logger

# Column width bounds for auto_column_width
MAX_CELL_WIDTH = 50  # Maximum character width to measure per cell (caps outliers)
MIN_DATA_WIDTH = 12  # Minimum width for formula-only or empty columns
HEADER_THRESHOLD = 10  # Max length for a cell to be considered a header/label vs actual data


def auto_column_width(worksheet: Worksheet) -> None:
    """Set column widths to fit the widest non-formula cell value plus padding.

    Iterates every column in the worksheet. For each column, measures the
    character length of all non-formula, non-None cell values and sets the
    column width to the maximum found plus a 2-character padding. Columns
    that contain only formulas or are entirely empty receive MIN_DATA_WIDTH.
    Individual cell contributions are capped at MAX_CELL_WIDTH to prevent
    outliers (e.g., long explanatory notes) from blowing out column widths.

    Formula-heavy columns (where formulas outnumber non-formula cells)
    receive MIN_DATA_WIDTH to ensure rendered values have adequate space.

    Args:
        worksheet: The openpyxl worksheet to resize.
    """
    logger = create_module_logger(__name__)
    logger.debug("Auto-adjusting column widths")
    for column_cells in worksheet.columns:
        # Measure each non-formula cell, capped at MAX_CELL_WIDTH
        lengths = [
            min(len(str(cell.value)), MAX_CELL_WIDTH)
            for cell in column_cells
            if cell.value is not None and cell.data_type != "f"
        ]
        # Count formula cells to detect formula-heavy columns
        formula_count = sum(
            1 for cell in column_cells if cell.value is not None and cell.data_type == "f"
        )

        # Determine if this is a formula-heavy column.
        # A column is formula-heavy if formulas are present AND the column appears to
        # contain only headers/labels (all measured cells shorter than HEADER_THRESHOLD)
        # rather than actual data content. This catches typical headers like "Amount" (6)
        # while allowing data like "ABCDEFGHIJK" (11+) to be measured normally.
        is_formula_heavy = (
            formula_count > 0
            and lengths
            and all(cell_length < HEADER_THRESHOLD for cell_length in lengths)
        )

        # Calculate width with MIN_DATA_WIDTH floor for formula-heavy or empty columns
        # Formula-heavy columns use measured width (including headers) with MIN_DATA_WIDTH as floor
        if not lengths:
            width = MIN_DATA_WIDTH
        elif is_formula_heavy:
            width = max((*lengths, MIN_DATA_WIDTH))
        else:
            width = max((*lengths, 2)) + 2

        first_cell = column_cells[0]
        column_idx = None
        try:
            column_idx = first_cell.column
            if column_idx is not None:
                column_letter = get_column_letter(column_idx)
                worksheet.column_dimensions[column_letter].width = width
        except (AttributeError, TypeError) as e:
            logger.warning("Failed to set column width for column %s: %s", column_idx, e)


def safe_remove_file(path: str | PathLike[str]) -> None:
    """Safely remove a file if it exists, logging any errors.

    Args:
        path: File path to remove.
    """
    logger = create_module_logger(__name__)
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
            logger.debug("Removed existing file: %s", p.name)
    except OSError as e:
        logger.warning("Failed to remove file %s: %s", path, e)
