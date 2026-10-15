from erp_api.services.finance_export import csv_row, safe_csv_cell


def test_csv_cells_neutralize_spreadsheet_formulas() -> None:
    assert safe_csv_cell("=HYPERLINK('bad')") == "'=HYPERLINK('bad')"
    assert safe_csv_cell("+123") == "'+123"
    assert safe_csv_cell("  =1+1") == "'  =1+1"
    assert safe_csv_cell("normal") == "normal"


def test_csv_row_uses_standard_csv_escaping_and_crlf() -> None:
    assert csv_row(["order,1", 'quoted"value', 100]) == (
        '"order,1","quoted""value",100\r\n'
    )
