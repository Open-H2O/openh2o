# SPDX-License-Identifier: AGPL-3.0-or-later
"""
152-03.3: the guides say what the schedule import and the production log import do.

The expected prose is one named constant per row (84 to 100) of
``.planning/phases/152-proven-by-strangers/152-03.3-ROWS.md``, Fixed column, with
the Now column kept beside it so the old sentence is shown to be gone. Whitespace
and line wraps are normalised before comparing; the guides wrap near 88 columns.
No data is used.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA_IMPORT = ROOT / "docs" / "DATA-IMPORT.md"
OPERATOR = ROOT / "docs" / "AI-OPERATOR-GUIDE.md"

ROW_84 = "Drinking water: the sampling schedule"
ROW_85 = (
    "You can import the state's sampling schedule with the `import_schedule` command "
    "or the import screen at `/drinking/schedule/import/`. The Schedule page links to "
    "that screen with **Import the state's schedule**. The import reads the Last and "
    "Next Sample Report from California's Division of Drinking Water. Save the report "
    "as a CSV file."
)
ROW_86 = (
    "Each row names a sampling point by its PS Code. Add the sampling points before "
    "the import. OpenH2O looks for each row's analyte by its code and then by its "
    "name. When no analyte on the site has the row's code or name, OpenH2O shows the "
    "analyte's name under **What is sampled** on the Schedule page."
)
ROW_87 = (
    "`FREQ MONTHS` sets the frequency. OpenH2O saves 1, 3, 12, 36, 72, 108 and 120 "
    "months as Monthly, Quarterly, Annual, Every 3 years, Every 6 years, Every 9 "
    "years and Every 10 years. OpenH2O saves any other number as Other. A new "
    "schedule row then gives the months in its notes. The state gives the next due "
    "date as a month only. OpenH2O keeps it as a month."
)
ROW_88 = (
    "You can import a newer file over an older one. When a schedule row has the "
    "sampling point and analyte of a row in the file, OpenH2O changes only that "
    "schedule row's frequency, Last done and Next due. The preview lists each change "
    "before anything is saved. A new schedule row gets the file's GROUP and NOTES in "
    "its notes. A changed schedule row keeps its own notes. A schedule row the newer "
    "file leaves out stays on the schedule. With `--dry-run` the command lists the "
    "same changes and saves nothing."
)
ROW_89 = (
    "The sampling schedule, when you do not have the state's file: "
    "`/drinking/schedule/add/`"
)
ROW_89_NOW = "The sampling schedule: `/drinking/schedule/add/`"
ROW_90 = (
    "OpenH2O tells the first two kinds of file below apart by their column headings. "
    "For any other headings, you choose on the preview what each column holds."
)
ROW_90_NOW = (
    "OpenH2O reads two layouts and tells them apart by their column headings:"
)
ROW_91 = "A monthly log with its own column headings"
ROW_92 = "Any other column headings"
ROW_93 = (
    "On the preview you choose the column that holds the month. For each other column "
    "you choose the type of water it holds. The month can be written `2024-01`, "
    "`1/2024` or `January 2024`. A column of month names with no year also works. In "
    "that case you enter the report year. You choose one unit for the whole file. "
    "This kind of log has no default unit. The import takes one column for each type "
    "of water. When the log has a column for each well, add the wells together into "
    "one column first."
)
ROW_94 = (
    "For a log with its own column headings, `--column` names what each column holds. "
    "`--operator-unit` sets the unit for the whole file."
)
ROW_95 = (
    "A production file gives figures for the whole system by type of water. The file "
    "does not name a meter. Before the import, add the meters for one type of water "
    "together into one figure a month."
)
ROW_95_NOW = (
    "The source column of the production file: one of the six source columns of a "
    "monthly log, or `TypeCode` in an export of California's Electronic Annual "
    "Report (eAR)."
)
ROW_96 = (
    "**Unit for rows with a blank unit**, on the preview of the production import "
    "screen. For a log with its own column headings, **Unit** on the same preview. "
    "That kind of log has no default unit."
)
ROW_97 = (
    "The Schedule page under Drinking water. Import the state's Last and Next Sample "
    "Report with **Import the state's schedule** or `import_schedule`. Add any other "
    "row with **+ Add to schedule**."
)
ROW_97_NOW = (
    "The Schedule page under Drinking water: add each row with **+ Add to schedule**."
)
ROW_98 = (
    "When a month and type of water are already on the site as a figure for the whole "
    "system, the import skips that figure. Importing the same file twice saves "
    "nothing the second time. A month entered by hand for one facility does not stop "
    "the import from saving the file's figure for that month and type of water."
)
ROW_98_NOW = (
    "A row whose month and type of water are already on the site is skipped and "
    "counted, so importing the same file twice saves nothing the second time."
)
ROW_99 = (
    "OpenH2O skips any row whose `Date/Month` is not a full month name. The "
    "template's `Maximum Day`, `Annual Total` and `Percent Treated` rows are three "
    "such rows. Once you enter the report year, the preview names each skipped row."
)
ROW_99_NOW = (
    "The rows `Maximum Day`, `Annual Total` and `Percent Treated` are skipped, and "
    "the preview names them."
)
ROW_100 = (
    "When the export repeats a month and type of water, OpenH2O keeps the first row "
    "and reports how many it skipped."
)
ROW_100_NOW = (
    "The export can repeat a row up to five times, and OpenH2O keeps one copy and "
    "reports how many it dropped."
)


def _flat(text):
    return " ".join(text.split())


def _read(path):
    return path.read_text(encoding="utf-8")


def _production_section():
    """The flattened text of the production section of the data import guide."""
    text = _flat(_read(DATA_IMPORT))
    start = text.find("Drinking water: production by month")
    assert start >= 0, "the production section is missing"
    end = text.find("## 4. Filling in from public sources", start)
    return text[start:end]


def _lines(path):
    """Each line of a guide, flattened, with a leading list dash removed."""
    out = []
    for line in _read(path).splitlines():
        line = _flat(line)
        out.append(line[2:] if line.startswith("- ") else line)
    return out


def _table_row_with(path, *cells):
    """The first table row that carries every cell, in order, as whole cells."""
    for line in _read(path).splitlines():
        if not line.lstrip().startswith("|"):
            continue
        parts = [_flat(part) for part in line.strip().strip("|").split(" | ")]
        parts = [part.strip() for part in parts]
        if all(cell in parts for cell in cells):
            positions = [parts.index(cell) for cell in cells]
            if positions == sorted(positions):
                return parts
    return None


# -- the new section on the sampling schedule (rows 84 to 88) -------------------


def test_row_84_the_schedule_section_has_its_heading():
    headings = [line for line in _lines(DATA_IMPORT) if line.startswith("#")]
    assert any(line.lstrip("# ").strip() == ROW_84 for line in headings)


@pytest.mark.parametrize(
    "sentence", [ROW_85, ROW_86, ROW_87, ROW_88], ids=["row85", "row86", "row87", "row88"]
)
def test_rows_85_to_88_are_in_the_data_import_guide(sentence):
    assert sentence in _flat(_read(DATA_IMPORT))


def test_the_schedule_section_follows_production_by_month():
    text = _flat(_read(DATA_IMPORT))
    production = text.find("Drinking water: production by month")
    schedule = text.find(ROW_84)
    assert production >= 0
    assert schedule > production, "the schedule section comes after production"


# -- row 89: the by-hand list ----------------------------------------------------


def test_row_89_the_by_hand_line_says_when_you_do_not_have_the_file():
    assert ROW_89 in _lines(DATA_IMPORT)


def test_row_89_the_old_by_hand_line_is_gone():
    lines = _lines(DATA_IMPORT)
    assert ROW_89 in lines  # the replacement must be there, so this fails today
    assert ROW_89_NOW not in lines


# -- rows 90 to 94, 98 to 100: production ----------------------------------------


def test_row_90_the_sentence_before_the_table_points_to_the_preview():
    assert ROW_90 in _production_section()


def test_row_90_the_old_two_layouts_sentence_is_gone_from_production():
    section = _production_section()
    assert ROW_90 in section  # the replacement must be there, so this fails today
    assert ROW_90_NOW not in section


def test_rows_91_to_93_are_one_table_row_of_the_layouts_table():
    row = _table_row_with(DATA_IMPORT, ROW_91, ROW_92, ROW_93)
    assert row is not None, "no table row has the three cells of rows 91, 92 and 93"
    assert row.index(ROW_92) == row.index(ROW_91) + 1
    assert row.index(ROW_93) == row.index(ROW_92) + 1


def test_row_94_the_command_paragraph_ends_with_the_column_option():
    assert ROW_94 in _production_section()


def test_row_98_the_skip_rule_names_the_whole_system_figure():
    assert ROW_98 in _production_section()


def test_row_98_the_old_skip_sentence_is_gone():
    section = _production_section()
    assert ROW_98 in section  # the replacement must be there, so this fails today
    assert ROW_98_NOW not in section


def test_row_99_the_section_5_cell_names_every_skipped_row():
    assert ROW_99 in _flat(_read(DATA_IMPORT))


def test_row_99_the_old_section_5_sentence_is_gone():
    text = _flat(_read(DATA_IMPORT))
    assert ROW_99 in text  # the replacement must be there, so this fails today
    assert ROW_99_NOW not in text


def test_row_100_the_ear_cell_says_the_first_row_is_kept():
    assert ROW_100 in _flat(_read(DATA_IMPORT))


def test_row_100_the_old_five_times_sentence_is_gone():
    text = _flat(_read(DATA_IMPORT))
    assert ROW_100 in text  # the replacement must be there, so this fails today
    assert ROW_100_NOW not in text


# -- rows 95 to 97: the AI operator guide ----------------------------------------


@pytest.mark.parametrize(
    "answer,asked",
    [
        (ROW_95, "Which meter feeds which water source"),
        (ROW_96, "The unit of the rows in a production file whose unit is blank"),
        (
            ROW_97,
            "Whether the organization wants OpenH2O to hold its sampling schedule",
        ),
    ],
    ids=["row95", "row96", "row97"],
)
def test_rows_95_to_97_are_the_answer_cells_of_their_table_rows(answer, asked):
    row = _table_row_with(OPERATOR, asked, answer)
    assert row is not None, f"no table row pairs '{asked}' with the new answer"
    assert row.index(answer) == row.index(asked) + 1


@pytest.mark.parametrize(
    "answer,now",
    [(ROW_95, ROW_95_NOW), (ROW_97, ROW_97_NOW)],
    ids=["row95", "row97"],
)
def test_rows_95_and_97_old_answers_are_gone(answer, now):
    text = _flat(_read(OPERATOR))
    assert answer in text  # the replacement must be there, so this fails today
    assert now not in text
