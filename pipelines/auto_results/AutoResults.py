import re
from docx import Document
from docx.shared import Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph

# Update the marginals path (values) and the results path (blank results). Keep the r in front of the '' to maintain string
MARGINALS_FILE_PATH = r'.\marginals.docx'
RESULTS_FILE_PATH = r'.\results.docx'
OUTPUT_FILE_PATH = r'.\Completed_Results.docx'
SPECIAL_CHARACTER = '???'  # Replace with any special character


def extract_values_from_marginals(document):
    values = []
    for paragraph in document.paragraphs:
        match_percent = re.search(r'(\d+)\s*%', paragraph.text)
        match_star_percent = re.search(r'\*%\s*', paragraph.text)
        match_zero = re.search(r'[^-]-\s*$', paragraph.text)

        if match_percent:
            values.append(match_percent.group(1))
        elif match_star_percent:
            values.append("<1")  # Replace *% with <1
        elif match_zero:
            values.append("0")

    return values

def apply_font_settings(run, value):
    run.text = run.text.replace(SPECIAL_CHARACTER, value, 1)
    run.font.size = Pt(9)
    run.font.name = 'Arial'
    run.font.color.rgb = RGBColor(0, 0, 0)

def process_paragraph(paragraph, values):
    for run in paragraph.runs:
        if SPECIAL_CHARACTER in run.text:
            value = values.pop(0) if values else ""
            apply_font_settings(run, value)


def process_document(document, values):
    values_index = 0  # Initialize index for values
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
            if values_index < len(values):
                values_index += 1
        else:
            break  # No more values, exit loop



def main():
    # Open the results document
    marginals_doc = Document(MARGINALS_FILE_PATH)
    values = extract_values_from_marginals(marginals_doc)
    print(values)
    if not values:
        print("No values found in the values list document.")
        return

    doc = Document(RESULTS_FILE_PATH)
    process_document(doc, values)

    doc.save(OUTPUT_FILE_PATH)

if __name__ == '__main__':
    main()
