"""CSV export neutralises spreadsheet formulas in log text, never in numbers."""

from app.engine.export import to_csv


def test_formulas_neutralised_numbers_untouched() -> None:
    csv = to_csv(
        ["message", "n"],
        [
            ['=HYPERLINK("http://198.51.100.9","click")', -5],
            ["@SUM(A1)", 3],
            ["+cmd", 0],
            ["-2+3", 1],
            ["\tTAB", 2],
            ["plain, with comma", 1],
            [None, None],
            [{"k": "=x"}, 4],
        ],
    )
    assert csv.split("\r\n") == [
        "message,n",
        '"\'=HYPERLINK(""http://198.51.100.9"",""click"")",-5',
        "'@SUM(A1),3",
        "'+cmd,0",
        "'-2+3,1",
        "'\tTAB,2",
        '"plain, with comma",1',
        ",",
        '"{""k"": ""=x""}",4',
        "",
    ]
