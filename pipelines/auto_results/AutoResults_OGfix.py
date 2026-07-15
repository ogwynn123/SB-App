import re
from docx import Document
from docx.shared import Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph

# Update the marginals path (values) and the results path (blank results). Keep the r in front of the '' to maintain string
MARGINALS_FILE_PATH = r'D:\OneDrive - Normington Petts\NPA Archive - Documents\Stelson\2026\NPA3787 Environment\Data\partial data\results\marg.docx'
RESULTS_FILE_PATH = r'D:\OneDrive - Normington Petts\NPA Archive - Documents\Stelson\2026\NPA3787 Environment\Data\partial data\results\NPA3787 results EMPTY.docx'
SPECIAL_CHARACTER = '!!'  # Replace with any special character

def extract_values_from_marginals(document):
    values = []
    for paragraph in document.paragraphs:
        match_percent = re.search(r'(\d+)\s*%', paragraph.text)
        match_star_percent = re.search(r'\*%\s*', paragraph.text)
        match_zero = re.search(r'[^-]-\s*$', paragraph.text)

        if match_percent:
            values.append(match_percent.group(1))
        elif match_star_percent:
            values.append('<1')  # Replace *% with <1
        elif match_zero:
            values.append('0')

    return values


def apply_font_settings(run):
    run.font.size = Pt(9)
    run.font.name = 'Arial'
    run.font.color.rgb = RGBColor(0, 0, 0)


def process_paragraph(paragraph, values):
    # Pass 1: replace placeholders that exist fully within a run.
    for run in paragraph.runs:
        while SPECIAL_CHARACTER in run.text:
            value = values.pop(0) if values else ''
            run.text = run.text.replace(SPECIAL_CHARACTER, value, 1)
            apply_font_settings(run)

    # Pass 2: replace placeholders split across adjacent runs ("!" + "!").
    i = 0
    runs = paragraph.runs
    while i < len(runs) - 1:
        run_left = runs[i]
        run_right = runs[i + 1]

        if run_left.text.endswith('!') and run_right.text.startswith('!'):
            value = values.pop(0) if values else ''
            run_left.text = run_left.text[:-1] + value
            run_right.text = run_right.text[1:]
            apply_font_settings(run_left)
        else:
            i += 1


def process_document(document, values):
    for content in document.element.body:
        if content.tag.endswith(('p', 'tbl')):  # Check if the content is a paragraph or table
            if content.tag.endswith('p'):  # Process paragraphs
                paragraph = Paragraph(content, document)
                process_paragraph(paragraph, values)
            elif content.tag.endswith('tbl'):  # Process tables
                table = Table(content, document)
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            process_paragraph(paragraph, values)
        else:
            break  # Exit when non-body content is reached


def main():
    # Open the results document
    marginals_doc = Document(MARGINALS_FILE_PATH)
    values = extract_values_from_marginals(marginals_doc)
    print(values)
    if not values:
        print('No values found in the values list document.')
        return

    doc = Document(RESULTS_FILE_PATH)
    process_document(doc, values)

    doc.save(r'D:\OneDrive - Normington Petts\NPA Archive - Documents\Stelson\2026\NPA3787 Environment\Data\partial data\results\NPA3787 results FILLED.docx')


if __name__ == '__main__':
    main()
